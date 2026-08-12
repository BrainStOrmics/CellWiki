"""Thread-scoped temporary attachments for CellWiki Agent conversations."""

from __future__ import annotations

from contextvars import ContextVar
import hashlib
import mimetypes
import re
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import List

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError
from pydantic import BaseModel, Field

from cellwiki.domain.contracts import SourceRecord
from cellwiki.services.operations import current_agent_run_id
from cellwiki.services.sources import SourceRegistry


class AgentAttachmentRecord(BaseModel):
    attachment_id: str
    thread_id: str
    original_name: str
    media_type: str
    size_bytes: int
    content_hash: str
    text_hash: str | None = None
    stored_path: str
    text_path: str | None = None
    promoted_source_id: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def attachment_reference(record: AgentAttachmentRecord) -> dict[str, object]:
    """Return the durable, non-content identity stored alongside a chat message."""

    return {
        "attachment_id": record.attachment_id,
        "original_name": record.original_name,
        "media_type": record.media_type,
        "content_hash": record.content_hash,
        "size_bytes": record.size_bytes,
    }


_ATTACHMENT_READ_LEDGER: ContextVar[tuple[str, frozenset[str]] | None] = ContextVar(
    "cellwiki_attachment_read_ledger",
    default=None,
)
_ATTACHMENT_READS_BY_RUN: dict[str, frozenset[str]] = {}
_ATTACHMENT_READS_LOCK = threading.RLock()
MAX_ATTACHMENT_SEARCHES_PER_RUN = 12
_ATTACHMENT_SEARCH_CACHE_BY_RUN: dict[
    str,
    dict[tuple[str, tuple[str, ...]], list[dict[str, str]]],
] = {}
_ATTACHMENT_SEARCH_COUNT_BY_RUN: dict[str, int] = {}
_ATTACHMENT_LAZY_READ_LOCKS: dict[str, threading.Lock] = {}
_ATTACHMENT_LAZY_READ_LOCKS_GUARD = threading.Lock()
_ATOMIC_WRITE_LOCKS: dict[str, threading.Lock] = {}
_ATOMIC_WRITE_LOCKS_GUARD = threading.Lock()


def normalize_attachment_search_query(query: str) -> str:
    """Normalize only whitespace/case for safe exact-query deduplication."""

    return " ".join(query.casefold().split())


def cached_attachment_search(
    query: str,
    attachment_ids: set[str],
    *,
    run_id: str | None = None,
) -> list[dict[str, str]] | None:
    """Return a prior result from this run without sharing evidence across runs."""

    run_key = run_id or current_agent_run_id()
    if not run_key:
        return None
    cache_key = (normalize_attachment_search_query(query), tuple(sorted(attachment_ids)))
    with _ATTACHMENT_READS_LOCK:
        matches = _ATTACHMENT_SEARCH_CACHE_BY_RUN.get(run_key, {}).get(cache_key)
        return [dict(match) for match in matches] if matches is not None else None


def begin_attachment_search(*, run_id: str | None = None) -> bool:
    """Reserve one bounded search slot for a run; local callers remain unrestricted."""

    run_key = run_id or current_agent_run_id()
    if not run_key:
        return True
    with _ATTACHMENT_READS_LOCK:
        count = _ATTACHMENT_SEARCH_COUNT_BY_RUN.get(run_key, 0)
        if count >= MAX_ATTACHMENT_SEARCHES_PER_RUN:
            return False
        _ATTACHMENT_SEARCH_COUNT_BY_RUN[run_key] = count + 1
    return True


def cache_attachment_search(
    query: str,
    attachment_ids: set[str],
    matches: list[dict[str, str]],
    *,
    run_id: str | None = None,
) -> None:
    """Cache one bounded result for the current run only."""

    run_key = run_id or current_agent_run_id()
    if not run_key:
        return
    cache_key = (normalize_attachment_search_query(query), tuple(sorted(attachment_ids)))
    with _ATTACHMENT_READS_LOCK:
        run_cache = _ATTACHMENT_SEARCH_CACHE_BY_RUN.setdefault(run_key, {})
        run_cache[cache_key] = [dict(match) for match in matches]


def record_attachment_read(attachment_id: str, *, run_id: str | None = None) -> None:
    """Record that the current run obtained evidence from an attachment tool."""

    run_key = run_id or current_agent_run_id() or "__local__"
    current = _ATTACHMENT_READ_LEDGER.get()
    with _ATTACHMENT_READS_LOCK:
        read_ids = set(_ATTACHMENT_READS_BY_RUN.get(run_key, frozenset()))
    if current is not None and current[0] == run_key:
        read_ids.update(current[1])
    read_ids.add(attachment_id)
    frozen = frozenset(read_ids)
    with _ATTACHMENT_READS_LOCK:
        _ATTACHMENT_READS_BY_RUN[run_key] = frozen
    _ATTACHMENT_READ_LEDGER.set((run_key, frozen))


