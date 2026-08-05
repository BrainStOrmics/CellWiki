"""Thread-scoped temporary attachments for CellWiki Agent conversations."""

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import List

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError
from pydantic import BaseModel, Field

from cellwiki.domain.contracts import SourceRecord
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
        text = _read_text_if_supported(stored_path)
        text_path: Path | None = None
        text_hash: str | None = None
        if text is not None:
            text_path = attachment_dir / "text.txt"
            text_path.write_text(text, encoding="utf-8")
            text_hash = f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
        record = AgentAttachmentRecord(
            attachment_id=attachment_id,
            thread_id=thread_id,
            original_name=safe_name,
            media_type=media_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
            size_bytes=stored_path.stat().st_size,
            content_hash=f"sha256:{self._sha256(stored_path)}",
            text_hash=text_hash,
            stored_path=str(stored_path.resolve()),
            text_path=str(text_path.resolve()) if text_path else None,
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
        text_path.write_text(text, encoding="utf-8")
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
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

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
