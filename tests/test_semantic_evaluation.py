# =============================================================================
# 语义评估测试 —— 验证语义评估指标的确定性计算
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path

from cellwiki.evaluation.semantic import evaluate_semantic_predictions, threshold_failures


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    path = ROOT / "evals" / "semantic" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_gold_reference_validates_semantic_harness_and_thresholds():
    metrics = evaluate_semantic_predictions(
        _load("dataset.json"),
        _load("reference_predictions.json"),
    )

    assert metrics["entity_recall"] == 1.0
    assert metrics["citation_accuracy"] == 1.0
    assert metrics["unsupported_claim_rate"] == 0.0
    assert threshold_failures(metrics, _load("thresholds.json")) == []


def test_semantic_metrics_penalize_unsupported_claims_and_bad_locators():
    dataset = _load("dataset.json")
    predictions = _load("reference_predictions.json")
    predictions["claims"][0]["locator"] = "invented:page"
    predictions["answers"][0]["claim_ids"].append("hallucinated_claim")
    predictions["answers"][0]["citations"].append(
        {"source_id": "unknown", "locator": "invented"}
    )

    metrics = evaluate_semantic_predictions(dataset, predictions)

    assert metrics["evidence_locator_coverage"] < 1.0
    assert metrics["citation_accuracy"] < 1.0
    assert metrics["unsupported_claim_rate"] > 0.0
