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

from contextlib import contextmanager
from collections.abc import Iterator
import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from cellwiki.domain.pending_diff import PendingDiff, PendingDiffStatus


_TRANSITIONS: dict[AgentRunStatus, set[AgentRunStatus]] = {
    AgentRunStatus.QUEUED: {
        AgentRunStatus.RUNNING,
        AgentRunStatus.WAITING_CONFIRMATION,
        AgentRunStatus.CANCELLED,
        AgentRunStatus.UNFINISHED,
        AgentRunStatus.FAILED,
    },
    AgentRunStatus.RUNNING: {
        AgentRunStatus.UNFINISHED,          # 预算/超时进入，可继续/恢复
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
        AgentRunStatus.UNFINISHED,  # 问题超时 -> 非终态待续
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
    AgentRunStatus.RETRYING: {AgentRunStatus.RUNNING, AgentRunStatus.FAILED, AgentRunStatus.UNFINISHED},
    AgentRunStatus.UNFINISHED: {AgentRunStatus.RUNNING, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED},
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

    def create_run(
        self,
        run: AgentRun,
        *,
        user_message_data: dict[str, Any] | None = None,
    ) -> AgentRun:
        message_data = user_message_data if user_message_data is not None else {}
        if user_message_data is None and run.attachment_ids:
            # Keep direct RuntimeStore callers and pre-message records compatible.
            message_data = {
                "attachments": [
                    {"attachment_id": attachment_id}
                    for attachment_id in dict.fromkeys(run.attachment_ids)
                ]
            }
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
                data=message_data,
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

    def list_thread_attachment_ids(self, thread_id: str) -> list[str]:
        """Recover the attachments available to later runs in this thread.

        Message-level references are authoritative for new runs. Run payloads are
        also checked so installations upgraded from the old Run-only attachment
        model remain usable.
        """

        with self._connect() as connection:
            message_rows = connection.execute(
                "SELECT data FROM agent_messages WHERE thread_id = ? ORDER BY sequence",
                (thread_id,),
            ).fetchall()
            run_rows = connection.execute(
                "SELECT payload FROM agent_runs WHERE thread_id = ? ORDER BY updated_at",
                (thread_id,),
            ).fetchall()

        attachment_ids: list[str] = []
        seen: set[str] = set()

        def add(value: object) -> None:
            if not isinstance(value, str) or not value or value in seen:
                return
            seen.add(value)
            attachment_ids.append(value)

        for row in message_rows:
            try:
                data = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                continue
            references = data.get("attachments", []) if isinstance(data, dict) else []
            if not isinstance(references, list):
                continue
            for reference in references:
                if isinstance(reference, dict):
                    add(reference.get("attachment_id"))

        for row in run_rows:
            try:
                run = AgentRun.model_validate_json(row[0])
            except (TypeError, ValueError):
                continue
            for attachment_id in run.attachment_ids:
                add(attachment_id)
        return attachment_ids

    # ---- 挂起问题（ask_user_question）----
    def save_pending_question(self, question: Any) -> dict:
        """Persist one open question bound to a run + tool call."""
        from cellwiki.domain.questions import PendingQuestion

        if not isinstance(question, PendingQuestion):
            question = PendingQuestion.model_validate(question)
        payload = question.model_dump_json()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR REPLACE INTO agent_questions(
                    question_id, run_id, thread_id, payload, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    question.question_id,
                    question.run_id,
                    question.thread_id,
                    payload,
                    question.status,
                    question.created_at.isoformat(),
                ),
            )
        return question.to_payload()

    def get_open_question(self, run_id: str) -> dict | None:
        """Return the newest pending question for a run, if any."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM agent_questions
                WHERE run_id = ? AND status = 'pending'
                ORDER BY created_at DESC, question_id LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def answer_question(
        self,
        run_id: str,
        answers: list[Any],
        *,
        timed_out: bool = False,
    ) -> dict | None:
        """Close an open question with the user's answers; returns the record."""
        question_id: str | None = None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT question_id, payload FROM agent_questions
                WHERE run_id = ? AND status = 'pending'
                ORDER BY created_at DESC, question_id LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            question_id, payload = row
            question = json.loads(payload)
            question["status"] = "timed_out" if timed_out else "answered"
            question["answers"] = answers
            question["answered_at"] = datetime.now(UTC).isoformat()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE agent_questions SET payload = ?, status = ?
                WHERE question_id = ?
                """,
                (json.dumps(question, ensure_ascii=False), question["status"], question_id),
            )
        return question

    def list_questions(self, run_id: str) -> list[dict]:
        """Return every question asked in a run, newest first."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM agent_questions
                WHERE run_id = ? ORDER BY created_at DESC, question_id
                """,
                (run_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    # ---- 线程身份 ----
    def create_thread(self, thread_id: str) -> None:
        """Persist one durable conversation identity."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO agent_threads(thread_id, created_at) VALUES (?, ?)",
                (thread_id, datetime.now(UTC).isoformat()),
            )

    def thread_exists(self, thread_id: str) -> bool:
        """Whether a conversation identity was previously allocated."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM agent_threads WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return row is not None

    # ---- 线程附件记录 ----
    def save_attachment(self, attachment: Any) -> dict:
        """Persist one thread-scoped attachment record (files live in AttachmentFileStore)."""
        from cellwiki.domain.attachments import ThreadAttachment

        if not isinstance(attachment, ThreadAttachment):
            attachment = ThreadAttachment.model_validate(attachment)
        payload = attachment.model_dump_json()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR REPLACE INTO agent_attachments(attachment_id, thread_id, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (attachment.attachment_id, attachment.thread_id, payload, attachment.created_at.isoformat()),
            )
        return attachment.to_payload()

    def list_attachments(self, thread_id: str) -> list[dict]:
        """Return the attachment records owned by one thread, newest first."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM agent_attachments
                WHERE thread_id = ? ORDER BY created_at DESC, attachment_id
                """,
                (thread_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_attachment(self, thread_id: str, attachment_id: str) -> dict | None:
        """Return one attachment record only when it belongs to the given thread."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload FROM agent_attachments
                WHERE thread_id = ? AND attachment_id = ?
                """,
                (thread_id, attachment_id),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def delete_attachments_for_thread(self, thread_id: str) -> int:
        """Delete every attachment record for a thread; returns the count removed."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM agent_attachments WHERE thread_id = ?", (thread_id,)
            )
        return cursor.rowcount

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
            connection.execute(
                "DELETE FROM pending_diffs WHERE thread_id = ?", (thread_id,)
            )
            connection.execute(
                "DELETE FROM agent_attachments WHERE thread_id = ?", (thread_id,)
            )
            connection.execute("DELETE FROM agent_threads WHERE thread_id = ?", (thread_id,))
        return int(run_count)

    # ---- 待确认 diff 持久化（阶段 4）----
    def save_pending_diff(self, diff: PendingDiff) -> None:
        """Create or update one pending diff row (idempotent by diff_id)."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO pending_diffs (diff_id, run_id, thread_id, status, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(diff_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    thread_id = excluded.thread_id,
                    status = excluded.status,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    diff.diff_id,
                    diff.run_id,
                    diff.thread_id,
                    diff.status.value,
                    diff.model_dump_json(),
                    diff.created_at.isoformat(),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def get_pending_diff(self, diff_id: str) -> PendingDiff:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM pending_diffs WHERE diff_id = ?", (diff_id,)
            ).fetchone()
        if row is None:
            raise KeyError(diff_id)
        return PendingDiff.model_validate_json(row[0])

    def list_pending_diffs(
        self, *, run_id: str | None = None, limit: int = 200
    ) -> list[PendingDiff]:
        query = "SELECT payload FROM pending_diffs"
        parameters: tuple = ()
        if run_id:
            query += " WHERE run_id = ?"
            parameters = (run_id,)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters += (limit,)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [PendingDiff.model_validate_json(row[0]) for row in rows]

    def update_pending_diff(
        self,
        diff_id: str,
        *,
        status: PendingDiffStatus,
        resolution: str | None = None,
    ) -> PendingDiff:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM pending_diffs WHERE diff_id = ?", (diff_id,)
            ).fetchone()
            if row is None:
                raise KeyError(diff_id)
            current = PendingDiff.model_validate_json(row[0])
            resolved_at = (
                datetime.now(UTC)
                if status in (PendingDiffStatus.ACCEPTED, PendingDiffStatus.REJECTED)
                else None
            )
            updated = current.model_copy(
                update={
                    "status": status,
                    "resolution": resolution,
                    "resolved_at": resolved_at,
                }
            )
            connection.execute(
                "UPDATE pending_diffs SET status = ?, payload = ?, updated_at = ? WHERE diff_id = ?",
                (status.value, updated.model_dump_json(), datetime.now(UTC).isoformat(), diff_id),
            )
        return updated

    def update_run(self, run: AgentRun) -> AgentRun:
        """Persist the full run payload (used for snapshot/diff bookkeeping)."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET status = ?, payload = ?, updated_at = ? WHERE run_id = ?",
                (run.status.value, run.model_dump_json(), datetime.now(UTC).isoformat(), run.run_id),
            )
        return run

    def claim_resume_unfinished(self, run_id: str) -> AgentRun:
        """Transition an unfinished run back to running (resume from checkpoint)."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            if AgentRunStatus.RUNNING not in _TRANSITIONS[current.status]:
                raise InvalidRunTransitionError(
                    f"invalid resume: {current.status.value} -> {AgentRunStatus.RUNNING.value}"
                )
            updated = current.model_copy(
                update={
                    "status": AgentRunStatus.RUNNING,
                    "finished_at": None,
                    "error_type": None,
                    "error_message": None,
                    "updated_at": datetime.now(UTC),
                }
            )
            connection.execute(
                "UPDATE agent_runs SET status = ?, payload = ?, updated_at = ? WHERE run_id = ?",
                (AgentRunStatus.RUNNING.value, updated.model_dump_json(), updated.updated_at.isoformat(), run_id),
            )
            self._insert_event(
                connection,
                updated,
                AgentEventType.RUN_STATUS,
                message="Run resumed from the unfinished checkpoint.",
                data={"status": AgentRunStatus.RUNNING.value},
            )
        return updated

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

    def recover_stale_runs(self) -> list[AgentRun]:
        """服务启动时收敛"孤儿"运行：RUNNING/RETRYING -> UNFINISHED(TIMEOUT)、
        CANCELLING -> CANCELLED、QUEUED -> UNFINISHED。worker 随进程消亡，
        任何 active 运行在重启后都无法继续推进，必须恢复后再手动继续。"""
        recovered: list[AgentRun] = []
        now = datetime.now(UTC)
        for run in self.list_runs(limit=10_000):
            if run.status == AgentRunStatus.CANCELLING:
                recovered.append(
                    self.transition(
                        run.run_id,
                        AgentRunStatus.CANCELLED,
                        message="Cancelled after restart.",
                        finished_at=now,
                    )
                )
            elif run.status == AgentRunStatus.QUEUED:
                recovered.append(
                    self.transition(
                        run.run_id,
                        AgentRunStatus.UNFINISHED,
                        error_type=AgentErrorType.TIMEOUT,
                        error_message="Interrupted before starting (restart).",
                        message="Run paused before execution (restart). Resume to continue.",
                        finished_at=now,
                    )
                )
            elif run.status in {
                AgentRunStatus.RUNNING,
                AgentRunStatus.RETRYING,
            }:
                recovered.append(
                    self.transition(
                        run.run_id,
                        AgentRunStatus.UNFINISHED,
                        error_type=AgentErrorType.TIMEOUT,
                        error_message="Interrupted by restart while running.",
                        message="Run paused (restart). Resume to continue.",
                        finished_at=now,
                    )
                )
        return recovered

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
        finished_at: datetime | None = None,
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
            update_fields: dict = {
                "status": status,
                "error_type": error_type,
                "error_message": error_message,
                "updated_at": datetime.now(UTC),
            }
            if finished_at is not None:
                update_fields["finished_at"] = finished_at
            updated = current.model_copy(update=update_fields)
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
                CREATE TABLE IF NOT EXISTS pending_diffs (
                    diff_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_attachments (
        attachment_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_agent_attachments_thread
        ON agent_attachments(thread_id, created_at);
    CREATE TABLE IF NOT EXISTS agent_threads (
        thread_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS agent_questions (
        question_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_agent_questions_run
        ON agent_questions(run_id, status, created_at);
    PRAGMA user_version=6;
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
                fallback_data = {
                    "attachments": [
                        {"attachment_id": attachment_id}
                        for attachment_id in dict.fromkeys(run.attachment_ids)
                    ]
                } if run.attachment_ids else {}
                existing_message = connection.execute(
                    "SELECT message_id, data FROM agent_messages WHERE run_id = ? AND role = ?",
                    (run.run_id, "user"),
                ).fetchone()
                if existing_message is None:
                    self._insert_message(
                        connection,
                        thread_id=run.thread_id,
                        run_id=run.run_id,
                        role="user",
                        content=run.input_message,
                        data=fallback_data,
                        update_existing=False,
                    )
                elif fallback_data:
                    try:
                        existing_data = json.loads(existing_message[1])
                    except (TypeError, json.JSONDecodeError):
                        existing_data = {}
                    if not isinstance(existing_data, dict):
                        existing_data = {}
                    existing_references = existing_data.get("attachments")
                    if not isinstance(existing_references, list):
                        existing_references = []
                    existing_ids = {
                        reference.get("attachment_id")
                        for reference in existing_references
                        if isinstance(reference, dict) and reference.get("attachment_id")
                    }
                    merged_references = list(existing_references)
                    merged_references.extend(
                        reference
                        for reference in fallback_data["attachments"]
                        if reference["attachment_id"] not in existing_ids
                    )
                    if merged_references != existing_references:
                        existing_data["attachments"] = merged_references
                        connection.execute(
                            "UPDATE agent_messages SET data = ? WHERE message_id = ?",
                            (json.dumps(existing_data, ensure_ascii=False), existing_message[0]),
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

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open one transaction-scoped connection and always release its handle.

        ``sqlite3.Connection`` commits or rolls back when used as a context
        manager, but it does not close itself. Explicitly closing here matters
        on Windows, where an uncollected connection keeps ``cellwiki.db`` locked.
        """

        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

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
        update_existing: bool = True,
    ) -> None:
        existing = connection.execute(
            "SELECT message_id FROM agent_messages WHERE run_id = ? AND role = ?",
            (run_id, role),
        ).fetchone()
        serialized_data = json.dumps(data, ensure_ascii=False, default=str)
        if existing and update_existing:
            connection.execute(
                "UPDATE agent_messages SET content = ?, data = ? WHERE message_id = ?",
                (content, serialized_data, existing[0]),
            )
            return
        if existing:
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
