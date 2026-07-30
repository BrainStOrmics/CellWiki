"""Read-only formal knowledge queries for the Product API and Agent tools."""

from __future__ import annotations

import contextvars
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from dataclasses import dataclass, field

from filelock import FileLock

from cellwiki.api.reader import WikiReader
from cellwiki.domain.contracts import (
    AgentAnswer,
    ValidationIssue,
    ValidationIssueCode,
    VerificationLevel,
)
from cellwiki.domain.query import QueryHit, QueryPage, QueryResponse
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.operations import current_agent_run_id
from cellwiki.services.pipeline import KnowledgePipelineHarness


class QueryVersionConflictError(RuntimeError):
    """Raised when one Formal Query would mix two published knowledge versions."""


@dataclass
class FormalQuerySession:
    """Durable read ledger for one Agent answer."""

    project_root: Path
    run_id: str
    knowledge_version: str
    pages: dict[str, QueryPage] = field(default_factory=dict)

    def record(self, page: QueryPage) -> None:
        self.pages[page.page_id] = page
        self._persist()

    def load_persisted(self) -> None:
        """Reload pages read by a specialist subagent in another graph context."""

        path = self.project_root / "data" / "runtime" / "query_sessions" / f"{self.run_id}.json"
        if not path.exists():
            return
        with _SESSION_FILE_LOCK:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("knowledge_version") != self.knowledge_version:
                    return
                for raw_page in payload.get("pages", []):
                    page = QueryPage.model_validate(raw_page)
                    if page.knowledge_version == self.knowledge_version:
                        self.pages[page.page_id] = page
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                # A partial ledger must never make the final-answer boundary crash.
                return

    def validate(self, answer: AgentAnswer) -> AgentAnswer:
        declared_confidence = answer.declared_confidence or answer.confidence
        issues: list[ValidationIssue] = []
        if answer.knowledge_scope == "general":
            return answer.model_copy(
                update={
                    "declared_confidence": declared_confidence,
                    "verification_level": VerificationLevel.UNVALIDATED,
                    "validation_issues": [],
                    "validation_warnings": [],
                }
            )
        if answer.knowledge_scope != "formal":
            return answer.model_copy(
                update={
                    "declared_confidence": declared_confidence,
                    "confidence": "low",
                    "knowledge_scope": "unvalidated",
                    "verification_level": VerificationLevel.UNVALIDATED,
                }
            )
        if answer.knowledge_version and not _knowledge_version_matches(
            answer.knowledge_version,
            self.knowledge_version,
        ):
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.VERSION_MISMATCH,
                    message="answer knowledge_version does not match the read ledger",
                )
            )
        if not answer.citations:
            issues.append(
                ValidationIssue(
                    code=ValidationIssueCode.MISSING_CITATION,
                    message="formal answers require at least one citation",
                )
            )
        for citation_index, citation in enumerate(answer.citations):
            page = self.pages.get(citation.page_id)
            if page is None:
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNREAD_PAGE,
                        message=f"citation page was not read: {citation.page_id}",
                        page_id=citation.page_id,
                        citation_index=citation_index,
                    )
                )
                continue
            if citation.source_id:
                cited_sources = {
                    part.strip()
                    for part in citation.source_id.replace(";", ",").split(",")
                    if part.strip()
                }
                if not cited_sources.intersection(page.source_ids):
                    issues.append(
                        ValidationIssue(
                            code=ValidationIssueCode.SOURCE_MISMATCH,
                            message=f"citation source is not attached to page: {citation.page_id}",
                            page_id=citation.page_id,
                            citation_index=citation_index,
                        )
                    )
            if not citation.locator or citation.locator.lower() not in page.markdown.lower():
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.LOCATOR_MISSING,
                        message=f"citation locator is missing or was not found: {citation.page_id}",
                        page_id=citation.page_id,
                        citation_index=citation_index,
                    )
                )
            if citation.evidence_id:
                # Existing renderer pages expose page/source references, but not
                # claim-level evidence IDs. Rejecting unknown IDs prevents a
                # model from manufacturing a stronger citation tier.
                issues.append(
                    ValidationIssue(
                        code=ValidationIssueCode.UNSUPPORTED_EVIDENCE_ID,
                        message=f"evidence_id is not available for page: {citation.page_id}",
                        page_id=citation.page_id,
                        citation_index=citation_index,
                    )
                )
        if issues:
            return answer.model_copy(
                update={
                    "declared_confidence": declared_confidence,
                    "confidence": "low",
                    "knowledge_scope": "unvalidated",
                    "verification_level": VerificationLevel.UNVALIDATED,
                    "knowledge_version": self.knowledge_version,
                    "validation_issues": [*answer.validation_issues, *issues],
                    "validation_warnings": [
                        *answer.validation_warnings,
                        *(issue.message for issue in issues),
                    ],
                }
            )
        return answer.model_copy(
            update={
                "declared_confidence": declared_confidence,
                "knowledge_version": self.knowledge_version,
                "verification_level": VerificationLevel.PAGE,
                "validation_issues": [],
                "validation_warnings": [],
            }
        )

    def _persist(self) -> None:
        path = self.project_root / "data" / "runtime" / "query_sessions" / f"{self.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_suffix(path.suffix + ".lock")
        with _SESSION_FILE_LOCK, FileLock(str(lock_path)):
            merged: dict[str, QueryPage] = {}
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    if existing.get("knowledge_version") == self.knowledge_version:
                        for raw_page in existing.get("pages", []):
                            page = QueryPage.model_validate(raw_page)
                            merged[page.page_id] = page
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    pass
            merged.update(self.pages)
            self.pages = merged
            payload = {
                "run_id": self.run_id,
                "knowledge_version": self.knowledge_version,
                "pages": [page.model_dump(mode="json") for page in self.pages.values()],
            }
            # A unique sibling avoids collisions with stale Windows handles;
            # the file lock prevents concurrent contexts from losing pages.
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                for attempt in range(5):
                    try:
                        temporary.replace(path)
                        break
                    except PermissionError:
                        if attempt == 4:
                            raise
                        time.sleep(0.02 * (attempt + 1))
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


