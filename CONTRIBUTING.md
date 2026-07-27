# 贡献与开发指南

CellWiki 目前处于 Windows Beta 候选阶段。所有变更应保持来源可追溯、正式知识受治理、项目数据不跨项目泄漏。

## 开始前

1. 阅读 [README.md](README.md)、[CONTEXT.md](CONTEXT.md) 和 [正式文档索引](docs/README.md)。
2. 涉及架构约束时先阅读 [ADR](docs/adr/)；不要仅依据 `design/archive/` 中的历史方案实现功能。
3. 保持真实 `.env`、本地运行数据、构建产物和虚拟环境不进入 Git。

## 本地环境

```powershell
uv sync --extra dev --extra desktop
Set-Location frontend
npm ci
Set-Location ..
Copy-Item .env.example .env
```

开发态统一入口：

```powershell
.venv\Scripts\cellwiki.exe dev
```

发布态和开发态的进程拓扑不同，详见 [architecture.md](docs/architecture.md)。

## 代码变更规则

- 为非直观的意图、数据所有权、错误处理和安全限制写注释或 docstring；不要写逐行复述型注释。
- 不绕过 `ChangeSet -> Approval -> CentralWriter -> Verification` 修改正式知识。
- 新增或修改领域概念时同步更新 `CONTEXT.md`、合同测试和必要的迁移。
- 新增 provider 行为时同步更新 [provider-compatibility.md](docs/provider-compatibility.md) 与回归测试。
- 不因一次任务顺手重构无关旧 Module；保持 diff 能追溯到明确需求。

## 测试

提交前按 [testing.md](docs/testing.md) 运行与变更相称的验证。最低要求：

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\check_docs.py

Set-Location frontend
npm test
npm run build
```

真实模型测试需要单独启用已配置的 provider，不应进入普通 pytest 或声称为 hosted CI 证据。

## 文档变更

文档遵循 [governance.md](docs/governance.md)：

- `docs/` 描述当前实现和操作方法。
- `design/active/` 保存尚未接受的提案。
- `design/research/` 保存外部调研。
- `design/archive/` 保留历史，不可作为当前实现依据。

新 Markdown 必须使用 UTF-8、frontmatter 和有效相对链接。改变用户可见行为、数据路径、模型供应商、发布流程或领域 Invariant 时，必须同步更新对应的唯一真相源文档。

## 提交与评审

- 按逻辑切分提交：领域/后端、前端、测试、文档和构建流程不要混为不可审查的大提交。
- 提交信息说明改变了什么以及为什么。
- Pull Request 应列出验证命令、是否需要迁移、是否影响数据/隐私/安全、以及文档是否已更新。
- 尚未建立 hosted CI 运行证据前，不要把本机测试结果描述为 CI 通过。
