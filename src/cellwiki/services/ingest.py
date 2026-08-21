# =============================================================================
# 导入服务 —— 从注册来源到不可变 ChangeSet 的基于证据的导入模块
# =============================================================================

# ---------------------------------------------------------------------------
# IngestService —— 导入服务
# 从注册来源到不可变 ChangeSet 的基于证据的导入管线。
# 核心流程：
# 1. 读取注册来源（SourceRecord）
# 2. 选择解析器解析文档（ParsedDocument）
# 3. 分块（DocumentChunk）
# 4. 调用 LLM 提取实体
# 5. 验证提取结果
# 6. 检测与现有知识的冲突
# 7. 生成不可变的 ChangeSet（不发布）
# 导入管线支持取消操作和进度报告，通过 OperationControl 实现。
# 使用缓存避免重复解析相同内容的来源。
# ---------------------------------------------------------------------------

"""Evidence-grounded ingest module from registered source to immutable ChangeSet."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from cellwiki.config import settings
from cellwiki.adapters.openai_extraction import OpenAIChunkExtractor
from cellwiki.domain.contracts import (
    ChangeOperation,
    ChangeOperationType,
    ChangeSet,
    Claim,
    EvidenceReference,
    EvidenceType,
    IngestStage,
    ReviewItem,
    RiskLevel,
    SourceRecord,
    SourceStatus,
    TaskStatus,
    KnowledgeSnapshot,
    PipelineTaskType,
)
from cellwiki.domain.documents import DocumentChunk, ParsedDocument
from cellwiki.domain.extraction import (
    PaperReference,
    CellTypeExtract,
    ExtractionResult,
    FunctionalCharacteristic,
    Marker,
)
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.chunking import chunk_document
from cellwiki.services.ingest_draft import AgentIngestDraftStore
from cellwiki.services.naming import (
    canonicalize_standard_name,
    is_cluster_identifier,
    normalize_standard_name,
)
from cellwiki.services.extraction import ChunkExtractor
from cellwiki.services.parsing import DocumentParsingService
from cellwiki.services.sources import SourceRegistry
from cellwiki.services.tasks import TaskEventRepository
from cellwiki.services.operations import (
    CancellationRegistry,
    OperationCancelled,
    OperationControl,
    OperationProgress,
)
from cellwiki.services.pipeline import KnowledgePipelineHarness


@dataclass
class _ParallelProgress:
    completed: int = 0
    live_completed: int = 0
    total_live_duration: float = 0.0


class IngestService:
    """Deep module owning parsing, chunk retries, evidence validation, conflicts, and proposal creation."""

    def __init__(
        self,
        project_root: Path,
        *,
        extractor: ChunkExtractor | None = None,
        parsing: DocumentParsingService | None = None,
        sources: SourceRegistry | None = None,
        changesets: ChangeSetRepository | None = None,
        tasks: TaskEventRepository | None = None,
        cancellations: CancellationRegistry | None = None,
        pipeline: KnowledgePipelineHarness | None = None,
        max_workers: int | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.extractor = extractor or OpenAIChunkExtractor()
        self.parsing = parsing or DocumentParsingService(self.project_root)
        self.sources = sources or SourceRegistry(self.project_root)
        self.changesets = changesets or ChangeSetRepository(self.project_root)
        self.tasks = tasks or TaskEventRepository(self.project_root)
        self.cancellations = cancellations or CancellationRegistry.for_project(self.project_root)
        self.pipeline = pipeline or KnowledgePipelineHarness(self.project_root)
        self.max_workers = max_workers or settings.ingest_max_concurrency
        if not 1 <= self.max_workers <= 4:
            raise ValueError("ingest max_workers must be between 1 and 4")
        self.cache_root = self.project_root / "data" / "runtime" / "extraction_cache"
        self._event_lock = threading.Lock()

    def prepare_change_set(
        self,
        source_id: str,
        run_id: str,
        *,
        force_parse: bool = False,
        force_extract: bool = False,
        cancellation_id: str | None = None,
        review_feedback: list[str] | None = None,
        revision_id: str | None = None,
        parent_change_set_id: str | None = None,
        parent_revision_id: str | None = None,
        agent_draft_run_id: str | None = None,
    ) -> ChangeSet:
        """Create a grounded proposal after reading the whole project state."""

        with self.pipeline.acquire(task_type=PipelineTaskType.INGEST, run_id=run_id) as lease:
            return self._prepare_change_set(
                source_id,
                run_id,
                force_parse=force_parse,
                force_extract=force_extract,
                cancellation_id=cancellation_id,
                review_feedback=review_feedback,
                revision_id=revision_id,
                parent_change_set_id=parent_change_set_id,
                parent_revision_id=parent_revision_id,
                agent_draft_run_id=agent_draft_run_id,
                snapshot=lease.snapshot,
            )

    def _prepare_change_set(
        self,
        source_id: str,
        run_id: str,
        *,
        force_parse: bool,
        force_extract: bool,
        cancellation_id: str | None,
        review_feedback: list[str] | None,
        revision_id: str | None,
        parent_change_set_id: str | None,
        parent_revision_id: str | None,
        agent_draft_run_id: str | None,
        snapshot: KnowledgeSnapshot,
    ) -> ChangeSet:
        """Build a proposal while the caller holds the project pipeline lease."""

        progress = 5
        operation_id = cancellation_id or run_id
        cancellation = self.cancellations.token(operation_id)
        operation_started = time.monotonic()
        self._event(run_id, source_id, IngestStage.SOURCE_READ, "Loading the registered source.", progress)
        try:
            if cancellation.is_set():
                raise OperationCancelled(f"operation {operation_id} was cancelled")
            source = self.sources.get(source_id)
            progress = 15
            self._event(run_id, source_id, IngestStage.PARSING, "Parsing the source with page locators.", progress)
            document = self.parsing.parse(source, force=force_parse)
            text_hash = _text_hash(document)
            self.sources.update_parse_metadata(
                source_id,
                parser_name=document.parser_name,
                parser_version=document.parser_version,
                parse_hash=document.parse_hash,
                text_hash=text_hash,
                metadata={**document.metadata, "parser_config": document.parser_config},
            )

            progress = 25
            if agent_draft_run_id is not None:
                draft = AgentIngestDraftStore(self.project_root).load(source_id, agent_draft_run_id)
                if draft is None:
                    raise ValueError(
                        f"agent ingest draft {agent_draft_run_id!r} was not found for source {source_id}"
                    )
                self._event(
                    run_id,
                    source_id,
                    IngestStage.CHUNKING,
                    "Finalizing staged agent ingest draft with deterministic guards.",
                    progress,
                    detail={
                        "draft_run_id": agent_draft_run_id,
                        "candidate_cell_types": len(draft.get("payload", {}).get("cell_types", [])),
                    },
                )
                extraction, review_items = _finalize_agent_draft(source, document, draft["payload"])
                progress = 68
                conflicts = [item for item in review_items if item.severity == RiskLevel.HIGH]
            else:
                # Smaller evidence chunks keep structured responses bounded. Two workers
                # recover throughput without creating an unbounded provider burst.
                chunks = chunk_document(
                    document,
                    max_characters=7_000,
                    overlap_characters=400,
                )
                self._event(
                    run_id,
                    source_id,
                    IngestStage.CHUNKING,
                    f"Prepared {len(chunks)} evidence-aware document chunk(s).",
                    progress,
                    detail={"chunk_count": len(chunks), "page_count": len(document.pages)},
                )
                if not chunks:
                    raise ValueError("parsed source produced no extractable document chunks")

                progress_state = _ParallelProgress()
                progress_lock = threading.Lock()
                batch_abort = threading.Event()
                results: dict[int, tuple[ExtractionResult, list[ReviewItem]]] = {}

                def progress_detail(
                    index: int,
                    update: OperationProgress | None = None,
                ) -> dict[str, int | float | str | None]:
                    with progress_lock:
                        elapsed = max(0.0, time.monotonic() - operation_started)
                        average = (
                            progress_state.total_live_duration / progress_state.live_completed
                            if progress_state.live_completed
                            else None
                        )
                        remaining = len(chunks) - progress_state.completed
                        eta = (
                            average * ((remaining + self.max_workers - 1) // self.max_workers)
                            if average is not None
                            else None
                        )
                        return {
                            "chunk_index": index,
                            "chunk_count": len(chunks),
                            "completed_chunks": progress_state.completed,
                            "concurrency": min(self.max_workers, len(chunks)),
                            "elapsed_seconds": round(elapsed, 1),
                            "estimated_remaining_seconds": round(eta, 1) if eta is not None else None,
                            "request_state": update.state if update else None,
                            "attempt": update.attempt if update else None,
                            "max_attempts": update.max_attempts if update else None,
                            "attempt_elapsed_seconds": (
                                round(update.attempt_elapsed_seconds, 1) if update else None
                            ),
                            "error": update.error if update else None,
                        }

                def extract_one(
                    index: int,
                    chunk: DocumentChunk,
                ) -> tuple[int, ExtractionResult, list[ReviewItem]]:
                    control = OperationControl(
                        operation_id,
                        cancellation,
                        additional_cancellation=batch_abort,
                        progress=lambda update: self._event(
                            run_id,
                            source_id,
                            IngestStage.ENTITY_EXTRACTION,
                            (
                                f"Chunk {index}/{len(chunks)} model attempt "
                                f"{update.attempt}/{update.max_attempts}: {update.state}."
                            ),
                            25 + int(35 * progress_state.completed / max(1, len(chunks))),
                            detail=progress_detail(index, update),
                        ),
                    )
                    control.raise_if_cancelled()
                    chunk_started = time.monotonic()
                    self._event(
                        run_id,
                        source_id,
                        IngestStage.ENTITY_EXTRACTION,
                        f"Extracting grounded facts from chunk {index}/{len(chunks)}.",
                        25 + int(35 * progress_state.completed / max(1, len(chunks))),
                        detail={
                            **progress_detail(index),
                            "chunk_id": chunk.chunk_id,
                            "page_start": chunk.page_start,
                            "page_end": chunk.page_end,
                        },
                    )
                    extraction, cache_hit = self._extract_chunk(
                        source,
                        document,
                        chunk,
                        force=force_extract,
                        control=control,
                        review_feedback=review_feedback,
                    )
                    validated, gaps = _ground_extraction(source, document, chunk, extraction)
                    control.raise_if_cancelled()
                    duration = time.monotonic() - chunk_started
                    with progress_lock:
                        progress_state.completed += 1
                        if not cache_hit:
                            progress_state.live_completed += 1
                            progress_state.total_live_duration += duration
                        completed = progress_state.completed
                    self._event(
                        run_id,
                        source_id,
                        IngestStage.ENTITY_EXTRACTION,
                        f"Completed grounded extraction for chunk {index}/{len(chunks)}.",
                        25 + int(35 * completed / max(1, len(chunks))),
                        detail={
                            **progress_detail(index),
                            "chunk_duration_seconds": round(duration, 1),
                            "cache_hit": cache_hit,
                        },
                    )
                    return index, validated, gaps


                with ThreadPoolExecutor(
                    max_workers=min(self.max_workers, len(chunks)),
                    thread_name_prefix="cellwiki-ingest",
                ) as executor:
                    futures = {
                        executor.submit(extract_one, index, chunk): index
                        for index, chunk in enumerate(chunks, start=1)
                    }
                    try:
                        for future in as_completed(futures):
                            index, extraction_chunk, gaps = future.result()
                            results[index] = (extraction_chunk, gaps)
                    except Exception:
                        # Stop requests already running beside the failed chunk. Their
                        # cancellation errors are secondary; the primary error is re-raised.
                        batch_abort.set()
                        for future in futures:
                            future.cancel()
                        raise

                grounded = [results[index][0] for index in sorted(results)]
                review_items = [
                    item
                    for index in sorted(results)
                    for item in results[index][1]
                ]

                progress = 68
                self._event(run_id, source_id, IngestStage.CONFLICT_ANALYSIS, "Merging duplicate entities and detecting conflicts.", progress)
                extraction, conflicts = _merge_extractions(source, document, grounded)
                review_items.extend(conflicts)
            source_candidates = self.sources.find_paper_candidates(
                source_id,
                doi=extraction.paper.doi,
                title=extraction.paper.title,
                year=extraction.paper.year,
            )
            for candidate_id, match_reason in source_candidates:
                review_items.append(
                    _review_item(
                        "possible_source_version_duplicate",
                        source_id,
                        (
                            f"Source {candidate_id} may be another file version of this paper "
                            f"({match_reason}); source identities were kept separate."
                        ),
                        RiskLevel.MEDIUM,
                    )
                )
            self.sources.update_metadata(
                source_id,
                {
                    "paper_identity": {
                        "doi": extraction.paper.doi,
                        "title": extraction.paper.title,
                        "year": extraction.paper.year,
                    }
                },
            )

            progress = 72
            self._event(
                run_id,
                source_id,
                IngestStage.VALIDATION,
                "Validating claim-level evidence against parsed source blocks.",
                progress,
                detail={"claim_count": len(extraction.claims), "review_item_count": len(review_items)},
            )
            _validate_claim_evidence(document, extraction.claims)
            if not extraction.claims:
                raise ValueError("ingest produced no source-grounded claims")

            target = self.project_root / "data" / "extraction" / f"{source_id}.json"
            if target.is_file():
                previous = ExtractionResult.model_validate_json(target.read_text(encoding="utf-8"))
                previous_document = previous.source_document
                parser_changed = any(
                    previous_document.get(key) != extraction.source_document.get(key)
                    for key in ("parse_hash", "parser_name", "parser_version", "parser_config")
                )
                if parser_changed and previous.model_dump(mode="json") != extraction.model_dump(mode="json"):
                    review_items.append(
                        _review_item(
                            "source_reparse_changed",
                            source_id,
                            "A new parser result changed the existing formal extraction for this source.",
                            RiskLevel.MEDIUM,
                        )
                    )
            evidence = _unique_evidence(extraction.claims)
            change_set = ChangeSet(
                change_set_id=_change_set_id(source, document, extraction, run_id),
                run_id=run_id,
                project_id="cellwiki",
                operations=[
                    ChangeOperation(
                        type=ChangeOperationType.UPSERT_EXTRACTION,
                        target_id=source_id,
                        payload=extraction.model_dump(mode="json"),
                        expected_version=_file_version(target),
                    )
                ],
                evidence=evidence,
                review_items=_unique_review_items(review_items),
                risk=RiskLevel.HIGH if conflicts else RiskLevel.MEDIUM,
                reason=f"Publish {len(extraction.claims)} grounded claims from source {source_id}.",
                snapshot_id=snapshot.snapshot_id,
                base_knowledge_version=snapshot.knowledge_version,
                revision_id=revision_id,
                parent_change_set_id=parent_change_set_id,
            )
            self.changesets.save(change_set)
            self.sources.update_status(source_id, SourceStatus.ANALYZED)
            self._event(
                run_id,
                source_id,
                IngestStage.HUMAN_REVIEW,
                "ChangeSet is ready for human review.",
                75,
                status=TaskStatus.AWAITING_REVIEW,
                change_set_id=change_set.change_set_id,
                detail={
                    "cell_type_count": len(extraction.cell_types),
                    "claim_count": len(extraction.claims),
                    "evidence_count": len(evidence),
                    "review_item_count": len(change_set.review_items),
                },
            )
            return change_set
        except OperationCancelled:
            self._event(
                run_id,
                source_id,
                IngestStage.ENTITY_EXTRACTION,
                "Ingest analysis was cancelled by the user.",
                progress,
                status=TaskStatus.CANCELLED,
                detail={"elapsed_seconds": round(time.monotonic() - operation_started, 1)},
            )
            raise
        except Exception as error:
            self.sources.mark_failed(source_id, str(error))
            self._event(
                run_id,
                source_id,
                IngestStage.ENTITY_EXTRACTION,
                "Ingest analysis failed.",
                progress,
                status=TaskStatus.FAILED,
                detail={"error": str(error)},
            )
            raise

    def _extract_chunk(
        self,
        source: SourceRecord,
        document: ParsedDocument,
        chunk: DocumentChunk,
        *,
        force: bool,
        control: OperationControl,
        review_feedback: list[str] | None = None,
    ) -> tuple[ExtractionResult, bool]:
        control.raise_if_cancelled()
        material = "\0".join(
            [
                source.content_hash,
                document.parse_hash,
                chunk.chunk_id,
                self.extractor.cache_identity,
                "schema:3",
                json.dumps(review_feedback or [], ensure_ascii=False, separators=(",", ":")),
            ]
        )
        key = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
        cache_path = self.cache_root / source.source_id / f"{key}.json"
        if cache_path.exists() and not force:
            return (
                ExtractionResult.model_validate_json(cache_path.read_text(encoding="utf-8")),
                True,
            )
        if review_feedback:
            result = self.extractor.extract(
                chunk,
                source,
                control=control,
                review_feedback=review_feedback,
            )
        else:
            result = self.extractor.extract(chunk, source, control=control)
        control.raise_if_cancelled()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".json.tmp")
        temporary.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(cache_path)
        return result, False

    def _event(
        self,
        run_id: str,
        source_id: str,
        stage: IngestStage,
        message: str,
        progress: int,
        *,
        status: TaskStatus = TaskStatus.RUNNING,
        change_set_id: str | None = None,
        detail: dict | None = None,
    ) -> None:
        with self._event_lock:
            self.tasks.record(
                run_id=run_id,
                source_id=source_id,
                stage=stage,
                status=status,
                message=message,
                progress=progress,
                change_set_id=change_set_id,
                detail=detail or {},
            )


def _ground_extraction(
    source: SourceRecord,
    document: ParsedDocument,
    chunk: DocumentChunk,
    extraction: ExtractionResult,
) -> tuple[ExtractionResult, list[ReviewItem]]:
    """Drop ungrounded fields and produce claims only from exact source occurrences."""
    return _ground_extraction_impl(source, document, extraction, chunk=chunk)


def _ground_extraction_document(
    source: SourceRecord,
    document: ParsedDocument,
    extraction: ExtractionResult,
) -> tuple[ExtractionResult, list[ReviewItem]]:
    """Document-wide grounding for staged agent drafts (no chunk boundary)."""
    return _ground_extraction_impl(source, document, extraction, chunk=None)


def _ground_extraction_impl(
    source: SourceRecord,
    document: ParsedDocument,
    extraction: ExtractionResult,
    *,
    chunk: DocumentChunk | None,
) -> tuple[ExtractionResult, list[ReviewItem]]:
    """Drop ungrounded fields and produce claims only from exact source occurrences."""
    paper = extraction.paper.model_copy(update={"paper_id": source.source_id, "local_path": source.stored_path})
    cell_types: list[CellTypeExtract] = []
    claims: list[Claim] = []
    gaps: list[ReviewItem] = []

    def lookup(term: str) -> EvidenceReference | None:
        if chunk is not None:
            return _evidence_for_term(source, document, chunk, term)
        return _evidence_for_term_document(source, document, term)

    for candidate in extraction.cell_types:
        # Naming guard: paper-internal cluster identifiers never become durable names.
        raw = candidate.standard_name
        canonical, _issue = canonicalize_standard_name(raw)
        fallback = ""
        if canonical is None:
            fallback = normalize_standard_name(candidate.name)
            if fallback and not is_cluster_identifier(fallback):
                canonical = fallback
        if canonical is None:
            gaps.append(
                _review_item(
                    "cluster_id_standard_name",
                    raw or candidate.name,
                    (
                        f"The extracted entity {candidate.name!r} uses a paper-internal cluster "
                        "identifier and has no safe biological name; it was not published."
                    ),
                    RiskLevel.HIGH,
                )
            )
            continue
        if fallback:
            candidate = candidate.model_copy(
                update={"standard_name": canonical, "synonyms": [*(candidate.synonyms or []), raw]}
            )

        mention = lookup(candidate.name)
        if mention is None:
            mention = lookup(canonical.replace("_", " "))
        if mention is None:
            gaps.append(
                _review_item(
                    "ungrounded_entity",
                    canonical,
                    f"The extracted entity {candidate.name!r} could not be located verbatim in the source.",
                    RiskLevel.HIGH,
                )
            )
            continue

        subject = canonical
        claims.append(_claim(subject, "mentioned_as", candidate.name, mention))
        markers: list[Marker] = []
        for marker in candidate.markers:
            evidence = lookup(marker.gene_symbol)
            if marker.evidence:
                evidence = lookup(marker.evidence) or evidence
            if evidence is None:
                gaps.append(
                    _review_item(
                        "missing_marker_evidence",
                        subject,
                        f"Marker {marker.gene_symbol} was proposed without a verbatim source occurrence.",
                        RiskLevel.MEDIUM,
                    )
                )
                continue
            predicate = {
                "positive": "positive_marker",
                "negative": "negative_marker",
                "transcript": "transcript_marker",
            }[marker.marker_type.value]
            claims.append(_claim(subject, predicate, marker.gene_symbol, evidence))
            markers.append(marker.model_copy(update={"evidence": evidence.excerpt}))

        functions: list[FunctionalCharacteristic] = []
        for function in candidate.functions:
            search_term = function.evidence or function.description
            evidence = lookup(search_term)
            if evidence is None:
                continue
            claims.append(_claim(subject, "has_function", function.description, evidence))
            functions.append(function.model_copy(update={"evidence": evidence.excerpt}))

        contexts: dict[str, list[str]] = {}
        for predicate, values in (
            ("species", candidate.species),
            ("tissue", candidate.tissues),
            ("disease", candidate.diseases),
        ):
            grounded_values: list[str] = []
            for value in values:
                evidence = lookup(value)
                if evidence is not None:
                    grounded_values.append(value)
                    claims.append(_claim(subject, predicate, value, evidence))
            contexts[predicate] = grounded_values

        parent_type = candidate.parent_type
        if parent_type:
            if is_cluster_identifier(parent_type):
                gaps.append(
                    _review_item(
                        "cluster_id_parent_type",
                        subject,
                        f"Parent type {parent_type!r} is a paper-internal cluster identifier; parent was dropped.",
                        RiskLevel.MEDIUM,
                    )
                )
                parent_type = None
            else:
                parent_evidence = lookup(parent_type.replace("_", " "))
                if parent_evidence is None:
                    parent_type = None
                else:
                    claims.append(_claim(subject, "is_a", parent_type, parent_evidence))

        cell_types.append(
            candidate.model_copy(
                update={
                    "standard_name": subject,
                    "paper_ref": paper,
                    "description": mention.excerpt,
                    "markers": markers,
                    "functions": functions,
                    "species": contexts["species"],
                    "tissues": contexts["tissue"],
                    "diseases": contexts["disease"],
                    "parent_type": parent_type,
                    "synonyms": [
                        synonym
                        for synonym in candidate.synonyms
                        if lookup(synonym) is not None
                    ],
                    "subpopulations": [],
                }
            )
        )

    return (
        ExtractionResult(
            paper=paper,
            cell_types=cell_types,
            raw_relationships=[],
            claims=_unique_claims(claims),
            source_document={
                "source_id": source.source_id,
                "parse_hash": document.parse_hash,
                "parser_name": document.parser_name,
                "parser_version": document.parser_version,
                "parser_config": document.parser_config,
            },
        ),
        gaps,
    )




def _merge_extractions(
    source: SourceRecord,
    document: ParsedDocument,
    extractions: list[ExtractionResult],
) -> tuple[ExtractionResult, list[ReviewItem]]:
    if not extractions:
        raise ValueError("no chunk extractions were produced")
    paper = extractions[0].paper.model_copy(update={"paper_id": source.source_id, "local_path": source.stored_path})
    merged: dict[str, CellTypeExtract] = {}
    claims = _unique_claims([claim for extraction in extractions for claim in extraction.claims])
    conflicts: list[ReviewItem] = []

    for extraction in extractions:
        for candidate in extraction.cell_types:
            key = normalize_standard_name(candidate.standard_name)
            if not key:
                continue
            existing = merged.get(key)
            if existing is None:
                candidate = _attach_casing_alias(candidate, key)
                merged[key] = candidate
                continue
            if candidate.standard_name != existing.standard_name:
                existing = existing.model_copy(
                    update={"synonyms": sorted(set(existing.synonyms + [candidate.standard_name]))}
                )
            if existing.cl_id and candidate.cl_id and existing.cl_id != candidate.cl_id:
                conflicts.append(
                    _review_item(
                        "ontology_mapping_conflict",
                        candidate.standard_name,
                        f"Conflicting Cell Ontology IDs: {existing.cl_id} and {candidate.cl_id}.",
                        RiskLevel.HIGH,
                    )
                )
            marker_types: dict[str, set[str]] = {}
            for marker in [*existing.markers, *candidate.markers]:
                marker_types.setdefault(marker.gene_symbol.upper(), set()).add(marker.marker_type.value)
            for gene, types in marker_types.items():
                if "positive" in types and "negative" in types:
                    related = [
                        claim.claim_id
                        for claim in claims
                        if claim.subject == candidate.standard_name and claim.object.upper() == gene
                    ]
                    conflicts.append(
                        _review_item(
                            "marker_direction_conflict",
                            candidate.standard_name,
                            f"Marker {gene} is reported as both positive and negative in this source.",
                            RiskLevel.HIGH,
                            claim_ids=related,
                        )
                    )
                    existing_context = set(existing.species + existing.tissues + existing.diseases)
                    candidate_context = set(candidate.species + candidate.tissues + candidate.diseases)
                    if existing_context and candidate_context and existing_context.isdisjoint(candidate_context):
                        conflicts.append(
                            _review_item(
                                "context_dependent_marker_conflict",
                                candidate.standard_name,
                                (
                                    f"Marker {gene} direction differs across non-overlapping "
                                    "species, tissue, or disease contexts."
                                ),
                                RiskLevel.MEDIUM,
                                claim_ids=related,
                            )
                        )
            merged[key] = existing.model_copy(
                update={
                    "synonyms": sorted(set(existing.synonyms + candidate.synonyms)),
                    "markers": _unique_markers(existing.markers + candidate.markers),
                    "functions": _unique_functions(existing.functions + candidate.functions),
                    "species": sorted(set(existing.species + candidate.species)),
                    "tissues": sorted(set(existing.tissues + candidate.tissues)),
                    "diseases": sorted(set(existing.diseases + candidate.diseases)),
                }
            )

    return (
        ExtractionResult(
            paper=paper,
            cell_types=sorted(merged.values(), key=lambda cell: cell.standard_name),
            raw_relationships=[],
            claims=claims,
            source_document={
                "source_id": source.source_id,
                "parse_hash": document.parse_hash,
                "parser_name": document.parser_name,
                "parser_version": document.parser_version,
                "parser_config": document.parser_config,
                "page_count": len(document.pages),
            },
        ),
        conflicts,
    )


def _evidence_for_term(
    source: SourceRecord,
    document: ParsedDocument,
    chunk: DocumentChunk,
    term: str,
) -> EvidenceReference | None:
    needle = term.strip()
    if not needle:
        return None
    for block_id in chunk.block_ids:
        block = document.block(block_id)
        match = re.search(re.escape(needle), block.text, flags=re.IGNORECASE)
        if match is None:
            continue
        start = max(0, block.text.rfind(".", 0, match.start()) + 1)
        end_marker = block.text.find(".", match.end())
        end = len(block.text) if end_marker == -1 else end_marker + 1
        if end - start > 600:
            start = max(0, match.start() - 220)
            end = min(len(block.text), match.end() + 320)
        excerpt = block.text[start:end].strip()
        evidence_material = f"{source.source_id}\0{block.block_id}\0{start}\0{end}\0{excerpt}"
        evidence_id = f"ev_{hashlib.sha256(evidence_material.encode('utf-8')).hexdigest()[:20]}"
        locator = f"page {block.page_number}"
        if block.section:
            locator += f" · {block.section}"
        return EvidenceReference(
            evidence_id=evidence_id,
            source_id=source.source_id,
            locator=locator,
            excerpt=excerpt,
            page_start=block.page_number,
            page_end=block.page_number,
            section=block.section,
            block_id=block.block_id,
            char_start=start,
            char_end=end,
            evidence_type=EvidenceType.DIRECT,
            confidence="high",
        )
    return None


def _evidence_for_term_document(
    source: SourceRecord,
    document: ParsedDocument,
    term: str,
) -> EvidenceReference | None:
    """Locate a verbatim term anywhere in the parsed document (whitespace-normalized)."""
    needle = term.strip()
    if len(needle) < 2 or len(needle) > 2000:
        return None
    for block in document.all_blocks():
        located = _normalized_locate(block.text, needle)
        if located is None:
            continue
        start, end = located
        if end - start > 600:
            start = max(0, start - 220)
            end = min(len(block.text), end + 320)
        excerpt = block.text[start:end].strip()
        if not excerpt:
            continue
        evidence_material = f"{source.source_id}\0{block.block_id}\0{start}\0{end}\0{excerpt}"
        evidence_id = f"ev_{hashlib.sha256(evidence_material.encode('utf-8')).hexdigest()[:20]}"
        locator = f"page {block.page_number}"
        if block.section:
            locator += f" \u00b7 {block.section}"
        return EvidenceReference(
            evidence_id=evidence_id,
            source_id=source.source_id,
            locator=locator,
            excerpt=excerpt,
            page_start=block.page_number,
            page_end=block.page_number,
            section=block.section,
            block_id=block.block_id,
            char_start=start,
            char_end=end,
            evidence_type=EvidenceType.DIRECT,
            confidence="high",
        )
    return None


def _normalized_locate(text: str, needle: str) -> tuple[int, int] | None:
    """Return original offsets of a case/whitespace-normalized substring match."""
    norm_text = re.sub(r"\s+", " ", text)
    norm_needle = re.sub(r"\s+", " ", needle).strip()
    pos = norm_text.casefold().find(norm_needle.casefold())
    if pos < 0:
        return None
    mapping: list[int] = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            mapping.append(i)
            while i < len(text) and text[i].isspace():
                i += 1
        else:
            mapping.append(i)
            i += 1
    if pos + len(norm_needle) - 1 >= len(mapping):
        return None
    return mapping[pos], mapping[pos + len(norm_needle) - 1] + 1



def _claim(subject: str, predicate: str, object_value: str, evidence: EvidenceReference) -> Claim:
    material = f"{subject}\0{predicate}\0{object_value}\0{evidence.evidence_id}"
    return Claim(
        claim_id=f"claim_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}",
        subject=subject,
        predicate=predicate,
        object=object_value,
        evidence=[evidence],
        confidence="high",
    )


def _validate_claim_evidence(document: ParsedDocument, claims: list[Claim]) -> None:
    for claim in claims:
        for evidence in claim.evidence:
            if evidence.block_id is None:
                raise ValueError(f"claim {claim.claim_id} has no block-level evidence locator")
            block = document.block(evidence.block_id)
            if evidence.excerpt not in block.text:
                raise ValueError(f"claim {claim.claim_id} evidence excerpt is not present in its source block")
            if evidence.page_start != block.page_number:
                raise ValueError(f"claim {claim.claim_id} evidence page does not match its source block")


def _attach_casing_alias(candidate: CellTypeExtract, key: str) -> CellTypeExtract:
    """Keep differently-cased forms of the same canonical name as synonyms only."""
    if candidate.standard_name == key:
        return candidate
    return candidate.model_copy(
        update={"standard_name": key, "synonyms": sorted(set(candidate.synonyms + [candidate.standard_name]))}
    )


def _finalize_agent_draft(
    source: SourceRecord,
    document: ParsedDocument,
    payload: dict,
) -> tuple[ExtractionResult, list[ReviewItem]]:
    """Run deterministic guards over a staged agent extraction draft."""
    raw_cell_types = payload.get("cell_types", [])
    if not isinstance(raw_cell_types, list) or not raw_cell_types:
        raise ValueError("agent ingest draft contains no cell_types")
    paper_info = payload.get("paper_info") or {}
    paper = PaperReference(
        paper_id=source.source_id,
        title=str(paper_info.get("title", "") or ""),
        doi=str(paper_info.get("doi", "") or ""),
        year=int(paper_info.get("year", 0) or 0),
        local_path=source.stored_path,
    )
    candidates: list[CellTypeExtract] = []
    errors: list[str] = []
    for index, item in enumerate(raw_cell_types):
        if not isinstance(item, dict):
            errors.append(f"cell_types[{index}] is not an object")
            continue
        try:
            candidates.append(CellTypeExtract.model_validate({**item, "paper_ref": paper}))
        except Exception as error:
            errors.append(f"cell_types[{index}] failed schema validation: {error}")
    if errors:
        raise ValueError("agent ingest draft failed validation: " + "; ".join(errors[:3]))

    extraction = ExtractionResult(
        paper=paper,
        cell_types=candidates,
        raw_relationships=payload.get("relationships") or [],
        source_document={
            "source_id": source.source_id,
            "parse_hash": document.parse_hash,
            "parser_name": document.parser_name,
            "parser_version": document.parser_version,
            "parser_config": document.parser_config,
        },
    )
    grounded, gaps = _ground_extraction_document(source, document, extraction)
    merged, conflicts = _merge_extractions(source, document, [grounded])
    review_items = _unique_review_items([*gaps, *conflicts])
    entity_unmatched = sum(1 for item in review_items if item.type == "ungrounded_entity")
    if candidates and entity_unmatched / len(candidates) > settings.ingest_ungrounded_entity_ratio_limit:
        review_items.append(
            _review_item(
                "excessive_ungrounded_entities",
                source.source_id,
                (
                    f"{entity_unmatched}/{len(candidates)} candidate entities could not be located "
                    f"verbatim; exceeds the {int(settings.ingest_ungrounded_entity_ratio_limit * 100)}% L0 limit."
                ),
                RiskLevel.HIGH,
            )
        )
    return merged, review_items


def _review_item(
    item_type: str,
    target_id: str,
    description: str,
    severity: RiskLevel,
    *,
    claim_ids: list[str] | None = None,
) -> ReviewItem:
    material = f"{item_type}\0{target_id}\0{description}"
    return ReviewItem(
        review_item_id=f"review_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}",
        type=item_type,
        target_id=target_id,
        description=description,
        severity=severity,
        claim_ids=claim_ids or [],
    )


def _unique_claims(claims: list[Claim]) -> list[Claim]:
    return list({claim.claim_id: claim for claim in claims}.values())


def _unique_evidence(claims: list[Claim]) -> list[EvidenceReference]:
    return list(
        {
            evidence.evidence_id or f"{evidence.source_id}:{evidence.locator}:{evidence.excerpt}": evidence
            for claim in claims
            for evidence in claim.evidence
        }.values()
    )


def _unique_review_items(items: list[ReviewItem]) -> list[ReviewItem]:
    return list({item.review_item_id: item for item in items}.values())


def _unique_markers(markers: list[Marker]) -> list[Marker]:
    return list(
        {
            (marker.gene_symbol.upper(), marker.marker_type.value, marker.evidence): marker
            for marker in markers
        }.values()
    )


def _unique_functions(functions: list[FunctionalCharacteristic]) -> list[FunctionalCharacteristic]:
    return list({(item.description, item.pathway, item.evidence): item for item in functions}.values())


def _text_hash(document: ParsedDocument) -> str:
    text = "\n".join(block.text for block in document.all_blocks())
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _change_set_id(
    source: SourceRecord,
    document: ParsedDocument,
    extraction: ExtractionResult,
    run_id: str,
) -> str:
    material = f"{source.source_id}\0{document.parse_hash}\0{run_id}\0{extraction.model_dump_json()}"
    return f"cs_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _file_version(path: Path) -> str:
    if not path.exists():
        return "missing"
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _normalize_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "unresolved_entity"