_SESSION: contextvars.ContextVar[FormalQuerySession | None] = contextvars.ContextVar(
    "cellwiki_formal_query_session", default=None
)
_SESSION_FILE_LOCK = threading.RLock()


class FormalAnswerGate:
    """Repair bounded unread citations, then assign the final trust state once."""

    MAX_REPAIR_PAGES = 5

    def __init__(
        self,
        session: FormalQuerySession,
        read_page: Callable[[str], QueryPage],
    ):
        self.session = session
        self.read_page = read_page

    def finalize(self, candidate: AgentAnswer) -> AgentAnswer:
        if candidate.knowledge_scope == "formal":
            unread: list[str] = []
            for citation in candidate.citations:
                if citation.page_id not in self.session.pages and citation.page_id not in unread:
                    unread.append(citation.page_id)
            for page_id in unread[: self.MAX_REPAIR_PAGES]:
                try:
                    self.read_page(page_id)
                except (FileNotFoundError, KeyError, OSError, ValueError):
                    # The validation pass below records a stable unread_page issue.
                    continue
        return self.session.validate(candidate)


class FormalQueryService:
    """Expose only the published Wiki projection through a structured contract."""

    def __init__(
        self,
        project_root: Path,
        *,
        reader: WikiReader | None = None,
        pipeline: KnowledgePipelineHarness | None = None,
        changesets: ChangeSetRepository | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.reader = reader or WikiReader(self.project_root)
        self.pipeline = pipeline or KnowledgePipelineHarness(self.project_root)
        self.changesets = changesets or ChangeSetRepository(self.project_root)

    def session(self) -> FormalQuerySession:
        run_id = current_agent_run_id() or "query-local"
        current = _SESSION.get()
        if (
            current is None
            or current.run_id != run_id
            or current.project_root != self.project_root
        ):
            current = FormalQuerySession(
                self.project_root,
                run_id,
                self.pipeline.current_knowledge_version(),
            )
            current.load_persisted()
            _SESSION.set(current)
        return current

    def validate_answer(self, answer: AgentAnswer) -> AgentAnswer:
        session = self.session()
        return FormalAnswerGate(session, self.read_page).finalize(answer)

    def _assert_version(self, session: FormalQuerySession) -> None:
        current = self.pipeline.current_knowledge_version()
        if current != session.knowledge_version:
            raise QueryVersionConflictError(
                "formal knowledge changed while the query was reading; retry the query"
            )

    def search(self, query: str, limit: int = 20) -> QueryResponse:
        session = self.session()
        self._assert_version(session)
        normalized_query = " ".join(query.split())
        raw_results = self.reader.search(normalized_query, limit=max(1, min(limit, 100)))
        results: list[QueryHit] = []
        for item in raw_results:
            page = self.reader.read_page(str(item["page_id"]))
            query_page = QueryPage(
                page_id=page["page_id"],
                path=page["path"],
                frontmatter=page["frontmatter"],
                markdown=page["markdown"],
                knowledge_version=session.knowledge_version,
                source_ids=_source_ids(page["frontmatter"]),
            )
            session.record(query_page)
            results.append(
                QueryHit(
                    page_id=str(item["page_id"]),
                    title=str(page["frontmatter"].get("display_name") or item["page_id"]),
                    snippet=str(item["snippet"]),
                    score=int(item["score"]),
                    source_ids=_source_ids(page["frontmatter"]),
                )
            )
        return QueryResponse(
            query=normalized_query,
            knowledge_version=session.knowledge_version,
            results=results,
            pending_change_set_count=self._pending_change_set_count(),
            warnings=(
                ["pending_changesets_excluded"]
                if self._pending_change_set_count()
                else []
            ),
        )

    def read_page(self, page_id: str) -> QueryPage:
        session = self.session()
        self._assert_version(session)
        page = self.reader.read_page(page_id)
        query_page = QueryPage(
            page_id=page["page_id"],
            path=page["path"],
            frontmatter=page["frontmatter"],
            markdown=page["markdown"],
            knowledge_version=session.knowledge_version,
            source_ids=_source_ids(page["frontmatter"]),
        )
        session.record(query_page)
        self._assert_version(session)
        return query_page

    def _pending_change_set_count(self) -> int:
        commits_dir = self.project_root / "data" / "runtime" / "commits"
        return sum(
            not (commits_dir / f"{change_set.change_set_id}.json").exists()
            for change_set in self.changesets.list()
        )


def _source_ids(frontmatter: dict[str, Any]) -> list[str]:
    """Extract stable source IDs from renderer-owned reference metadata."""

    values: list[str] = []
    references = frontmatter.get("references", [])
    if isinstance(references, list):
        for reference in references:
            if isinstance(reference, dict):
                source_id = reference.get("source_id") or reference.get("paper_id")
                if isinstance(source_id, str) and source_id and source_id not in values:
                    values.append(source_id)
    sources = frontmatter.get("sources", [])
    if isinstance(sources, list):
        for source_id in sources:
            if isinstance(source_id, str) and source_id and source_id not in values:
                values.append(source_id)
    return values


def _knowledge_version_matches(candidate: str, expected: str) -> bool:
    """Accept exact versions or an unambiguous provider-truncated hash."""

    normalized = candidate.strip()
    if normalized == expected:
        return True
    for marker in ("…", "..."):
        if marker in normalized:
            prefix, suffix = normalized.split(marker, 1)
            return bool(prefix and suffix and expected.startswith(prefix) and expected.endswith(suffix))
    return False
