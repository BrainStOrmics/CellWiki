# =============================================================================
# 研究服务 —— 受控外部研究：搜索结果仅成为注册的源候选
# =============================================================================

# ---------------------------------------------------------------------------
# ResearchService —— 研究服务
# 受控的外部研究：搜索结果仅成为注册的源候选，不会自动写入 Wiki。
# 支持通过外部 API（如 Semantic Scholar、PubMed）搜索文献，
# 并将每个结果注册为 SourceRecord 和 ResearchCandidate。
# 候选来源需要经过导入→ChangeSet→人工审批的完整流程才能正式入库。
# 研究服务没有写入或提交能力，确保知识库的完整性。
# ---------------------------------------------------------------------------

"""Governed external research: search results become registered source candidates only."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import requests
from pydantic import HttpUrl

from cellwiki.domain.research import (
    ExternalResearchResult,
    ResearchCandidate,
    ResearchRefreshRun,
    ResearchRefreshStatus,
    ResearchPublicationStatus,
)
from cellwiki.domain.contracts import PipelineTaskType
from cellwiki.services.pipeline import KnowledgePipelineHarness, PipelineLease
from cellwiki.services.sources import SourceRegistry


class ResearchSearchAdapter(Protocol):
    """Search seam used by the governed Research module."""

    def search(self, query: str, *, limit: int) -> list[ExternalResearchResult]: ...


class CrossrefSearchAdapter:
    """Metadata-only public adapter; it never downloads arbitrary result URLs."""

    endpoint = "https://api.crossref.org/works"
    provider_name = "crossref"

    def __init__(self, *, timeout_seconds: float = 20):
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, limit: int) -> list[ExternalResearchResult]:
        params: dict[str, str | int] = {
            "query": query,
            "rows": max(1, min(limit, 20)),
        }
        response = requests.get(
            self.endpoint,
            params=params,
            headers={"User-Agent": "CellWiki/2.0 (local research metadata client)"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        items = response.json().get("message", {}).get("items", [])
        results: list[ExternalResearchResult] = []
        for item in items:
            doi = str(item.get("DOI") or "").strip() or None
            url = str(item.get("URL") or (f"https://doi.org/{doi}" if doi else "")).strip()
            title_values = item.get("title") or []
            title = str(title_values[0] if title_values else doi or "Untitled research result")
            if not url:
                continue
            author_names = [
                " ".join(part for part in (author.get("given", ""), author.get("family", "")) if part).strip()
                for author in item.get("author") or []
            ]
            year = _crossref_year(item)
            publication_status = (
                ResearchPublicationStatus.PREPRINT
                if item.get("type") in {"posted-content", "preprint"}
                else ResearchPublicationStatus.PEER_REVIEWED
            )
            results.append(
                ExternalResearchResult(
                    external_id=doi or str(item.get("URL") or hashlib.sha256(title.encode()).hexdigest()),
                    title=title,
                    url=HttpUrl(url),
                    authors=[name for name in author_names if name],
                    published_year=year,
                    doi=doi,
                    abstract=_strip_crossref_markup(str(item.get("abstract") or "")),
                    publication_status=publication_status,
                    is_paywalled=None,
                )
            )
        return results


class ResearchService:
    """Register external metadata and persist Review-ready ResearchCandidates.

    This Module deliberately has no CentralWriter dependency. Publishing research
    therefore requires a later ingest-generated ChangeSet and human approval.
    """

    def __init__(self, project_root: Path, *, adapter: ResearchSearchAdapter | None = None):
        self.project_root = Path(project_root).resolve()
        self.adapter = adapter or CrossrefSearchAdapter()
        self.registry = SourceRegistry(self.project_root)
        self.candidate_dir = self.project_root / "data" / "runtime" / "research" / "candidates"
        self.run_dir = self.project_root / "data" / "runtime" / "research" / "runs"
        self.staging_dir = self.project_root / "data" / "runtime" / "research" / "staging"

    def search_and_register(
        self,
        query: str,
        *,
        project_id: str = "cellwiki",
        limit: int = 5,
    ) -> list[ResearchCandidate]:
        run = self.refresh(query, project_id=project_id, limit=limit)
        candidates = {candidate.candidate_id: candidate for candidate in self.list_candidates(project_id)}
        return [candidates[candidate_id] for candidate_id in run.candidate_ids if candidate_id in candidates]

    def refresh(
        self,
        query: str,
        *,
        project_id: str = "cellwiki",
        limit: int = 5,
        run_id: str | None = None,
        lease: PipelineLease | None = None,
    ) -> ResearchRefreshRun:
        """Run a snapshot-bound external refresh that only registers candidates."""

        query = " ".join(query.split())
        if not query:
            raise ValueError("research query is required")
        refresh_run_id = run_id or f"refresh_{uuid.uuid4().hex}"
        requested_limit = max(1, min(limit, 20))
        provider = self._provider_name()
        pipeline = KnowledgePipelineHarness(self.project_root)

        if lease is None:
            with pipeline.acquire(task_type=PipelineTaskType.LINT, run_id=refresh_run_id) as owned_lease:
                return self._refresh_with_lease(
                    query,
                    project_id=project_id,
                    requested_limit=requested_limit,
                    refresh_run_id=refresh_run_id,
                    provider=provider,
                    lease=owned_lease,
                )
        if lease.task_type is not PipelineTaskType.LINT or lease.run_id != refresh_run_id:
            raise ValueError("external refresh lease must be the matching LINT task lease")
        return self._refresh_with_lease(
            query,
            project_id=project_id,
            requested_limit=requested_limit,
            refresh_run_id=refresh_run_id,
            provider=provider,
            lease=lease,
        )

    def _refresh_with_lease(
        self,
        query: str,
        *,
        project_id: str,
        requested_limit: int,
        refresh_run_id: str,
        provider: str,
        lease: PipelineLease,
    ) -> ResearchRefreshRun:
        """Register candidates while the caller owns the refresh snapshot and lease."""

        snapshot = lease.snapshot
        provenance = {
            "provider": provider,
            "adapter": type(self.adapter).__name__,
            "query": query,
            "snapshot_id": snapshot.snapshot_id,
            "knowledge_version": snapshot.knowledge_version,
        }
        try:
            results = self.adapter.search(query, limit=requested_limit)
            existing = {
                self._candidate_dedup_key(candidate): candidate.candidate_id
                for candidate in self.list_candidates(project_id)
            }
            candidate_ids: list[str] = []
            duplicate_ids: list[str] = []
            for result in results:
                dedup_key = _research_dedup_key(result)
                existing_id = existing.get(dedup_key)
                if existing_id is not None:
                    duplicate_ids.append(existing_id)
                    continue
                candidate = self.register_candidate(
                    query,
                    result,
                    project_id=project_id,
                    provider=provider,
                    refresh_run_id=refresh_run_id,
                    snapshot_id=snapshot.snapshot_id,
                    dedup_key=dedup_key,
                )
                existing[dedup_key] = candidate.candidate_id
                candidate_ids.append(candidate.candidate_id)
            run = ResearchRefreshRun(
                refresh_run_id=refresh_run_id,
                project_id=project_id,
                query=query,
                provider=provider,
                snapshot_id=snapshot.snapshot_id,
                knowledge_version=snapshot.knowledge_version,
                requested_limit=requested_limit,
                status=ResearchRefreshStatus.COMPLETED,
                candidate_ids=candidate_ids,
                duplicate_candidate_ids=duplicate_ids,
                provider_provenance=provenance,
                completed_at=datetime.now(UTC),
            )
        except Exception as error:
            run = ResearchRefreshRun(
                refresh_run_id=refresh_run_id,
                project_id=project_id,
                query=query,
                provider=provider,
                snapshot_id=snapshot.snapshot_id,
                knowledge_version=snapshot.knowledge_version,
                requested_limit=requested_limit,
                status=ResearchRefreshStatus.FAILED,
                provider_provenance=provenance,
                error=str(error)[:1000],
                completed_at=datetime.now(UTC),
            )
            self._save_refresh_run(run)
            raise
        self._save_refresh_run(run)
        return run

    def register_candidate(
        self,
        query: str,
        result: ExternalResearchResult,
        *,
        project_id: str = "cellwiki",
        provider: str = "unknown",
        refresh_run_id: str | None = None,
        snapshot_id: str | None = None,
        dedup_key: str | None = None,
    ) -> ResearchCandidate:
        accessed_at = datetime.now(UTC)
        payload = {
            "external_id": result.external_id,
            "title": result.title,
            "url": str(result.url),
            "authors": result.authors,
            "published_year": result.published_year,
            "doi": result.doi,
            "abstract": result.abstract,
            "publication_status": result.publication_status.value,
            "is_paywalled": result.is_paywalled,
            "accessed_at": accessed_at.isoformat(),
            "provider": provider,
            "refresh_run_id": refresh_run_id or "",
            "snapshot_id": snapshot_id or "",
            "dedup_key": dedup_key or _research_dedup_key(result),
        }
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        staging = self.staging_dir / f"research_{hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]}.json"
        staging.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            source = self.registry.register(
                staging,
                source_type="network_metadata",
                original_name=f"{_safe_slug(result.title)}.research.json",
            )
        finally:
            staging.unlink(missing_ok=True)
        source = self.registry.update_metadata(
            source.source_id,
            {
                "network_source": payload,
                "research_query": query,
                "research_status": "candidate_only",
                "research_provenance": {
                    "provider": provider,
                    "refresh_run_id": refresh_run_id or "",
                    "snapshot_id": snapshot_id or "",
                },
            },
        )
        warnings: list[str] = []
        if result.publication_status == ResearchPublicationStatus.PREPRINT:
            warnings.append("preprint_not_peer_reviewed")
        if result.publication_status == ResearchPublicationStatus.RETRACTED:
            warnings.append("retracted_source")
        if result.is_paywalled is True:
            warnings.append("paywalled_full_text_not_verified")
        if result.is_paywalled is None:
            warnings.append("full_text_access_unknown")

        material = f"{project_id}\0{query}\0{source.source_id}"
        candidate = ResearchCandidate(
            candidate_id=f"research_{hashlib.sha256(material.encode()).hexdigest()[:20]}",
            project_id=project_id,
            query=query,
            source_id=source.source_id,
            title=result.title,
            url=result.url,
            status=result.publication_status,
            warnings=warnings,
            accessed_at=accessed_at,
            provider=provider,
            refresh_run_id=refresh_run_id,
            snapshot_id=snapshot_id,
            dedup_key=dedup_key or _research_dedup_key(result),
        )
        self.candidate_dir.mkdir(parents=True, exist_ok=True)
        path = self.candidate_dir / f"{candidate.candidate_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(candidate.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return candidate

    def list_candidates(self, project_id: str = "cellwiki") -> list[ResearchCandidate]:
        if not self.candidate_dir.exists():
            return []
        candidates = [
            ResearchCandidate.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.candidate_dir.glob("research_*.json"))
        ]
        return [candidate for candidate in candidates if candidate.project_id == project_id]

    def list_refresh_runs(self, project_id: str = "cellwiki") -> list[ResearchRefreshRun]:
        if not self.run_dir.exists():
            return []
        runs = [
            ResearchRefreshRun.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.run_dir.glob("refresh_*.json"))
        ]
        return [run for run in runs if run.project_id == project_id]

    def _save_refresh_run(self, run: ResearchRefreshRun) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / f"{run.refresh_run_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    def _provider_name(self) -> str:
        return str(
            getattr(self.adapter, "provider_name", type(self.adapter).__name__)
        ).strip().lower()

    @staticmethod
    def _candidate_dedup_key(candidate: ResearchCandidate) -> str:
        if candidate.dedup_key:
            return candidate.dedup_key
        return f"url:{str(candidate.url).strip().lower().rstrip('/')}"


def _crossref_year(item: dict) -> int | None:
    for key in ("published-print", "published-online", "issued"):
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            return int(parts[0][0])
    return None


def _strip_crossref_markup(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (slug or "research_result")[:100]


def _research_dedup_key(result: ExternalResearchResult) -> str:
    if result.doi:
        return f"doi:{result.doi.strip().lower().removeprefix('https://doi.org/')}"
    if result.external_id:
        return f"external:{result.external_id.strip().lower()}"
    title = re.sub(r"[^a-z0-9]+", " ", result.title.lower()).strip()
    year = result.published_year or "unknown"
    return f"title:{title}:{year}"
