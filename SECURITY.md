# 安全说明

## 支持范围

CellWiki 当前为未签名 Windows Beta。安全修复以当前 `main` 的后续版本为准；尚未承诺长期支持分支。

## 报告漏洞

请不要在公开 issue 中披露可利用细节、API Key、论文原文、患者数据、token 或本机路径。向项目维护者私下提供：

- 影响范围和复现步骤。
- CellWiki 版本、Windows 版本和是否为发布态。
- 已脱敏日志。
- 最小复现来源；不要附带受限或敏感论文。

维护者应先确认问题，再决定修复、回归测试、发布说明和公开披露时间。

## 当前安全假设

- 发布态 sidecar 仅绑定 `127.0.0.1`。
- Tauri 在每次启动时生成 bearer token；写请求需要该 token。
- API Key 优先存放在 Windows Credential Manager，界面只显示是否已配置和脱敏提示。
- 日志 formatter 会脱敏常见 Authorization 与 API Key 形式。
- Agent、Research、Memory 和 Lint 不能绕过 ChangeSet 与人工 Approval 直接写入正式知识。
- 项目数据保存在操作系统应用数据目录，不与安装目录混用。

## 已知风险

- OpenAI-compatible 模型调用会把输入 chunk 发送到用户配置的外部提供商。
- PDF、Markdown 和外部来源可能包含恶意指令、异常文件或不可靠科学主张。
- 目前安装包未代码签名，Windows SmartScreen 可能提示风险。
- 目前没有完整的项目级一键安全删除界面。
- 依赖升级、SBOM、自动更新和干净 VM 安装验证尚未成为正式发布门禁。

数据传输、保留和删除规则见 [docs/data-and-privacy.md](docs/data-and-privacy.md)；运行安全细节见 [docs/architecture.md](docs/architecture.md)。
