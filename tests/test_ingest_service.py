# =============================================================================
# 导入服务测试 —— Agent 草稿定稿、证据来源、冲突审查与取消
# =============================================================================

"""End-to-end tests for agent-draft ingest, grounding, conflicts, and cancellation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from cellwiki.config import Settings
from cellwiki.domain.contracts import ApprovalDecision
from cellwiki.services.central_writer import CentralWriter
from cellwiki.services.ingest import IngestService
from cellwiki.services.ingest_draft import AgentIngestDraftStore
from cellwiki.services.operations import CancellationRegistry, OperationCancelled
from cellwiki.services.quality import inspect_projection
from cellwiki.services.sources import SourceRegistry
from cellwiki.services.tasks import TaskEventRepository


FIXTURES = Path(__file__).parent / "fixtures"


def _stage_draft(
    project_root: Path,
    source,
    *,
    run_id: str = "draft_1",
    paper_info: dict | None = None,
    cell_types: list[dict] | None = None,
) -> str:
    """Persist a staged ingest-agent draft grounded in the source text."""
    payload = {
        "paper_info": paper_info or {"title": "Fixture paper", "doi": "", "year": 2024},
        "cell_types": cell_types
        or [
            {
                "name": "Regulatory T cell",
                "standard_name": "regulatory_t_cell",
                "markers": [
                    {"gene_symbol": "FOXP3", "marker_type": "positive", "evidence": "FOXP3"}
                ],
            }
        ],
    }
    AgentIngestDraftStore(project_root).save(source.source_id, run_id, payload)
    return run_id


def test_agent_draft_is_required_and_no_chunked_fallback_runs(tmp_path: Path):
    source = SourceRegistry(tmp_path).register(
        FIXTURES / "sample_source.md", source_type="paper"
    )

    with pytest.raises(ValueError, match="agent-only"):
        IngestService(tmp_path).prepare_change_set(source.source_id, "run_no_draft")

    assert SourceRegistry(tmp_path).get(source.source_id).status.value == "registered"
    assert not (tmp_path / "data" / "extraction" / f"{source.source_id}.json").exists()


def test_ingest_creates_claim_evidence_from_agent_draft_and_reuses_it(tmp_path: Path):
    source = SourceRegistry(tmp_path).register(
        FIXTURES / "sample_source.md", source_type="paper"
    )
    _stage_draft(tmp_path, source, run_id="draft_fixture")
    ingest = IngestService(tmp_path)

    first = ingest.prepare_change_set(
        source.source_id, "run_fixture_1", agent_draft_run_id="draft_fixture"
    )
    second = ingest.prepare_change_set(
        source.source_id, "run_fixture_2", agent_draft_run_id="draft_fixture"
    )

    assert first.change_set_id != second.change_set_id
    assert first.evidence
    assert first.snapshot_id is not None
    assert first.base_knowledge_version is not None
    assert all(item.block_id and item.page_start for item in first.evidence)
    payload = first.operations[0].payload
    assert payload["claims"]
    assert payload["source_document"]["parser_name"] == "plain-text"
    chunking = [
        event.detail
        for event in TaskEventRepository(tmp_path).list_events("run_fixture_1")
        if event.stage.value == "chunking"
    ]
    assert chunking and chunking[0].get("extraction_mode") == "agent_draft"
    updated_source = SourceRegistry(tmp_path).get(source.source_id)
    assert updated_source.parse_hash
    assert updated_source.text_hash


def test_ingest_surfaces_marker_direction_conflicts(tmp_path: Path):
    source = SourceRegistry(tmp_path).register(
        FIXTURES / "conflicting_source.md", source_type="paper"
    )
    _stage_draft(
        tmp_path,
        source,
        run_id="draft_conflict",
        cell_types=[
            {
                "name": "Regulatory T cell",
                "standard_name": "regulatory_t_cell",
                "markers": [
                    {"gene_symbol": "FOXP3", "marker_type": "positive", "evidence": "FOXP3"}
                ],
            },
            {
                "name": "Regulatory T cell",
                "standard_name": "regulatory_t_cell",
                "markers": [
                    {"gene_symbol": "FOXP3", "marker_type": "negative", "evidence": "FOXP3"}
                ],
            },
        ],
    )

    change_set = IngestService(tmp_path).prepare_change_set(
        source.source_id, "run_conflict", agent_draft_run_id="draft_conflict"
    )

    conflicts = [
        item for item in change_set.review_items if item.type == "marker_direction_conflict"
    ]
    assert change_set.risk.value == "high"
    assert conflicts
    assert conflicts[0].claim_ids


def test_real_pdf_runs_source_to_evidence_changeset_projection_and_lint(tmp_path: Path):
    registry = SourceRegistry(tmp_path)
    source = registry.register(FIXTURES / "page_aware_source.pdf", source_type="paper")
    _stage_draft(tmp_path, source, run_id="draft_pdf")
    ingest = IngestService(tmp_path)

    first = ingest.prepare_change_set(
        source.source_id, "run_pdf_first", agent_draft_run_id="draft_pdf"
    )
    CentralWriter(tmp_path).commit(
        first.change_set_id,
        approval=ApprovalDecision(approved=True, decided_by="fixture-test"),
    )
    extraction_path = tmp_path / "data" / "extraction" / f"{source.source_id}.json"
    wiki_page = tmp_path / "wiki" / "cell_types" / "regulatory_t_cell.md"

    assert extraction_path.is_file()
    assert wiki_page.is_file()
    expected_page = (
        FIXTURES / "expected_wiki_regulatory_t_cell.md"
    ).read_text(encoding="utf-8").replace("src_8967205c87259b809eae", source.source_id)
    assert wiki_page.read_text(encoding="utf-8") == expected_page
    assert any(
        evidence.page_start == 2 and "FOXP3" in evidence.excerpt
        for evidence in first.evidence
    )
    assert inspect_projection(tmp_path)["error_count"] == 0

    second = ingest.prepare_change_set(
        source.source_id, "run_pdf_second", agent_draft_run_id="draft_pdf"
    )
    CentralWriter(tmp_path).commit(
        second.change_set_id,
        approval=ApprovalDecision(approved=True, decided_by="fixture-test"),
    )
    published = extraction_path.read_text(encoding="utf-8")
    assert published.count(f'"paper_id": "{source.source_id}"') >= 1
    assert len(SourceRegistry(tmp_path).list_sources()) == 1


def test_different_files_with_matching_doi_are_flagged_as_version_candidates(tmp_path: Path):
    first_path = FIXTURES / "sample_source.md"
    second_path = tmp_path / "reformatted_source.md"
    second_path.write_text(
        first_path.read_text(encoding="utf-8") + "\n\nReformatted supplementary note.\n",
        encoding="utf-8",
    )
    registry = SourceRegistry(tmp_path)
    first_source = registry.register(first_path, source_type="paper")
    second_source = registry.register(second_path, source_type="paper")
    paper_info = {"title": "Fixture paper", "doi": "10.1234/cellwiki", "year": 2025}
    _stage_draft(tmp_path, first_source, run_id="draft_v1", paper_info=paper_info)
    _stage_draft(tmp_path, second_source, run_id="draft_v2", paper_info=paper_info)
    ingest = IngestService(tmp_path)

    ingest.prepare_change_set(
        first_source.source_id, "run_first_version", agent_draft_run_id="draft_v1"
    )
    second = ingest.prepare_change_set(
        second_source.source_id, "run_second_version", agent_draft_run_id="draft_v2"
    )

    candidates = [
        item
        for item in second.review_items
        if item.type == "possible_source_version_duplicate"
    ]
    assert candidates
    assert first_source.source_id in candidates[0].description
    assert first_source.source_id != second_source.source_id


def test_ingest_cancellation_is_checked_at_entry_and_preserves_source_state(tmp_path: Path):
    source = SourceRegistry(tmp_path).register(
        FIXTURES / "sample_source.md", source_type="paper"
    )
    _stage_draft(tmp_path, source, run_id="draft_cancel")
    registry = CancellationRegistry.for_project(tmp_path)
    registry.register("run_cancel_ingest")
    registry.cancel("run_cancel_ingest")

    with pytest.raises(OperationCancelled):
        IngestService(tmp_path).prepare_change_set(
            source.source_id, "run_cancel_ingest", agent_draft_run_id="draft_cancel"
        )

    assert SourceRegistry(tmp_path).get(source.source_id).status.value == "registered"
    ledger = TaskEventRepository(tmp_path).list_events("run_cancel_ingest")
    assert ledger[-1].status.value == "cancelled"
    assert AgentIngestDraftStore(tmp_path).load(source.source_id, "draft_cancel") is not None


def test_ingest_max_output_tokens_defaults_12000_and_caps_at_64k() -> None:
    assert Settings(_env_file=None).ingest_max_output_tokens == 12000
    assert (
        Settings(_env_file=None, ingest_max_output_tokens=65_536).ingest_max_output_tokens
        == 65_536
    )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ingest_max_output_tokens=65_537)
