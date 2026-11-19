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
- 短链先展开：`xhslink.com` 等短链先还原为真实 URL 再抓。若返回「重定向到其他域名」（如 `www.rednote.com`），用返回的新 URL 重抓一次。
- 遇到登录墙、反爬或正文为空（如「你访问的页面不见了」）：用移动端 UA 请求 `https://www.xiaohongshu.com/explore/<id>?xsec_token=...&xsec_source=pc_share`，从页面 `__INITIAL_STATE__` 的 `desc` 字段提取正文（话题标签按噪音忽略）；仍取不到再用网页搜索找转载/摘要；再不行请用户贴正文或截图，**明确告知本批暂未入库**。
- 一次多个链接全部读完再进 Step 2。

#### 图片型帖子（题目在图里，小红书面经常见）
1. 抓原图：`python3 scripts/fetch_xhs_images.py "<帖子URL>" --out /tmp/xhs_imgs`。脚本从 SSR 的 `imageList` 取 `!h5_1080jpg` 原图（约 1080×1800）；桌面页只是 JS 壳取不到图，`!style_*` 的 240×400 缩略图不要用于识别。
2. 逐张用图像读取工具**逐字转录**：按从上到下顺序、保留编号与标点、不总结不改写；多张图按编号拼成完整题目列表，检查编号连续性，缺号在汇报里说明。编号只用于核对顺序，入库题目行不带帖内编号。
3. 图片模糊/被裁/张数不足/分享令牌过期时，请用户发原图或截图；识别不出的题目留空说明，**绝不猜题**。OCR 存疑的题干标注出来，在收尾汇报请用户核对。

#### 读帖硬规则
- 只提取正文中的面试题目，忽略评论区闲聊、广告、作者求职吐槽；题干保留原话、只写题目本身，不附加帖内编号、图号或「追问／加分／答砸」之类标记。
- 帖子自带参考答案／解析，与题目分开暂存为「本批参考素材」，不混进题干、不写进题库，只用于 Step 4 校验。

### Step 2 · 语义去重（LLM）
- `python3 cli.py status` / `search --query` / MCP `list_questions`、`search_questions` 拿到已有题清单。
- 按 `references/dedup_and_answer_rules.md` 三步判定：考察点 + 提问角度 + 答案是否相同 → 跳过 / 并入 / 新增。新增必须写「关联」字段（相关 Q 号 + 一句差别）。把结果整理成 `--items` JSON：`[{"category":"...","topic":"...","relation":"..."}]`。

### Step 3 · 批量只写题（CLI，确认后）
```bash
python3 cli.py stage --preview <preview_id> --items items.json --confirm
```
只写 `#### Qxxx · 类别 · 状态：待分析` + `**题目**` + `**关联**`；不改已有题干、不写答案。`preview-confirm` 策略下必须显式 `--confirm`。

### Step 4 · 逐题分析（LLM，插件不代写）
按编号一题一题处理，每题完整走完再处理下一题。每题补：
- `**考什么**`：一句话点破面试官想听什么。
- `**解题思路**`：2–4 步，每步一行，说清先判断什么、再怎么组织；优先讲「怎么想」，其次才是结论。
- `**参考答案**`：可直接口述的 3–6 句，约 150–250 字、上限 350 字；不堆公式、不铺背景、不写成教程；对比点到为止。

与其他题有关联时，用一句话点明「和 Qxxx 的差别在于……」，不重复展开那题的内容。状态从「待分析」改「已分析」。

**帖子自带答案的处理顺序**：先独立完成上述三段，再对照「本批参考素材」——补漏关键判断点、纠正明显错误或过时说法；原帖展开的新角度若构成独立分支，回 Step 2 判是否新增题目。不复制、不轻度改写原帖答案充当 `**参考答案**`，也不因原帖答案长而放宽字数。原帖说法有问题时，在参考答案里一句话点明，不另开长篇辨析。

不确定时写明面试中可如何说明不确定并给出验证思路；不编造具体数字、论文结论或不存在的技术细节。

### Step 5 · 收尾（LLM + CLI）
- LLM 更新「关联索引」与「更新日志」（日期 + 本批来源 + 新增数）。
- `python3 cli.py finalize`：结构校验 + 从题库重算图谱（**题库本身不重建**）。
- 汇报格式（逐项给全，不要只报一个总数）：
  - 本批共读到多少题；**新增 N 题**（列出 Q 号与类别）；**跳过 M 题**（逐条给出对应母题 Q 号）；**已解析 K 题**。
  - 题库文件路径。
  - 若对照了帖子自带的参考答案：说明对照了几份、是否补漏或纠错。
  - 图片帖若缺号或 OCR 存疑，在此请用户核对。

**用户说「先记录，暂不分析」时**：只做 Step 1–3 + Step 5，留下「待分析」状态并汇报；后续用户说「分析」时，从题库所有「待分析」条目继续 Step 4（不多题为一批糊答案）。

## 练习模式（苏格拉底式，借自 rederive）

