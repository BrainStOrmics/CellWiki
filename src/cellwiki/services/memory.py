# =============================================================================
# 记忆服务 —— 项目范围的情景记忆和稳定记忆持久化
# =============================================================================

"""Project-scoped, governed episode and stable memory persistence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Iterator, List

from cellwiki.domain.memory import (
    MemoryCandidate,
    MemoryKind,
    MemoryRecall,
    MemoryRecord,
    MemoryStatus,
)


# ---------------------------------------------------------------------------
# MemoryStore —— 记忆存储服务
# 项目范围的情景记忆和稳定记忆的持久化存储。
# 使用 SQLite 数据库，包含两个核心表：
# - memory_records: 持久化记录表（稳定存储）
# - memory_fts: 全文搜索索引（可丢弃的检索索引）
# 所有读写方法都需要显式的项目 ID，防止意外的跨项目召回。
# 支持确定性去重、冲突检测和过期清理。
# ---------------------------------------------------------------------------
class MemoryStore:
    """Admit, recall, expire, and delete memory without touching formal knowledge.

    The record table is durable; the FTS table is a disposable retrieval index.
    All read and write methods require an explicit project ID to prevent accidental
    cross-project recall.
    """

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        # 记忆数据库路径
        self.db_path = self.project_root / "data" / "runtime" / "memory.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._create_schema(connection)

    # 接收记忆候选，应用确定性去重和冲突策略
    def admit(self, candidate: MemoryCandidate) -> MemoryRecord:
        """Apply deterministic deduplication and conflict policy to a candidate."""

        now = datetime.now(UTC)
        content_hash = self._content_hash(candidate.content)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                """
                SELECT * FROM memories
                WHERE project_id = ? AND kind = ? AND content_hash = ? AND status = 'active'
                """,
                (candidate.project_id, candidate.kind.value, content_hash),
            ).fetchone()
            if duplicate:
                connection.rollback()
                return self._record(duplicate)

            conflicts: list[str] = []
            if candidate.kind == MemoryKind.STABLE and candidate.key:
                rows = connection.execute(
                    """
                    SELECT memory_id FROM memories
                    WHERE project_id = ? AND kind = 'stable' AND memory_key = ?
                      AND status = 'active' AND content_hash != ?
                    """,
                    (candidate.project_id, candidate.key, content_hash),
                ).fetchall()
                conflicts = [str(row[0]) for row in rows]
            status = MemoryStatus.CONFLICT if conflicts else MemoryStatus.ACTIVE
            memory_id = f"mem_{hashlib.sha256(f'{candidate.project_id}\0{candidate.candidate_id}\0{content_hash}'.encode()).hexdigest()[:20]}"
            connection.execute(
                """
                INSERT INTO memories(
                    memory_id, project_id, kind, content, memory_key, run_id, confidence,
                    tags_json, status, conflicts_json, expires_at, content_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    candidate.project_id,
                    candidate.kind.value,
                    candidate.content,
                    candidate.key,
                    candidate.run_id,
                    candidate.confidence,
                    json.dumps(candidate.tags, ensure_ascii=False),
                    status.value,
                    json.dumps(conflicts),
                    candidate.expires_at.isoformat() if candidate.expires_at else None,
                    content_hash,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            if status == MemoryStatus.ACTIVE:
                rowid = connection.execute(
                    "SELECT rowid FROM memories WHERE memory_id = ?", (memory_id,)
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)",
                    (rowid, candidate.content, " ".join(candidate.tags)),
                )
            connection.commit()
            return self.get(candidate.project_id, memory_id)

    def get(self, project_id: str, memory_id: str) -> MemoryRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE project_id = ? AND memory_id = ?",
                (project_id, memory_id),
            ).fetchone()
        if not row:
            raise KeyError(memory_id)
        return self._record(row)

    def list(
        self,
        project_id: str,
        *,
        kind: MemoryKind | None = None,
        include_inactive: bool = False,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        self.expire(project_id)
        clauses = ["project_id = ?"]
        params: list[object] = [project_id]
        if kind:
            clauses.append("kind = ?")
            params.append(kind.value)
        if not include_inactive:
            clauses.append("status = 'active'")
        params.append(max(1, min(limit, 500)))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._record(row) for row in rows]

    def recall(
        self,
        project_id: str,
        query: str,
        *,
        kinds: Iterable[MemoryKind] | None = None,
        limit: int = 6,
        token_budget: int = 800,
    ) -> tuple[List[MemoryRecord], MemoryRecall]:
        """Recall a bounded set and record exactly which memories were exposed."""

        self.expire(project_id)
        terms = [term for term in query.split() if term]
        requested = [kind.value for kind in (kinds or [])]
        records: List[MemoryRecord] = []
        tokens = 0
        if terms and token_budget > 0:
            # Natural user requests often contain extra words that are absent from a
            # concise memory. OR preserves recall; bm25/confidence still rank the most
            # relevant bounded records first, and project/status filters prevent bleed.
            fts_query = " OR ".join(
                f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms
            )
            kind_clause = "AND m.kind IN ({})".format(",".join("?" for _ in requested)) if requested else ""
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT m.* FROM memories_fts
                    JOIN memories m ON m.rowid = memories_fts.rowid
                    WHERE memories_fts MATCH ? AND m.project_id = ? AND m.status = 'active'
                    {kind_clause}
                    ORDER BY bm25(memories_fts), m.confidence DESC, m.updated_at DESC
                    LIMIT ?
                    """,
                    [fts_query, project_id, *requested, max(1, min(limit, 50))],
                ).fetchall()
            for row in rows:
                record = self._record(row)
                estimated = max(1, len(record.content) // 4)
                if records and tokens + estimated > token_budget:
                    break
                if not records and estimated > token_budget:
                    # A single large memory is clipped at the retrieval seam, never in storage.
                    clipped = record.model_copy(update={"content": record.content[: token_budget * 4]})
                    records.append(clipped)
                    tokens = token_budget
                    break
                records.append(record)
                tokens += estimated

        recall = MemoryRecall(
            recall_id=f"recall_{uuid.uuid4().hex}",
            project_id=project_id,
            query=query,
            memory_ids=[record.memory_id for record in records],
            estimated_tokens=tokens,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_recalls(recall_id, project_id, query, memory_ids_json, estimated_tokens, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    recall.recall_id,
                    project_id,
                    query,
                    json.dumps(recall.memory_ids),
                    tokens,
                    recall.created_at.isoformat(),
                ),
            )
            connection.commit()
        return records, recall

    def resolve_conflict(self, project_id: str, memory_id: str, *, activate: bool) -> MemoryRecord:
        record = self.get(project_id, memory_id)
        if record.status != MemoryStatus.CONFLICT:
            raise ValueError("memory is not awaiting conflict resolution")
        status = MemoryStatus.ACTIVE if activate else MemoryStatus.DELETED
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE memories SET status = ?, updated_at = ? WHERE project_id = ? AND memory_id = ?",
                (status.value, datetime.now(UTC).isoformat(), project_id, memory_id),
            )
            if activate:
                rowid = connection.execute(
                    "SELECT rowid FROM memories WHERE memory_id = ?", (memory_id,)
                ).fetchone()[0]
                connection.execute(
                    "INSERT OR REPLACE INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)",
                    (rowid, record.content, " ".join(record.tags)),
                )
            connection.commit()
        return self.get(project_id, memory_id)

    def delete(self, project_id: str, memory_id: str) -> MemoryRecord:
        record = self.get(project_id, memory_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rowid = connection.execute(
                "SELECT rowid FROM memories WHERE project_id = ? AND memory_id = ?",
                (project_id, memory_id),
            ).fetchone()[0]
            connection.execute("DELETE FROM memories_fts WHERE rowid = ?", (rowid,))
            connection.execute(
                "UPDATE memories SET status = 'deleted', updated_at = ? WHERE memory_id = ?",
                (datetime.now(UTC).isoformat(), memory_id),
            )
            connection.commit()
        return record.model_copy(update={"status": MemoryStatus.DELETED})

    def expire(self, project_id: str) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT rowid FROM memories
                WHERE project_id = ? AND status = 'active' AND expires_at IS NOT NULL AND expires_at <= ?
                """,
                (project_id, now),
            ).fetchall()
            if not rows:
                return 0
            connection.execute("BEGIN IMMEDIATE")
            for row in rows:
                connection.execute("DELETE FROM memories_fts WHERE rowid = ?", (row[0],))
            connection.execute(
                """
                UPDATE memories SET status = 'expired', updated_at = ?
                WHERE project_id = ? AND status = 'active' AND expires_at IS NOT NULL AND expires_at <= ?
                """,
                (now, project_id, now),
            )
            connection.commit()
            return len(rows)

    def rebuild_index(self) -> int:
        """Recreate the disposable FTS table from durable admitted records."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM memories_fts")
            rows = connection.execute(
                "SELECT rowid, content, tags_json FROM memories WHERE status = 'active'"
            ).fetchall()
            for row in rows:
                connection.execute(
                    "INSERT INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)",
                    (row["rowid"], row["content"], " ".join(json.loads(row["tags_json"]))),
                )
            connection.commit()
            return len(rows)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            self._create_schema(connection)
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories(
                memory_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                memory_key TEXT,
                run_id TEXT,
                confidence REAL NOT NULL,
                tags_json TEXT NOT NULL,
                status TEXT NOT NULL,
                conflicts_json TEXT NOT NULL,
                expires_at TEXT,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memory_scope ON memories(project_id, status, kind);
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content, tags, tokenize='unicode61 remove_diacritics 2'
            );
            CREATE TABLE IF NOT EXISTS memory_recalls(
                recall_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                query TEXT NOT NULL,
                memory_ids_json TEXT NOT NULL,
                estimated_tokens INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            project_id=row["project_id"],
            kind=MemoryKind(row["kind"]),
            content=row["content"],
            key=row["memory_key"],
            run_id=row["run_id"],
            confidence=row["confidence"],
            tags=json.loads(row["tags_json"]),
            status=MemoryStatus(row["status"]),
            conflicts_with=json.loads(row["conflicts_json"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(" ".join(content.lower().split()).encode()).hexdigest()