def attachment_read_ids(run_id: str | None = None) -> frozenset[str]:
    """Return attachment IDs read by the current run or local tool context."""

    run_key = run_id or current_agent_run_id() or "__local__"
    with _ATTACHMENT_READS_LOCK:
        persisted = _ATTACHMENT_READS_BY_RUN.get(run_key, frozenset())
    current = _ATTACHMENT_READ_LEDGER.get()
    if current is None or current[0] != run_key:
        return persisted
    return frozenset({*persisted, *current[1]})


def clear_attachment_read_ledger(run_id: str) -> None:
    """Release the in-memory evidence ledger after a run reaches a terminal state."""

    with _ATTACHMENT_READS_LOCK:
        _ATTACHMENT_READS_BY_RUN.pop(run_id, None)
        _ATTACHMENT_SEARCH_CACHE_BY_RUN.pop(run_id, None)
        _ATTACHMENT_SEARCH_COUNT_BY_RUN.pop(run_id, None)
    current = _ATTACHMENT_READ_LEDGER.get()
    if current is not None and current[0] == run_id:
        _ATTACHMENT_READ_LEDGER.set(None)


class AttachmentService:
    """Persist temporary files under one Agent thread without registering Sources."""

    def __init__(self, project_root: Path, *, source_registry: SourceRegistry | None = None):
        self.project_root = Path(project_root)
        self.base_dir = self.project_root / "data" / "runtime" / "agent_uploads"
        self.source_registry = source_registry or SourceRegistry(self.project_root)

    def create(
        self,
        thread_id: str,
        source_path: Path,
        *,
        original_name: str,
        media_type: str | None = None,
    ) -> AgentAttachmentRecord:
        self._validate_thread_id(thread_id)
        source_path = Path(source_path).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        safe_name = Path(original_name or source_path.name).name or "attachment.bin"
        attachment_id = f"att_{uuid.uuid4().hex}"
        attachment_dir = self._thread_dir(thread_id) / attachment_id
        attachment_dir.mkdir(parents=True, exist_ok=False)
        stored_path = attachment_dir / safe_name
        shutil.copy2(source_path, stored_path)
        record = AgentAttachmentRecord(
            attachment_id=attachment_id,
            thread_id=thread_id,
            original_name=safe_name,
            media_type=media_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
            size_bytes=stored_path.stat().st_size,
            content_hash=f"sha256:{self._sha256(stored_path)}",
            # Text extraction is deliberately deferred until an Agent tool asks
            # for content. Uploading an attachment must remain metadata-only.
            text_hash=None,
            stored_path=str(stored_path.resolve()),
            text_path=None,
        )
        self._write_record(record)
        return record

    def list(self, thread_id: str) -> list[AgentAttachmentRecord]:
        self._validate_thread_id(thread_id)
        thread_dir = self._thread_dir(thread_id)
        if not thread_dir.exists():
            return []
        records = []
        for path in sorted(thread_dir.glob("att_*/metadata.json")):
            records.append(AgentAttachmentRecord.model_validate_json(path.read_text(encoding="utf-8")))
        return records

    def get(self, thread_id: str, attachment_id: str) -> AgentAttachmentRecord:
        self._validate_thread_id(thread_id)
        self._validate_attachment_id(attachment_id)
        path = self._record_path(thread_id, attachment_id)
        if not path.exists():
            raise KeyError(attachment_id)
        record = AgentAttachmentRecord.model_validate_json(path.read_text(encoding="utf-8"))
        if record.thread_id != thread_id:
            raise KeyError(attachment_id)
        return record

    def read_text(self, thread_id: str, attachment_id: str) -> str:
        record = self.get(thread_id, attachment_id)
        if record.text_path:
            path = Path(record.text_path)
            if path.is_file():
                return path.read_text(encoding="utf-8")

        # Serialize the common same-service case, then re-read metadata because
        # another service instance may have completed the projection meanwhile.
        with self._lazy_read_lock(thread_id, attachment_id):
            record = self.get(thread_id, attachment_id)
            if record.text_path:
                path = Path(record.text_path)
                if path.is_file():
                    return path.read_text(encoding="utf-8")

            # Older uploads may predate PDF extraction or have lost their derived
            # text file. Rebuild the disposable text projection from the immutable
            # stored file before returning an empty result.
            stored_path = Path(record.stored_path)
            if not stored_path.is_file():
                return ""
            text = _read_text_if_supported(stored_path)
            if text is None:
                return ""
            text_path = stored_path.parent / "text.txt"
            _atomic_write_text(text_path, text)
            self._write_record(
                record.model_copy(
                    update={
                        "text_path": str(text_path.resolve()),
                        "text_hash": f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}",
                    }
                )
            )
            return text

    def search_text(
        self,
        thread_id: str,
        query: str,
        *,
        attachment_ids: set[str] | None = None,
    ) -> List[dict[str, str]]:
        needle = query.strip().lower()
        if not needle:
            return []
        matches: List[dict[str, str]] = []
        for record in self.list(thread_id):
            if attachment_ids is not None and record.attachment_id not in attachment_ids:
                continue
            text = self.read_text(thread_id, record.attachment_id)
            index = text.lower().find(needle)
            if index >= 0:
                start = max(0, index - 120)
                end = min(len(text), index + len(query) + 120)
                matches.append(
                    {
                        "attachment_id": record.attachment_id,
                        "original_name": record.original_name,
                        "chunk_id": f"{record.attachment_id}:text:{start}",
                        "excerpt": text[start:end],
                    }
                )
        return matches

    def promote_to_source(self, thread_id: str, attachment_id: str) -> SourceRecord:
        record = self.get(thread_id, attachment_id)
        if record.promoted_source_id:
            return self.source_registry.get(record.promoted_source_id)
        source = self.source_registry.register(
            Path(record.stored_path),
            source_type="paper",
            original_name=record.original_name,
        )
        updated = record.model_copy(update={"promoted_source_id": source.source_id})
        self._write_record(updated)
        return source

    def delete(self, thread_id: str, attachment_id: str) -> AgentAttachmentRecord:
        """Delete one thread-scoped upload after its message reference is cleared."""

        record = self.get(thread_id, attachment_id)
        attachment_dir = self._thread_dir(thread_id) / attachment_id
        if attachment_dir.resolve().parent != self._thread_dir(thread_id).resolve():
            raise ValueError("attachment path escaped its thread directory")
        if attachment_dir.exists():
            shutil.rmtree(attachment_dir)
        return record

    def delete_thread(self, thread_id: str) -> int:
        count = len(self.list(thread_id))
        thread_dir = self._thread_dir(thread_id)
        if thread_dir.exists():
            shutil.rmtree(thread_dir)
        return count

    def _thread_dir(self, thread_id: str) -> Path:
        return self.base_dir / thread_id

    def _record_path(self, thread_id: str, attachment_id: str) -> Path:
        return self._thread_dir(thread_id) / attachment_id / "metadata.json"

    def _write_record(self, record: AgentAttachmentRecord) -> None:
        path = self._record_path(record.thread_id, record.attachment_id)
        _atomic_write_text(path, record.model_dump_json(indent=2))

    def _lazy_read_lock(self, thread_id: str, attachment_id: str) -> threading.Lock:
        key = str(self._record_path(thread_id, attachment_id).resolve())
        with _ATTACHMENT_LAZY_READ_LOCKS_GUARD:
            return _ATTACHMENT_LAZY_READ_LOCKS.setdefault(key, threading.Lock())

    @staticmethod
    def _validate_thread_id(thread_id: str) -> None:
        if not re.fullmatch(r"thread_[a-f0-9]{32}", thread_id):
            raise KeyError(thread_id)

    @staticmethod
    def _validate_attachment_id(attachment_id: str) -> None:
        if not re.fullmatch(r"att_[a-f0-9]{32}", attachment_id):
            raise KeyError(attachment_id)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


def _read_text_if_supported(path: Path) -> str | None:
    if path.suffix.lower() == ".pdf":
        try:
            pages: list[str] = []
            with pdfplumber.open(path) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                    if text.strip():
                        pages.append(f"[Page {page_number}]\n{text.strip()}")
            return "\n\n".join(pages) or None
        except (OSError, ValueError, PDFSyntaxError):
            return None
    if path.suffix.lower() not in {".txt", ".md", ".csv", ".tsv", ".json"}:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _atomic_write_text(path: Path, content: str) -> None:
    """Write runtime metadata without sharing a Windows temporary path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.{uuid.uuid4().hex}{path.suffix}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        key = str(path.resolve())
        with _ATOMIC_WRITE_LOCKS_GUARD:
            write_lock = _ATOMIC_WRITE_LOCKS.setdefault(key, threading.Lock())
        # Windows can reject simultaneous replacement of the same destination
        # even when the source temp files are different.
        with write_lock:
            temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
