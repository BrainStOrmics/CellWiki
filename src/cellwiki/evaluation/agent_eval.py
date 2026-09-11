# =============================================================================
# Agent 运行评测 —— 面向当前工作区架构的确定性轨迹打分
# =============================================================================
# 与 semantic.py 的分工：semantic 面向旧治理链的"答案清单"合同
# （SourceRecord + locator），本模块面向当前 Agent 的真实产出：最终回答里的
# 工作区相对路径引用、run 结束后的 git 改动面、以及系统强制 lint 的结论。
# 打分是纯确定性的：只读固定 fixture，不发起任何模型或网络调用，因此可以
# 进入 CI 作为发布门控；真实模型成绩必须另写 predictions 文件。
# =============================================================================

"""Deterministic metrics over current-architecture CellWiki Agent run records."""

from __future__ import annotations

import fnmatch
import posixpath
import re
from pathlib import Path
from typing import Any

from cellwiki.evaluation.semantic import threshold_failures

# 系统拥有的四个根级文件：内容写入由 ADR-0009 在工具层拦截，评测负责发现
# Agent 是否还在徒劳尝试（每次尝试都白烧预算，也说明提示词没有被遵守）。
_SYSTEM_OWNED_FILES = {"overview.md", "statistics.md", "log.md", "audit_report.md"}
# 与运行时门禁保持一致：L1 警告不阻塞待确认 diff，只有 L0 错误算不通过。
_LINT_PASS_STATUSES = {"passed", "passed_with_warnings"}
# 反斜杠也要吃进来：Windows 模型常引用 wiki\cell_types\x.md，_norm 会统一成
# 正斜杠；漏掉它会把一次合法引用误判成编造。
_PATH_TOKEN = re.compile(r"[A-Za-z0-9_./\u4e00-\u9fff\\-]+\.md")


def _ratio(numerator: float, denominator: float) -> float:
    """Recall-style ratio: an empty requirement set counts as fully satisfied."""

    return numerator / denominator if denominator else 1.0


def _rate(numerator: float, denominator: float) -> float:
    """Violation-style rate: nothing observed means nothing violated."""

    return numerator / denominator if denominator else 0.0


def _norm(value: Any) -> str:
    return posixpath.normpath(str(value or "").strip().replace("\\", "/").lstrip("/"))


def cited_paths(answer: str) -> list[str]:
    """Pull workspace-relative Markdown citations out of a plain-text answer.

    Public because the opt-in real-model smoke gate must judge citations the same
    way the release metric does; a second copy of the regex would drift.

    Only directory-qualified tokens count. The product contract is "引用即工作区
    相对路径"; a bare `FOXP3.md` is how models enumerate a folder or name a file
    that does not exist yet, so treating mentions as citations turned an honest
    refusal into a fabricated-citation failure.
    """

    found: list[str] = []
    for token in _PATH_TOKEN.findall(answer or ""):
        path = _norm(token)
        if "/" in path and path not in found:
            found.append(path)
    return found


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


# 逐题计数是唯一的判据来源：整卷汇总和单题判定都从同一份 tally 计算，
# 不会出现"两套标准互相漂移"。tally 的键就是指标的分子与分母。
_TALLY_KEYS = (
    "answer_present",
    "citation_total",
    "citation_valid",
    "unresolved_citations",
    "system_maintenance_changes",
    "expected_citation_total",
    "expected_citation_hit",
    "key_point_total",
    "key_point_grounded",
    "unanswerable_total",
    "unanswerable_correct",
    "query_total",
    "query_read_only_violations",
    "expected_change_total",
    "expected_change_hit",
    "affected_total",
    "unintended_writes",
    "lint_required",
    "lint_passed",
    "system_file_attempts",
    "model_calls",
    "tool_calls",
    "elapsed_seconds",
)

# 逐题判定时必须排除的键：这些是跨题口径（题数、成本）或不设门控的人工核对项，
# 拿它们卡单题阈值会得出错误结论。
_AGGREGATE_ONLY_KEYS = frozenset(
    {
        "case_count",
        "model_calls",
        "tool_calls",
        "elapsed_seconds",
        "unresolved_citation_count",
        "system_maintenance_change_count",
    }
)

Tally = dict[str, float]


def _new_tally() -> Tally:
    return {key: 0.0 for key in _TALLY_KEYS}


