# 变更记录

本项目采用 Keep a Changelog 的简化格式。版本号以 [`VERSION`](VERSION) 为唯一来源；每个可交付版本的安装包证据由 release manifest 生成。

## Unreleased

### Added

- 自包含的公开产品入口、贡献指南、安全与隐私说明和版本记录。
- 文档检查与 release manifest 自动化入口。

### Changed

- 公开入口文档不再依赖未随代码仓库分发的本地项目与设计文档。
- 发布说明不再手工维护固定安装包哈希。
- 旧 CLI、顶层兼容壳、`:2024` LangGraph 调试服务及其旧专用依赖已退役；只保留 `cellwiki` 与 `cellwiki-sidecar` 两个 Python 入口。
- 工具面由 `_CellWikiToolBoundaryMiddleware` 的 allowlist 单层承重；框架侧 `HarnessProfile.excluded_tools` 已退役（零独有职责，且按名误删白名单工具）。

### Removed

- 删除旧治理链（ChangeSet / Approval / CentralWriter / snapshot / ingest 管线 / memory / research / TaskRouter / SearchIndex / KnowledgeGraph）及旧 CLI、顶层兼容壳和 `:2024` LangGraph 调试入口；当前版本以 git 承载版本与审批。
- Wiki renderer 不再生成指向已退役 `relationships.json`、`graph.dot`、`graph.mmd` 的链接。
- 删除无调用者的读工具 `get_project_status`、`search_wiki`、`read_wiki_page`（自 git 治理重构后就不在白名单与组装列表里）；前端三张工具卡保留，仅供历史 transcript 渲染。

## 2.0.0-beta

> 本节保留该 beta 阶段的历史能力记录；其中 ChangeSet / CentralWriter / FTS5 / KnowledgeGraph 等旧治理链已在此后版本删除，当前能力以 README 与代码为准。

### Added

- Tauri 桌面工作区与 Python sidecar。
- Deep Agents WikiAgent、持久 AgentRun、SSE、审批续跑、取消和重试。
- 基于 SourceRecord、Claim、EvidenceReference 和 ChangeSet 的受治理 ingest。
- CentralWriter 原子发布、快照、验证和回滚。
- FTS5、KnowledgeGraph、受治理 Memory/Research 与 L2 semantic lint 第一版。

### Known limitations

- 安装包未签名，干净 Windows VM 验收待完成。
- PDF 解析主要基于 pdfplumber，复杂布局可能失真。
- OpenAI-compatible 模型供应商在结构化输出、工具调用、超时和上下文限制方面存在差异，接入前需要单独验证。