与上面的**入库流程完全独立**：这里只读题库、不写题库，目的是让用户自己把答案**推导**出来，而不是念给他听。参考 `rederive` 的核心思想：先抛出问题，一次只加一条约束，讲解是最后手段。

### 触发

```
python3 cli.py coach --qid Q117   # 指定题
python3 cli.py coach              # 随机抽一道已分析题
python3 cli.py coach --category "RAG"   # 限定类别随机抽
python3 cli.py coach --list       # 列出可练习的题号
```

返回的 JSON 里：`root_probe` 是这道题要考的矛盾，`steps` 是 2–4 个推导步骤，**`reveal_only` 是答案，全程隐藏**。

### 引导流程（严格遵守）

1. **开场只给场景，不给答案**：用 2–4 句把 `root_probe` 说成一个真实情境，不带 `steps` 和答案里的术语/结论。最后只问一个问题：「你会怎么处理？」——消息里只能有一个问号。
2. **一次加一条约束**：用户答完后，取下一个 `step`，把它改写成「如果有 <该步给出的条件>，你的方案会出现 <不这么做会怎样> 的问题，怎么改？」——仍然只问一个问题。**绝不直接说出该步的 point**。
3. **答对就确认并命名**：用户的思路命中该步要点时立刻肯定，用**通用技术判断的名字**（如「按轨迹归因」「按成本分层选型」）点一下，不要念题库原句、不引用具体题目文本。然后进入下一 `step`。
4. **卡住时的处理**（用户说不知道，或答案没满足当前约束）：
   - 第一次卡住：把当前 `step` 拆成 2–4 个可选方向，各附一句代价，问「哪个更符合这个约束？」
   - 选错：追加一条会让该选项失效的约束，让他重选，不公布对错原因。
   - **连续两次答错**：提出「要不要我画个草图？」；用户同意后，用纯文本画出已有的条件和约束在哪一步断裂，**绝不画出缺失的那一步**。
5. **中途绝不揭示答案**：即使用户直接问「答案是什么」，也不给——再加一条约束，或描述缺失那块必须完成什么，但不命名、不念 `reveal_only`。
6. **推导完成后才揭示**：用户走完所有 `steps` 或明确放弃后，才展示 `reveal_only.answer`，并一句话对照他的思路与参考的差别。此时才允许说「你重新推导出了 X」。
7. **一次只问一个问题**：发送消息前数问号与「能不能/可不可以/试试」这类请求，只保留第一个。

### 练习记录

每题结束后，追加一行到 `state/coach_log.md`（不存在则创建，gitignore 已覆盖 `state/`）：

```
- YYYY-MM-DD Qxxx | 卡在：<第几步、哪里>、<什么让他继续> | 自己想到：<哪些点> | 提示次数：N | 结果：完成/放弃
```

结尾给用户一句简短小结：卡在哪一步、有几次没靠提示、建议下次练哪类。不要给人贴标签，不要打分、排名或连胜。

## 知识图谱

`python3 cli.py graph --refresh` 生成：
- `graph/knowledge_graph.json`：节点 = Question / Category / Entity / Angle；边 = `IN_CATEGORY`、`RELATED`（直接来自题库「关联」字段）、`MENTIONS`、`HAS_ANGLE`。全部从现有字段确定性抽取，不靠推断。
- `graph/knowledge_graph.mmd`：类别为中心的 Mermaid 视图。
- `graph/gaps.json`：类别分布、空类别、孤立题、高频实体 —— 供 P2 的 M6「图谱驱动补题」使用。

查询：`graph --format gaps`、`neighbors --qid Q001`、MCP `graph_summary` / `graph_neighbors`。

## Obsidian 题库 KG（派生视图）

题库 `ai_question.md` 仍是唯一真源；Obsidian 目录是**由它生成的镜像**，不反向写回。首次生成、之后增量更新：

```bash
python3 cli.py obsidian                    # 生成/更新到题库同级的「题库笔记」目录
python3 cli.py obsidian --vault <路径>      # 指定其它 vault
python3 cli.py obsidian --dry-run          # 只报告将创建/更新哪些文件
python3 cli.py finalize --obsidian         # Step 5 收尾时顺带同步
```

- 每道题一个 `Qxxx.md`：YAML frontmatter（qid/类别/状态/实体/角度）+ 题目 + 关联双链 + 考什么/解题思路/参考答案。
- `**关联**` 里的 `Q019（三层归因）` 渲染成 `[[Q019]] — 三层归因`，Graph View 里就是可点击的边。
- 类别/实体/角度各生成枢纽页（`类别-*.md`、`实体-*.md`、`角度-*.md`），带反向链接。
- 每篇笔记末尾有 `<!-- USER NOTES: BEGIN/END -->` 区，**重建时原样保留**手写内容。
- 只有渲染内容变化的笔记才重写，重复运行是幂等的。

Obsidian 用法：把生成目录（默认 `~/Documents/interview/题库笔记`）作为 vault 打开，开 Graph View 即可。

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
