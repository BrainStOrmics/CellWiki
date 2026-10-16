# 变更记录

本项目采用 Keep a Changelog 的简化格式。版本号以 [`VERSION`](VERSION) 为唯一来源；每个可交付版本的安装包证据由 release manifest 生成。

## Unreleased

### Added

- 终端客户端新会话显示欢迎横幅：Claude Code 风格的红色块状像素猫
  （16×16 单色半块字符，眼睛/嘴巴用负形挖空）+ `CellWiki v0.1.0`、
  当前模型、工作区路径与 `| Using … · /model` 提示；发出第一条消息或
  `/resume` 后隐藏，`/new` 与 `/clear` 恢复；窄终端退化为纯文字行。
- 终端客户端 `/model` 升级为会话级模型选择器：列出目录里启用的
  provider/model，支持输入即搜索、`↑`/`↓` 移动、`Enter` 应用、`Esc`
  取消；选择随 `POST /api/agent/runs` 的 `model` 字段下发（对齐桌面端
  composer 的 ModelSwitcher），不写工作区默认；`/model <model_id>` 直接
  切换、`/model default` 清除覆盖，状态行与 `/status` 标注 `(session)`。
- 终端客户端新增主题切换：`/theme` 选择器支持 `↑`/`↓` 实时预览、
  `Enter` 持久化到 `~/.cellwiki/tui.json`、`Esc` 还原；内置 `auto`
  （按终端背景选深浅）、`dark`、`light`、`dark-daltonized`、
  `light-daltonized`、`dark-ansi`、`light-ansi`，配色覆盖输入框、对话、
  审批卡与状态行；`CELLWIKI_TUI_THEME` 优先于配置文件。
- 终端客户端新增助手消息的终端 Markdown 子集渲染：`**加粗**`、`*斜体*`、
  行内代码、链接、标题、列表（`• `）、引用（`│ `）与代码块；样式按显示
  宽度折行，流式输出同源渲染；表格、图片与 HTML 不渲染。
- 自包含的公开产品入口、贡献指南、安全与隐私说明和版本记录。
- 文档检查与 release manifest 自动化入口。
- 设置页工作区记忆面板新增文件视图：可直接查看只读的
  `memory_summary.md` 与 `MEMORY.md`，并从话题文件查看、编辑或删除成型记忆。
- 工作区记忆新增后台自动提取：普通终态会话默认在空闲 4 小时后进入持久化
  `memory_jobs` 调度；“记住/更正”等显式信号仍走高优先级快速路径，进程重启可恢复
  未完成的提取任务。
- 新增 CellWiki 侧只读注释证据接口 `POST /api/v1/annotation-support`：用独立
  `CELLWIKI_ANNOTATION_API_TOKEN` 鉴权（未配置时禁用），只投影已提交且已批准的
  schema/Wiki 知识，确定性返回候选与可追溯文献证据；`support_score` 恒为
  `null`。调用方（CellHashtag）接入、端口发现、最终注释与生物学准确率评估仍
  待后续工作，本版本不作任何准确率承诺。
- 新增本地 daemon（`cellwiki serve`）与 TypeScript/Ink 终端客户端
  （`terminal/` + `cellwiki-tui`，Node >= 22）：每个工作区一个常驻运行时，
  只监听 loopback，发现文件与控制 token 位于用户状态目录（0600）；`cellwiki`
  无子命令把终端 UI 交给 `cellwiki-tui`，支持单列 scrollback、流式与工具行、
  内联提问与 pending diff 审批、`/` 命令、`@` 文件补全、`Esc` 打断与忙时
  排队。Python 终端界面已退役；`cellwiki dev`、`cellwiki serve` 与桌面
  sidecar 行为不变。

### Changed

- 终端客户端 `/new` 现在清空屏幕并开始新会话：清空 transcript、重置
  thread/run/usage/queue 状态并回到 `run idle`（旧会话仍可用 `/resume`
  找回）；`/clear` 保持只清视图的语义。
- 终端客户端主色统一：每个主题预设的 `code`（Markdown 行内代码/代码块）
  与 `claude`（主色）取同一值；助手 bullet `●`、Markdown 列表 `•`、
  输入框边框/标题/`❯` 提示符与代码同色。
- 终端客户端 dark 主题主色改为截图取样的紫色 `#B1B9F9`（助手 bullet、
  spinner、`✻`、输入框提示符与标题、行内代码与代码块同色）；light 主题
  使用深紫变体（`#7C3AED`/`#6D28D9`）；助手 bullet 与 spinner 现在按主题
  主色渲染，不再使用默认前景色。
