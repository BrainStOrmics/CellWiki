# Agentic CellWiki

Agentic CellWiki 是一个本地优先的科学 Wiki，提供 Windows 桌面与 Linux 终端两种入口：
**你选定的工作目录就是知识库**。
系统为它初始化 git 仓库并建好 `wiki/`、`raw/` 与根级维护文件；WikiAgent 在同一工作区内
阅读与编辑，系统负责派生文件与阻断式门禁，**每次正式变更由人工逐条判定 diff**。

> [!WARNING]
> 当前版本是未签名 Windows Beta 候选版。论文 chunk、Wiki 上下文和对话会发送给用户配置的模型供应商（OpenAI 兼容协议或原生 Anthropic）；处理敏感或未发表资料前，请先阅读 [安全说明](SECURITY.md)。

## 核心工作流

```text
工作区（一个 git 仓库 = 知识库）
  -> 附件晋升或预置 raw/ 扫描登记，成为可追溯正式源
  -> Agent run：白名单工具读、写、lint、add、commit
  -> 审批单元 diff_<run_id>_<n>（一行一次判定）
  -> 用户接受（审计生效）或拒绝（只 revert 本单元）
```

正式知识只允许通过 `Run -> 待确认 diff -> 用户接受` 写入：git 承载版本与审批，历史永不改写。运行严格串行：同一时刻最多一个
活动 run 与一个未判定 diff，未判定期间新 run（包括只读 run）不启动。

## 已具备能力

- **来源与导入**：附件（pdf/md/txt）上传后由服务端提取文本，run 内按范围读取并受 run 级读取
  预算约束；经用户确认后 `promote_attachment` 晋升为 `raw/<source_id>/` 正式源。Agent 读取工作区
  `schema.md` 的页面模板后直接用文件工具读取 `raw/<source_id>/` 并生成页面；每条 claim 必须带
  `Evidence: Tier 1` 到 `Tier 5` 和可解析来源，实体引用使用 `[[page_id]]`。
- **工作区浏览与受控编辑**：Obsidian 式文件树、md/txt/PDF 只读预览、页面全文搜索（当前实现是
  对 `wiki/` 的扫描）；界面编辑合成 `workspace_edit` run，同样经待确认 diff 生效。
- **Agent 协作**：持久 AgentRun 与 SSE 事件流、run 作用域跨进程 checkpoint、工具时间线与思考行、
  `ask_user_question` 提问卡片与续跑、取消、重试与 `/diagnostics` 诊断；会话登记表使新建会话与
  零 run 会话即时可见、可回访。
- **治理门禁**：Agent 只能用白名单工具与白名单 git 动作（改写历史的命令一律拒绝）、受路径沙箱
  约束、`lint_knowledge_base` 仅报告不修复；`log.md`、`audit_report.md`、`overview.md`、
  `statistics.md` 由系统维护提交，Agent 不得改写。
- **桌面与配置**：React/Tauri 三栏工作台；发布态由 Tauri 启动本地 sidecar（仅绑定 `127.0.0.1`，
  启动期随机端口与 bearer token，写请求需带令牌）；设置页管理模型供应商目录（多个供应商，
  各含 Base URL、协议、API Key 与模型清单，配置免重启生效，对话框可随时切换当前模型）、
  日志级别与中英界面，API Key 优先存 Windows Credential Manager。

**尚未落地，不要按这些预期使用**：子 Agent 委托（注册表为空）、MCP 适配
（已接受、暂缓实施）、安装包代码签名与干净 VM 外部验收。

## Linux / 终端使用

终端路径需要 Python 3.12 + `uv`（daemon 与 Agent 运行时）以及 Node.js 22+
（TypeScript/Ink 终端客户端）：

```bash
uv tool install /path/to/CellWiki
npm install -g cellwiki-tui
cd /path/to/knowledge-base
cellwiki
```

