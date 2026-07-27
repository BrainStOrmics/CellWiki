# =============================================================================
# 研究图测试 —— 验证外部研究发现的 LangGraph 子图
# =============================================================================

from __future__ import annotations

from cellwiki.legacy import research_graph


class _Candidate:
    def model_dump(self, mode: str = "python") -> dict:
        return {
            "candidate_id": "research_fixture",
            "source_id": "src_registered",
            "warnings": ["preprint_not_peer_reviewed"],
        }


def test_legacy_research_seam_emits_only_registered_ingest_candidates(monkeypatch):
    class FakeResearchService:
        def __init__(self, project_root):
            self.project_root = project_root

        def search_and_register(self, query: str, *, project_id: str, limit: int):
            return [_Candidate()]

    monkeypatch.setattr(research_graph, "ResearchService", FakeResearchService)
    state = {
        "search_queries": ["Treg markers"],
        "search_results": [],
        "max_iterations": 1,
    }

    registered = research_graph.register_candidates(state)  # type: ignore[arg-type]
    summarized = research_graph.summarize_candidates(
        {"search_results": registered["search_results"]}  # type: ignore[arg-type]
    )

    proposal = summarized["proposed_updates"][0]
    assert proposal["source_id"] == "src_registered"
    assert proposal["action"] == "ingest_registered_source"
    assert proposal["requires_changeset"] is True
    assert proposal["requires_human_approval"] is True
    assert "create_page" not in str(summarized)
