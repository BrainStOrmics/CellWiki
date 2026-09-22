# Agent 评测体系 v2（旁路轨）

v2 是**旁路**建设的多轮评测体系：gate/diagnostic 双层共享同一套 suite、
fixture、scorer 与报告格式。v1（`evals/agent/` + `agent_eval.py`）保持原样，
继续作为现有 CI 门控；v2 验收之前不替换、不改动 v1。

## 目录结构

```text
evals/agent_v2/
  README.md                 # 本文件
  suites/gate.json          # 门控集：构建/查询/维护/拒绝回滚/安全注入五类
  suites/diagnostic.json    # 诊断集：include gate 场景 + 诊断扩展位（首版为空，
                            # 新增场景必须带自己的 oracle 与 mutations）
  fixtures/<name>/workspace/   # 冻结 fixture（完整工作区，raw/ + wiki/ + 根文件）
  oracles/*.py              # 无模型参考解（每个 fixture 一个）
  mutations/*.py            # 负向变异（每个正式场景至少一个）
  runs/                     # 本地运行产物，永不入库（.gitignore）
```

## suite 合同（schema_version = 2）

suite 顶层：`schema_version`（固定 2）、`suite_id`、`suite_version`、
`layer`（`gate` | `diagnostic` | `sealed`）、可选 `includes`（诊断集展开
gate 场景）、可选 `question_policy`（固定脚本用户的提问应答政策）、
`scenarios[]`。

scenario 字段：`scenario_id`、`kind`、`tags`、`fixture`（相对
`evals/agent_v2/`，指向含 `workspace/` 的 fixture 目录）、`budget`
（`max_model_calls` / `max_tool_calls` / `max_runtime_seconds`；前两者映射
产品 `RunBudget` 与评分断言）、`steps[]`、`oracle`（可重放参考解）、
`mutations[]`（负向变异，gate 层必填）。

step 动作只有五个：

- `send`：同一 `thread_id` 启动一条新消息，等待该 run 到终态（或提问挂起）。
- `answer_question`：回复当前 `ask_user_question` 并等待续跑；无挂起问题时
  记为 no-op（`expect_question` 语义由 suite 显式表达）。
- `accept_diff` / `reject_diff`：判定当前 pending diff（走产品审批语义，
  不绕过串行门禁）。
- `assert`：对本步的确定性断言集合求值。

断言类型（`src/cellwiki/evaluation/agent_eval_v2.py` 注册表）：`file_exists`、
`file_not_exists`、`file_contains`、`file_not_contains`、`link_resolves`、
`changed_paths_subset`、`answer_contains`、`answer_not_contains`、
`citation_exists`、`no_unresolved_citations`、`terminal_status_in`、
`lint_passed`、`max_model_calls`、`no_system_file_write_attempts`。
schema 校验失败在**任何模型请求之前**抛 `SuiteValidationError`。

## oracle 合同

oracle 是**无模型参考解**：在无 API Key 环境重放 scenario 的每个 `send`，
只修改 harness 复制出的工作区副本，并达到断言预期的终态。模块必须暴露
`respond(ctx: ScriptContext) -> ScriptResult`：

- `ScriptContext`：`workspace`（本 trial 的工作区路径）、`message`（当前
  用户消息）、`resume_answers`（问题续跑时的答案；oracle 不应提问）。
- `ScriptResult`：`answer`（最终回答文本，引用工作区相对路径）、
  `tool_calls`（记录为 TOOL_STARTED/COMPLETED 证据，供 write_calls 口径
  使用）、`error`（可选，模拟失败）。

oracle 用普通文件写入 + `run_git` 提交（repo-local 身份由
`ensure_workspace` 提供），**不经过产品工具链**——它是参考答案，不是产品
运行；产品沙箱/白名单行为由产品自己的测试守护。

## 负向变异合同

mutation 与 oracle 同一 `respond()` 合同，但**故意做错一件事**：每个变异
声明 `MUTATION = {mutation_id, scenario_id, expected_codes, expected_primary?,
expected_invalid_run?}`。自检（`scripts/evaluate_agent_eval_v2.py --mutations`）
要求变异 run **不通过**，且失败断言覆盖声明的 `expected_codes`——证明
scorer 能拦住对应的错误，而不是"总分仍高"地放行。

## 运行产物与边界

- `runs/<时间戳>/`：`report.json`、`report.md`、`baseline-diff.json`、
  `results/`（逐 trial 逐 step 的 final-state.json 与 events.jsonl）。已
  gitignore，永不入库。
- 每 (scenario, trial) 使用 `build/agent-v2-eval/` 下的独立工作区副本
  （Windows SQLite 句柄约束，同 v1 的做法），trial 内保持同一 `thread_id`。
- 报告不记录 API Key、完整 base URL 或用户隐私文本。
- gate 判定：安全/终态绝对失败立即阻塞；`invalid_run`（infra 失败、预算耗
  尽等）不算通过也不被重试洗绿；相对回归按"基线 3/3 稳定、候选 2/3 失败
  阻塞、1/3 标 flake"的规则执行。

## 入口

```powershell
# 无网络自检：schema + oracle 重放全绿 + 负向变异按预期变红
.venv\Scripts\python.exe scripts/evaluate_agent_eval_v2.py --suite gate --oracle --mutations

# 真实模型 gate（需要模型配置与额度），每题 3 trial
.venv\Scripts\python.exe scripts/run_agent_eval_v2.py --suite gate --trials 3

# 与基线对比
.venv\Scripts\python.exe scripts/run_agent_eval_v2.py --suite gate --trials 3 --baseline evals/agent_v2/runs/<stamp>/report.json
```

真实模型运行和 BFCL 校准（`scripts/run_bfcl_calibration.py`）都是显式
opt-in，不进入默认 CI；缺少外部环境时结果一律标 `partial`，不伪造分数。
