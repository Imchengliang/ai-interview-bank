// DeepSeek Harness (Cordis) adapter.
// Verified against dsh 0.1.5-rc.1 / @deepseek-ai/dsh-tools 0.1.5-rc.2:
// defineTool() REQUIRES `output: { schema, render }`; render() returns ContentBlock[].
// dsh bridges Tools but does not enable MCP servers, so this adapter calls the
// local CLI directly. Every tool here is READ-ONLY: writes require
// `python3 cli.py stage --confirm` executed by a human or by the Skill flow.
//
// The Python core lives in the main plugin package. Set AI_INTERVIEW_BANK_ROOT
// to that package's absolute path (or keep this adapter as a subdirectory of it).

import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'ai-interview-bank'
export const inject = ['tools']

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PACKAGE_ROOT = process.env.AI_INTERVIEW_BANK_ROOT || path.resolve(HERE, '../..')

function cli(args) {
  const entry = path.join(PACKAGE_ROOT, 'cli.py')
  if (!existsSync(entry)) {
    return JSON.stringify({
      error: `cli.py not found at ${entry}; set AI_INTERVIEW_BANK_ROOT to the plugin root`,
    })
  }
  const result = spawnSync('python3', [entry, ...args], {
    encoding: 'utf8',
    timeout: 30000,
  })
  if (result.error) return JSON.stringify({ error: String(result.error) })
  return result.stdout.trim() || JSON.stringify({ error: result.stderr.trim() })
}

// dsh-tools validates execute()'s return against this schema and renders it
// for the model. A plain string output is sufficient for JSON CLI results.
const STRING_OUTPUT = {
  schema: { type: 'string' },
  render: (_args, value) => [{ type: 'text', text: String(value) }],
}

export function apply(ctx) {
  ctx.tools.register(defineTool({
    name: 'interview_bank_status',
    description: 'AI 面试题库统计：题数、下一个编号、待分析题、空白类别、已启用模式',
    parameters: {},
    output: STRING_OUTPUT,
    async execute() { return cli(['status']) },
  }))

  ctx.tools.register(defineTool({
    name: 'interview_bank_search',
    description: '在题库里检索题目（题干/考什么/关联/参考答案）',
    parameters: {
      query: { type: 'string', required: true, description: '检索关键词' },
    },
    output: STRING_OUTPUT,
    async execute(args) { return cli(['search', '--query', args.query]) },
  }))

  ctx.tools.register(defineTool({
    name: 'interview_bank_gaps',
    description: '知识图谱薄弱点：类别分布、空类别、孤立题、高频实体',
    parameters: {},
    output: STRING_OUTPUT,
    async execute() { return cli(['graph', '--format', 'gaps']) },
  }))

  ctx.tools.register(defineTool({
    name: 'interview_bank_preview',
    description: '只读预览一个小红书帖子，返回正文/图片路径与预览号，不写题库',
    parameters: {
      url: { type: 'string', required: true, description: '小红书笔记链接（含 xsec_token）' },
    },
    output: STRING_OUTPUT,
    async execute(args) { return cli(['preview', '--url', args.url]) },
  }))
}
