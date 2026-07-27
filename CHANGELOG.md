# 变更记录

本项目采用 Keep a Changelog 的简化格式。版本号以 [`VERSION`](VERSION) 为唯一来源；每个可交付版本的安装包证据由 release manifest 生成。

## Unreleased

### Added

- Agentic CellWiki 文档治理：正式文档索引、架构、路线图、测试、隐私、供应商兼容、故障恢复和安全说明。
- `design/` 的 active/research/archive 分类和文档状态元数据。
- 文档检查与 release manifest 自动化入口。

### Changed

- README 改为项目入口和文档导航；当前事实转移到 `docs/`。
- 发布说明不再手工维护固定安装包哈希。
- 产品 CLI、抽取、投影和领域模型已与旧 CLI/图工作流分离；旧实现集中到 `cellwiki.legacy`，默认 `cellwiki` 入口只启动桌面产品运行时。
- WikiAgent 使用精确 Deep Agents HarnessProfile 隐藏通用文件/TODO 工具，并通过 `submit_agent_answer` 在不强制 `tool_choice` 的前提下校验结构化最终回答。

## 2.0.0-beta

### Added

- Tauri 桌面工作区与 Python sidecar。
- Deep Agents WikiAgent、持久 AgentRun、SSE、审批续跑、取消和重试。
- 基于 SourceRecord、Claim、EvidenceReference 和 ChangeSet 的受治理 ingest。
- CentralWriter 原子发布、快照、验证和回滚。
- FTS5、KnowledgeGraph、受治理 Memory/Research 与 L2 semantic lint 第一版。

### Known limitations

- 安装包未签名，干净 Windows VM 验收待完成。
- PDF 解析主要基于 pdfplumber，复杂布局可能失真。
- 模型供应商能力存在差异，详见 [docs/provider-compatibility.md](docs/provider-compatibility.md)。
