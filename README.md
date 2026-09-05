# Agentic CellWiki

Agentic CellWiki 是一个本地优先的 Windows 桌面科学 Wiki：**你选定的工作目录就是知识库**。
系统为它初始化 git 仓库并建好 `wiki/`、`raw/` 与根级维护文件；WikiAgent 在同一工作区内
阅读与编辑，系统负责派生文件与阻断式门禁，**每次正式变更由人工逐条判定 diff**。

> [!WARNING]
> 当前版本是未签名 Windows Beta 候选版。论文 chunk、Wiki 上下文和对话会发送给用户配置的 OpenAI-compatible 模型供应商；处理敏感或未发表资料前，请先阅读 [安全说明](SECURITY.md)。

## 核心工作流

```text
工作区（一个 git 仓库 = 知识库）
  -> 附件晋升或预置 raw/ 扫描登记，成为可追溯正式源
  -> Agent run：白名单工具读、写、lint、add、commit
  -> 审批单元 diff_<run_id>_<n>（一行一次判定）
  -> 用户接受（审计生效）或拒绝（只 revert 本单元）
```

正式知识只允许通过 `Run -> 待确认 diff -> 用户接受` 写入：git 承载版本与审批，历史永不改写
（见 `docs/adr/0007-git-carries-versioning-and-approval.md`）。运行严格串行：同一时刻最多一个
活动 run 与一个未判定 diff，未判定期间新 run（包括只读 run）不启动。当前实现说明见
`docs/architecture.md`，长期决策理由见 `docs/adr/`。

## 已具备能力

- **来源与导入**：附件（pdf/md/txt）上传后由服务端提取文本，run 内按范围读取并受 run 级读取
  预算约束；经用户确认后 `promote_attachment` 晋升为 `raw/<source_id>/` 正式源，`ingest_sources`
  按工作区 `schema.md` 生成草稿页。用户直接放进 `raw/` 的预置源由产品侧「扫描并登记」幂等登记，
  不复制文件、不产生 git 变更。
- **工作区浏览与受控编辑**：Obsidian 式文件树、md/txt/PDF 只读预览、页面全文搜索（当前实现是
  对 `wiki/` 的扫描）；界面编辑合成 `workspace_edit` run，同样经待确认 diff 生效。
- **Agent 协作**：持久 AgentRun 与 SSE 事件流、工具时间线与思考行、`ask_user_question` 提问卡片
  与续跑、取消、重试与 `/diagnostics` 诊断；会话登记表使新建会话与零 run 会话即时可见、可回访。
- **治理门禁**：Agent 只能用白名单工具与白名单 git 动作（改写历史的命令一律拒绝）、受路径沙箱
  约束、`lint_knowledge_base` 仅报告不修复；`log.md`、`audit_report.md`、`overview.md`、
  `statistics.md` 由系统维护提交，Agent 不得改写。
- **桌面与配置**：React/Tauri 三栏工作台；发布态由 Tauri 启动本地 sidecar（仅绑定 `127.0.0.1`，
  启动期随机端口与 bearer token，写请求需带令牌）；设置页管理模型 Base URL、模型 ID、API Key、
  日志级别与中英界面，API Key 优先存 Windows Credential Manager。

**尚未落地，不要按这些预期使用**：跨进程持久化 checkpoint（
`docs/adr/0010-run-scoped-persistent-checkpointer.md` 已接受但实现未合入，当前 checkpoint 只存在于
进程内）、子 Agent 委托（注册表为空）、安装包代码签名与干净 VM 外部验收。完整清单见
`docs/architecture.md`「当前限制」。

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

旧版 CLI 和 LangGraph 调试工作流只通过 `.venv\Scripts\cellwiki-legacy.exe` 显式调用；它们是迁移期兼容能力，不属于桌面产品入口。

模型 Base URL、model ID、API Key、日志级别和界面语言也可以在桌面端“设置”中修改。发布态优先使用 Windows Credential Manager 保存 API Key。

## Windows Beta

发布版由 Tauri 启动打包的 Python sidecar，不要求最终用户安装源码、Python、Node.js 或 Rust。当前安装包尚未签名；发布前应完成后端测试、前端测试与构建、打包 sidecar 健康检查以及干净 Windows 环境安装验收。

## 公开文档

- [领域词汇与约束](CONTEXT.md)
- [贡献与开发指南](CONTRIBUTING.md)
- [安全假设、数据隐私与漏洞报告](SECURITY.md)
- [版本变化](CHANGELOG.md)
