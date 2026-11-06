# AI 面试题库（ai-interview-bank）

把零散的 AI 面试题沉淀成**一份**可检索、可生长的本地题库，并从中生成知识图谱。支持 Claude Code / Codex / WorkBuddy / DeepSeek Harness 四种宿主安装。

---

## 这个项目解决什么

刷面经时真正的问题不是「看不到题」，而是：

- 题目散在几十条帖子里，截图、正文、评论区各一半；
- 换个说法的同一道题反复出现，手动比对根本记不住；
- 收藏了几百条，回头想复习某个方向时找不出来；
- 只知道答案，不知道这题在**考什么**，换个问法就答不上来。

于是这个插件把流程固定成五步，让 Agent 替你机械地做记录、做去重、做索引，把「想清楚」留给人：

```
读帖 → 语义去重 → 批量只写题 → 逐题分析 → 索引 + 图谱刷新
```

答案**不抄帖子**。帖子自带的参考答案只作校验素材——先独立写，写完再对照，补漏、纠错、识别新分支。

## 特点

- **单一真源**：一个 markdown 文件。不建副本、不按批次新建文件、不改写历史题干、不复用编号。
- **语义去重**：按「考察点 + 提问角度 + 答案是否等价」三步判定，跳过 / 并入 / 新增，新增必须写「关联」字段。
- **两段式写入**：新题先入「待分析」，再逐题补「考什么 / 解题思路 / 参考答案」。不会出现一堆只有标题的空条目。
- **知识图谱**：节点为 Question / Category / Entity / Angle，边全部从题库既有字段确定性抽取，不靠推断。
- **只读 MCP**：六个查询工具，没有任何写工具。写库一律走本地 CLI，由你确认。
- **题目不带来源**：条目里只有题目和分析，链接、图号、批次只记在更新日志。

## 安装

| 宿主 | 安装方式 |
|---|---|
| **Claude Code** | `/plugin marketplace add Imchengliang/ai-interview-bank` → `/plugin install ai-interview-bank@ai-interview-bank-marketplace` |
| **Codex** | `codex plugin marketplace add Imchengliang/ai-interview-bank` → `codex plugin add ai-interview-bank@ai-interview-bank-marketplace` |
| **WorkBuddy** | 复制本目录到 `~/.workbuddy/skills/ai-interview-bank/` |
| **DeepSeek Harness** | `dsh plugin --profile <name> add <包路径>/agents/deepseek-harness`，并把 `AI_INTERVIEW_BANK_ROOT` 指向主包目录 |
| **通用 / 任意 MCP 客户端** | `npx skills add Imchengliang/ai-interview-bank`，或在 MCP 配置里指向 `python3 <包路径>/mcp_server.py` |

要求：Python 3.9+，无第三方依赖（MCP server 是手写的 stdio JSON-RPC，不需要 `mcp` / `fastmcp`）。

## 快速开始

```bash
# 1. 初始化：生成 config.json、内部游标，并从现有题库生成图谱
python3 cli.py init

# 2. 改 config.json 的 bank_path 指向你的题库（默认 ~/Documents/interview/ai_question.md）
#    题库不存在？把 assets/ai_question_template.md 复制过去即可，init 不会覆盖已有文件

# 3. 看看状态
python3 cli.py status
```

然后就可以把帖子链接丢给 Agent 了：

```
整理这个帖子 https://www.xiaohongshu.com/explore/xxxxx
```

Agent 会走完五步，在写库前先给你预览。

## 命令行

```bash
python3 cli.py init                          # 初始化配置与图谱
python3 cli.py status                        # 题库统计、下一编号、待分析题、启用模式
python3 cli.py verify                        # 结构与编号完整性校验
python3 cli.py preview --url "<链接>"         # 读帖，返回正文/图片路径与 preview_id（不写库）
python3 cli.py stage --preview <id> --items items.json --confirm   # 批量只写题
python3 cli.py finalize                      # 收尾校验 + 重算图谱
python3 cli.py search --query "RAG"          # 搜题
python3 cli.py graph --refresh               # 重建图谱
python3 cli.py neighbors --qid Q001          # 查相邻题
python3 cli.py mcp                           # 启动只读 MCP server
```

## 写入策略