- 终端客户端 Markdown 渲染可读性优化：行内代码与代码块改用主题 `code` 色
  （不再是 dim 灰），引用文字保持正文色、仅前缀 dim；六个主题预设补齐
  `code` 令牌。
- 终端客户端输入框改为圆角边框盒子（顶边右侧显示会话标题，新会话显示
  工作区名，运行结束后刷新后端生成的 thread 标题）；进入 TUI 默认新会话，
  不再自动接续最近一次对话，`/resume` 打开历史会话选择器。
- 终端客户端修复全屏滚动与命令菜单：`↑`/`↓` 在 fullscreen 下单行滚动对话
  （`PgUp`/`PgDn` 半屏、`Ctrl+Home`/`Ctrl+End` 跳转不变），输入历史移到
  `Ctrl+P`/`Ctrl+N`，排队消息改为 `Ctrl+U` 撤回；`/` 命令菜单改为跟随
  光标滚动窗口，11 个命令都可用 `↑`/`↓` 选中。
- 终端客户端 `/resume` 改为全屏会话选择器：输入即搜索、`↑`/`↓` 移动、
  `Enter` 恢复、`Esc` 取消，`/resume <n>` 保留按序号切换；对话呈现对齐
  Claude Code：用户消息为 `❯` 行 + 整行底色，助手消息以 `●` 开头、续行
  缩进，run 结束行显示 `✻ done in Ns · HH:MM`；提问选项支持 `↑`/`↓` +
  `Enter` 选择（自由文本输入不受影响）。
- 终端客户端默认改为 fullscreen 渲染（Ink `alternateScreen` + 窗口化
  viewport）：输入框固定底部，`PgUp`/`PgDn` 半屏滚动、`Ctrl+Home`/
  `Ctrl+End` 跳转，滚离底部时暂停自动跟随并提示新行；帧高度恒等于终端
  行数，修复 Windows 经典渲染的重复帧。`cellwiki-tui --classic` 或
  `CELLWIKI_TUI_CLASSIC=1` 保留主屏 scrollback 渲染。
- 公开入口文档不再依赖未随代码仓库分发的本地项目与设计文档。
- 发布说明不再手工维护固定安装包哈希。
- 设置页工作区记忆面板收敛为“状态行 + 记忆文件列表”：手动合并、队列信息和
  来源清理不再出现在默认界面，候选合并由后台自动完成；话题条目仍可展开查看、
  编辑或删除。
- 旧 CLI、顶层兼容壳、`:2024` LangGraph 调试服务及其旧专用依赖已退役；只保留 `cellwiki` 与 `cellwiki-sidecar` 两个 Python 入口。
- 工具面由 `_CellWikiToolBoundaryMiddleware` 的 allowlist 单层承重；框架侧 `HarnessProfile.excluded_tools` 已退役（零独有职责，且按名误删白名单工具）。

### Removed

- 删除旧治理链（ChangeSet / Approval / CentralWriter / snapshot / ingest 管线 / memory / research / TaskRouter / SearchIndex / KnowledgeGraph）及旧 CLI、顶层兼容壳和 `:2024` LangGraph 调试入口；当前版本以 git 承载版本与审批。
- Wiki renderer 不再生成指向已退役 `relationships.json`、`graph.dot`、`graph.mmd` 的链接。
- 删除无调用者的读工具 `get_project_status`、`search_wiki`、`read_wiki_page`（自 git 治理重构后就不在白名单与组装列表里）；前端三张工具卡保留，仅供历史 transcript 渲染。
- 删除已无消费方的「扫描并登记 raw/」通路（文件树按钮、`POST /api/workspace/raw/scan` 与 `scan_raw_sources`）；其原始消费方 `ingest_sources` 已退役，附件晋升与直接读取 `raw/` 的导入方式不变。

### Fixed

- 工作区初始化生成的 `.gitignore` 现在同时忽略 `.env` 与 `.env.*`；自动收口
  commit 与审批 diff 显式排除这些本地凭据文件，旧工作区也不会把 API key
  卷进审批单元。
- 自动收口在并发调用下于串行段内重读脏区，后到者不再因空提交失败；`git`
  命令失败信息在 stderr 为空时回退显示 stdout，便于诊断。

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
