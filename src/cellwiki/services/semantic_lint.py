# =============================================================================
# 语义 Lint 服务 —— 矛盾、上下文缺口和弱支持的确定性 L2 候选检测
# =============================================================================

# ---------------------------------------------------------------------------
# SemanticLintService —— 语义 Lint 服务
# 检测 Wiki 投影中的矛盾、上下文缺口和弱支持的 L2 级别候选问题。
# L2 是建议性级别，不阻塞发布，但提示用户可能存在的质量问题。
# 检测逻辑包括：同一细胞类型的标记物矛盾、不完整的上下文信息、
# 单源支持不足等。
# ---------------------------------------------------------------------------

"""Deterministic L2 candidates for contradictions, context gaps, and weak support."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from cellwiki.domain.contracts import ReviewItem, RiskLevel
from cellwiki.domain.linting import LintFinding, LintLevel, LintSeverity


class SemanticLintService:
    """Generate advisory L2 findings without invoking a model or mutating knowledge."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.review_path = self.project_root / "data" / "runtime" / "reviews" / "l2.json"

    def inspect(self, *, persist_reviews: bool = True) -> list[LintFinding]:
        claims = self._claims()
        findings: list[LintFinding] = []
        by_subject_object: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        by_statement: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for claim in claims:
            subject = str(claim.get("subject") or "")
            predicate = str(claim.get("predicate") or "")
            obj = str(claim.get("object") or "")
            by_statement[(subject, predicate, obj)].append(claim)
            if predicate in {"expresses", "does_not_express"}:
                by_subject_object[(subject, obj)].append(claim)

        for (subject, obj), grouped in by_subject_object.items():
            predicates = {str(claim.get("predicate")) for claim in grouped}
            if predicates == {"expresses", "does_not_express"}:
                findings.append(
                    self._finding(
                        category="cross_source_contradiction",
                        target_id=subject,
                        locator=f"marker:{obj}",
                        message=f"Conflicting claims report both positive and negative {obj} expression.",
                        evidence={
                            "supporting_claims": [self._evidence_summary(item) for item in grouped],
                            "counterexamples": [self._evidence_summary(item) for item in grouped],
                            "uncertainty": "The apparent conflict may depend on tissue, species, state, or assay context.",
                        },
                        severity=LintSeverity.WARNING,
                    )
                )

        for (subject, predicate, obj), grouped in by_statement.items():
            if predicate in {"mentioned_as", "is_a"}:
                continue
            source_ids = {
                str(evidence.get("source_id"))
                for claim in grouped
                for evidence in claim.get("evidence") or []
                if evidence.get("source_id")
            }
            if len(source_ids) == 1:
                findings.append(
                    self._finding(
                        category="single_source_support",
                        target_id=subject,
                        locator=f"claim:{predicate}:{obj}",
                        message=f"Key statement '{subject} {predicate} {obj}' has only one registered source.",
                        evidence={
                            "supporting_claims": [self._evidence_summary(item) for item in grouped],
                            "counterexamples": [],
                            "uncertainty": "No independent registered source currently corroborates this statement.",
                        },
                        severity=LintSeverity.INFO,
                    )
                )
            qualifiers = grouped[0].get("qualifiers") or {}
            if predicate in {"expresses", "does_not_express", "has_function"} and not any(
                key in qualifiers for key in ("species", "tissue", "condition", "assay")
            ):
                findings.append(
                    self._finding(
                        category="missing_scientific_context",
                        target_id=subject,
                        locator=f"claim:{predicate}:{obj}",
                        message=f"Statement '{subject} {predicate} {obj}' lacks species, tissue, condition, or assay qualifiers.",
                        evidence={
                            "supporting_claims": [self._evidence_summary(item) for item in grouped],
                            "counterexamples": [],
                            "uncertainty": "The statement may not generalize beyond the source experiment.",
                        },
                        severity=LintSeverity.INFO,
                    )
                )

        for path in sorted((self.project_root / "wiki" / "cell_types").glob("*.md")) if (self.project_root / "wiki" / "cell_types").exists() else []:
            text = path.read_text(encoding="utf-8").lower()
            if any(term in text for term in (" always ", " universally ", " all cells ", "始终", "普遍")):
                related_sources = {
                    str(evidence.get("source_id"))
                    for claim in claims
                    if claim.get("subject") == path.stem
                    for evidence in claim.get("evidence") or []
                    if evidence.get("source_id")
                }
                if len(related_sources) < 2:
                    findings.append(
                        self._finding(
                            category="statement_strength_exceeds_evidence",
                            target_id=path.stem,
                            locator="wiki:body",
                            message="Wiki wording appears universal but fewer than two sources support the page.",
                            evidence={
                                "supporting_claims": [],
                                "counterexamples": [],
                                "uncertainty": "Universal wording requires broader independent evidence.",
                            },
                            severity=LintSeverity.WARNING,
                        )
                    )

        deduplicated = {finding.finding_id: finding for finding in findings}
        result = sorted(deduplicated.values(), key=lambda item: item.finding_id)
        if persist_reviews:
            self._persist_reviews(result)
        return result

    def review_items(self) -> list[ReviewItem]:
        return [
            ReviewItem(
                review_item_id=f"review_{finding.finding_id.removeprefix('lint_')}",
                type=finding.category,
                target_id=finding.target_id,
                description=finding.message,
                severity=RiskLevel.MEDIUM
                if finding.severity == LintSeverity.WARNING
                else RiskLevel.LOW,
                claim_ids=[
                    str(item.get("claim_id"))
                    for evidence in finding.evidence
                    for item in evidence.get("supporting_claims", [])
                    if item.get("claim_id")
                ],
            )
            for finding in self.inspect(persist_reviews=False)
        ]

    def _claims(self) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        extraction_dir = self.project_root / "data" / "extraction"
        for path in sorted(extraction_dir.glob("*.json")) if extraction_dir.exists() else []:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            claims.extend(payload.get("claims") or [])
        return claims

    def _persist_reviews(self, findings: list[LintFinding]) -> None:
        self.review_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "findings": [finding.model_dump(mode="json") for finding in findings],
            "review_items": [item.model_dump(mode="json") for item in self.review_items()],
        }
        temporary = self.review_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(self.review_path)

    @staticmethod
    def _finding(
        *,
        category: str,
        target_id: str,
        locator: str,
        message: str,
        evidence: dict[str, Any],
        severity: LintSeverity,
    ) -> LintFinding:
        return LintFinding(
            finding_id=LintFinding.stable_id(
                level=LintLevel.L2,
                category=category,
                target_id=target_id,
                locator=locator,
            ),
            level=LintLevel.L2,
            severity=severity,
            category=category,
            target_id=target_id,
            locator=locator,
            message=message,
            evidence=[evidence],
            blocking=False,
            auto_fixable=False,
        )

    @staticmethod
    def _evidence_summary(claim: dict[str, Any]) -> dict[str, Any]:
        evidence = claim.get("evidence") or []
        return {
            "claim_id": claim.get("claim_id"),
            "predicate": claim.get("predicate"),
            "source_ids": sorted(
                {str(item.get("source_id")) for item in evidence if item.get("source_id")}
            ),
            "locators": [item.get("locator") or item.get("block_id") for item in evidence],
        }

