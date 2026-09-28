# =============================================================================
# 工作区记忆存储（ADR-0016 切片 1）
# =============================================================================
# 记忆是工作区级协作记忆：Markdown 真相源在 data/runtime/memory/，候选与索引
# 在 cellwiki.db。写入统一收口到本模块，供 Phase 2 合并、add_ad_hoc_note 与
# 面板编辑共用；derived_hash 记录自动写入的内容校验和，用于识别用户手动编辑
# 并跳过自动合并。本切片只提供存储与候选队列，不含提取与合并管线。
# =============================================================================

"""Workspace-memory storage: candidate queue, active index, Markdown artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cellwiki.domain.memory import (
    MemoryCandidate,
    MemoryCandidateStatus,
    MemoryEntry,
    MemoryKind,
    MemorySummary,
    MemoryTopicFamily,
)

MEMORY_DIR_NAME = "memory"
MEMORY_SUMMARY_FILE = "memory_summary.md"
MEMORY_INDEX_FILE = "MEMORY.md"
MEMORY_SCHEMA_VERSION = 1
# 对齐 Codex：文件 <10,000 UTF-8 bytes，注入硬截断 2,500 tokens。
MEMORY_SUMMARY_MAX_BYTES = 10_000
MEMORY_SUMMARY_MAX_TOKENS = 2_500
CHARS_PER_TOKEN = 4
SUMMARY_HEADINGS = (
    "## User Profile",
    "## User Preferences",
    "## General Tips",
    "## What's in Memory",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _split_summary_sections(body: str) -> dict[str, str]:
    """Split a summary body into its four fixed sections (missing -> empty)."""

    sections: dict[str, str] = {heading: "" for heading in SUMMARY_HEADINGS}
    current: str | None = None
    buffer: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped in sections:
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = stripped
            buffer = []
            continue
        if stripped == "v1" and current is None and not buffer:
            continue
        if current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return sections


def validate_summary_body(body: str) -> None:
    """Raise ValueError when a summary breaks the fixed Codex-shaped contract."""

    lines = body.splitlines()
    if not lines or lines[0].strip() != "v1":
        raise ValueError("memory summary must start with a bare v1 line")
    if len(body.encode("utf-8")) >= MEMORY_SUMMARY_MAX_BYTES:
        raise ValueError(
            f"memory summary must stay under {MEMORY_SUMMARY_MAX_BYTES} UTF-8 bytes"
        )
    for heading in SUMMARY_HEADINGS:
        if not any(line.strip() == heading for line in lines):
            raise ValueError(f"memory summary is missing heading {heading}")


def render_summary(
    *,
    profile: str = "",
    preferences: str = "",
    tips: str = "",
    index: str = "",
) -> str:
    """Render a valid summary body from its four sections."""

    parts = [
        "v1",
        "",
        "## User Profile",
        profile.strip(),
        "",
        "## User Preferences",
        preferences.strip(),
        "",
        "## General Tips",
        tips.strip(),
        "",
        "## What's in Memory",
        index.strip(),
        "",
    ]
    body = "\n".join(parts)
    validate_summary_body(body)
    return body


class WorkspaceMemoryStore:
    """Own the memory artifact directory and the candidate/index rows."""

    def __init__(self, workspace_root: Path, runtime_db: Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.runtime_db = Path(runtime_db)
        self.memory_dir = self.workspace_root / "data" / "runtime" / MEMORY_DIR_NAME

    # -- filesystem ------------------------------------------------------

    def ensure_layout(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def summary_path(self) -> Path:
        return self.memory_dir / MEMORY_SUMMARY_FILE

    def index_path(self) -> Path:
        return self.memory_dir / MEMORY_INDEX_FILE

    def read_summary(self) -> str:
        path = self.summary_path()
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")

    def write_summary(self, body: str) -> None:
        validate_summary_body(body)
        self.ensure_layout()
        self.summary_path().write_text(body, encoding="utf-8")

    def write_index(self, body: str) -> None:
        self.ensure_layout()
        self.index_path().write_text(body, encoding="utf-8")

    def read_entry_body(self, file_name: str) -> str:
        path = self._safe_entry_path(file_name)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")

    def write_entry_file(self, entry: MemoryEntry, body: str) -> str:
        """Write one entry file and return the derived hash of the payload."""

        self.ensure_layout()
        payload = {"memory_id": entry.memory_id, "title": entry.title, "body": body}
        derived = _content_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        frontmatter = {
            "memory_id": entry.memory_id,
            "schema_version": MEMORY_SCHEMA_VERSION,
            "kind": entry.kind.value,
            "topic_family": entry.topic_family.value,
            "title": entry.title,
            "workspace": entry.workspace,
            "derived_hash": derived,
            "auto_update": entry.auto_update,
            "user_edited": entry.user_edited,
            "updated_at": _now(),
        }
        lines = ["---"]
        for key, value in frontmatter.items():
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        lines.extend(["---", "", body.strip(), ""])
        self._safe_entry_path(entry.file_name).write_text(
            "\n".join(lines), encoding="utf-8"
        )
        return derived

    def _safe_entry_path(self, file_name: str) -> Path:
        candidate = (self.memory_dir / file_name).resolve()
        if self.memory_dir.resolve() not in candidate.parents:
            raise ValueError(f"memory file escapes the memory directory: {file_name}")
        if candidate.suffix != ".md" or candidate.name in {
            MEMORY_SUMMARY_FILE,
            MEMORY_INDEX_FILE,
        }:
            raise ValueError(f"invalid memory file name: {file_name}")
        return candidate

    # -- database --------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.runtime_db)
        connection.row_factory = sqlite3.Row
        return connection

    @property
    def _workspace_key(self) -> str:
        return str(self.workspace_root)

    def add_candidate(
        self,
        *,
        kind: MemoryKind,
        topic_family: MemoryTopicFamily,
        title: str,
        body: str,
        origin_run_id: str,
        origin_thread_id: str,
        source_refs: list[str] | None = None,
    ) -> MemoryCandidate:
        candidate = MemoryCandidate(
            memory_id=f"mem_{uuid.uuid4().hex}",
            workspace=self._workspace_key,
            kind=kind,
            topic_family=topic_family,
            title=title,
            body=body,
            source_refs=list(source_refs or []),
            origin_run_id=origin_run_id,
            origin_thread_id=origin_thread_id,
            derived_hash=_content_hash(body),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_candidates(
                    memory_id, workspace, kind, topic_family, title, body,
                    source_refs, origin_run_id, origin_thread_id, status,
                    derived_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.memory_id,
                    candidate.workspace,
                    candidate.kind.value,
                    candidate.topic_family.value,
                    candidate.title,
                    candidate.body,
                    json.dumps(candidate.source_refs, ensure_ascii=False),
                    candidate.origin_run_id,
                    candidate.origin_thread_id,
                    candidate.status.value,
                    candidate.derived_hash,
                    candidate.created_at.isoformat(),
                    candidate.updated_at.isoformat(),
                ),
            )
        return candidate

    def list_candidates(
        self, *, status: MemoryCandidateStatus | None = MemoryCandidateStatus.PENDING
    ) -> list[MemoryCandidate]:
        query = "SELECT * FROM memory_candidates WHERE workspace = ?"
        parameters: list[object] = [self._workspace_key]
        if status is not None:
            query += " AND status = ?"
            parameters.append(status.value)
        query += " ORDER BY created_at"
        with self._connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [self._candidate_from_row(row) for row in rows]

    def mark_candidate(
        self, memory_id: str, status: MemoryCandidateStatus
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE memory_candidates SET status = ?, updated_at = ? "
                "WHERE memory_id = ? AND workspace = ?",
                (status.value, _now(), memory_id, self._workspace_key),
            )

    def _candidate_from_row(self, row: sqlite3.Row) -> MemoryCandidate:
        return MemoryCandidate(
            memory_id=row["memory_id"],
            workspace=row["workspace"],
            kind=MemoryKind(row["kind"]),
            topic_family=MemoryTopicFamily(row["topic_family"]),
            title=row["title"],
            body=row["body"],
            source_refs=json.loads(row["source_refs"] or "[]"),
            origin_run_id=row["origin_run_id"],
            origin_thread_id=row["origin_thread_id"],
            status=MemoryCandidateStatus(row["status"]),
            derived_hash=row["derived_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def upsert_entry(
        self,
        *,
        memory_id: str,
        kind: MemoryKind,
        topic_family: MemoryTopicFamily,
        title: str,
        file_name: str,
        derived_hash: str,
        user_edited: bool = False,
        auto_update: bool = True,
    ) -> MemoryEntry:
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT created_at, usage_count, last_used_at FROM memory_entries "
                "WHERE memory_id = ? AND workspace = ?",
                (memory_id, self._workspace_key),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            usage_count = int(existing["usage_count"]) if existing else 0
            last_used_at = existing["last_used_at"] if existing else None
            connection.execute(
                """
                INSERT INTO memory_entries(
                    memory_id, workspace, kind, topic_family, title, file_name,
                    derived_hash, user_edited, auto_update, usage_count,
                    created_at, updated_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    kind = excluded.kind,
                    topic_family = excluded.topic_family,
                    title = excluded.title,
                    file_name = excluded.file_name,
                    derived_hash = excluded.derived_hash,
                    user_edited = excluded.user_edited,
                    auto_update = excluded.auto_update,
                    updated_at = excluded.updated_at
                """,
                (
                    memory_id,
                    self._workspace_key,
                    kind.value,
                    topic_family.value,
                    title,
                    file_name,
                    derived_hash,
                    int(user_edited),
                    int(auto_update),
                    usage_count,
                    created_at,
                    now,
                    last_used_at,
                ),
            )
        return MemoryEntry(
            memory_id=memory_id,
            workspace=self._workspace_key,
            kind=kind,
            topic_family=topic_family,
            title=title,
            file_name=file_name,
            derived_hash=derived_hash,
            user_edited=user_edited,
            auto_update=auto_update,
        )

    def list_entries(self) -> list[MemoryEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_entries WHERE workspace = ? "
                "ORDER BY topic_family, updated_at DESC",
                (self._workspace_key,),
            ).fetchall()
        return [self._entry_from_row(row) for row in rows]

    def get_entry(self, memory_id: str) -> MemoryEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_entries WHERE memory_id = ? AND workspace = ?",
                (memory_id, self._workspace_key),
            ).fetchone()
        return self._entry_from_row(row) if row else None

    def set_entry_auto_update(self, memory_id: str, auto_update: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE memory_entries SET auto_update = ?, user_edited = ?, "
                "updated_at = ? WHERE memory_id = ? AND workspace = ?",
                (
                    int(auto_update),
                    0 if auto_update else 1,
                    _now(),
                    memory_id,
                    self._workspace_key,
                ),
            )

    def delete_entry(self, memory_id: str) -> None:
        entry = self.get_entry(memory_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM memory_entries WHERE memory_id = ? AND workspace = ?",
                (memory_id, self._workspace_key),
            )
        if entry is not None:
            path = self._safe_entry_path(entry.file_name)
            path.unlink(missing_ok=True)

    def _entry_from_row(self, row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            memory_id=row["memory_id"],
            workspace=row["workspace"],
            kind=MemoryKind(row["kind"]),
            topic_family=MemoryTopicFamily(row["topic_family"]),
            title=row["title"],
            file_name=row["file_name"],
            derived_hash=row["derived_hash"],
            user_edited=bool(row["user_edited"]),
            auto_update=bool(row["auto_update"]),
            usage_count=int(row["usage_count"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_used_at=(
                datetime.fromisoformat(row["last_used_at"])
                if row["last_used_at"]
                else None
            ),
        )

    def summary_record(self) -> MemorySummary | None:
        body = self.read_summary()
        if not body:
            return None
        return MemorySummary(
            workspace=self._workspace_key,
            body=body,
            generation=self._content_generation(body),
        )

    @staticmethod
    def _content_generation(body: str) -> int:
        return int(_content_hash(body)[:8], 16)


__all__ = [
    "MEMORY_INDEX_FILE",
    "MEMORY_SUMMARY_FILE",
    "MEMORY_SUMMARY_MAX_BYTES",
    "MEMORY_SUMMARY_MAX_TOKENS",
    "SUMMARY_HEADINGS",
    "WorkspaceMemoryStore",
    "render_summary",
    "validate_summary_body",
]