`cellwiki` 无子命令把终端 UI 交给 `cellwiki-tui`（找不到时给出安装提示），
daemon 缺失时自动拉起。进入 TUI 默认是新会话，不会自动接续最近一次对话；
要接着旧会话用 `/resume`。输入框是带圆角边框的盒子，顶边右侧显示当前会话
标题（新会话显示工作区名），首条消息发出后才创建 thread。交互式终端默认
使用 fullscreen 渲染：界面画在终端
备用屏（alternate screen，类似 vim），输入框固定在底部，对话在固定
viewport 内窗口化显示，`PgUp`/`PgDn` 半屏滚动、`Ctrl+Home`/`Ctrl+End`
跳到最早/最新并恢复自动跟随，`↑`/`↓` 单行滚动；输入历史用 `Ctrl+P`/
`Ctrl+N`，排队消息用 `Ctrl+U` 撤回。鼠标滚轮未启用（客户端不捕获鼠标，
保留终端原生选择）。备用屏没有终端原生 scrollback，`Cmd+F` 等
终端搜索不可用；需要主屏 scrollback 时用 `cellwiki-tui --classic` 或设置
`CELLWIKI_TUI_CLASSIC=1` 退回经典渲染。界面支持 `/` 命令（`/help` `/new`
`/resume` `/clear` `/status` `/continue` `/retry` `/diff` `/model`
`/context` `/quit`）、内联提问与 pending diff 数字键审批、`@` 工作区文件
补全、`Esc` 打断、忙时 `Enter` 排队。`/resume` 打开可搜索的会话选择器
（输入过滤，`↑`/`↓` 移动，`Enter` 恢复，`Esc` 取消）；对话中用户消息显示
为 `❯` 行，助手消息以 `●` 开头，run 结束行显示 `✻ done in Ns · HH:MM`。
助手消息按终端 Markdown 子集渲染（`**加粗**`、`*斜体*`、行内代码、链接、
标题、列表、引用、代码块），不再显示原始标记；行内代码与代码块使用主题的
`code` 色（不是 dim），可随 `/theme` 调整对比度；表格与图片不渲染。
`/theme` 打开主题选择器：`↑`/`↓` 实时预览，`Enter` 应用并写入
`~/.cellwiki/tui.json`，`Esc` 取消；内置 `auto`（按终端背景选深浅）、
`dark`、`light`、`dark-daltonized`、`light-daltonized`、`dark-ansi`、
`light-ansi`，配色覆盖输入框、对话、审批卡与状态行，
`CELLWIKI_TUI_THEME` 环境变量优先。dark 主题主色为紫色 `#B1B9F9`
（助手 bullet、spinner、行内代码与代码块同色），light 主题使用深紫变体；
每个预设的 `code` 与主色取同一值，输入框边框/标题/`❯` 提示符与
Markdown 列表 `•` 也使用该主色。
`/new` 清空屏幕并开始新会话（旧会话仍可在 `/resume` 里找回），
`/clear` 只清当前视图、不切换会话。
`/model` 打开模型选择器（输入即搜索，`↑`/`↓` 移动，`Enter` 应用，
`Esc` 取消）：选择只作用于本次 TUI 会话后续的 run（对齐桌面端 composer
的模型切换器，不写工作区默认），状态行与 `/status` 标注 `(session)`；
`/model <model_id>` 直接切换，`/model default` 回到目录默认。
新会话（启动、`/new`、`/clear`）会在上方显示欢迎横幅：Claude Code 风格的
红色块状像素猫（16×16 单色半块字符，眼睛/嘴巴用负形挖空）+
`CellWiki v0.1.0`、当前模型、工作区路径与 `| Using … · /model` 提示；
发出第一条消息或 `/resume` 后收起，窄终端退化为文字行。
Python 终端界面已退役；
`cellwiki dev`、`cellwiki serve` 与 `cellwiki daemon *` 仍由 Python 提供。

`cellwiki serve [--workspace PATH] [--detach]` 前台或后台运行 daemon；
`cellwiki daemon status|stop|restart --workspace PATH` 管理生命周期。daemon 只
监听 `127.0.0.1`，发现文件与控制 token 位于用户状态目录
（`$XDG_RUNTIME_DIR` 优先，否则 `~/.cellwiki`）且权限 0600。

终端客户端当前覆盖对话、提问、审批、运行控制、模型与上下文显示；附件、
线程重命名/删除、工作区浏览/搜索/编辑、设置与记忆面板按后续计划补齐。

## 开发环境

要求：Windows 10/11、Python 3.12、Node.js 22+、Rust/Tauri Windows 构建依赖，以及推荐的 `uv`。

```powershell
cd D:\GitHub\CellWiki
uv sync --extra dev --extra desktop
Set-Location frontend
npm ci
Set-Location ..
Copy-Item .env.example .env
```

开发态启动：

```powershell
.venv\Scripts\cellwiki.exe dev
```

旧版 CLI 与 LangGraph 调试入口已退役；当前开发态只由 `cellwiki dev` 编排 Product API 与桌面端，正式使用路径仍是工作区与 Agent。

模型供应商在桌面端“设置 → 模型服务”中管理（支持多个供应商，各含模型清单，配置免重启生效，对话框可切换当前模型）；开发态 `.env` 的 `OPENAI_*` 会在首次使用时自动导入为默认供应商，并保留为目录为空时的兜底。日志级别和界面语言也在“设置”中修改。发布态优先使用 Windows Credential Manager 保存 API Key。

## Windows Beta

发布版由 Tauri 启动打包的 Python sidecar，不要求最终用户安装源码、Python、Node.js 或 Rust。当前安装包尚未签名；发布前应完成后端测试、前端测试与构建、打包 sidecar 健康检查以及干净 Windows 环境安装验收。

## 公开文档

- [领域词汇与约束](CONTEXT.md)
- [贡献与开发指南](CONTRIBUTING.md)
- [安全假设、数据隐私与漏洞报告](SECURITY.md)
- [版本变化](CHANGELOG.md)
