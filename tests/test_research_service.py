# =============================================================================
# 研究服务测试 —— 验证外部研究结果注册和候选状态
# =============================================================================

"""Research results must be registered and remain candidate-only."""

from __future__ import annotations

from pathlib import Path

from cellwiki.domain.research import (
    ExternalResearchResult,
    ResearchPublicationStatus,
)
from cellwiki.services.research import ResearchService
from cellwiki.services.sources import SourceRegistry


class StaticResearchAdapter:
    def search(self, query: str, *, limit: int):
        return [
            ExternalResearchResult(
                external_id="10.1234/treg",
                title="A public Treg preprint",
                url="https://doi.org/10.1234/treg",
                authors=["A. Researcher"],
                published_year=2026,
                doi="10.1234/treg",
                abstract="FOXP3 evidence candidate.",
                publication_status=ResearchPublicationStatus.PREPRINT,
            )
        ][:limit]


def test_research_registers_source_but_cannot_publish_formal_knowledge(tmp_path: Path):
    service = ResearchService(tmp_path, adapter=StaticResearchAdapter())

    candidates = service.search_and_register("Treg FOXP3")
    candidate = candidates[0]
    source = SourceRegistry(tmp_path).get(candidate.source_id)

    assert source.source_type == "network_metadata"
    assert source.metadata["network_source"]["url"] == "https://doi.org/10.1234/treg"
    assert source.metadata["research_status"] == "candidate_only"
    assert "preprint_not_peer_reviewed" in candidate.warnings
    assert not (tmp_path / "data" / "extraction").exists()
    assert not (tmp_path / "wiki").exists()
    assert not (tmp_path / "data" / "runtime" / "changesets").exists()


def test_research_refresh_captures_snapshot_provenance_and_deduplicates(tmp_path: Path):
    service = ResearchService(tmp_path, adapter=StaticResearchAdapter())

    first = service.refresh("Treg FOXP3", project_id="cellwiki", limit=5)
    second = service.refresh("Treg FOXP3", project_id="cellwiki", limit=5)

    assert first.status == "completed"
    assert first.snapshot_id
    assert first.knowledge_version.startswith("sha256:")
    assert first.provider == "staticresearchadapter"
    assert len(first.candidate_ids) == 1
    assert first.duplicate_candidate_ids == []
    candidate = service.list_candidates()[0]
    assert candidate.candidate_status == "candidate"
    assert candidate.provider == "staticresearchadapter"
    assert candidate.refresh_run_id == first.refresh_run_id
    assert candidate.snapshot_id == first.snapshot_id
    assert second.candidate_ids == []
    assert second.duplicate_candidate_ids == [candidate.candidate_id]
    assert len(service.list_candidates()) == 1
    assert not (tmp_path / "wiki").exists()
