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

## 上下文读数

`/context` 显示当前会话最近一次模型调用的上下文读数，字段来自服务端
`GET /api/agent/threads/{thread_id}/context-usage`：

```text
26.7k / 65.5k · compact 32.5k · fallback 65.5k · retain 8.5k
```

- 上限使用服务端解析后的 `effective_context_limit`，不把全局
  `AGENT_CONTEXT_MAX_TOKENS` 当成模型真实窗口。
- `fallback` 表示模型未声明 `max_input_tokens`；当前安全窗口为 `65.5k`。
- 压缩完成后显示摘要化结果，例如
  `context compacted 240.6k -> 18.2k (assistant group)`；`summary only` 表示
  没有可保留的完整消息组。

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
