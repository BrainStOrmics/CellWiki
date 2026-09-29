"""Persistent scheduling state for workspace-memory background work."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cellwiki.domain.memory import (
    MemoryJob,
    MemoryJobKind,
    MemoryJobStatus,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class MemoryJobStore:
    """Own persistent memory jobs in the workspace runtime database."""

    def __init__(self, runtime_db: Path, workspace_root: Path) -> None:
        self.runtime_db = Path(runtime_db)
        self.workspace_root = Path(workspace_root).resolve()

    @property
    def _workspace_key(self) -> str:
        return str(self.workspace_root)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.runtime_db)
        connection.row_factory = sqlite3.Row
        return connection

    def upsert_thread_job(
        self,
        *,
        thread_id: str,
        available_at: datetime,
        input_watermark: str,
        priority: int = 0,
        payload: dict[str, object] | None = None,
    ) -> MemoryJob:
        """Create or refresh the single extraction job for one thread."""

        now = _iso(_now())
        job_id = f"memjob_{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory_jobs(
                    job_id, workspace, thread_id, kind, status, priority,
                    available_at, worker_id, lease_until, retry_at, retry_count,
                    input_watermark, last_success_watermark, last_error, payload,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', NULL, NULL, 0, ?, '', '', ?, ?, ?)
                ON CONFLICT(workspace, thread_id, kind) DO UPDATE SET
                    status = excluded.status,
                    priority = excluded.priority,
                    available_at = excluded.available_at,
                    worker_id = '',
                    lease_until = NULL,
                    retry_at = NULL,
                    retry_count = 0,
                    input_watermark = excluded.input_watermark,
                    last_error = '',
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    job_id,
                    self._workspace_key,
                    thread_id,
                    MemoryJobKind.THREAD_EXTRACT.value,
                    MemoryJobStatus.PENDING.value,
                    priority,
                    _iso(available_at),
                    input_watermark,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        job = self.get_thread_job(thread_id)
        assert job is not None
        return job

    def get_job(self, job_id: str) -> MemoryJob | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_jobs WHERE job_id = ? AND workspace = ?",
                (job_id, self._workspace_key),
            ).fetchone()
        return self._job_from_row(row) if row else None

    def get_thread_job(self, thread_id: str) -> MemoryJob | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM memory_jobs
                WHERE workspace = ? AND thread_id = ? AND kind = ?
                """,
                (
                    self._workspace_key,
                    thread_id,
                    MemoryJobKind.THREAD_EXTRACT.value,
                ),
            ).fetchone()
        return self._job_from_row(row) if row else None

    def list_jobs(
        self,
        *,
        kind: MemoryJobKind | None = None,
        status: MemoryJobStatus | None = None,
    ) -> list[MemoryJob]:
        query = "SELECT * FROM memory_jobs WHERE workspace = ?"
        parameters: list[object] = [self._workspace_key]
        if kind is not None:
            query += " AND kind = ?"
            parameters.append(kind.value)
        if status is not None:
            query += " AND status = ?"
            parameters.append(status.value)
        query += " ORDER BY available_at, created_at"
        with self._connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [self._job_from_row(row) for row in rows]

    def claim_thread_jobs(
        self,
        *,
        now: datetime,
        worker_id: str,
        lease_seconds: int,
        limit: int,
    ) -> list[MemoryJob]:
        """Atomically lease due thread jobs, including expired leases."""

        if limit <= 0:
            return []
        now_text = _iso(now)
        lease_text = _iso(now + timedelta(seconds=lease_seconds))
        pending = MemoryJobStatus.PENDING.value
        failed = MemoryJobStatus.FAILED.value
        leased = MemoryJobStatus.LEASED.value
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM memory_jobs
                WHERE workspace = ? AND kind = ?
                  AND (
                    (
                      status = ?
                      AND available_at <= ?
                      AND (retry_at IS NULL OR retry_at <= ?)
                    )
                    OR (
                      status = ?
                      AND retry_at IS NOT NULL
                      AND retry_at <= ?
                    )
                    OR (
                      status = ?
                      AND lease_until IS NOT NULL
                      AND lease_until <= ?
                    )
                  )
                ORDER BY priority DESC, available_at, created_at
                LIMIT ?
                """,
                (
                    self._workspace_key,
                    MemoryJobKind.THREAD_EXTRACT.value,
                    pending,
                    now_text,
                    now_text,
                    failed,
                    now_text,
                    leased,
                    now_text,
                    limit,
                ),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE memory_jobs
                    SET status = ?, worker_id = ?, lease_until = ?, updated_at = ?
                    WHERE job_id = ? AND workspace = ?
                    """,
                    (
                        leased,
                        worker_id,
                        lease_text,
                        now_text,
                        row["job_id"],
                        self._workspace_key,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if not rows:
            return []
        job_ids = [row["job_id"] for row in rows]
        placeholders = ", ".join("?" for _ in job_ids)
        with self._connect() as connection:
            refreshed = {
                row["job_id"]: row
                for row in connection.execute(
                    f"SELECT * FROM memory_jobs WHERE job_id IN ({placeholders})",
                    tuple(job_ids),
                ).fetchall()
            }
        return [self._job_from_row(refreshed[job_id]) for job_id in job_ids]

    def complete_with_output(
        self,
        job_id: str,
        *,
        watermark: str,
    ) -> None:
        self._complete(
            job_id,
            status=MemoryJobStatus.SUCCEEDED,
            watermark=watermark,
        )

    def complete_without_output(
        self,
        job_id: str,
        *,
        watermark: str,
    ) -> None:
        self._complete(
            job_id,
            status=MemoryJobStatus.SUCCEEDED_NO_OUTPUT,
            watermark=watermark,
        )

    def _complete(
        self,
        job_id: str,
        *,
        status: MemoryJobStatus,
        watermark: str,
    ) -> None:
        now = _iso(_now())
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE memory_jobs
                SET status = ?, worker_id = '', lease_until = NULL,
                    retry_at = NULL, last_success_watermark = ?,
                    last_error = '', updated_at = ?
                WHERE job_id = ? AND workspace = ?
                """,
                (status.value, watermark, now, job_id, self._workspace_key),
            )

    def reschedule(
        self,
        job_id: str,
        *,
        available_at: datetime,
        error: str = "",
    ) -> None:
        now = _iso(_now())
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE memory_jobs
                SET status = ?, available_at = ?, worker_id = '',
                    lease_until = NULL, retry_at = NULL,
                    last_error = ?, updated_at = ?
                WHERE job_id = ? AND workspace = ?
                """,
                (
                    MemoryJobStatus.PENDING.value,
                    _iso(available_at),
                    error[:2000],
                    now,
                    job_id,
                    self._workspace_key,
                ),
            )

    def fail(
        self,
        job_id: str,
        *,
        error: str,
        retry_at: datetime | None,
        max_retries: int,
    ) -> None:
        now = _iso(_now())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT retry_count FROM memory_jobs
                WHERE job_id = ? AND workspace = ?
                """,
                (job_id, self._workspace_key),
            ).fetchone()
            retry_count = int(row["retry_count"]) + 1 if row else 1
            terminal = retry_at is None or retry_count >= max_retries
            connection.execute(
                """
                UPDATE memory_jobs
                SET status = ?, worker_id = '', lease_until = NULL,
                    retry_at = ?, retry_count = ?, last_error = ?, updated_at = ?
                WHERE job_id = ? AND workspace = ?
                """,
                (
                    MemoryJobStatus.FAILED.value,
                    _iso(retry_at)
                    if not terminal and retry_at is not None
                    else None,
                    retry_count,
                    error[:2000],
                    now,
                    job_id,
                    self._workspace_key,
                ),
            )

    def _job_from_row(self, row: sqlite3.Row) -> MemoryJob:
        return MemoryJob(
            job_id=row["job_id"],
            workspace=row["workspace"],
            thread_id=row["thread_id"],
            kind=MemoryJobKind(row["kind"]),
            status=MemoryJobStatus(row["status"]),
            priority=int(row["priority"]),
            available_at=datetime.fromisoformat(row["available_at"]),
            worker_id=str(row["worker_id"] or ""),
            lease_until=_from_iso(row["lease_until"]),
            retry_at=_from_iso(row["retry_at"]),
            retry_count=int(row["retry_count"]),
            input_watermark=str(row["input_watermark"] or ""),
            last_success_watermark=str(row["last_success_watermark"] or ""),
            last_error=str(row["last_error"] or ""),
            payload=json.loads(row["payload"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


__all__ = ["MemoryJobStore"]
