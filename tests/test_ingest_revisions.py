from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.extraction import ExtractionResult, PaperReference
from cellwiki.domain.revisions import RevisionStatus
from cellwiki.models import CellTypeExtract
from cellwiki.services.ingest import IngestService
from cellwiki.services.revisions import IngestRevisionService
from cellwiki.services.sources import SourceRegistry


FIXTURE = Path(__file__).parent / "fixtures" / "sample_source.md"


class FeedbackExtractor:
    name = "revision-fixture"
    version = "1"
    cache_identity = "revision-fixture:1"

    def __init__(self) -> None:
        self.feedback: list[tuple[str, ...]] = []

    def extract(self, chunk, source, *, control=None, review_feedback=None):
        if control is not None:
            control.raise_if_cancelled()
        normalized_feedback = tuple(review_feedback or ())
        self.feedback.append(normalized_feedback)
        paper = PaperReference(
            paper_id=source.source_id,
            title="Revision fixture",
            local_path=source.stored_path,
        )
        return ExtractionResult(
            paper=paper,
            cell_types=[
                CellTypeExtract(
                    name="Regulatory T cell",
                    standard_name="regulatory_t_cell",
                    paper_ref=paper,
                )
            ],
        )


def test_review_feedback_creates_a_child_ingest_revision_and_reaches_extractor(
    tmp_path: Path,
) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    extractor = FeedbackExtractor()
    ingest = IngestService(tmp_path, extractor=extractor)
    original = ingest.prepare_change_set(source.source_id, "run_original")

    revisions = IngestRevisionService(tmp_path, ingest=ingest)
    revision = revisions.request_revision(
        original.change_set_id,
        reviewer="default-reviewer",
        comments=["Add the evidence locator for the marker direction."],
    )

    assert revision.status is RevisionStatus.REQUESTED
    assert revision.parent_change_set_id == original.change_set_id
    assert revision.source_id == source.source_id
    assert revision.comments[0].body.startswith("Add the evidence")

    child = revisions.prepare_revision(revision.revision_id, run_id="run_revision")
    stored = revisions.get(revision.revision_id)

    assert child.change_set_id != original.change_set_id
    assert child.revision_id == revision.revision_id
    assert child.parent_change_set_id == original.change_set_id
    assert stored.status is RevisionStatus.READY
    assert stored.change_set_id == child.change_set_id
    assert ("Add the evidence locator for the marker direction.",) in extractor.feedback


def test_revision_request_does_not_mutate_the_original_changeset(tmp_path: Path) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    original = IngestService(tmp_path, extractor=FeedbackExtractor()).prepare_change_set(
        source.source_id,
        "run_original",
    )
    original_json = original.model_dump_json()

    IngestRevisionService(tmp_path).request_revision(
        original.change_set_id,
        reviewer="default-reviewer",
        comments=["Please clarify the source context."],
    )

    assert original.model_dump_json() == original_json


def test_product_api_persists_review_comments_as_a_revision(tmp_path: Path) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    original = IngestService(tmp_path, extractor=FeedbackExtractor()).prepare_change_set(
        source.source_id,
        "run_original",
    )
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
