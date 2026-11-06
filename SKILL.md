---
name: ai-interview-bank
description: 跨 Agent 可安装的 AI 面试题题库插件。当用户贴小红书/其他平台的 AI 面试题链接、要求整理面经、查看或补充题库、检索题目、生成知识图谱时使用。流程固定为「读帖 → 语义去重 → 批量只写题 → 逐题分析 → 索引日志 + 图谱刷新」，答案必须由 LLM 逐题独立撰写。
agent_created: true
---

# AI 面试题题库（可分发插件版）

## 这是什么

把零散的 AI 面试题沉淀成**一份**本地题库（题目 + 考什么 + 解题思路 + 参考答案），并从中生成知识图谱。本包提供的是**跨 Agent 可安装形态 + 可编程接口 + 图谱**。

- 题库唯一真源：`config.json` 里的 `bank_path`（默认 `~/Documents/interview/ai_question.md`）。
- `references/` 与 `scripts/` 存放流程规则与辅助脚本；`assets/` 是题库骨架。
- `core/` 只做机械工作；**Step 1 转录、Step 2 语义去重、Step 4 逐题写答案必须由 LLM 完成**，Python 不代写。

## 配置与初始化

```bash
python3 cli.py init      # 生成 config.json、内部游标、并从现有题库生成图谱
python3 cli.py status    # 查看题库统计、下一个编号、待分析题、已启用模式
python3 cli.py verify    # 结构与编号完整性校验
```

首次安装后先改 `config.json` 的 `bank_path` 指向你的题库；**已有题库不会被重建或覆盖**。

## 写入策略（默认 preview-confirm）

主动拉到的新题**一律先预览、经用户确认后才写库**。`stage` 不带 `--confirm` 只会返回拒绝原因。P0 只启用 `m0_manual_link`；`m1`–`m8` 是预留模式开关，未注册适配器时不会拉题。

## 五步流程（不可变）

### Step 1 · 读帖（LLM + CLI）
- 用户贴链接：`python3 cli.py preview --url "<链接>"`，或直接调 MCP 工具 `preview_note`。返回正文/图片本地路径与 `preview_id`；**这一步不写题库**。
- 图片型帖子：逐张用图像读取工具逐字转录（保留编号只为核对顺序，入库不写帖内编号）；正文拿不到时用移动端 SSR 的 `desc`，再不行请用户贴正文或原图，**绝不猜题**。
- 一次多个链接全部读完再进 Step 2。

### Step 2 · 语义去重（LLM）
- `python3 cli.py status` / `search --query` / MCP `list_questions`、`search_questions` 拿到已有题清单。
- 按 `references/dedup_and_answer_rules.md` 三步判定：考察点 + 提问角度 + 答案是否相同 → 跳过 / 并入 / 新增。新增必须写「关联」字段（相关 Q 号 + 一句差别）。把结果整理成 `--items` JSON：`[{"category":"...","topic":"...","relation":"..."}]`。

### Step 3 · 批量只写题（CLI，确认后）
```bash
python3 cli.py stage --preview <preview_id> --items items.json --confirm
```
只写 `#### Qxxx · 类别 · 状态：待分析` + `**题目**` + `**关联**`；不改已有题干、不写答案。`preview-confirm` 策略下必须显式 `--confirm`。

### Step 4 · 逐题分析（LLM，插件不代写）
按编号一题一题补 `**考什么**`（一句话）、`**解题思路**`（2–4 步）、`**参考答案**`（3–6 句，约 150–250 字、上限 350 字），状态改「已分析」。帖子自带答案只作**写完之后的**校验素材：补漏、纠错、识别新分支，禁止照抄。不确定时写明验证思路，不编造数字或论文结论。

### Step 5 · 收尾（LLM + CLI）
- LLM 更新「关联索引」与「更新日志」，并汇报新增/跳过/已解析数量。
- `python3 cli.py finalize`：结构校验 + 从题库重算图谱（**题库本身不重建**）。

## 知识图谱

`python3 cli.py graph --refresh` 生成：
- `graph/knowledge_graph.json`：节点 = Question / Category / Entity / Angle；边 = `IN_CATEGORY`、`RELATED`（直接来自题库「关联」字段）、`MENTIONS`、`HAS_ANGLE`。全部从现有字段确定性抽取，不靠推断。
- `graph/knowledge_graph.mmd`：类别为中心的 Mermaid 视图。
- `graph/gaps.json`：类别分布、空类别、孤立题、高频实体 —— 供 P2 的 M6「图谱驱动补题」使用。

