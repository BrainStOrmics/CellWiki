# cellwiki-tui

CellWiki 终端客户端（TypeScript + Ink + React），通过 Product API 与本地
daemon 通信。要求 Node.js >= 22。

## 快速开始

```bash
# 1. 安装 Python CLI（含 cellwiki 命令）
uv tool install /path/to/CellWiki

# 2. 安装终端客户端（npm 上没有公开包，用本地 link）
cd /path/to/CellWiki/terminal
npm ci
npm run build
npm link          # 生成全局 cellwiki-tui 命令

# 3. 进入知识库目录并启动
cd /path/to/knowledge-base
cellwiki
```

`cellwiki`（Python 包）无子命令时会查找 `cellwiki-tui` 并交接；未安装时提示
先执行上面的 `npm link`。daemon 由 Python 的 `cellwiki serve` 提供，TS 客户端
只消费发现文件与 Product API。

终端不提供供应商设置界面，模型配置写在知识库根目录的 `.env` 里：

```dotenv
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://your-provider/v1
OPENAI_MODEL=your-model-id
OPENAI_API_PROTOCOL=chat_completions
```

`OPENAI_API_PROTOCOL` 可取 `chat_completions`、`responses` 或 `anthropic`。daemon 首次
使用时把它自动导入为默认供应商。终端只读知识库自己的 `.env`，桌面端保存的供应商配置
不会自动带过来。

## 常用操作

### 会话

- 启动后默认是新会话，不自动接续最近一次对话。
- `/resume` 打开可搜索的会话选择器：输入过滤，`↑`/`↓` 移动，`Enter` 恢复，`Esc` 取消。
- `/new` 清屏并开始新会话，旧会话仍可在 `/resume` 里找回。
- `/clear` 只清当前视图，不切换会话。
- 输入框边框右上角显示当前会话标题；新会话显示工作区名，首条消息发出后才创建 thread。

### 命令

- `/help` 显示命令与按键列表。
- `/status` 显示工作区、模型、run 与上下文状态。
- `/context` 显示最近一次模型调用的上下文读数。
- `/continue` 续跑一个中断的 run。
- `/retry` 重放一个失败的 run。
- `/cancel [id]` 放弃占住工作区的 run。
- `/diff` 重新打开待确认 diff 的审批界面。
- `/model [id]` 选择本次会话使用的模型（只作用于当前 TUI 会话，不改工作区默认）。
- `/theme` 打开主题选择器。
- `/quit` 退出 TUI，daemon 继续在后台运行。

### 审批与提问

- 待确认 diff 是内联数字键提示：`1` 接受、`2` 拒绝、`3` 查看完整 diff、`Esc` 稍后。
- 提问同样是内联数字键，可用 `↑`/`↓` + `Enter` 选择，也可直接输入编号或自由文本。
- 审批前会重新拉取补丁，同一单元在审批期间被刷新会要求重新确认。
- 审批期间输入框只响应上述按键，已输入的草稿保留到审批结束。

### 输入与滚动

- `@` 触发工作区文件补全，最多显示 8 个候选。
- `Esc` 打断当前运行的模型请求。
- 忙时按 `Enter` 排队消息，`Ctrl+U` 撤回排队消息。
- `Ctrl+P`/`Ctrl+N` 翻阅输入历史。
- fullscreen 下 `↑`/`↓` 单行滚动，`PgUp`/`PgDn` 半屏滚动，`Ctrl+Home`/`Ctrl+End` 跳到最早/最新。
- 滚离底部后暂停自动跟随，顶部提示新增行数；`PgDn` 或 `Ctrl+End` 恢复跟随。

### 显示

