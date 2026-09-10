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

# 系统拥有的四个根级文件：内容写入由 ADR-0009 在工具层拦截，评测负责发现
# Agent 是否还在徒劳尝试（每次尝试都白烧预算，也说明提示词没有被遵守）。
_SYSTEM_OWNED_FILES = {"overview.md", "statistics.md", "log.md", "audit_report.md"}
# 与运行时门禁保持一致：L1 警告不阻塞待确认 diff，只有 L0 错误算不通过。
_LINT_PASS_STATUSES = {"passed", "passed_with_warnings"}
# 反斜杠也要吃进来：Windows 模型常引用 wiki\cell_types\x.md，_norm 会统一成
# 正斜杠；漏掉它会把一次合法引用误判成编造。
_PATH_TOKEN = re.compile(r"[A-Za-z0-9_./\u4e00-\u9fff\\-]+\.md")


def _ratio(numerator: int, denominator: int) -> float:
    """Recall-style ratio: an empty requirement set counts as fully satisfied."""

    return numerator / denominator if denominator else 1.0


def _rate(numerator: int, denominator: int) -> float:
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


def evaluate_agent_predictions(
    dataset: dict[str, Any],
    predictions: dict[str, Any],
    workspace_root: Path,
) -> dict[str, float]:
    """Score exported run records against the fixed case set.

    A citation only counts when the referenced file exists in the fixture
    workspace, and a key point is only grounded when one of its keywords is
    really present in an already-cited file. That keeps a fluent but unsupported
    answer from earning credit, which is the whole point of this harness.
    """

    fixture_root = Path(workspace_root)
    cases = {str(item["case_id"]): item for item in dataset.get("cases", [])}
    records = {str(item["case_id"]): item for item in predictions.get("cases", [])}

    citation_total = 0
    citation_valid = 0
    unresolved_citations = 0
    system_maintenance_changes = 0
    expected_citation_total = 0
    expected_citation_hit = 0
    key_point_total = 0
    key_point_grounded = 0
    unanswerable_total = 0
    unanswerable_correct = 0
    query_total = 0
    query_read_only_violations = 0
    expected_change_total = 0
    expected_change_hit = 0
    affected_total = 0
    unintended_writes = 0
    lint_required = 0
    lint_passed = 0
    system_file_attempts = 0
    model_calls = 0.0
    tool_calls = 0.0
    elapsed_seconds = 0.0

    for case_id, case in cases.items():
        record = records.get(case_id, {})
        answer = str(record.get("answer") or "")
        # 维护题会新建页面：对着原始 fixture 校验合法产出，会把成功判成编造。
        root = Path(str(record.get("workspace") or fixture_root))
        cited = cited_paths(answer)
        cited_text: dict[str, str] = {}
        for path in cited:
            citation_total += 1
            page = root / path
            if page.is_file():
                citation_valid += 1
                try:
                    cited_text[path] = page.read_text(
                        encoding="utf-8", errors="replace"
                    ).casefold()
                except OSError:
                    cited_text[path] = ""

        # ADR-0009：收尾与判定事件由系统写四个维护文件，产品把它们排除在待审
        # diff 之外；评测同理，另计入 system_maintenance_change_count。
        raw_changed = [
            _norm(item) for item in record.get("changed_paths") or [] if _norm(item)
        ]
        system_maintenance_changes += sum(
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
        unresolved_citations += sum(1 for path in cited if not (root / path).is_file())
        system_file_attempts += sum(
            1 for path in writes if posixpath.basename(path) in _SYSTEM_OWNED_FILES
        )
        usage = record.get("usage") or {}
        model_calls += float(usage.get("model_calls") or 0)
        tool_calls += float(usage.get("tool_calls") or 0)
        elapsed_seconds += float(usage.get("elapsed_seconds") or 0)

        if str(case.get("kind") or "query") == "query":
            query_total += 1
            query_read_only_violations += int(bool(changed) or bool(writes))
            if bool(case.get("answerable", True)):
                for expected in case.get("expected_citations") or []:
                    expected_citation_total += 1
                    expected_citation_hit += int(_norm(expected) in cited)
                for point in case.get("key_points") or []:
                    keywords = [
                        str(word).casefold()
                        for word in point.get("keywords") or []
                        if str(word).strip()
                    ]
                    key_point_total += 1
                    key_point_grounded += int(
                        any(
                            keyword in text
                            for text in cited_text.values()
                            for keyword in keywords
                        )
                    )
            else:
                unanswerable_total += 1
                # 正确的失败方式：明确承认证据缺失（结构化的 missing_evidence 或
                # 数据集列举的承认措辞）。列举现有页面、点名缺失的文件都是诚实拒答
                # 的正常表现；纯路径规则无法区分“当作依据引用”与“声明其不存在”，
                # 所以那部分交给人工抽样读 predictions 正文。
                markers = [
                    str(item).casefold()
                    for item in case.get("unanswerable_markers") or []
                ]
                admitted = bool(record.get("missing_evidence")) or any(
                    marker in answer.casefold() for marker in markers
                )
                unanswerable_correct += int(admitted)
            continue

        expected_patterns = [str(item) for item in case.get("expected_changes") or []]
        allowed_patterns = [str(item) for item in case.get("allowed_changes") or []]
        affected = sorted(set(changed) | set(writes))
        for pattern in expected_patterns:
            expected_change_total += 1
            expected_change_hit += int(any(fnmatch.fnmatch(path, pattern) for path in changed))
        affected_total += len(affected)
        unintended_writes += sum(
            1 for path in affected if not _matches_any(path, allowed_patterns)
        )
        if bool(case.get("requires_lint_pass", True)):
            lint_required += 1
            lint_passed += int(str(record.get("lint_status")) in _LINT_PASS_STATUSES)

    return {
        "case_count": float(len(cases)),
        "citation_validity": _rate(citation_valid, citation_total),
        "expected_citation_recall": _ratio(expected_citation_hit, expected_citation_total),
        "groundedness": _ratio(key_point_grounded, key_point_total),
        "unanswerable_accuracy": _ratio(unanswerable_correct, unanswerable_total),
        "read_only_violation_rate": _rate(query_read_only_violations, query_total),
        "expected_write_recall": _ratio(expected_change_hit, expected_change_total),
        "unintended_write_rate": _rate(unintended_writes, affected_total),
        "lint_pass_rate": _ratio(lint_passed, lint_required),
        "system_file_write_attempts": float(system_file_attempts),
        # 以下两项不设门控，只供人工核对：列举/计划里的缺失文件名不是编造引用，
        # 系统维护文件的变化也不是 Agent 的产出。
        "unresolved_citation_count": float(unresolved_citations),
        "system_maintenance_change_count": float(system_maintenance_changes),
        "model_calls": model_calls,
        "tool_calls": tool_calls,
        "elapsed_seconds": elapsed_seconds,
    }
