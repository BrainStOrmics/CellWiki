# =============================================================================
# Agent 运行评测测试 —— 验证工作区轨迹打分器的确定性与发布门控
# =============================================================================

"""Contract tests for the current-architecture Agent evaluation metrics."""

from __future__ import annotations

import json
from pathlib import Path

from cellwiki.evaluation.agent_eval import cited_paths, evaluate_agent_predictions
from cellwiki.evaluation.semantic import threshold_failures


ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals" / "agent"


def _load(name: str) -> dict:
    return json.loads((EVALS / name).read_text(encoding="utf-8"))


def _metrics(predictions: dict) -> dict[str, float]:
    return evaluate_agent_predictions(_load("dataset.json"), predictions, EVALS / "workspace")


def _case(predictions: dict, case_id: str) -> dict:
    return next(case for case in predictions["cases"] if case["case_id"] == case_id)


def test_gold_reference_validates_agent_harness_and_thresholds():
    predictions = _load("reference_predictions.json")

    metrics = _metrics(predictions)

    assert metrics["citation_validity"] == 1.0
    assert metrics["expected_citation_recall"] == 1.0
    assert metrics["groundedness"] == 1.0
    assert metrics["unanswerable_accuracy"] == 1.0
    assert metrics["read_only_violation_rate"] == 0.0
    assert metrics["expected_write_recall"] == 1.0
    assert metrics["unintended_write_rate"] == 0.0
    assert metrics["lint_pass_rate"] == 1.0
    assert metrics["system_file_write_attempts"] == 0.0
    assert threshold_failures(metrics, _load("thresholds.json")) == []


def test_citation_must_point_at_a_real_fixture_file():
    predictions = _load("reference_predictions.json")
    _case(predictions, "query_treg_markers")["answer"] = "依据：wiki/cell_types/invented_page.md"

    metrics = _metrics(predictions)

    assert metrics["citation_validity"] < 1.0
    assert metrics["groundedness"] < 1.0
    assert threshold_failures(metrics, _load("thresholds.json"))


def test_citing_a_real_page_for_an_unanswerable_question_is_rejected():
    predictions = _load("reference_predictions.json")
    refusal = _case(predictions, "query_unanswerable_subset")
    refusal["answer"] = "肺 iNKT 的关键标记物参考 wiki/cell_types/regulatory_t_cell.md。"
    refusal["missing_evidence"] = []

    metrics = _metrics(predictions)

    assert metrics["unanswerable_accuracy"] == 0.0
    assert threshold_failures(metrics, _load("thresholds.json"))


def test_query_run_that_touches_the_workspace_breaks_the_read_only_gate():
    predictions = _load("reference_predictions.json")
    _case(predictions, "query_tissue_cells")["changed_paths"] = [
        "wiki/tissues/colorectal_tumor.md"
    ]

    metrics = _metrics(predictions)

    assert metrics["read_only_violation_rate"] > 0.0
    assert threshold_failures(metrics, _load("thresholds.json"))


def test_writing_a_system_owned_file_is_counted_even_when_blocked():
    predictions = _load("reference_predictions.json")
    _case(predictions, "maintenance_system_files_denied")["write_calls"] = ["log.md"]

    metrics = _metrics(predictions)

    assert metrics["system_file_write_attempts"] == 1.0
    assert metrics["unintended_write_rate"] > 0.0
    assert threshold_failures(metrics, _load("thresholds.json"))


def test_missing_expected_page_write_lowers_maintenance_recall():
    predictions = _load("reference_predictions.json")
    _case(predictions, "maintenance_ingest_subset_page")["changed_paths"] = []

    metrics = _metrics(predictions)

    assert metrics["expected_write_recall"] == 0.0
    assert threshold_failures(metrics, _load("thresholds.json"))


def test_cited_paths_extracts_workspace_paths_from_plain_text():
    answer = "依据 wiki/cell_types/regulatory_t_cell.md；另见 wiki\\marker_genes\\FOXP3.md。"

    assert cited_paths(answer) == [
        "wiki/cell_types/regulatory_t_cell.md",
        "wiki/marker_genes/FOXP3.md",
    ]
