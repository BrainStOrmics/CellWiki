# =============================================================================
# 导入服务测试 —— 端到端验证导入管线、缓存复用和冲突审查
# =============================================================================

"""End-to-end tests for grounded ingest, cache reuse, and conflict review items."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from cellwiki.config import Settings
from cellwiki.domain.contracts import ApprovalDecision
from cellwiki.models import CellTypeExtract, ExtractionResult, Marker, MarkerType, PaperReference
from cellwiki.services.central_writer import CentralWriter
from cellwiki.services.ingest import IngestService
from cellwiki.services.operations import CancellationRegistry, OperationCancelled
from cellwiki.services.quality import inspect_projection
from cellwiki.services.sources import SourceRegistry
from cellwiki.services.tasks import TaskEventRepository


FIXTURES = Path(__file__).parent / "fixtures"


class DeterministicExtractor:
    name = "deterministic-fixture"
    version = "1"
    cache_identity = "deterministic-fixture:1"

    def __init__(self):
        self.calls = 0

    def extract(self, chunk, source, *, control=None):
        if control is not None:
            control.raise_if_cancelled()
        self.calls += 1
        paper = PaperReference(
            paper_id=source.source_id,
            title="Fixture paper",
            local_path=source.stored_path,
        )
        text = chunk.text.lower()
        if "regulatory t" not in text:
            return ExtractionResult(paper=paper)
        marker_type = None
        if "foxp3" in text:
            marker_type = MarkerType.NEGATIVE if "negative" in text else MarkerType.POSITIVE
        markers = (
            [Marker(gene_symbol="FOXP3", marker_type=marker_type, evidence="FOXP3")]
            if marker_type
            else []
        )
        return ExtractionResult(
            paper=paper,
            cell_types=[
                CellTypeExtract(
                    name="Regulatory T cell",
                    standard_name="regulatory_t_cell",
                    markers=markers,
                    paper_ref=paper,
                )
            ],
        )


def test_ingest_creates_claim_evidence_and_reuses_chunk_cache(tmp_path: Path):
    source = SourceRegistry(tmp_path).register(
        FIXTURES / "sample_source.md", source_type="paper"
    )
    extractor = DeterministicExtractor()
    ingest = IngestService(tmp_path, extractor=extractor)

    first = ingest.prepare_change_set(source.source_id, "run_fixture_1")
    calls_after_first_run = extractor.calls
    second = ingest.prepare_change_set(source.source_id, "run_fixture_2")

    assert first.change_set_id != second.change_set_id
    assert extractor.calls == calls_after_first_run
    assert first.evidence
    assert first.snapshot_id is not None
    assert first.base_knowledge_version is not None
    assert all(item.block_id and item.page_start for item in first.evidence)
    payload = first.operations[0].payload
    assert payload["claims"]
    assert payload["source_document"]["parser_name"] == "plain-text"
    updated_source = SourceRegistry(tmp_path).get(source.source_id)
    assert updated_source.parse_hash
    assert updated_source.text_hash


def test_cache_hits_do_not_bias_live_request_eta(tmp_path: Path):
    """Near-zero cache reads must not make remaining model work look instantaneous."""

    source = SourceRegistry(tmp_path).register(
        FIXTURES / "sample_source.md", source_type="paper"
    )
    ingest = IngestService(tmp_path, extractor=DeterministicExtractor())
    ingest.prepare_change_set(source.source_id, "run_eta_populate")
    ingest.prepare_change_set(source.source_id, "run_eta_cached")

    completed = [
        event.detail
        for event in TaskEventRepository(tmp_path).list_events("run_eta_cached")
        if event.message.startswith("Completed grounded extraction")
    ]
    assert completed
    assert all(detail.get("cache_hit") is True for detail in completed)
    assert all(detail.get("estimated_remaining_seconds") is None for detail in completed)


def test_ingest_surfaces_marker_direction_conflicts(tmp_path: Path):
    source = SourceRegistry(tmp_path).register(
        FIXTURES / "conflicting_source.md", source_type="paper"
    )

    change_set = IngestService(
        tmp_path, extractor=DeterministicExtractor()
    ).prepare_change_set(source.source_id, "run_conflict")

    conflicts = [item for item in change_set.review_items if item.type == "marker_direction_conflict"]
    assert change_set.risk.value == "high"
    assert conflicts
    assert conflicts[0].claim_ids


def test_real_pdf_runs_source_to_evidence_changeset_projection_and_lint(tmp_path: Path):
    registry = SourceRegistry(tmp_path)
    source = registry.register(FIXTURES / "page_aware_source.pdf", source_type="paper")
    ingest = IngestService(tmp_path, extractor=DeterministicExtractor())

    first = ingest.prepare_change_set(source.source_id, "run_pdf_first")
    CentralWriter(tmp_path).commit(
        first.change_set_id,
        approval=ApprovalDecision(approved=True, decided_by="fixture-test"),
    )
    extraction_path = tmp_path / "data" / "extraction" / f"{source.source_id}.json"
    wiki_page = tmp_path / "wiki" / "cell_types" / "regulatory_t_cell.md"

    assert extraction_path.is_file()
    assert wiki_page.is_file()
    assert wiki_page.read_text(encoding="utf-8") == (
        FIXTURES / "expected_wiki_regulatory_t_cell.md"
    ).read_text(encoding="utf-8")
    assert any(evidence.page_start == 2 and "FOXP3" in evidence.excerpt for evidence in first.evidence)
    assert inspect_projection(tmp_path)["error_count"] == 0

    # Re-ingesting the same immutable source replaces its extraction projection;
    # it does not append duplicate facts or source identities.
    second = ingest.prepare_change_set(source.source_id, "run_pdf_second")
    CentralWriter(tmp_path).commit(
        second.change_set_id,
        approval=ApprovalDecision(approved=True, decided_by="fixture-test"),
    )
    published = extraction_path.read_text(encoding="utf-8")
    assert published.count(f'"paper_id": "{source.source_id}"') >= 1
    assert len(SourceRegistry(tmp_path).list_sources()) == 1


def test_failed_chunk_is_retried_without_repeating_cached_chunks(tmp_path: Path):
    class FlakyExtractor(DeterministicExtractor):
        def __init__(self):
            super().__init__()
            self.attempts: dict[str, int] = {}
            self.failed_once = False

        def extract(self, chunk, source, *, control=None):
            self.attempts[chunk.chunk_id] = self.attempts.get(chunk.chunk_id, 0) + 1
            if len(self.attempts) >= 2 and not self.failed_once:
                self.failed_once = True
                raise RuntimeError("temporary structured output failure")
            return super().extract(chunk, source, control=control)

    source = SourceRegistry(tmp_path).register(
        FIXTURES / "sample_source.md", source_type="paper"
    )
    extractor = FlakyExtractor()
    ingest = IngestService(tmp_path, extractor=extractor)

    with pytest.raises(RuntimeError, match="structured output"):
        ingest.prepare_change_set(source.source_id, "run_flaky_first")
    attempts_after_failure = dict(extractor.attempts)
    assert not (tmp_path / "data" / "extraction" / f"{source.source_id}.json").exists()
    assert not (tmp_path / "wiki" / "cell_types").exists()

    change_set = ingest.prepare_change_set(source.source_id, "run_flaky_retry")

    first_cached_chunk = next(iter(attempts_after_failure))
    assert extractor.attempts[first_cached_chunk] == 1
    assert change_set.evidence


def test_different_files_with_matching_doi_are_flagged_as_version_candidates(tmp_path: Path):
    class DoiExtractor(DeterministicExtractor):
        def extract(self, chunk, source, *, control=None):
            result = super().extract(chunk, source, control=control)
            return result.model_copy(
                update={"paper": result.paper.model_copy(update={"doi": "10.1234/cellwiki", "year": 2025})}
            )

    first_path = FIXTURES / "sample_source.md"
    second_path = tmp_path / "reformatted_source.md"
    second_path.write_text(
        first_path.read_text(encoding="utf-8") + "\n\nReformatted supplementary note.\n",
        encoding="utf-8",
    )
    registry = SourceRegistry(tmp_path)
    first_source = registry.register(first_path, source_type="paper")
    second_source = registry.register(second_path, source_type="paper")

    IngestService(tmp_path, extractor=DoiExtractor()).prepare_change_set(
        first_source.source_id, "run_first_version"
    )
    second = IngestService(tmp_path, extractor=DoiExtractor()).prepare_change_set(
        second_source.source_id, "run_second_version"
    )

    candidates = [
        item for item in second.review_items if item.type == "possible_source_version_duplicate"
    ]
    assert candidates
    assert first_source.source_id in candidates[0].description
    assert first_source.source_id != second_source.source_id


def test_ingest_extracts_multiple_chunks_with_bounded_parallelism(tmp_path: Path):
    """Independent chunks should overlap, while never exceeding the configured worker bound."""

    class ConcurrentExtractor(DeterministicExtractor):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def extract(self, chunk, source, *, control=None):
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(0.03)
                return super().extract(chunk, source, control=control)
            finally:
                with self.lock:
                    self.active -= 1

    source = SourceRegistry(tmp_path).register(
        FIXTURES / "long_52_page_source.pdf", source_type="paper"
    )
    extractor = ConcurrentExtractor()
    ingest = IngestService(tmp_path, extractor=extractor, max_workers=2)

    ingest.prepare_change_set(source.source_id, "run_parallel")

    assert extractor.calls > 2
    assert extractor.max_active == 2
    extraction_details = [
        event.detail
        for event in TaskEventRepository(tmp_path).list_events("run_parallel")
        if event.stage.value == "entity_extraction"
    ]
    assert any(
        detail.get("chunk_index") == 1
        and detail.get("chunk_count") == extractor.calls
        and detail.get("concurrency") == 2
        for detail in extraction_details
    )
    assert any(detail.get("estimated_remaining_seconds") is not None for detail in extraction_details)


def test_ingest_defaults_to_one_provider_worker_for_stability(tmp_path: Path, monkeypatch):
    """The default provider path should avoid overlapping long model requests."""

    monkeypatch.delenv("INGEST_MAX_CONCURRENCY", raising=False)

    with patch("cellwiki.services.ingest.settings", Settings(_env_file=None)):
        ingest = IngestService(tmp_path, extractor=DeterministicExtractor())

    assert ingest.max_workers == 1


def test_chunk_failure_aborts_sibling_model_work(tmp_path: Path):
    """A primary chunk error should cooperatively stop requests already running beside it."""

    both_started = threading.Event()
    sibling_aborted = threading.Event()

    class FailingParallelExtractor(DeterministicExtractor):
        def __init__(self):
            super().__init__()
            self.lock = threading.Lock()

        def extract(self, chunk, source, *, control=None):
            with self.lock:
                self.calls += 1
                call_number = self.calls
                if self.calls >= 2:
                    both_started.set()
            if call_number == 1:
                assert both_started.wait(timeout=1)
                raise RuntimeError("primary chunk failed")
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                assert control is not None
                try:
                    control.raise_if_cancelled()
                except OperationCancelled:
                    sibling_aborted.set()
                    raise
                time.sleep(0.005)
            return super().extract(chunk, source, control=control)

    source = SourceRegistry(tmp_path).register(
        FIXTURES / "long_52_page_source.pdf", source_type="paper"
    )
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="primary chunk failed"):
        IngestService(
            tmp_path,
            extractor=FailingParallelExtractor(),
            max_workers=2,
        ).prepare_change_set(source.source_id, "run_sibling_abort")

    assert sibling_aborted.is_set()
    assert time.monotonic() - started < 0.75


def test_ingest_cancellation_stops_active_chunks_and_preserves_source_state(tmp_path: Path):
    """Cancellation is a terminal user action, not a source-analysis failure."""

    started = threading.Event()

    class CancellableExtractor(DeterministicExtractor):
        def extract(self, chunk, source, *, control=None):
            started.set()
            while True:
                assert control is not None
                control.raise_if_cancelled()
                time.sleep(0.005)

    source = SourceRegistry(tmp_path).register(
        FIXTURES / "page_aware_source.pdf", source_type="paper"
    )
    registry = CancellationRegistry.for_project(tmp_path)
    registry.register("run_cancel_ingest")
    ingest = IngestService(tmp_path, extractor=CancellableExtractor(), max_workers=2)
    outcome: list[BaseException] = []

    worker = threading.Thread(
        target=lambda: _capture_error(
            outcome,
            lambda: ingest.prepare_change_set(source.source_id, "run_cancel_ingest"),
        )
    )
    worker.start()
    assert started.wait(timeout=1)
    registry.cancel("run_cancel_ingest")
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert isinstance(outcome[0], OperationCancelled)
    assert SourceRegistry(tmp_path).get(source.source_id).status.value == "registered"
    assert TaskEventRepository(tmp_path).list_events("run_cancel_ingest")[-1].status.value == "cancelled"


def _capture_error(outcome: list[BaseException], callback) -> None:
    try:
        callback()
    except BaseException as error:
        outcome.append(error)
