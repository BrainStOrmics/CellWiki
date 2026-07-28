# 贡献与开发指南

CellWiki 目前处于 Windows Beta 候选阶段。所有变更应保持来源可追溯、正式知识受治理、项目数据不跨项目泄漏。

## 开始前

1. 阅读 [README.md](README.md)、[CONTEXT.md](CONTEXT.md) 和 [SECURITY.md](SECURITY.md)。
2. 涉及领域或架构约束时，以 `CONTEXT.md`、当前代码合同和测试为依据；不要仅依据本地历史材料实现功能。
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

开发态由 `cellwiki.exe dev` 编排本地服务；发布态由 Tauri 启动打包的 Python sidecar。涉及启动、关闭、认证或路径的变更必须分别验证两种运行方式。

## 代码变更规则

- 为非直观的意图、数据所有权、错误处理和安全限制写注释或 docstring；不要写逐行复述型注释。
- 不绕过 `ChangeSet -> Approval -> CentralWriter -> Verification` 修改正式知识。
- 新增或修改领域概念时同步更新 `CONTEXT.md`、合同测试和必要的迁移。
- 新增 provider 行为时同步更新公开说明、版本记录与回归测试。
- 不因一次任务顺手重构无关旧 Module；保持 diff 能追溯到明确需求。

## 测试

提交前运行与变更相称的验证。最低要求：

```powershell
.venv\Scripts\python.exe -m pytest -q

Set-Location frontend
npm test
npm run build
```

真实模型测试需要单独启用已配置的 provider，不应进入普通 pytest 或声称为 hosted CI 证据。

## 公开文档变更

- `README.md` 维护产品定位、能力边界、环境要求和公开导航。
- `CONTEXT.md` 维护领域词汇与不可违反的约束。
- `CONTRIBUTING.md` 维护公开开发流程。
- `SECURITY.md` 维护数据处理、安全假设、已知风险和漏洞报告方式。
- `CHANGELOG.md` 记录用户可见的版本变化。

新 Markdown 必须使用 UTF-8 和有效相对链接。改变用户可见行为、数据路径、模型供应商、发布流程或领域 Invariant 时，必须同步更新对应的公开文档。

## 提交与评审

- 按逻辑切分提交：领域/后端、前端、测试、文档和构建流程不要混为不可审查的大提交。
- 提交信息说明改变了什么以及为什么。
- Pull Request 应列出验证命令、是否需要迁移、是否影响数据/隐私/安全、以及文档是否已更新。
- 尚未建立 hosted CI 运行证据前，不要把本机测试结果描述为 CI 通过。
