# cellwiki-tui

CellWiki 终端客户端（TypeScript + Ink + React），通过 Product API 与本地
daemon 通信。要求 Node.js >= 22。

## 开发

```bash
npm ci
npm run typecheck
npm test
npm run build
npm link          # 生成全局 cellwiki-tui 命令
```

`cellwiki`（Python 包）无子命令时会查找 `cellwiki-tui` 并交接；未安装时给出
`npm install -g cellwiki-tui` 提示。daemon 由 Python 的 `cellwiki serve`
提供，TS 客户端只消费发现文件与 Product API。

## 真实 daemon smoke

```bash
CELLWIKI_CLI=/path/to/.venv/bin/cellwiki npm run smoke
```

脚本会创建临时工作区、拉起 daemon、连接 API、跑一个指向无效本地端点的
失败 run（验证真实 SSE），最后停止 daemon。

## 结构

- `src/api/`：HTTP 与 SSE 客户端。
- `src/daemon/`：发现文件、token、健康检查与自动拉起。
- `src/controller.ts`：run/thread/gate/queue 状态与副作用。
- `src/components/`：Ink 界面（Static transcript、live 流式、审批、提问、
  composer、状态栏）。
- `tests/`：Vitest 单测与 ink-testing-library 流程测试。