默认 `preview-confirm`：主动拉到的新题一律先预览、经确认后才落盘。`stage` 不带 `--confirm` 只会返回拒绝原因，不碰题库。

P0 只启用 `m0_manual_link`（手动贴链接）。`m1`–`m8`（关键词扫描、博主追踪、合集导入、转发收件箱、跨平台、图谱驱动补题、评论挖掘、定期摘要）是预留开关；没有注册适配器时不会去拉题，打开也不会产生副作用。

## 知识图谱

`cli.py graph --refresh` 生成三个文件：

| 文件 | 内容 |
|---|---|
| `graph/knowledge_graph.json` | 节点 Question / Category / Entity / Angle；边 `IN_CATEGORY`、`RELATED`、`MENTIONS`、`HAS_ANGLE` |
| `graph/knowledge_graph.mmd` | 类别为中心的 Mermaid 视图 |
| `graph/gaps.json` | 类别分布、空类别、孤立题、高频实体 |

`RELATED` 边直接来自题库条目的「关联」字段，不是模型猜的。`gaps.json` 是给「补题」用的：哪些方向题目过少、哪些题没有任何关联。

## MCP 工具（只读）

`bank_status`、`list_questions`、`search_questions`、`graph_summary`、`graph_neighbors`、`preview_note`。

没有写工具是有意的：写库需要人确认，而 Codex 会自动拒绝第三方 MCP 的写调用。只读 + 本地 CLI 写入，在四种宿主上行为一致。

## 项目结构

```
.
├── SKILL.md                    # 流程定义（Agent 读这个）
├── cli.py                      # 命令行入口
├── mcp_server.py               # 只读 MCP server（手写 stdio JSON-RPC）
├── core/                       # config / bank / sources / graph / pipeline
├── references/                 # 题库配置约定、去重与答案规则
├── scripts/                    # list_questions.py、fetch_xhs_images.py
├── assets/                     # 题库骨架模板
├── agents/deepseek-harness/    # dsh（Cordis）适配器
├── .claude-plugin/             # plugin.json + marketplace.json
├── .mcp.json                   # 跨宿主 MCP 启动器
└── tests/                      # smoke_test.py、host_matrix.py、dsh_adapter_test.mjs
```

`config.json`、`state/`、`graph/` 都在 `.gitignore` 里——那是本地运行时数据，不进版本库。

## 几个设计决定

**MCP 用 `/bin/sh` 启动器，不用 `${CLAUDE_PLUGIN_ROOT}`。** Claude Code 会展开这个变量，Codex 不会——它既不展开变量、也不注入 plugin root 环境变量，cwd 还是你的项目目录。直接写 `"args": ["${CLAUDE_PLUGIN_ROOT}/mcp_server.py"]` 在 Codex 上会以 `connection closed: initialize response` 失败。启动器依次在参数目录、`~/.codex/plugins/cache/`、`~/.claude/plugins/cache/`、cwd 里找 `mcp_server.py`，四种宿主都能起来。

**图谱只做确定性抽取。** 实体来自配置的术语表 + 题目文本匹配，关联来自人写的「关联」字段。这样图谱可以随题库稳定重算，不会因为换了个模型就变了形状。

**答案不抄原帖。** 原帖答案在你写完之后的角色是校验：它指出了什么你漏了、哪里你写错了、有没有你自己没想到的分支。直接抄会让题库变成二手信息集合，换个问法就用不上。

## 范围与限制

- **P0 只支持手动贴链接**，不做后台自动抓取。小红书没有公开 API，抓取依赖登录态，且社区内容的使用受平台条款约束——所以这一步留给人主动触发。
- **抓取有降级链**：桌面页 → 移动端 UA → SSR `desc` 字段 → 图片逐张转录 → 请你贴原文。哪一步都不猜题。
- **图片型帖子需要 Agent 有图像读取能力**，否则只能走「请你贴原文」。
- **不做题库共享/云同步**，就是一个你本地的 markdown 文件，自己 git 管或直接备份。

## 测试

```bash
python3 tests/smoke_test.py       # 24 项：写入闸门、结构保真、图谱、MCP 协议
python3 tests/host_matrix.py      # 11 项：四宿主配置与变量规则（只读，不发模型请求）
node tests/dsh_adapter_test.mjs   # dsh 适配器运行时验证
```

## 许可证

MIT
