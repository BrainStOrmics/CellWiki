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
- **Run**：桌面端一条消息触发的一次 Agent 执行。每个 run 有独立的迭代预算、
  超时、事件流、checkpoint 与终态；可以 unfinished 收尾并续跑。
- **待确认 diff**：维护型 run 结束后系统生成的 git 差异。接受 = 审计生效；
  拒绝 = 系统 revert 该 run 全部 commit。
- **审批**：用户对待确认 diff 的接受或拒绝；阻断式、一次一个。
- **查询 run**：只读且不产生 diff 的 run；Agent 直接读 md 回答，引用即文件路径。
- **lint_knowledge_base**：确定性知识库检查器（frontmatter、链接完整性、
  空引用、派生一致性），只报告不修复；run 结束时系统强制重跑。
- **ask_user_question**：运行中向用户提问的工具，契约含 5+1 修订。
- **子 Agent 扩展点**：spec 注册表 + 独立工具白名单；v1 注册表为空。
- **保留术语（品牌与兼容）**：CewiPilot、`WikiAgentContext`、
  `build_wiki_agent`、`cellwiki-agent`。

## 不变式

1. 知识库是 git 承载的 md 工作区；正式内容变更只能经 `Run -> 待确认 diff ->
   用户接受`。
2. git 历史永不改写；撤销只用 revert；禁止 `reset --hard` / `clean` / `rm` /
   `rebase` / `amend` / `push` / `fetch` / `checkout --`。
3. Agent 可读写整个工作目录；`log.md` 与 `audit_report.md` 只读，
   `overview.md` 与 `statistics.md` 系统重建。
4. run 严格串行：同一时刻最多一个进行中的 run 与一个未处理待确认 diff。
5. 查询 run 只读、不产生 diff。
6. lint 门禁：run 结束系统强制重跑 `lint_knowledge_base`；失败不进入待确认、
   不撤销 commit。
7. 预算或时长耗尽终态 = `unfinished`：commit 保留、可续；"继续" = 新 run +
   checkpoint 恢复 + `parent_run_id`；崩溃恢复继承剩余预算。
8. 内容归 Agent、派生与门禁归系统、人工负责接受/拒绝 diff。
9. 品牌与兼容术语不随重构改名。
