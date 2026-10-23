# Agentic CellWiki

Agentic CellWiki 是一个本地优先的科学 Wiki：**你选定的工作目录就是知识库**。
系统为它初始化 git 仓库并建好 `wiki/`、`raw/` 与根级维护文件；WikiAgent 在同一工作区内
阅读与编辑，系统负责派生文件与阻断式门禁，**每次正式变更由人工逐条判定 diff**。

桌面端与 TUI 是同一个本地运行时的两个客户端，操作的是同一批知识库。

> [!WARNING]
> 当前版本是未签名 Windows Beta 候选版。论文 chunk、Wiki 上下文和对话会发送给用户配置的
> 模型供应商（OpenAI 兼容协议或原生 Anthropic）；处理敏感或未发表资料前，请先阅读
> [安全说明](SECURITY.md)。

## 快速开始

系统提供两个入口：**桌面端只支持 Windows**，**TUI 支持 Windows 与 Linux**。
完整安装、构建和接口开放步骤见 [部署指南](DEPLOYMENT.md)。

| 入口 | 平台 | 指南 |
| --- | --- | --- |
| 桌面端 | Windows | [构建与安装](DEPLOYMENT.md#windows-桌面端) |
| TUI | Linux | [Linux 完整 1–10 步](DEPLOYMENT.md#linux-tui) |
| TUI | Windows | [Windows TUI](DEPLOYMENT.md#windows-tui) |

### TUI 最小启动（Linux）

前置工具为 Git、[uv](https://docs.astral.sh/uv/) 和 Node.js 22+。首次部署必须使用
`main` 分支。

1. **取得源码并安装 CLI 与 TUI。**

   ```bash
   git clone -b main https://github.com/BrainStOrmics/CellWiki.git
   cd CellWiki
   uv python install 3.12
   uv tool install "$PWD"
   cd terminal
   npm ci
   npm run build
   npm link
   cd ..
   ```

2. **建立知识库并复制页面契约。** `schema.md` 由用户自己放入工作目录：

   ```bash
   mkdir -p "$HOME/kb/my-kb"
   cp schema.md "$HOME/kb/my-kb/schema.md"
   ```

3. **配置模型。** TUI 从知识库根目录的 `.env` 读取供应商配置：

   ```dotenv
   OPENAI_API_KEY=...
   OPENAI_BASE_URL=https://your-provider/v1
   OPENAI_MODEL=your-model-id
   OPENAI_API_PROTOCOL=chat_completions
   ```

   把文件保存为 `~/kb/my-kb/.env`，并限制权限：

   ```bash
   chmod 600 "$HOME/kb/my-kb/.env"
   ```

4. **启动 TUI。**

   ```bash
   cd "$HOME/kb/my-kb"
   cellwiki
   ```

   首次启动会自动初始化 git、`wiki/`、`raw/` 和根级维护文件。TUI 没有附件上传，
   需要手工把来源放进 `raw/<source_id>/`；完整投料、审批和注释接口步骤见
   [Linux TUI 部署](DEPLOYMENT.md#linux-tui)。

完整 TUI 命令与按键见 [TUI 命令与按键](#tui-命令与按键)。

## 工作区结构

选定目录后由系统初始化，你不需要手工建：

```text
my-kb/
├── wiki/                 # Agent 维护的知识页面，按 schema.md 的页面类型分目录
├── raw/                  # 原始论文，一个来源一个目录，纳入 git
├── schema.md             # 页面提取契约：你自己放入，Agent 只读
├── index.md              # 导航正文（Agent 维护）
├── contradictions.md     # 矛盾台账（Agent 维护）
├── overview.md           # 概览（系统重建）
├── statistics.md         # 统计（系统重建）
├── log.md                # 判定记录（系统追加）
├── audit_report.md       # 审计报告（系统追加）
├── .gitignore            # 运行时产物与本地凭据的边界
└── data/runtime/         # 运行库与检查点，不进版本库
```

文件归属是硬约束：

- Agent 可读写整个工作区，但 `schema.md`、`log.md`、`audit_report.md` 只读，
  `overview.md` 与 `statistics.md` 由系统重建。
- git 历史永不改写，撤销只允许 `revert`。
- 正式知识只能经 `Run → 待确认 diff → 用户接受` 写入。
- run 严格串行：同一时刻最多一个活动 run 和一个未判定的待确认 diff；存在未判定 diff 时，
  新 run（包括只读查询）不启动。

## 核心工作流

```text
工作区（一个 git 仓库 = 知识库）
  -> 附件经用户确认后晋升为 raw/<source_id>/ 正式源
  -> Agent run：白名单工具读、写、lint、add、commit
  -> 审批单元 diff_<run_id>_<n>（一行一次判定）
  -> 用户接受（审计生效）或拒绝（只 revert 本单元）
```

## 能力与边界

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
- **注释证据接口**：同机只读接口 `POST /api/v1/annotation-support`，把已提交且已人工审批的知识
  按 Marker 与背景投影成候选类型和可追溯文献证据，供外部注释 Agent 取用；独立令牌鉴权、
  不调用模型、不写知识库，最终标签与置信度仍由调用方决定。接入方式见
  [注释证据接口接入说明](ANNOTATION_API.md)。

Agent 的工具面固定为 13 个：`glob`、`grep`、`read_file`、`write_file`、`edit_file`、
`delete_file`、`rename_file`、`git`、`run_powershell`、`lint_knowledge_base`、
`ask_user_question`、`read_attachment`、`promote_attachment`。开启工作区记忆时额外开放
`list_memory`、`read_memory`、`search_memory`、`add_ad_hoc_note`。

**尚未落地，不要按这些预期使用**：子 Agent 委托（注册表为空）、MCP 适配
（已接受、暂缓实施）、安装包代码签名与干净 VM 外部验收。

## 数据与隐私

- 桌面端数据目录：`%APPDATA%\org.brainstormics.cellwiki\CellWikiData`（`projects/default`、
  `logs`、`runtime`、`cache`、`backups`、`config`）。日志在 `logs\cellwiki-sidecar.log`。
- 知识库目录（`wiki/`、`raw/`、根级 md、git 历史）完全由你选定的位置决定，不写入应用数据目录。
- 所有服务只监听 `127.0.0.1`；桌面 sidecar 用启动期 bearer token 保护写请求，daemon 的控制
  token 存在用户状态目录且权限 0600。
- 论文 chunk、Wiki 上下文与对话会发给你配置的模型供应商；API Key 优先存操作系统凭据库，
  日志对密钥与 Authorization 脱敏。
- 升级前自动备份到 `backups\upgrade-*.zip`；卸载不删应用数据。

更多细节见 [安全说明](SECURITY.md)。

## TUI 命令与按键

终端客户端只覆盖对话、提问、审批、运行控制、模型与上下文显示；附件、线程重命名/删除、
工作区浏览/搜索/编辑、设置与记忆面板尚未实现。

- `/help` 命令与按键列表，`/new` 新会话，`/resume` 恢复历史会话，`/status` 运行状态，
  `/context` 上下文读数。
- `/continue` 续跑中断的 run，`/retry` 重试失败的 run，`/cancel` 放弃占住工作区的 run。
- `/diff` 重新打开待确认 diff，`/model` 切换本次会话的模型，`/theme` 切换配色，`/quit` 退出
  （daemon 继续在后台运行）。
- 待确认 diff 与提问是内联数字键：`1` 接受、`2` 拒绝、`3` 查看完整 diff、`Esc` 稍后。
- `@` 触发工作区文件补全，`Esc` 打断运行，忙时 `Enter` 排队、`Ctrl+U` 撤回。
- daemon 每个工作区一个常驻进程，只监听 `127.0.0.1`；用
  `cellwiki daemon status|stop|restart --workspace PATH` 管理。

完整说明（含主题、渲染与排障）见 [终端客户端说明](terminal/README.md)。

## 开发环境

要求：Windows 10/11、Python 3.12、Node.js 22+、Rust/Tauri Windows 构建依赖，以及推荐的 `uv`。

```powershell
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

旧版 CLI 与 LangGraph 调试入口已退役；当前开发态只由 `cellwiki dev` 编排 Product API 与桌面端，
正式使用路径仍是工作区与 Agent。

模型供应商在桌面端「设置 → 模型服务」中管理（支持多个供应商，各含模型清单，配置免重启生效，
对话框可切换当前模型）；开发态 `.env` 的 `OPENAI_*` 会在首次使用时自动导入为默认供应商，
并保留为目录为空时的兜底。日志级别和界面语言也在「设置」中修改。发布态优先使用 Windows
Credential Manager 保存 API Key。

测试与质量门禁：

```powershell
.venv\Scripts\python.exe -m pytest -q
uv run ruff check src tests
uv run mypy src
Set-Location frontend
npm test
npm run build
```

终端客户端另有 `npm run typecheck` 与 `npm test`（见 [terminal/README.md](terminal/README.md)）。
本机 `.env` 若设置 `AUTO_ACCEPT_PENDING_DIFFS=true`，会改变待确认 diff 的测试预期。

## 公开文档

- [领域词汇与约束](CONTEXT.md)
- [贡献与开发指南](CONTRIBUTING.md)
- [安全假设、数据隐私与漏洞报告](SECURITY.md)
- [版本变化](CHANGELOG.md)
- [部署指南](DEPLOYMENT.md)
- [注释证据接口接入说明](ANNOTATION_API.md)
