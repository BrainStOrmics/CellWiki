# CellWiki Agent 运行评测卷（当前工作区架构）

这份卷子评的是**现在的 CewiPilot**：白名单工具 + 工作区 git + 待确认 diff。
它取代旧 `evals/semantic/` 的作用（那份卷子的答案清单合同属于已删除的
ChangeSet/SearchIndex 治理链，保留只为兼容）。

## 组成

- `dataset.json`：6 道题。4 道查询题（其中 1 道故意无解）、2 道维护题。
- `workspace/`：固定测试知识库（6 个页面 + 6 个根级文件 + 1 份 paraphrase 来源）。
  它只是 fixture，评测时会被复制到 `build/agent-eval/<case_id>/` 再 `git init`。
- `thresholds.json`：发布门控（min/max）。
- `reference_predictions.json`：**手写黄金参考**，用来证明打分器和阈值本身是对的，
  不是模型成绩。
- `runs/<时间戳>/`：真实模型跑出来的 `predictions.json` 与 `report.json`。
  这个目录不入库，且永远不覆盖黄金参考。

## 怎么跑

确定性打分（不需要 API Key，CI 每次提交都跑）：

```powershell
uv run python scripts/evaluate_agent_runs.py
```

真实模型跑全部题目（需要模型配置，会产生费用）：

```powershell
.venv\Scripts\python.exe scripts/run_agent_eval.py
.venv\Scripts\python.exe scripts/run_agent_eval.py --case query_treg_markers --case query_unanswerable_subset
```

## 指标含义

- `citation_validity`：回答里提到的每个 `.md` 路径都必须在工作区里真实存在。
  低于 1.0 就是编造引用。
- `expected_citation_recall` / `groundedness`：该引的页面引到没有；每个采分点的
  关键词必须真的出现在被引用文件的正文里。
- `unanswerable_accuracy`：无解的题必须"不引用任何文件 + 明确说缺证据"。
- `read_only_violation_rate`：查询题必须只读，改到文件就算违规（不变式 5）。
- `expected_write_recall` / `unintended_write_rate`：维护题该改的改了没有，
  以及有没有动不该动的路径。
- `lint_pass_rate`：终态过不过系统 lint（L1 警告不算失败）。
- `system_file_write_attempts`：尝试写 `log.md`/`audit_report.md`/
  `overview.md`/`statistics.md` 的次数。工具层会拦住，但尝试本身就说明提示词没被
  遵守，而且白烧预算。
- `model_calls` / `tool_calls` / `elapsed_seconds`：成本，用于发现失控循环。

## 两个不设门控、只供人工核对的计数

- `unresolved_citation_count`：答案里以路径形式出现、但在工作区里不存在的 token。
- `system_maintenance_change_count`：改动面里属于系统维护文件（ADR-0009 由系统写）
  的条数，**不算** Agent 的越界改动。

已知的判据边界（首轮真实运行暴露）：纯路径规则无法区分「把某页当作依据引用」与
「声明某页不存在 / 计划新建某页」。模型诚实的回答是后者：

> 无法回答：`wiki/` 与 `raw/` 中 iNKT 关键词 0 命中，也没有肺组织页
> （`wiki/tissues/lung.md` 不存在）

因此 `citation_validity` 目前定的是零容忍（min 1.0），这类"点名不存在的文件"会把
门控判红，需要人工读一眼 `predictions.json` 确认它到底是编造依据还是诚实声明。

## 加一道题

1. 在 `workspace/` 里补需要的页面（细胞类型页要满足 lint：`standard_name` 等于
   文件名、有 H1、有 `references`）。
2. 在 `dataset.json` 里加 case：`kind` 是 `query` 或 `maintenance`；查询题写
   `expected_citations` + `key_points`；维护题写 `expected_changes` +
   `allowed_changes`。
3. 在 `reference_predictions.json` 里补一条对应的黄金记录，跑
   `uv run python scripts/evaluate_agent_runs.py` 确认仍然全绿。