def _tally_case(case: dict[str, Any], record: dict[str, Any], fixture_root: Path) -> Tally:
    """Score one case into numerators/denominators.

    Citations are validated against the workspace this case actually produced
    when the run record reports one: a maintenance run that cites the page it
    just created is correct, and judging it against the pristine fixture would
    score real work as an invented path.
    """

    tally = _new_tally()
    answer = str(record.get("answer") or "")
    # 没有最终回答的 run 不能靠"没有可违反的门控"混过去：meta 题没有期望引用时，
    # 空回答会让所有 recall 口径的 0/0 全算满分，形成假绿。
    tally["answer_present"] += int(bool(answer.strip()))
    root = Path(str(record.get("workspace") or fixture_root))
    cited = cited_paths(answer)
    cited_text: dict[str, str] = {}
    for path in cited:
        tally["citation_total"] += 1
        page = root / path
        if page.is_file():
            tally["citation_valid"] += 1
            try:
                cited_text[path] = page.read_text(
                    encoding="utf-8", errors="replace"
                ).casefold()
            except OSError:
                cited_text[path] = ""
    tally["unresolved_citations"] += sum(1 for path in cited if not (root / path).is_file())

    # ADR-0009：收尾与判定事件由系统写四个维护文件，产品把它们排除在待审 diff
    # 之外；评测同理，另计入不门控的 system_maintenance_change_count。
    raw_changed = [
        _norm(item) for item in record.get("changed_paths") or [] if _norm(item)
    ]
    tally["system_maintenance_changes"] += sum(
        1
        for path in raw_changed
        if posixpath.basename(path) in _SYSTEM_OWNED_FILES
    )
    changed = [
        path
        for path in raw_changed
        if posixpath.basename(path) not in _SYSTEM_OWNED_FILES
    ]
    writes = [_norm(item) for item in record.get("write_calls") or [] if _norm(item)]
    tally["system_file_attempts"] += sum(
        1 for path in writes if posixpath.basename(path) in _SYSTEM_OWNED_FILES
    )
    usage = record.get("usage") or {}
    tally["model_calls"] += float(usage.get("model_calls") or 0)
    tally["tool_calls"] += float(usage.get("tool_calls") or 0)
    tally["elapsed_seconds"] += float(usage.get("elapsed_seconds") or 0)

    if str(case.get("kind") or "query") == "query":
        tally["query_total"] += 1
        tally["query_read_only_violations"] += int(bool(changed) or bool(writes))
        if bool(case.get("answerable", True)):
            for expected in case.get("expected_citations") or []:
                tally["expected_citation_total"] += 1
                tally["expected_citation_hit"] += int(_norm(expected) in cited)
            for point in case.get("key_points") or []:
                keywords = [
                    str(word).casefold()
                    for word in point.get("keywords") or []
                    if str(word).strip()
                ]
                tally["key_point_total"] += 1
                tally["key_point_grounded"] += int(
                    any(
                        keyword in text
                        for text in cited_text.values()
                        for keyword in keywords
                    )
                )
        else:
            tally["unanswerable_total"] += 1
            # 正确的失败方式：明确承认证据缺失（结构化的 missing_evidence 或
            # 数据集列举的承认措辞）。列举现有页面、点名缺失的文件都是诚实拒答
            # 的正常表现；纯路径规则无法区分"当作依据引用"与"声明其不存在"，
            # 所以那部分交给人工抽样读 predictions 正文。
            markers = [
                str(item).casefold()
                for item in case.get("unanswerable_markers") or []
            ]
            admitted = bool(record.get("missing_evidence")) or any(
                marker in answer.casefold() for marker in markers
            )
            tally["unanswerable_correct"] += int(admitted)
        return tally

    expected_patterns = [str(item) for item in case.get("expected_changes") or []]
    allowed_patterns = [str(item) for item in case.get("allowed_changes") or []]
    affected = sorted(set(changed) | set(writes))
    for pattern in expected_patterns:
        tally["expected_change_total"] += 1
        tally["expected_change_hit"] += int(
            any(fnmatch.fnmatch(path, pattern) for path in changed)
        )
    tally["affected_total"] += len(affected)
    tally["unintended_writes"] += sum(
        1 for path in affected if not _matches_any(path, allowed_patterns)
    )
    if bool(case.get("requires_lint_pass", True)):
        tally["lint_required"] += 1
        tally["lint_passed"] += int(str(record.get("lint_status")) in _LINT_PASS_STATUSES)
    return tally