- 交互式终端默认 fullscreen（alternate screen），输入框固定底部，对话在固定 viewport 内窗口化显示。
- fullscreen 不保留主屏 scrollback，终端原生搜索与复制不可用；需要时用 `cellwiki-tui --classic` 或 `CELLWIKI_TUI_CLASSIC=1` 退回经典渲染。
- 鼠标滚轮未启用，保留终端原生选择。
- 用户消息显示为 `❯` 行，助手消息以 `●` 开头，run 结束行显示 `✻ done in Ns · HH:MM`。
- 助手消息按终端 Markdown 子集渲染：`**加粗**`、`*斜体*`、行内代码、链接、标题、列表、引用、代码块；表格与图片不渲染。
- 行内代码与代码块使用主题的 `code` 色（不是 dim）。
- 新会话显示欢迎横幅：终端猫形象、版本、当前模型、工作区路径与 `| Using … · /model` 提示；发出第一条消息或 `/resume` 后收起，窄终端退化为文字行。

### 主题

- `/theme` 打开主题选择器：`↑`/`↓` 实时预览，`Enter` 应用并写入 `~/.cellwiki/tui.json`，`Esc` 取消。
- 内置预设：`auto`（按终端背景选深浅）、`dark`、`light`、`dark-daltonized`、`light-daltonized`、`dark-ansi`、`light-ansi`。
- 配色覆盖输入框、对话、审批卡与状态行；`CELLWIKI_TUI_THEME` 环境变量优先于配置文件。
- dark 主题主色为紫色 `#B1B9F9`，light 主题使用深紫变体；每个预设的 `code` 与主色取同一值。

### 上下文读数

- `/context` 显示当前会话最近一次模型调用的上下文读数，字段来自服务端
  `GET /api/agent/threads/{thread_id}/context-usage`。
- 输出形如 `26.7k / 65.5k · compact 32.5k · fallback 65.5k · retain 8.5k`。
- 上限使用服务端解析后的 `effective_context_limit`，不把全局 `AGENT_CONTEXT_MAX_TOKENS`
  当成模型真实窗口。
- `fallback` 表示模型未声明 `max_input_tokens`；当前安全窗口为 `65.5k`。
- 压缩完成后显示摘要化结果，例如 `context compacted 240.6k -> 18.2k (assistant group)`；
  `summary only` 表示没有可保留的完整消息组。

## daemon 管理

daemon 每个工作区一个常驻进程，由 Python 侧提供：

```bash
cellwiki serve --workspace /path/to/knowledge-base --detach
cellwiki daemon status  --workspace /path/to/knowledge-base
cellwiki daemon restart --workspace /path/to/knowledge-base
cellwiki daemon stop    --workspace /path/to/knowledge-base
```

- TUI 发现缺失或陈旧的 daemon 时会自动拉起 `cellwiki serve --detach`。
- daemon 只监听 `127.0.0.1`；发现文件与控制 token 位于
  `$XDG_RUNTIME_DIR/cellwiki/daemon/<workspace-hash>/`（不可用时回退
  `~/.cellwiki/daemon/<workspace-hash>/`），权限 0600。
- daemon 日志位于工作区 `data/runtime/logs/daemon.log`，启动失败详情在同一 daemon 状态目录的 `launch.log`。
- 版本不匹配时 TS 客户端会停下并提示：按 `r` 重启 daemon，按 `q` 退出；重启会中断存在的活动 run。

## 尚未覆盖

- 附件上传、线程重命名/删除、工作区浏览/搜索/编辑、设置与记忆面板。
- 鼠标滚轮、终端内选择与 transcript 视图。

## 开发

```bash
npm ci
npm run typecheck
npm test
npm run build
npm link          # 生成全局 cellwiki-tui 命令
```

### 真实 daemon smoke

```bash
CELLWIKI_CLI=/path/to/.venv/bin/cellwiki npm run smoke
```

脚本会创建临时工作区、拉起 daemon、连接 API、跑一个指向无效本地端点的
失败 run（验证真实 SSE），最后停止 daemon。

### 结构

- `src/api/`：HTTP 与 SSE 客户端。
- `src/daemon/`：发现文件、token、健康检查与自动拉起。
- `src/controller.ts`：run/thread/gate/queue 状态与副作用。
- `src/components/`：Ink 界面（Static transcript、live 流式、审批、提问、
  composer、状态栏）。
- `tests/`：Vitest 单测与 ink-testing-library 流程测试。
