# CellWiki Domain Context

本文件定义产品领域的术语与不变式，是领域模型与测试的入口。实现模块、测试与
架构决策以本文档为准；长期决策原因见 `docs/adr/`；当前架构见
`docs/architecture.md`。代码或测试与本文档冲突时必须停止并报告，而不是静默改写。

## 术语表

- **工作目录（workspace）**：用户选定并交给 CellWiki 管理的知识库目录。选定后
  CellWiki 自动 `git init` 并创建 `wiki/`、`raw/` 与六个根级 md；它是 Agent 的
  唯一操作域，所有路径解析必须落在其中。
- **raw/**：论文等原始资料目录，纳入 git，用户与 Agent 均可读写。
- **wiki/**：Agent 维护的知识条目目录（例如 `cell_types/`）。
- **根级文件**：
  - `index.md`：Agent 维护导航正文；统计由系统重建注入。
  - `contradiction.md`：Agent 维护矛盾台账。
  - `overview.md`、`statistics.md`：系统重建，Agent 不可手写。
  - `log.md`、`audit_report.md`：系统 append-only，Agent 不可写。
  - `.gitignore`：系统初始化创建的运行时产物边界（忽略 `data/runtime/`）；已存在
    则原样保留、不改写。它不是四个系统维护文件之一，Agent 可读写。之所以由系统
    创建：运行库与检查点里是消息正文和工具输出原文，而不变式 2 规定历史永不改写，
    一次误提交就无法撤回。
- **Run**：桌面端一条消息触发的一次 Agent 执行。每个 run 有独立的迭代预算、
  超时、事件流、checkpoint 与终态；可以 unfinished 收尾并续跑。图状态键是 **run
  作用域**的 `{thread_id}::{run_id}`（ADR-0010），所以同一会话里连续两个 run 不会
  读到对方的状态；checkpoint 无 TTL、无体积上限，只随线程删除级联回收。
  `resume`（"继续"）= 同一 run 回到 RUNNING、在自己的 checkpoint 上续跑，非新
  run；`retry` 仍是同一 run，但**先删掉该 run 的状态键**再从有界 transcript 重放
  ——两者不同义。
- **待确认 diff（审批单元）**：run 发布提交时系统生成的 git 差异审批单元，
  id 形如 `diff_<run_id>_<n>`；一个 run 可产生一串单元，**一行一次判定、不可
  回退**。接受 = 审计生效；拒绝 = 系统 revert **本单元**的 commit。单元边界 =
  判定而非发布：上一单元未判定时同一 run 重发布就地刷新该 pending 行。详见
  ADR-0007 决策 2（2026-09-03 修订）。
- **审批**：用户对未判定审批单元的接受或拒绝；阻断式、一次一个。
- **待审 diff 面板**：APP 侧边栏入口，展示当前未判定审批单元的 git 补丁并接受/拒绝；已判定单元以只读历史折叠区呈现。
- **查询 run**：只读且不产生 diff 的 run；Agent 直接读 md 回答，引用即文件路径。
- **会话（thread）**：点 `+` 或发出首条消息时登记的多轮对话身份，是 APP 历史
  列表的主体；一个会话含 0..N 个 run，零 run 会话同样可见、可回访。
- **会话标题（thread title）**：会话的用户可见标签，预留给 LLM 总结命名；未命名时
  回退会话 ID 后缀，尚未开始的会话显示"新会话"占位。
- **lint_knowledge_base**：确定性知识库检查器（frontmatter、链接完整性、
  空引用、派生一致性），只报告不修复；run 结束时系统强制重跑。
- **ask_user_question**：运行中向用户提问的工具，契约含 5+1 修订。
- **附件（attachment）**：用户上传到线程的 pdf/md/txt（单文件 <100MB、单次 <=20、
  每线程 <=500MB），仅作为线程临时 Agent 上下文，上传时服务端提取文本（PDF pdfplumber，
  v1 无 OCR），24h 兜底清理 + promote 即删。
- **附件清单（attachment manifest）**：run 启动时注入 Layer B 的附件元数据与预览，
  模型据此决定读取哪些附件。
- **promote**：用户经 ask_user_question 同意后，把附件提升为 raw/<source_id>/ 正式源
  （原件 + 提取文本 + meta.json），登记 data/runtime/sources/<source_id>.json，并提交 git。
- **预置源登记（raw scan）**：用户从产品侧发起的"扫描并登记 raw/"动作，按目录名
  登记用户直接放进 `raw/<目录名>/` 的源（source_id = 目录名，幂等，不复制、不产生
  git 变更）；无提取文本的 PDF 登记为 needs_extraction。Agent 工具白名单不因此扩大。
- **schema.md**：工作区根目录可插拔的提取契约；ingest 前 Agent 读取，缺失时回退内置默认。
- **工作区编辑（workspace edit）**：APP 对 md/txt 的受控修改，走合成 run 提交与
  pending diff 审批，不绕过“Run -> 待确认 diff -> 用户接受”。
- **系统维护 commit**：accept diff 后，系统把 overview/statistics 重建、index 统计注入与 log/audit 追加合并为一个确定性 commit（`chore(system): maintenance after run <id> (<verdict>)`），不在拒绝 revert 范围。
- **子 Agent 扩展点**：spec 注册表 + 独立工具白名单；v1 注册表为空。
- **应用根 / 工作区根**：应用根是代码仓库（含 .venv 与 frontend 工具链），固定由代码位置推断；工作区根是用户选择的知识库目录，持久化在 .env 的 PROJECT_ROOT，未选择时回退应用根。wiki/ data/ raw/ 与 Agent 工作区都基于工作区根。
- **保留术语（品牌与兼容）**：CewiPilot、`WikiAgentContext`、
  `build_wiki_agent`、`cellwiki-agent`。

## 不变式

1. 知识库是 git 承载的 md 工作区；正式内容变更只能经 `Run -> 待确认 diff ->
   用户接受`。
2. git 历史永不改写；撤销只用 revert；禁止 `reset --hard` / `clean` / `rm` /
   `rebase` / `amend` / `push` / `fetch` / `checkout --`。
3. Agent 可读写整个工作目录；`log.md` 与 `audit_report.md` 只读，
   `overview.md` 与 `statistics.md` 系统重建。
4. run 严格串行：同一时刻最多一个进行中的 run 与一个未判定审批单元。
5. 查询 run 只读、不产生 diff。
6. lint 门禁：run 结束系统强制重跑 `lint_knowledge_base`；失败不进入待确认、
   不撤销 commit。
7. 中断态 = `unfinished`：预算或时长耗尽、崩溃/重启恢复、以及**用户主动停止**都落
   这里，commit 保留、可续；"继续" = 同一 run 回到 RUNNING、从该 run 的 checkpoint
   续跑并继承剩余预算（ADR-0010 决策 6 取代了"带相同输入重新执行"的旧机制）。
   `cancelled` 只表示"放弃一个已中断的 run"，不是停止的落点，因此停止不等于释放
   工作区（见不变量 4）。审批单元边界 = 判定而非发布（见术语"待确认 diff"）。
8. 内容归 Agent、派生与门禁归系统、人工负责接受/拒绝 diff。
9. 品牌与兼容术语不随重构改名。
10. 系统维护文件（`overview.md`/`statistics.md` 系统重建，`log.md`/`audit_report.md` append-only）只在 run 判定事件由系统维护；accept 后合并为系统维护 commit 提交；Agent 工具对系统维护文件的写操作一律拒绝。