def _metrics_from_tally(tally: Tally, case_count: int) -> dict[str, float]:
    return {
        "case_count": float(case_count),
        "answer_present_rate": _ratio(tally["answer_present"], case_count),
        # 空引用集是"没有无效引用"，不是"引用全无效"：用 _ratio 的语义。
        # 逐题判定时这道题可能是合法的零引用回答（例如诚实拒答），用 _rate 会
        # 把 0/0 当成 0.0 从而误判失败。
        "citation_validity": _ratio(tally["citation_valid"], tally["citation_total"]),
        "expected_citation_recall": _ratio(
            tally["expected_citation_hit"], tally["expected_citation_total"]
        ),
        "groundedness": _ratio(tally["key_point_grounded"], tally["key_point_total"]),
        "unanswerable_accuracy": _ratio(
            tally["unanswerable_correct"], tally["unanswerable_total"]
        ),
        "read_only_violation_rate": _rate(
            tally["query_read_only_violations"], tally["query_total"]
        ),
        "expected_write_recall": _ratio(
            tally["expected_change_hit"], tally["expected_change_total"]
        ),
        "unintended_write_rate": _rate(tally["unintended_writes"], tally["affected_total"]),
        "lint_pass_rate": _ratio(tally["lint_passed"], tally["lint_required"]),
        "system_file_write_attempts": tally["system_file_attempts"],
        # 以下两项不设门控，只供人工核对：列举/计划里的缺失文件名不是编造引用，
        # 系统维护文件的变化也不是 Agent 的产出。
        "unresolved_citation_count": tally["unresolved_citations"],
        "system_maintenance_change_count": tally["system_maintenance_changes"],
        "model_calls": tally["model_calls"],
        "tool_calls": tally["tool_calls"],
        "elapsed_seconds": tally["elapsed_seconds"],
    }


def evaluate_agent_predictions(
    dataset: dict[str, Any],
    predictions: dict[str, Any],
    workspace_root: Path,
) -> dict[str, float]:
    """Score exported run records against the fixed case set.

    A citation only counts when the referenced file exists in the case workspace,
    and a key point is only grounded when one of its keywords is really present in
    an already-cited file. That keeps a fluent but unsupported answer from earning
    credit, which is the whole point of this harness.
    """

    fixture_root = Path(workspace_root)
    cases = {str(item["case_id"]): item for item in dataset.get("cases", [])}
    records = {str(item["case_id"]): item for item in predictions.get("cases", [])}

    total = _new_tally()
    for case_id, case in cases.items():
        tally = _tally_case(case, records.get(case_id, {}), fixture_root)
        for key, value in tally.items():
            total[key] += value
    return _metrics_from_tally(total, len(cases))


def case_metrics(
    case: dict[str, Any],
    record: dict[str, Any],
    workspace_root: Path,
) -> dict[str, float]:
    """Same metrics as the paper-level call, scoped to a single case."""

    return _metrics_from_tally(_tally_case(case, record, Path(workspace_root)), 1)


def case_outcomes(
    dataset: dict[str, Any],
    predictions: dict[str, Any],
    workspace_root: Path,
    thresholds: dict[str, dict[str, float]],
) -> dict[str, bool]:
    """Per-case pass/fail for one trial.

    A case passes when none of the gates that apply to it fails, so reliability and
    the release gate share one definition instead of inventing a second standard.
    Cross-case metrics (cost, case count) and the ungated human-review counters are
    excluded by design.
    """

    rules = {
        name: rule
        for name, rule in thresholds.items()
        if name not in _AGGREGATE_ONLY_KEYS
    }
    cases = {str(item["case_id"]): item for item in dataset.get("cases", [])}
    records = {str(item["case_id"]): item for item in predictions.get("cases", [])}
    return {
        case_id: not threshold_failures(
            case_metrics(case, records.get(case_id, {}), workspace_root), rules
        )
        for case_id, case in cases.items()
    }


def trial_pass_rates(outcomes: list[dict[str, bool]]) -> dict[str, float]:
    """Reliability across repeated trials, in the spirit of tau-bench's pass^k.

    ``pass_1`` is the share of (case, trial) observations that passed;
    ``pass_k`` is the share of cases that passed in *every* trial, which is the
    number that describes a strictly serialized single-user product.
    """

    case_ids = sorted({case_id for trial in outcomes for case_id in trial})
    observed = sum(len(trial) for trial in outcomes)
    passed = sum(sum(1 for value in trial.values() if value) for trial in outcomes)
    stable = [
        case_id
        for case_id in case_ids
        if outcomes and all(trial.get(case_id, False) for trial in outcomes)
    ]
    return {
        "trials": float(len(outcomes)),
        "pass_1": _rate(float(passed), float(observed)),
        "pass_k": _ratio(float(len(stable)), float(len(case_ids))),
        "stable_case_count": float(len(stable)),
    }