查询：`graph --format gaps`、`neighbors --qid Q001`、MCP `graph_summary` / `graph_neighbors`。

## MCP 工具（只读）

`python3 cli.py mcp` 或 `python3 mcp_server.py` 启动 stdio server，暴露 `bank_status`、`list_questions`、`search_questions`、`graph_summary`、`graph_neighbors`、`preview_note`。**没有任何写工具**：写库一律走本地 CLI/Skill，这也规避了 Codex 自动拒绝第三方 MCP 写调用的行为。

## 各宿主安装

| 宿主 | 安装方式 |
|---|---|
| Claude Code | `/plugin marketplace add Imchengliang/ai-interview-bank` → `/plugin install ai-interview-bank@ai-interview-bank-marketplace`；插件通过 `.claude-plugin/plugin.json` 声明 skills 与 `.mcp.json` |
| Codex | `codex plugin marketplace add Imchengliang/ai-interview-bank` → `codex plugin add ai-interview-bank@ai-interview-bank-marketplace`；或把本目录放进 `.codex/skills/` 并手动 `codex mcp add` |
| WorkBuddy | 复制本目录到 `~/.workbuddy/skills/ai-interview-bank/` |
| 通用 | `npx skills add Imchengliang/ai-interview-bank` 安装到 `.agents/skills/`；任意 MCP 客户端配置 `python3 <包>/mcp_server.py` |
| DeepSeek Harness (dsh) | `dsh plugin --profile <name> add <包>/agents/deepseek-harness`；`dsh.bundle.patch` 声明会让 dsh 自动把包加入 `dsh.profile.bundles`。四个只读工具经本地 CLI 调用，需设置 `AI_INTERVIEW_BANK_ROOT` 指向主包目录。dsh 默认不启用 MCP server、只桥接 Tools，故不走 MCP 路径 |

### 宿主实测要点（实测于 claude 2.1.234 / codex 0.164.0 / dsh 0.1.5-rc.1 / WorkBuddy）

- `.mcp.json` 使用 `/bin/sh` 启动器，**不依赖任何宿主的插件根变量**。Claude Code 会展开 `${CLAUDE_PLUGIN_ROOT}`；Codex 既不展开变量、也不注入 plugin root 环境变量、cwd 还是项目目录，所以启动器会依次在参数、`~/.codex/plugins/cache/`、`~/.claude/plugins/cache/`、当前目录里找 `mcp_server.py`。**不要改回 `"args": ["${CLAUDE_PLUGIN_ROOT}/mcp_server.py"]`**，那会让 Codex 的 MCP 启动直接失败（实测 `connection closed: initialize response`）。
- Claude Code：`claude plugin validate --strict <包>`（marketplace 必须有 `description`）、`marketplace add`、`plugin install --scope local` 均通过；`claude plugin details` 识别 1 Skill + 1 MCP；`claude mcp list` 显示 ✔ Connected。模型侧工具调用需要有效的 Claude 登录态。
- Codex：`codex plugin marketplace add <包>` → `codex plugin add ai-interview-bank@ai-interview-bank-marketplace` 通过；MCP 工具调用默认需要审批，非交互用 `--approve-for-me`（交互式直接批准）。`bank_status` 已实测返回真实题库状态。
- dsh：适配器用真实 `@deepseek-ai/dsh-tools` 的 `defineTool`，该 API **强制要求 `output.schema` + `output.render(args, value) -> ContentBlock[]`**，缺 `output` 会在注册时崩。`tests/dsh_adapter_test.mjs` 做运行时验证；隔离 `DSH_HOME` 安装后 `--dump-config` 会出现 `# == dsh-ai-interview-bank` bundle 层。
- WorkBuddy：官方 `package_skill.py` 打包校验通过；安装到 `~/.workbuddy/skills/ai-interview-bank` 后可由 Skill 工具真实加载。
- 一键复测：`python3 tests/host_matrix.py`（只读，不发模型请求）。

## 不可违反

- 题库单一真源，不建副本、不分批新建文件；不改写已有题干、不复用编号、不删除历史条目。
- **题目条目不写来源**（链接、图号、日期）；批次信息只进「更新日志」。`state/processed_sources.json` 是链接级幂等的**内部元数据**，与题库条目无关。
- 不存原帖全文/图片，只存题干要点和自己的分析。
- 分析必须逐题进行；主动模式默认关、默认预览确认。
