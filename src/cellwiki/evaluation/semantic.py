# =============================================================================
# 语义评估 —— 基于固定评估清单的确定性语义指标计算
# =============================================================================
# 使用精确的稳定 ID（非模糊匹配）驱动指标计算，确保 CI 环境的确定性。
# 评估维度包括实体召回率、证据引用准确率、无依据声明率、
# 变更集有效性等，用于发布门控决策。
# =============================================================================

"""Deterministic semantic metrics over a fixed CellWiki evaluation manifest."""

from __future__ import annotations

from typing import Any


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _citation_key(value: dict[str, Any]) -> tuple[str, str]:
    return str(value.get("source_id", "")), str(value.get("locator", ""))


def evaluate_semantic_predictions(
    dataset: dict[str, Any],
    predictions: dict[str, Any],
) -> dict[str, float]:
    """Score externally produced predictions without making a model or network call.

    Exact stable IDs deliberately drive the metrics. This keeps CI deterministic
    and prevents a fluent answer from receiving credit when it lacks the expected
    SourceRecord and locator provenance.
    """

    expected_entities = {str(item) for item in dataset.get("entities", [])}
    predicted_entities = {str(item) for item in predictions.get("entities", [])}
    entity_matches = expected_entities & predicted_entities

    expected_claims = {
        str(item["claim_id"]): item for item in dataset.get("claims", [])
    }
    predicted_claims = {
        str(item["claim_id"]): item for item in predictions.get("claims", [])
    }
    matched_claim_ids = expected_claims.keys() & predicted_claims.keys()
    locator_matches = sum(
        _citation_key(expected_claims[claim_id])
        == _citation_key(predicted_claims[claim_id])
        for claim_id in matched_claim_ids
    )

    cases = {str(item["case_id"]): item for item in dataset.get("cases", [])}
    answers = {str(item["case_id"]): item for item in predictions.get("answers", [])}
    citation_total = 0
    citation_correct = 0
    answer_claim_total = 0
    unsupported_claims = 0
    unanswerable_total = 0
    unanswerable_correct = 0
    for case_id, case in cases.items():
        answer = answers.get(case_id, {})
        expected_case_claims = {str(item) for item in case.get("expected_claim_ids", [])}
        predicted_case_claims = {str(item) for item in answer.get("claim_ids", [])}
        answer_claim_total += len(predicted_case_claims)
        unsupported_claims += len(predicted_case_claims - expected_case_claims)

        expected_citations = {
            _citation_key(item) for item in case.get("expected_citations", [])
        }
        predicted_citations = [
            _citation_key(item) for item in answer.get("citations", [])
        ]
        citation_total += len(predicted_citations)
        citation_correct += sum(item in expected_citations for item in predicted_citations)

        if not bool(case.get("answerable", True)):
            unanswerable_total += 1
            if not predicted_case_claims and bool(answer.get("missing_evidence")):
                unanswerable_correct += 1

    expected_lint = {str(item) for item in dataset.get("expected_lint_categories", [])}
    predicted_lint = {str(item) for item in predictions.get("lint_categories", [])}
    operations = list(predictions.get("changeset_operations", []))
    invalid_operations = sum(not bool(item.get("valid", False)) for item in operations)
    unsupported_rate = (
        unsupported_claims / answer_claim_total if answer_claim_total else 0.0
    )
    changeset_error_rate = (
        invalid_operations / len(operations) if operations else 0.0
    )
    usage = predictions.get("usage", {})

    metrics = {
        "entity_precision": _ratio(len(entity_matches), len(predicted_entities)),
        "entity_recall": _ratio(len(entity_matches), len(expected_entities)),
        "claim_recall": _ratio(len(matched_claim_ids), len(expected_claims)),
        "evidence_locator_coverage": _ratio(locator_matches, len(expected_claims)),
        "citation_accuracy": _ratio(citation_correct, citation_total),
        "unsupported_claim_rate": unsupported_rate,
        "groundedness": 1.0 - unsupported_rate,
        "lint_recall": _ratio(len(expected_lint & predicted_lint), len(expected_lint)),
        "unanswerable_accuracy": _ratio(unanswerable_correct, unanswerable_total),
        "changeset_error_rate": changeset_error_rate,
        "estimated_cost_usd": float(usage.get("estimated_cost_usd", 0.0)),
        "model_calls": float(usage.get("model_calls", 0)),
    }

    ablation = predictions.get("ablation")
    if isinstance(ablation, dict):
        baseline = float(ablation.get("baseline_grounded_success", 0.0))
        enabled = float(ablation.get("enabled_grounded_success", 0.0))
        metrics["experimental_feature_gain"] = enabled - baseline
    return {name: round(value, 6) for name, value in metrics.items()}


def threshold_failures(
    metrics: dict[str, float],
    thresholds: dict[str, dict[str, float]],
) -> list[str]:
    """Return human-readable release-gate failures for min/max threshold rules."""

    failures: list[str] = []
    for name, rule in thresholds.items():
        value = metrics.get(name)
        if value is None:
            failures.append(f"{name}: metric missing")
        elif "min" in rule and value < float(rule["min"]):
            failures.append(f"{name}: {value:.4f} < {float(rule['min']):.4f}")
        elif "max" in rule and value > float(rule["max"]):
            failures.append(f"{name}: {value:.4f} > {float(rule['max']):.4f}")
    return failures
