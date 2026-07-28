# Agentic CellWiki

Agentic CellWiki 是一个本地优先的 Windows 桌面科学知识库：它把论文转化为带页码、文本块和来源定位的结构化 Claim；经人工审核后生成可追溯 Wiki，并允许用户在侧边与 WikiAgent 围绕页面、来源或选中文本协作。

> [!WARNING]
> 当前版本是未签名 Windows Beta 候选版。论文 chunk、Wiki 上下文和对话会发送给用户配置的 OpenAI-compatible 模型供应商；处理敏感或未发表资料前，请先阅读 [安全说明](SECURITY.md)。

## 核心工作流

```text
Source
  -> Parse and evidence-aware chunks
  -> Grounded extraction
  -> ChangeSet
  -> Human approval
  -> CentralWriter
  -> Formal knowledge, Wiki, search, graph and lint
```

正式知识只允许通过 `ChangeSet -> Approval -> CentralWriter -> Verification` 写入。Agent、Research 和 Lint 都不能绕过这条路径。

## 已具备能力

- PDF、Markdown 和 TXT 的来源登记、分页解析、证据定位、缓存、重试和取消。
- Claim、EvidenceReference、冲突识别、ReviewItem、ChangeSet、审批、发布、验证和回滚。
- React/Tauri 三栏桌面工作区：来源树、Wiki/证据/图谱、WikiAgent 对话。
- Deep Agents 运行时：持久 AgentRun、SSE、checkpoint、审批续跑、取消和重试。
- FTS5、KnowledgeGraph、受治理 Memory/Research 与 L2 semantic lint 第一版。
- 设置页中的模型配置、系统凭据、中文/英文和运行日志。

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
