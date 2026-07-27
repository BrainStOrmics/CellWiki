# =============================================================================
# 语义 Lint 测试 —— 验证 L2 语义审查的输出
# =============================================================================

"""L2 findings expose evidence, counterexamples, and uncertainty without writing Wiki."""

from __future__ import annotations

import json
from pathlib import Path

from cellwiki.services.semantic_lint import SemanticLintService


def _claim(claim_id: str, predicate: str, source_id: str) -> dict:
    return {
        "claim_id": claim_id,
        "subject": "regulatory_t_cell",
        "predicate": predicate,
        "object": "FOXP3",
        "qualifiers": {},
        "evidence": [{"source_id": source_id, "locator": "page:1", "excerpt": "FOXP3"}],
    }


def test_l2_conflict_and_context_findings_are_advisory_review_items(tmp_path: Path):
    extraction_dir = tmp_path / "data" / "extraction"
    extraction_dir.mkdir(parents=True)
    (extraction_dir / "src_a.json").write_text(
        json.dumps({"claims": [_claim("claim_a", "expresses", "src_a")]}), encoding="utf-8"
    )
    (extraction_dir / "src_b.json").write_text(
        json.dumps({"claims": [_claim("claim_b", "does_not_express", "src_b")]}), encoding="utf-8"
    )
    service = SemanticLintService(tmp_path)

    findings = service.inspect()
    conflict = next(item for item in findings if item.category == "cross_source_contradiction")
    review_items = service.review_items()

    assert conflict.blocking is False
    assert conflict.auto_fixable is False
    assert conflict.evidence[0]["supporting_claims"]
    assert conflict.evidence[0]["counterexamples"]
    assert conflict.evidence[0]["uncertainty"]
    assert any(item.type == "cross_source_contradiction" for item in review_items)
    assert service.review_path.is_file()

