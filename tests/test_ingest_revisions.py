# =============================================================================
# 修订测试 —— 反馈记录与 Agent 草稿定稿的子变更集
# =============================================================================

"""Revision request persistence and agent-draft revision finalization."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.revisions import RevisionStatus
from cellwiki.services.ingest import IngestService
from cellwiki.services.ingest_draft import AgentIngestDraftStore
from cellwiki.services.revisions import IngestRevisionService
from cellwiki.services.sources import SourceRegistry


FIXTURE = Path(__file__).parent / "fixtures" / "sample_source.md"


def _stage_draft(project_root: Path, source, *, run_id: str = "draft_1") -> str:
    AgentIngestDraftStore(project_root).save(
        source.source_id,
        run_id,
        {
            "paper_info": {"title": "Revision fixture", "doi": "", "year": 2024},
            "cell_types": [
                {
                    "name": "Regulatory T cell",
                    "standard_name": "regulatory_t_cell",
                    "markers": [
                        {"gene_symbol": "FOXP3", "marker_type": "positive", "evidence": "FOXP3"}
                    ],
                }
            ],
        },
    )
    return run_id


def _prepare_original(project_root: Path, source):
    _stage_draft(project_root, source, run_id="draft_original")
    return IngestService(project_root).prepare_change_set(
        source.source_id,
        "run_original",
        agent_draft_run_id="draft_original",
    )


def test_revision_feedback_creates_a_child_ingest_revision_finalized_from_a_new_draft(
    tmp_path: Path,
) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    original = _prepare_original(tmp_path, source)
    revisions = IngestRevisionService(tmp_path)

    revision = revisions.request_revision(
        original.change_set_id,
        reviewer="default-reviewer",
        comments=["Add the evidence locator for the marker direction."],
    )

    assert revision.status is RevisionStatus.REQUESTED
    assert revision.parent_change_set_id == original.change_set_id
    assert revision.source_id == source.source_id
    assert revision.comments[0].body.startswith("Add the evidence")

    _stage_draft(tmp_path, source, run_id="draft_child")
    child = revisions.prepare_revision(
        revision.revision_id,
        run_id="run_revision",
        agent_draft_run_id="draft_child",
    )
    stored = revisions.get(revision.revision_id)

    assert child.change_set_id != original.change_set_id
    assert child.revision_id == revision.revision_id
    assert child.parent_change_set_id == original.change_set_id
    assert stored.status is RevisionStatus.READY
    assert stored.change_set_id == child.change_set_id


def test_prepare_revision_fails_fast_without_a_staged_draft(tmp_path: Path) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    original = _prepare_original(tmp_path, source)
    revisions = IngestRevisionService(tmp_path)
    revision = revisions.request_revision(
        original.change_set_id,
        reviewer="default-reviewer",
        comments=["Missing draft guarantee."],
    )

    with pytest.raises(ValueError, match="agent-only"):
        revisions.prepare_revision(
            revision.revision_id,
            run_id="run_no_draft",
            agent_draft_run_id="draft_missing",
        )

    assert revisions.get(revision.revision_id).status is RevisionStatus.REQUESTED


def test_revision_request_does_not_mutate_the_original_changeset(tmp_path: Path) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    original = _prepare_original(tmp_path, source)
    original_json = original.model_dump_json()

    IngestRevisionService(tmp_path).request_revision(
        original.change_set_id,
        reviewer="default-reviewer",
        comments=["Please clarify the source context."],
    )

    assert original.model_dump_json() == original_json


def test_product_api_persists_review_comments_as_a_revision(tmp_path: Path) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    original = _prepare_original(tmp_path, source)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        f"/api/changesets/{original.change_set_id}/revision",
        json={
            "reviewer": "default-reviewer",
            "comments": ["Please include the source section in the evidence summary."],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["revision"]["status"] == "requested"
    assert payload["revision"]["parent_change_set_id"] == original.change_set_id
    assert payload["revision"]["comments"][0]["author"] == "default-reviewer"
