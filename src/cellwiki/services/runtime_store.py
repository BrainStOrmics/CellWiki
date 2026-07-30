# =============================================================================
# 运行时存储 —— CellWiki 运行状态和桌面事件的 SQLite 存储
# =============================================================================

# ---------------------------------------------------------------------------
# RuntimeStore —— 运行时存储
# CellWiki 运行状态和桌面事件的 SQLite 持久化存储。
# 提供运行记录的创建、查询、状态转换、事件追加等功能。
# 支持按 thread_id 查询运行列表，按 run_id 获取事件流。
# 所有写入操作使用事务确保数据一致性。
# ---------------------------------------------------------------------------

"""SQLite truth for CellWiki run state and stable desktop events."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cellwiki.domain.runs import (
    AgentErrorType,
    AgentEvent,
    AgentEventType,
    AgentRun,
    AgentRunOutcome,
    AgentSpan,
    AgentRunStatus,
    RunUsage,
)


_TRANSITIONS: dict[AgentRunStatus, set[AgentRunStatus]] = {
    AgentRunStatus.QUEUED: {
        AgentRunStatus.RUNNING,
        AgentRunStatus.WAITING_CONFIRMATION,
        AgentRunStatus.CANCELLED,
    },
    AgentRunStatus.RUNNING: {
        AgentRunStatus.WAITING_CONFIRMATION,
        AgentRunStatus.WAITING_APPROVAL,
        AgentRunStatus.APPLYING,
        AgentRunStatus.SUCCEEDED,
        AgentRunStatus.REJECTED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLING,
    },
    AgentRunStatus.WAITING_CONFIRMATION: {
        AgentRunStatus.RUNNING,
        AgentRunStatus.CANCELLED,
    },
    AgentRunStatus.WAITING_APPROVAL: {
        AgentRunStatus.RUNNING,
        AgentRunStatus.REJECTED,
        AgentRunStatus.CANCELLED,
    },
    AgentRunStatus.APPLYING: {
        AgentRunStatus.VERIFYING,
        AgentRunStatus.FAILED,
    },
    AgentRunStatus.VERIFYING: {
        AgentRunStatus.SUCCEEDED,
        AgentRunStatus.FAILED,
    },
    AgentRunStatus.FAILED: {AgentRunStatus.RETRYING},
    AgentRunStatus.RETRYING: {AgentRunStatus.RUNNING, AgentRunStatus.FAILED},
    AgentRunStatus.CANCELLING: {AgentRunStatus.CANCELLED, AgentRunStatus.FAILED},
    AgentRunStatus.SUCCEEDED: set(),
    AgentRunStatus.REJECTED: set(),
    AgentRunStatus.CANCELLED: set(),
}


class InvalidRunTransitionError(RuntimeError):
    pass


class TerminalRunError(RuntimeError):
    """Raised when code attempts to append work after a finalized run."""


class RuntimeStore:
    """Deep persistence module: schema, transitions, sequencing, and atomic event append live here."""

    def __init__(self, project_root: Path):
        self.path = Path(project_root).resolve() / "data" / "runtime" / "cellwiki.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._ensure_schema()
        self._backfill_messages()

    def create_run(self, run: AgentRun) -> AgentRun:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO agent_runs(run_id, thread_id, status, payload, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.thread_id,
                    run.status.value,
                    run.model_dump_json(),
                    run.updated_at.isoformat(),
                ),
            )
            self._insert_event(
                connection,
                run,
                AgentEventType.RUN_STATUS,
                message="Run queued.",
                progress=0,
                data={"status": run.status.value},
            )
            self._insert_message(
                connection,
                thread_id=run.thread_id,
                run_id=run.run_id,
                role="user",
                content=run.input_message,
                data={},
            )
        return run

    def append_message(
        self,
        *,
        thread_id: str,
        run_id: str,
        role: str,
        content: str,
        data: dict | None = None,
    ) -> dict:
        """Persist one user or assistant message in the durable thread transcript."""
        if role not in {"user", "assistant"}:
            raise ValueError("message role must be user or assistant")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_message(
                connection,
                thread_id=thread_id,
                run_id=run_id,
                role=role,
                content=content,
                data=data or {},
            )
            row = connection.execute(
                """
                SELECT message_id, thread_id, run_id, sequence, role, content, data, created_at
                FROM agent_messages WHERE thread_id = ? AND run_id = ? AND role = ?
                """,
                (thread_id, run_id, role),
            ).fetchone()
        return self._message_payload(row)

    def list_messages(self, thread_id: str) -> list[dict]:
        """Return the complete ordered transcript for a durable thread."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT message_id, thread_id, run_id, sequence, role, content, data, created_at
                FROM agent_messages WHERE thread_id = ? ORDER BY sequence
                """,
                (thread_id,),
            ).fetchall()
            process_by_run = {
                run_id: self._list_process_steps(connection, run_id)
                for run_id in {row[2] for row in rows if row[4] == "assistant"}
            }
        return [
            self._message_payload(row, process=process_by_run.get(row[2], []))
            for row in rows
        ]

    def list_context_messages(self, thread_id: str) -> list[dict[str, str]]:
        """Return only observable transcript fields used for later model context."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, role, content
                FROM agent_messages
                WHERE thread_id = ?
                ORDER BY sequence
                """,
                (thread_id,),
            ).fetchall()
        return [
            {"run_id": str(row[0]), "role": str(row[1]), "content": str(row[2])}
            for row in rows
            if str(row[2]).strip()
        ]

    def delete_thread(self, thread_id: str) -> int:
        """Delete all product records for a thread and return its run count."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_count = connection.execute(
                "SELECT COUNT(*) FROM agent_runs WHERE thread_id = ?", (thread_id,)
            ).fetchone()[0]
            connection.execute("DELETE FROM agent_messages WHERE thread_id = ?", (thread_id,))
            connection.execute(
                "DELETE FROM agent_events WHERE run_id IN "
                "(SELECT run_id FROM agent_runs WHERE thread_id = ?)",
                (thread_id,),
            )
            connection.execute("DELETE FROM agent_runs WHERE thread_id = ?", (thread_id,))
        return int(run_count)

    def get_run(self, run_id: str) -> AgentRun:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return AgentRun.model_validate_json(row[0])

    def list_runs(self, *, thread_id: str | None = None, limit: int = 100) -> list[AgentRun]:
        query = "SELECT payload FROM agent_runs"
        parameters: tuple = ()
        if thread_id:
            query += " WHERE thread_id = ?"
            parameters = (thread_id,)
        query += " ORDER BY updated_at DESC LIMIT ?"
        parameters += (limit,)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [AgentRun.model_validate_json(row[0]) for row in rows]

    def transition(
        self,
        run_id: str,
        status: AgentRunStatus,
        *,
        error_type: AgentErrorType | None = None,
        error_message: str | None = None,
        message: str | None = None,
        progress: int | None = None,
        data: dict | None = None,
    ) -> AgentRun:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            if status != current.status and status not in _TRANSITIONS[current.status]:
                raise InvalidRunTransitionError(
                    f"invalid run transition: {current.status.value} -> {status.value}"
                )
            updated = current.model_copy(
                update={
                    "status": status,
                    "error_type": error_type,
                    "error_message": error_message,
                    "updated_at": datetime.now(UTC),
                }
            )
            connection.execute(
                "UPDATE agent_runs SET status = ?, payload = ?, updated_at = ? WHERE run_id = ?",
                (status.value, updated.model_dump_json(), updated.updated_at.isoformat(), run_id),
            )
            if status != current.status:
                # Persist the transition in the same transaction as the run row so the
                # desktop never has to infer lifecycle state from conversational text.
                self._insert_event(
                    connection,
                    updated,
                    AgentEventType.RUN_STATUS,
                    message=message or f"Run status changed to {status.value}.",
                    progress=progress,
                    data={"status": status.value, **(data or {})},
                )
        return updated

    def update_usage(self, run_id: str, usage: RunUsage) -> AgentRun:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            updated = current.model_copy(
                update={"usage": usage, "updated_at": datetime.now(UTC)}
            )
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE run_id = ?",
                (updated.model_dump_json(), updated.updated_at.isoformat(), run_id),
            )
        return updated

    def increment_retry(self, run_id: str) -> AgentRun:
        """Advance retry accounting atomically before scheduling the resumed checkpoint."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            updated = current.model_copy(
                update={"retry_count": current.retry_count + 1, "updated_at": datetime.now(UTC)}
            )
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE run_id = ?",
                (updated.model_dump_json(), updated.updated_at.isoformat(), run_id),
            )
        return updated

    def finalize_run(self, run_id: str, outcome: AgentRunOutcome) -> AgentRun:
        """Persist a self-contained terminal outcome as the last lifecycle event."""

        terminal_statuses = {
            AgentRunStatus.WAITING_CONFIRMATION,
            AgentRunStatus.WAITING_APPROVAL,
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.REJECTED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
        if outcome.status not in terminal_statuses:
            raise ValueError(f"{outcome.status.value} is not a terminal run outcome")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            if current.finished_at is not None:
                if current.status == outcome.status:
                    return current
                raise InvalidRunTransitionError(
                    f"run already finalized as {current.status.value}"
                )
            if outcome.status != current.status and outcome.status not in _TRANSITIONS[current.status]:
                raise InvalidRunTransitionError(
                    f"invalid run transition: {current.status.value} -> {outcome.status.value}"
                )

            updated = current.model_copy(
                update={
                    "status": outcome.status,
                    "error_type": outcome.error_type,
                    "error_message": outcome.error_message,
                    "finished_at": outcome.finished_at,
                    "updated_at": outcome.finished_at,
                }
            )
            connection.execute(
                "UPDATE agent_runs SET status = ?, payload = ?, updated_at = ? WHERE run_id = ?",
                (
                    updated.status.value,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    run_id,
                ),
            )
            error_type = outcome.error_type.value if outcome.error_type else None
            if outcome.status == AgentRunStatus.FAILED:
                self._insert_event(
                    connection,
                    updated,
                    AgentEventType.ERROR,
                    message=outcome.error_message or outcome.message,
                    data={
                        "status": outcome.status.value,
                        "error_type": error_type,
                        "retryable": outcome.retryable,
                    },
                )
            self._insert_event(
                connection,
                updated,
                AgentEventType.RUN_STATUS,
                message=outcome.message,
                progress=outcome.progress,
                data={
                    "status": outcome.status.value,
                    "terminal": True,
                    "error_type": error_type,
                    "error_message": outcome.error_message,
                    "retryable": outcome.retryable,
                    "finished_at": outcome.finished_at.isoformat(),
                },
            )
        return updated

    def claim_resume(self, run_id: str, *, decision: str) -> AgentRun:
        """Claim one approval continuation with a compare-and-set transition."""

        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            if current.status is not AgentRunStatus.WAITING_APPROVAL:
                raise InvalidRunTransitionError(
                    "only a waiting-approval run can be resumed"
                )
            updated = current.model_copy(
                update={
                    "status": AgentRunStatus.RUNNING,
                    "finished_at": None,
                    "updated_at": datetime.now(UTC),
                }
            )
            connection.execute(
                "UPDATE agent_runs SET status = ?, payload = ?, updated_at = ? "
                "WHERE run_id = ? AND status = ?",
                (
                    AgentRunStatus.RUNNING.value,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    run_id,
                    AgentRunStatus.WAITING_APPROVAL.value,
                ),
            )
            self._insert_event(
                connection,
                updated,
                AgentEventType.RUN_STATUS,
                message="Approval continuation claimed.",
                data={"status": AgentRunStatus.RUNNING.value, "decision": decision},
            )
        return updated

    def claim_task_confirmation(self, run_id: str, *, decision: str) -> AgentRun:
        """Reopen one confirmed task proposal without replaying natural language."""

        if decision not in {"execute", "cancel"}:
            raise ValueError("decision must be execute or cancel")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            if current.status is not AgentRunStatus.WAITING_CONFIRMATION:
                raise InvalidRunTransitionError(
                    "only a waiting-confirmation run can be confirmed"
                )
            updated = current.model_copy(
                update={
                    "status": AgentRunStatus.RUNNING,
                    "finished_at": None,
                    "updated_at": datetime.now(UTC),
                }
            )
            connection.execute(
                "UPDATE agent_runs SET status = ?, payload = ?, updated_at = ? "
                "WHERE run_id = ? AND status = ?",
                (
                    AgentRunStatus.RUNNING.value,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    run_id,
                    AgentRunStatus.WAITING_CONFIRMATION.value,
                ),
            )
            self._insert_event(
                connection,
                updated,
                AgentEventType.RUN_STATUS,
                message="Task confirmation resolved.",
                data={"status": AgentRunStatus.RUNNING.value, "decision": decision},
            )
        return updated

    def claim_retry(self, run_id: str) -> AgentRun:
        """Atomically increment retry accounting and claim the retry slot."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            if current.status is not AgentRunStatus.FAILED:
                raise InvalidRunTransitionError("only a failed run can be retried")
            updated = current.model_copy(
                update={
                    "status": AgentRunStatus.RETRYING,
                    "retry_count": current.retry_count + 1,
                    "finished_at": None,
                    "updated_at": datetime.now(UTC),
                }
            )
            connection.execute(
                "UPDATE agent_runs SET status = ?, payload = ?, updated_at = ? "
                "WHERE run_id = ? AND status = ?",
                (
                    AgentRunStatus.RETRYING.value,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    run_id,
                    AgentRunStatus.FAILED.value,
                ),
            )
            self._insert_event(
                connection,
                updated,
                AgentEventType.RUN_STATUS,
                message="Retry claimed from the latest durable checkpoint.",
                data={"status": AgentRunStatus.RETRYING.value},
            )
        return updated

    def append_event(
        self,
        run_id: str,
        event_type: AgentEventType,
        *,
        message: str = "",
        progress: int | None = None,
        data: dict | None = None,
    ) -> AgentEvent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = AgentRun.model_validate_json(row[0])
            if run.finished_at is not None:
                raise TerminalRunError(
                    f"cannot append {event_type.value} after run finalized as {run.status.value}"
                )
            event = self._insert_event(
                connection,
                run,
                event_type,
                message=message,
                progress=progress,
                data=data,
            )
        return event

    def list_events(self, run_id: str, *, after: int = 0) -> list[AgentEvent]:
        self.get_run(run_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM agent_events WHERE run_id = ? AND sequence > ? ORDER BY sequence",
                (run_id, after),
            ).fetchall()
        return [AgentEvent.model_validate_json(row[0]) for row in rows]

    def upsert_span(self, span: AgentSpan) -> AgentSpan:
        """Persist redacted diagnostics without storing prompts or credentials."""

        safe_span = span.model_copy(update={"data": _redact_span_data(span.data)})
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM agent_runs WHERE run_id = ?",
                (safe_span.run_id,),
            ).fetchone() is None:
                raise KeyError(safe_span.run_id)
            connection.execute(
                """
                INSERT INTO agent_spans(span_id, run_id, payload, started_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(span_id) DO UPDATE SET payload = excluded.payload
                """,
                (
                    safe_span.span_id,
                    safe_span.run_id,
                    safe_span.model_dump_json(),
                    safe_span.started_at.isoformat(),
                ),
            )
        return safe_span

    def list_spans(self, run_id: str) -> list[AgentSpan]:
        self.get_run(run_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM agent_spans WHERE run_id = ? ORDER BY started_at, span_id",
                (run_id,),
            ).fetchall()
        return [AgentSpan.model_validate_json(row[0]) for row in rows]

    def _ensure_schema(self) -> None:
        with self._schema_lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_agent_runs_thread ON agent_runs(thread_id, updated_at);
                CREATE TABLE IF NOT EXISTS agent_events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence),
                    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS agent_messages (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(thread_id, sequence),
                    UNIQUE(run_id, role),
                    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS ix_agent_messages_thread
                    ON agent_messages(thread_id, sequence);
                CREATE TABLE IF NOT EXISTS agent_spans (
                    span_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS ix_agent_spans_run
                    ON agent_spans(run_id, started_at);
                PRAGMA user_version=2;
                """
            )

    def _backfill_messages(self) -> None:
        """Backfill transcripts created before the durable message table existed.

        Older installations persisted the user prompt in ``AgentRun`` and the final
        answer only in ``agent_events``. Reconstruct those two observable messages
        once at startup so upgrading the application does not make old sessions
        appear empty. The operation is idempotent because ``_insert_message``
        checks the unique ``(run_id, role)`` constraint before inserting.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT payload FROM agent_runs ORDER BY updated_at ASC"
            ).fetchall()
            runs = sorted(
                (AgentRun.model_validate_json(row[0]) for row in rows),
                key=lambda run: run.created_at,
            )
            for run in runs:
                self._insert_message(
                    connection,
                    thread_id=run.thread_id,
                    run_id=run.run_id,
                    role="user",
                    content=run.input_message,
                    data={},
                )
                event_rows = connection.execute(
                    """
                    SELECT payload FROM agent_events
                    WHERE run_id = ?
                    ORDER BY sequence DESC
                    """,
                    (run.run_id,),
                ).fetchall()
                for event_row in event_rows:
                    event = AgentEvent.model_validate_json(event_row[0])
                    if event.type != AgentEventType.FINAL_RESPONSE:
                        continue
                    answer = event.message or str(event.data.get("answer", ""))
                    if answer:
                        self._insert_message(
                            connection,
                            thread_id=run.thread_id,
                            run_id=run.run_id,
                            role="assistant",
                            content=answer,
                            data=event.data,
                        )
                    break

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        run: AgentRun,
        event_type: AgentEventType,
        *,
        message: str = "",
        progress: int | None = None,
        data: dict | None = None,
    ) -> AgentEvent:
        """Append one event while the caller holds the run's write transaction."""

        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_events WHERE run_id = ?",
            (run.run_id,),
        ).fetchone()[0]
        event = AgentEvent(
            event_id=f"aevt_{uuid.uuid4().hex}",
            run_id=run.run_id,
            thread_id=run.thread_id,
            sequence=sequence,
            type=event_type,
            message=message,
            progress=progress,
            data=data or {},
        )
        connection.execute(
            "INSERT INTO agent_events(run_id, sequence, event_id, payload) VALUES (?, ?, ?, ?)",
            (run.run_id, sequence, event.event_id, event.model_dump_json()),
        )
        return event

    @staticmethod
    def _insert_message(
        connection: sqlite3.Connection,
        *,
        thread_id: str,
        run_id: str,
        role: str,
        content: str,
        data: dict,
    ) -> None:
        existing = connection.execute(
            "SELECT message_id FROM agent_messages WHERE run_id = ? AND role = ?",
            (run_id, role),
        ).fetchone()
        serialized_data = json.dumps(data, ensure_ascii=False, default=str)
        if existing:
            connection.execute(
                "UPDATE agent_messages SET content = ?, data = ? WHERE message_id = ?",
                (content, serialized_data, existing[0]),
            )
            return
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_messages WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO agent_messages(
                message_id, thread_id, run_id, sequence, role, content, data, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"message_{uuid.uuid4().hex}",
                thread_id,
                run_id,
                sequence,
                role,
                content,
                serialized_data,
                datetime.now(UTC).isoformat(),
            ),
        )

    @staticmethod
    def _list_process_steps(connection: sqlite3.Connection, run_id: str) -> list[dict]:
        """Project durable runtime events into the concise trace shown in chat bubbles."""
        displayable_types = {
            AgentEventType.TOOL_STARTED,
            AgentEventType.TOOL_COMPLETED,
            AgentEventType.TOOL_FAILED,
            AgentEventType.SUBAGENT_STARTED,
            AgentEventType.SUBAGENT_COMPLETED,
            AgentEventType.PROGRESS,
            AgentEventType.REVIEW_REQUIRED,
            AgentEventType.CHANGESET_READY,
            AgentEventType.VERIFICATION,
            AgentEventType.ERROR,
        }
        rows = connection.execute(
            "SELECT payload FROM agent_events WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        steps: list[dict] = []
        for row in rows:
            event = AgentEvent.model_validate_json(row[0])
            if event.type not in displayable_types:
                continue
            phase = (
                "failed"
                if event.type in {AgentEventType.TOOL_FAILED, AgentEventType.ERROR}
                else "running"
                if event.type in {AgentEventType.TOOL_STARTED, AgentEventType.SUBAGENT_STARTED}
                else "completed"
            )
            steps.append(
                {
                    "event_id": event.event_id,
                    "run_id": event.run_id,
                    "thread_id": event.thread_id,
                    "sequence": event.sequence,
                    "type": event.type.value,
                    "message": event.message,
                    "progress": event.progress,
                    "data": event.data,
                    "created_at": event.created_at.isoformat(),
                    "phase": phase,
                }
            )
        run_row = connection.execute(
            "SELECT status FROM agent_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        terminal_phase = {
            AgentRunStatus.FAILED.value: "failed",
            AgentRunStatus.CANCELLED.value: "cancelled",
            AgentRunStatus.SUCCEEDED.value: "completed",
            AgentRunStatus.REJECTED.value: "completed",
            AgentRunStatus.WAITING_CONFIRMATION.value: "completed",
            AgentRunStatus.WAITING_APPROVAL.value: "completed",
        }.get(str(run_row[0]) if run_row else "")
        if terminal_phase:
            for step in steps:
                if step["phase"] == "running":
                    step["phase"] = terminal_phase
        return steps

    @staticmethod
    def _message_payload(row: tuple, *, process: list[dict] | None = None) -> dict:
        data = json.loads(row[6])
        if row[4] == "assistant" and process:
            data["process"] = process
        return {
            "message_id": row[0],
            "thread_id": row[1],
            "run_id": row[2],
            "sequence": row[3],
            "role": row[4],
            "content": row[5],
            "data": data,
            "created_at": row[7],
        }


_SENSITIVE_SPAN_KEYS = {
    "api_key",
    "authorization",
    "bearer",
    "token",
    "prompt",
    "reasoning_content",
    "chain_of_thought",
    "raw_request",
    "raw_response",
}


def _redact_span_data(value):
    if isinstance(value, dict):
        return {
            str(key): _redact_span_data(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_SPAN_KEYS
        }
    if isinstance(value, list):
        return [_redact_span_data(item) for item in value]
    if isinstance(value, str):
        return value[:1000]
    return value
