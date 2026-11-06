// Runtime verification of the DeepSeek Harness adapter against the REAL
// installed @deepseek-ai/dsh-tools (not a mock of defineTool).
//
//   node tests/dsh_adapter_test.mjs <plugin-package-root>
//
// ESM bare-specifier resolution is anchored at the importing file, so we copy
// the adapter into a temp dir and rewrite only its single bare import to the
// absolute installed entry. Everything else (output schema, render contract,
// parameter spec, CLI execution) is exercised unchanged.

import { mkdtempSync, writeFileSync, readFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import assert from 'node:assert/strict'

const ROOT = process.argv[2]
if (!ROOT) {
  console.error('usage: node dsh_adapter_test.mjs <plugin-package-root>')
  process.exit(2)
}
process.env.AI_INTERVIEW_BANK_ROOT = ROOT

const candidates = [
  process.env.DSH_TOOLS_ENTRY,
  '/opt/homebrew/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js',
  path.join(process.env.HOME || '', '.dsh/profiles/node_modules/@deepseek-ai/dsh-tools/lib/index.js'),
  '/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js',
].filter(Boolean)
const entry = candidates.find((p) => existsSync(p))
if (!entry) {
  console.error('SKIP: @deepseek-ai/dsh-tools not found; set DSH_TOOLS_ENTRY to its lib/index.js')
  process.exit(3)
}

const source = readFileSync(path.join(ROOT, 'agents/deepseek-harness/plugin.mjs'), 'utf8')
const patched = source.replace(
  "from '@deepseek-ai/dsh-tools'",
  `from '${pathToFileURL(entry).href}'`,
)
const modPath = path.join(mkdtempSync(path.join(tmpdir(), 'aibank-dsh-')), 'plugin.mjs')
writeFileSync(modPath, patched)
const mod = await import(pathToFileURL(modPath).href)

assert.equal(mod.name, 'ai-interview-bank')
assert.deepEqual(mod.inject, ['tools'])

const registered = []
mod.apply({ tools: { register: (definition) => { registered.push(definition); return () => {} } } })
assert.equal(registered.length, 4, 'expected exactly 4 registered tools')

for (const tool of registered) {
  assert.ok(tool.name && tool.description, `${tool.name}: missing name/description`)
  assert.ok(tool.parameters && tool.output, `${tool.name}: missing parameters/output`)
  assert.equal(typeof tool.output.render, 'function', `${tool.name}: missing output.render`)
  assert.deepEqual(
    tool.output.render({}, 'hello'),
    [{ type: 'text', text: 'hello' }],
    `${tool.name}: render must return ContentBlock[]`,
  )
  assert.equal(typeof tool.execute, 'function', `${tool.name}: missing execute`)
}

const statusTool = registered.find((t) => t.name === 'interview_bank_status')
const raw = await statusTool.execute({})
const status = JSON.parse(raw)
assert.ok(status.questions > 0 && status.next_id, 'status tool did not reach the real CLI')

const searchTool = registered.find((t) => t.name === 'interview_bank_search')
const searchRaw = await searchTool.execute({ query: 'Rerank' })
assert.ok(!JSON.parse(searchRaw).error, 'search tool failed')

console.log('DSH_ADAPTER_OK ' + JSON.stringify({
  dsh_tools: entry,
  tools: registered.map((t) => t.name),
  questions: status.questions,
  next_id: status.next_id,
}))
