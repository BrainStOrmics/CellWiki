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
from cellwiki.services.checkpoints import (
    delete_thread_checkpoints,
    has_run_checkpoint,
    latest_run_checkpoint_id,
)


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
    # RETRYING 也在后继里：is_retryable_run 与 run payload 的 retryable 都宣布中断态
    # 可重试，前端更把 retry 当成「继续」撞上 checkpoint_missing 之后的兜底出路。
    # ADR-0010 决策 5 只定 retry 的语义，没钉死"谁能 retry"。
    AgentRunStatus.UNFINISHED: {
        AgentRunStatus.RUNNING,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
        AgentRunStatus.RETRYING,
    },
    # CANCELLING 能落 UNFINISHED：主动停止是暂停而不是销毁（ADR-0007 决策 10 的
    # "用户停止后继续"），图状态还在载体里。CANCELLED 仍是后继——那是"放弃一个已
    # 中断的 run"，也是松开串行门禁的出口。
    AgentRunStatus.CANCELLING: {AgentRunStatus.CANCELLED, AgentRunStatus.FAILED, AgentRunStatus.UNFINISHED},
    AgentRunStatus.SUCCEEDED: set(),
    AgentRunStatus.REJECTED: set(),
    AgentRunStatus.CANCELLED: set(),
}


class InvalidRunTransitionError(RuntimeError):
    pass


class TerminalRunError(RuntimeError):
    """Raised when code attempts to append work after a finalized run."""


class SerialGateViolationError(RuntimeError):
    """决策 7：在同一个 BEGIN IMMEDIATE 事务里发现已有活动 run。

    检查与建 run 必须同事务，否则两个并发提交都能通过检查、各建一个 run，
    严格串行门禁形同虚设。由 agent_runtime 翻译成对外的 AgentRunInProgressError。
    """


class ThreadDeletionBlockedError(RuntimeError):
    """Raised when deleting a thread would destroy live work or an undecided verdict."""


# 仍占据严格串行闸门、或仍可被推进的 run 状态。删除线程会把这些行连同其
# worker 的写入目标一起抽走，因此删除护栏与闸门共用这一份定义。
# WAITING_APPROVAL 不在 `_ensure_single_active_run` 的集合里（它由"未判定
# 审批单元阻塞新 run"这条独立门禁覆盖），但对删除而言它同样是活动的。
ACTIVE_RUN_STATUSES: frozenset[AgentRunStatus] = frozenset(
    {
        AgentRunStatus.QUEUED,
        AgentRunStatus.RUNNING,
        AgentRunStatus.RETRYING,
        AgentRunStatus.CANCELLING,
        AgentRunStatus.UNFINISHED,
        AgentRunStatus.WAITING_CONFIRMATION,
        AgentRunStatus.WAITING_APPROVAL,
    }
)

# 会话标题的确定性派生参数（不接 LLM）：折叠空白后截 40 字符。
_THREAD_TITLE_MAX_CHARS = 40
_THREAD_TITLE_PLACEHOLDER = "新会话"


def _assert_run_transition(
    current: AgentRunStatus,
    target: AgentRunStatus,
    *,
    allowed_sources: frozenset[AgentRunStatus] | None = None,
    action: str = "run transition",
) -> None:
    """Single legality gate for every path that advances a run's status.

    ``allowed_sources`` narrows ``_TRANSITIONS`` for claim-style entry points
    (resume / retry / approval continuation) whose admission must be stricter
    than the table permits; omitting it means "whatever the table allows".
    New code that moves a run forward must call this instead of re-deriving the
    check, so a tightened gate cannot be bypassed by a second, stale copy.
    """

    if allowed_sources is not None:
        if current not in allowed_sources:
            raise InvalidRunTransitionError(
                f"invalid {action}: {current.value} -> {target.value}"
            )
        return
    if target != current and target not in _TRANSITIONS[current]:
        raise InvalidRunTransitionError(
            f"invalid {action}: {current.value} -> {target.value}"
        )


def _derive_thread_title(message: str) -> str:
    """Collapse whitespace, truncate to 40 chars, fall back to the placeholder."""
    collapsed = " ".join(str(message or "").split())
    if not collapsed:
        return _THREAD_TITLE_PLACEHOLDER
    return collapsed[:_THREAD_TITLE_MAX_CHARS]


class RuntimeStore:
    """Deep persistence module: schema, transitions, sequencing, and atomic event append live here."""

    def __init__(self, project_root: Path):
        # ADR-0010 决策 11/12：checkpoint 载体与运行库同在 data/runtime 下，
        # 删线程时要按 run 作用域键级联删掉它，因此这里记住工作区根。
        self.project_root = Path(project_root).resolve()
        self.path = self.project_root / "data" / "runtime" / "cellwiki.db"
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
            self._insert_run(connection, run, message_data=message_data)
        return run

    def create_run_if_idle(
        self,
        run: AgentRun,
        *,
        request_id: str | None = None,
        active_statuses: frozenset[AgentRunStatus] = ACTIVE_RUN_STATUSES,
        user_message_data: dict[str, Any] | None = None,
    ) -> tuple[AgentRun, bool]:
        """ADR-0010 决策 7：把"查无活动 run + 建 run"合并进同一 ``BEGIN IMMEDIATE``。

        返回 ``(run, replayed)``。检查与写入同事务是关键：分开做的话两个并发提交
        都能通过检查、各建一个 run，严格串行门禁与幂等门同时失效。命中已有
        ``request_id`` 时返回既有 run 且 ``replayed=True``，调用方仍应回 202。
        """
        message_data = user_message_data if user_message_data is not None else {}
        if user_message_data is None and run.attachment_ids:
            message_data = {
                "attachments": [
                    {"attachment_id": attachment_id}
                    for attachment_id in dict.fromkeys(run.attachment_ids)
                ]
            }
        active_values = sorted(status.value for status in active_statuses)
        placeholders = ", ".join("?" for _ in active_values)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if request_id:
                existing = connection.execute(
                    "SELECT payload FROM agent_runs WHERE request_id = ?", (request_id,)
                ).fetchone()
                if existing is not None:
                    return AgentRun.model_validate_json(existing[0]), True
            blocker = connection.execute(
                f"SELECT run_id, status FROM agent_runs WHERE status IN ({placeholders}) "
                "ORDER BY updated_at DESC LIMIT 1",
                active_values,
            ).fetchone()
            if blocker is not None:
                raise SerialGateViolationError(
                    f"another agent run is active: {blocker[0]} ({blocker[1]})"
                )
            self._insert_run(
                connection, run, message_data=message_data, request_id=request_id
            )
        return run, False

    def _insert_run(
        self,
        connection: sqlite3.Connection,
        run: AgentRun,
        *,
        message_data: dict[str, Any],
        request_id: str | None = None,
    ) -> None:
        """Write one run row plus its queued event and user message, in the open transaction."""
        # Keep the registry complete at the storage boundary: the history list
        # reads agent_threads, so a run whose thread was never registered would
        # make that conversation invisible and unreachable again.
        connection.execute(
            "INSERT OR IGNORE INTO agent_threads(thread_id, created_at) VALUES (?, ?)",
            (run.thread_id, run.created_at.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO agent_runs(run_id, thread_id, status, payload, updated_at, request_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.thread_id,
                run.status.value,
                run.model_dump_json(),
                run.updated_at.isoformat(),
                request_id if request_id is not None else run.request_id,
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

    def save_pending_question_and_transition(
        self,
        question: Any,
        *,
        message: str,
        data: dict | None = None,
    ) -> dict:
        """Atomically expose a question and move its run to WAITING_CONFIRMATION."""
        from cellwiki.domain.questions import PendingQuestion

        if not isinstance(question, PendingQuestion):
            question = PendingQuestion.model_validate(question)
        payload = question.model_dump_json()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (question.run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(question.run_id)
            current = AgentRun.model_validate_json(row[0])
            target = AgentRunStatus.WAITING_CONFIRMATION
            _assert_run_transition(current.status, target)
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
            now = datetime.now(UTC)
            updated = current.model_copy(update={"status": target, "updated_at": now})
            connection.execute(
                "UPDATE agent_runs SET status = ?, payload = ?, updated_at = ? WHERE run_id = ?",
                (target.value, updated.model_dump_json(), now.isoformat(), question.run_id),
            )
            if target != current.status:
                self._insert_event(
                    connection,
                    updated,
                    AgentEventType.RUN_STATUS,
                    message=message,
                    data={"status": target.value, **(data or {})},
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

    def list_threads(self, *, limit: int = 50) -> list[dict]:
        """Return registry entries, most recently active first.

        Zero-run threads are included on purpose: a conversation allocated by the
        desktop "+" button must stay selectable before its first run exists, which
        is exactly the case the run-derived history list could not represent.
        Recency is derived from the newest run instead of a registry counter, so no
        run write path has to maintain session bookkeeping.
        """

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    t.thread_id,
                    t.title,
                    t.created_at,
                    (SELECT COUNT(*) FROM agent_runs r
                      WHERE r.thread_id = t.thread_id) AS run_count,
                    (SELECT r.run_id FROM agent_runs r
                      WHERE r.thread_id = t.thread_id
                      ORDER BY r.updated_at DESC, r.run_id LIMIT 1) AS latest_run_id,
                    (SELECT r.status FROM agent_runs r
                      WHERE r.thread_id = t.thread_id
                      ORDER BY r.updated_at DESC, r.run_id LIMIT 1) AS latest_status,
                    MAX(t.created_at, COALESCE(
                        (SELECT MAX(r.updated_at) FROM agent_runs r
                          WHERE r.thread_id = t.thread_id),
                        t.created_at
                    )) AS updated_at
                FROM agent_threads t
                ORDER BY updated_at DESC, t.thread_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "thread_id": row[0],
                "title": row[1],
                "created_at": row[2],
                "updated_at": row[6],
                "run_count": int(row[3]),
                "latest_run_id": row[4],
                "latest_status": row[5],
            }
            for row in rows
        ]

    def _ensure_thread_registry(self, connection: sqlite3.Connection) -> None:
        """Upgrade the two-column ``agent_threads`` table into a real registry.

        SQLite has no ``ADD COLUMN IF NOT EXISTS``, so the live column list decides.
        Databases created before the registry existed can hold runs without an
        identity row; re-registering them keeps the history list complete. The
        backfilled ``created_at`` uses the earliest known run activity because
        ``agent_runs`` stores its creation time inside the payload, and ordering
        already prefers the newest run. Both steps run on every start and must
        stay idempotent.
        """

        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(agent_threads)")
        }
        if "title" not in columns:
            connection.execute("ALTER TABLE agent_threads ADD COLUMN title TEXT")
        connection.execute(
            """
            INSERT OR IGNORE INTO agent_threads(thread_id, created_at)
            SELECT r.thread_id, MIN(r.updated_at) FROM agent_runs r
            WHERE NOT EXISTS (
                SELECT 1 FROM agent_threads t WHERE t.thread_id = r.thread_id
            )
            GROUP BY r.thread_id
            """
        )

    def _ensure_run_idempotency_schema(self, connection: sqlite3.Connection) -> None:
        """ADR-0010 决策 7 + 裁决 #13：幂等键落在内联守卫 ALTER，不走 Alembic。

        直连建库路径（测试与 ``scripts/serve_e2e.py``）不会跑 Alembic，只补 revision
        会让这些库静默缺列，幂等门形同虚设。SQLite 的 ``ADD COLUMN`` 不能带 UNIQUE，
        唯一性由紧随其后的部分唯一索引承担；NULL 不参与唯一性判定，因此升级前的
        既有 run 可以全部留空。
        """

        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(agent_runs)")
        }
        if "request_id" not in columns:
            connection.execute("ALTER TABLE agent_runs ADD COLUMN request_id TEXT")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_runs_request_id "
            "ON agent_runs(request_id) WHERE request_id IS NOT NULL"
        )

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

    def mark_attachment_promoted(
        self,
        thread_id: str,
        attachment_id: str,
        source_id: str,
    ) -> dict | None:
        """Record that an attachment was promoted into raw/<source_id>/."""
        record = self.get_attachment(thread_id, attachment_id)
        if record is None:
            return None
        from cellwiki.domain.attachments import ThreadAttachment

        record["promoted_source_id"] = source_id
        attachment = ThreadAttachment.model_validate(record)
        self.save_attachment(attachment)
        return attachment.to_payload()

    def delete_attachments_for_thread(self, thread_id: str) -> int:
        """Delete every attachment record for a thread; returns the count removed."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM agent_attachments WHERE thread_id = ?", (thread_id,)
            )
        return cursor.rowcount

    def delete_attachment(self, thread_id: str, attachment_id: str) -> bool:
        """Delete one thread-scoped attachment record; False when it is not owned."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM agent_attachments WHERE thread_id = ? AND attachment_id = ?",
                (thread_id, attachment_id),
            )
        return cursor.rowcount > 0

    def attachment_was_sent(self, thread_id: str, attachment_id: str) -> bool:
        """Whether a run in this thread already consumed the attachment.

        已随消息发出的附件不可"撤回"：composer 的删除动作必须报冲突，而不是
        悄悄把 run 记录里的引用变成悬空 ID。
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM agent_runs WHERE thread_id = ?", (thread_id,)
            ).fetchall()
        for row in rows:
            try:
                run = AgentRun.model_validate_json(row[0])
            except (TypeError, ValueError):
                continue
            if attachment_id in run.attachment_ids:
                return True
        return False

    def delete_thread(self, thread_id: str) -> int:
        """Delete all product records for a thread and return its run count.

        护栏：存在活动 run 或未判定审批单元时拒绝删除。没有它，删线程就是绕过
        阻断式审批的后门（待确认 diff 直接消失），也会把正在执行的 worker 的
        写入目标一起抽走。错误里点名每个阻塞者，调用方据此给出可操作提示。
        """
        active_values = frozenset(status.value for status in ACTIVE_RUN_STATUSES)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_rows = connection.execute(
                "SELECT run_id, status FROM agent_runs WHERE thread_id = ?",
                (thread_id,),
            ).fetchall()
            blockers = [
                f"run {row[0]} is {row[1]}"
                for row in run_rows
                if str(row[1]) in active_values
            ]
            blockers.extend(
                f"pending diff {row[0]} is undecided"
                for row in connection.execute(
                    "SELECT diff_id FROM pending_diffs WHERE thread_id = ? AND status = ?",
                    (thread_id, PendingDiffStatus.PENDING.value),
                ).fetchall()
            )
            if blockers:
                raise ThreadDeletionBlockedError(
                    f"thread {thread_id} cannot be deleted: " + "; ".join(blockers)
                )
            run_count = len(run_rows)
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
        # ADR-0010 决策 11：图状态是不可重建的持久数据，删线程必须级联删掉它，
        # 否则删除承诺只覆盖了运行库。放在闸门之后、事务之外：载体是独立文件。
        delete_thread_checkpoints(self.project_root, thread_id)
        return int(run_count)

    # ---- 待确认 diff 持久化（阶段 4；审批单元 = 一行一次判定）----
    def save_pending_diff(self, diff: PendingDiff) -> PendingDiff:
        """Insert a new approval unit, or refresh one that is still pending.

        已判定（accepted/rejected）的行是只写一次的历史：任何复用同一 diff_id 的
        重发布都必须失败，而不是静默把判定结果覆盖回 pending。未判定行的就地刷新
        保留原 created_at，使单元顺序（按 created_at 排序）稳定。
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, payload FROM pending_diffs WHERE diff_id = ?",
                (diff.diff_id,),
            ).fetchone()
            if row is not None:
                if row[0] != PendingDiffStatus.PENDING.value:
                    raise InvalidRunTransitionError(
                        f"diff {diff.diff_id} is already {row[0]} and cannot be republished"
                    )
                diff = diff.model_copy(
                    update={
                        "created_at": PendingDiff.model_validate_json(row[1]).created_at
                    }
                )
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
        return diff

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
        data: dict[str, Any] | None = None,
    ) -> PendingDiff:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM pending_diffs WHERE diff_id = ?", (diff_id,)
            ).fetchone()
            if row is None:
                raise KeyError(diff_id)
            current = PendingDiff.model_validate_json(row[0])
            if (
                current.status != PendingDiffStatus.PENDING
                and status == PendingDiffStatus.PENDING
            ):
                # 已判定记录只写一次：不存在"重新打开回 pending"的状态回退。
                raise InvalidRunTransitionError(
                    f"diff {diff_id} is already {current.status.value} and cannot be reopened"
                )
            resolved_at = current.resolved_at
            if (
                status in (PendingDiffStatus.ACCEPTED, PendingDiffStatus.REJECTED)
                and resolved_at is None
            ):
                resolved_at = datetime.now(UTC)
            updates: dict[str, Any] = {
                "status": status,
                "resolution": resolution,
                "resolved_at": resolved_at,
            }
            if data is not None:
                updates["data"] = {**(current.data or {}), **data}
            updated = current.model_copy(update=updates)
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
        """Transition an unfinished run back to running (resume from checkpoint).

        准入只接受 ``UNFINISHED``。这里曾按 ``RUNNING in _TRANSITIONS[current]``
        判定，而 ``QUEUED`` / ``WAITING_CONFIRMATION`` / ``WAITING_APPROVAL`` 三者
        的后继集合都含 ``RUNNING``，于是"待确认 diff 尚未判定"也能被 resume 拉回
        RUNNING —— 审批门禁的绕过路径。挂起问题的续跑走 ``answer_question``，
        审批续跑走 ``claim_resume``，两者都不经过这里。
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            _assert_run_transition(
                current.status,
                AgentRunStatus.RUNNING,
                allowed_sources=frozenset({AgentRunStatus.UNFINISHED}),
                action="resume",
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

    def thread_usage_summary(self, thread_id: str) -> dict[str, int | float]:
        """Aggregate durable run usage for one thread (read-only account book)."""
        runs = self.list_runs(thread_id=thread_id, limit=1000)
        total_input = sum(run.usage.input_tokens for run in runs)
        total_output = sum(run.usage.output_tokens for run in runs)
        total_cached = sum(run.usage.cached_input_tokens for run in runs)
        return {
            "run_count": len(runs),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cached_input_tokens": total_cached,
            "avg_cache_hit_rate": round(total_cached / total_input, 4) if total_input > 0 else 0.0,
        }

    def recover_stale_runs(self, *, graph_state_durable: bool = True) -> list[AgentRun]:
        """服务启动时收敛"孤儿"运行：RUNNING/RETRYING -> UNFINISHED(TIMEOUT)、
        CANCELLING -> CANCELLED、QUEUED -> UNFINISHED。worker 随进程消亡，
        任何 active 运行在重启后都无法继续推进，必须恢复后再手动继续。

        ``graph_state_durable`` 为假（协议型 adapter，没有图状态）时不动
        WAITING_CONFIRMATION：它的挂起状态归外部服务，本库无从判断是否还在。
        """
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
                converged = self.transition(
                    run.run_id,
                    AgentRunStatus.UNFINISHED,
                    error_type=AgentErrorType.TIMEOUT,
                    error_message="Interrupted by restart while running.",
                    message="Run paused (restart). Resume to continue.",
                    finished_at=now,
                )
                # 决策 4（2026-09-07 修订）：字段回写只发生在流关闭/分段边界，进程被
                # 硬杀时钩子没机会跑，于是字段停在 NULL 而载体里图状态完好。启动收敛是
                # 唯一无竞争的回填时机——manager 在构造执行器之前就调本方法。续跑闸门
                # 只问存在性、不读该字段，回填是为了兑现决策 4"成为可查询字段"的承诺。
                if not converged.checkpoint_id:
                    backfilled = latest_run_checkpoint_id(
                        self.project_root, converged.thread_id, converged.run_id
                    )
                    if backfilled:
                        converged = self.set_run_checkpoint(converged.run_id, backfilled)
                recovered.append(converged)
            elif run.status == AgentRunStatus.WAITING_CONFIRMATION and graph_state_durable:
                # 决策 10：挂在提问上的 run 重启后仍停在 WAITING_CONFIRMATION。
                # checkpoint 还在就原样留着，用户直接作答即可续跑；丢了就关掉未回答
                # 的问题并落到 UNFINISHED，让"继续"按决策 4 明确拒绝并要求重发，
                # 而不是在空图上静默 Command(resume=...)。
                # 决策 4（2026-09-07 修订）：判定只看载体，不再以字段为空短路——硬杀
                # 同样会让这里的字段停在 NULL，短路会白白关掉一个其实还能作答的问题。
                if has_run_checkpoint(self.project_root, run.thread_id, run.run_id):
                    if not run.checkpoint_id:
                        backfilled = latest_run_checkpoint_id(
                            self.project_root, run.thread_id, run.run_id
                        )
                        if backfilled:
                            self.set_run_checkpoint(run.run_id, backfilled)
                    continue
                self.answer_question(run.run_id, [], timed_out=True)
                recovered.append(
                    self.transition(
                        run.run_id,
                        AgentRunStatus.UNFINISHED,
                        error_type=AgentErrorType.TIMEOUT,
                        error_message=(
                            "Question state was lost across a restart; "
                            "resend the message to start a new run."
                        ),
                        message="Question lost on restart. Resend the message to continue.",
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
            _assert_run_transition(current.status, status)
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

    def set_run_checkpoint(self, run_id: str, checkpoint_id: str | None) -> AgentRun:
        """ADR-0010 决策 4：每段流结束时写回最新 checkpoint 标识。

        这是字段回写而不是生命周期推进，因此不走 ``_assert_run_transition``、
        也不产生事件。写回后 ``checkpoint_id`` 成为可查询字段：为空的 run
        在可恢复态下走显式失败，禁止在空图上静默续跑。
        """

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            updated = current.model_copy(
                update={"checkpoint_id": checkpoint_id, "updated_at": datetime.now(UTC)}
            )
            connection.execute(
                "UPDATE agent_runs SET payload = ?, updated_at = ? WHERE run_id = ?",
                (updated.model_dump_json(), updated.updated_at.isoformat(), run_id),
            )
        return updated

    def update_usage(
        self, run_id: str, usage: RunUsage, *, accumulate: bool = False
    ) -> AgentRun:
        """Persist run usage; ``accumulate`` sums it into the lifetime totals.

        Every stream segment (initial submit, budget resume, retry) reports only
        its own counters, so overwriting would drop all but the last segment.
        """

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            merged = _merge_usage(current.usage, usage) if accumulate else usage
            updated = current.model_copy(
                update={"usage": merged, "updated_at": datetime.now(UTC)}
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
                # finished_at 非空不等于"真终态"：预算/超时暂停写成 unfinished 的 run
                # 之后仍可 resume，也必须仍可 cancel（否则松开串行门的唯一入口会 500）。
                # 真终态（succeeded/rejected/cancelled）的后继集合为空，交给下面的
                # _TRANSITIONS 合法性检查拦截。
                if not _TRANSITIONS[current.status]:
                    raise InvalidRunTransitionError(
                        f"run already finalized as {current.status.value}"
                    )
            if outcome.status != current.status:
                _assert_run_transition(current.status, outcome.status)

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
            _assert_run_transition(
                current.status,
                AgentRunStatus.RUNNING,
                allowed_sources=frozenset({AgentRunStatus.WAITING_APPROVAL}),
                action="approval continuation",
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
            _assert_run_transition(
                current.status,
                AgentRunStatus.RUNNING,
                allowed_sources=frozenset({AgentRunStatus.WAITING_CONFIRMATION}),
                action="task confirmation",
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
        """Atomically increment retry accounting and claim the retry slot.

        准入是 ``FAILED`` 与 ``UNFINISHED``。后者不是放松安全，是与既有意图对齐：
        ``is_retryable_run`` 对 unfinished+{system,rate_limit,timeout} 返回真、run
        payload 因此给 ``retryable: true``，前端更把 retry 当成「继续」撞上
        ``checkpoint_missing`` 之后唯一的兜底出路。只放行 FAILED 时那条出路是死的
        ——用户点「重试」必然 409，等于没有兜底。ADR-0010 决策 5 只定 retry 的语义
        （同 run_id、先删状态键、从有界 transcript 重放），没有钉死"谁能 retry"。
        """

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            current = AgentRun.model_validate_json(row[0])
            _assert_run_transition(
                current.status,
                AgentRunStatus.RETRYING,
                allowed_sources=frozenset(
                    {AgentRunStatus.FAILED, AgentRunStatus.UNFINISHED}
                ),
                action="retry",
            )
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
        allow_terminal: bool = False,
    ) -> AgentEvent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = AgentRun.model_validate_json(row[0])
            if run.finished_at is not None and not allow_terminal:
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
        created_at TEXT NOT NULL,
        title TEXT
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
    PRAGMA user_version=7;
                """
            )
            self._ensure_thread_registry(connection)
            self._ensure_run_idempotency_schema(connection)

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
    def _apply_thread_title(
        connection: sqlite3.Connection, thread_id: str, content: str
    ) -> None:
        """Set the conversation title once, deterministically, from its first user message.

        只在标题为空时写入：历史列表的标签不能随对话漂移，也不能被后续消息改名。
        """
        connection.execute(
            "UPDATE agent_threads SET title = ? "
            "WHERE thread_id = ? AND (title IS NULL OR title = '')",
            (_derive_thread_title(content), thread_id),
        )

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
        if role == "user":
            RuntimeStore._apply_thread_title(connection, thread_id, content)
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


def _merge_usage(base: RunUsage, add: RunUsage) -> RunUsage:
    """Sum one stream segment's usage into the run's lifetime totals.

    ``ttft_ms`` keeps the first observed value (the run's first model call),
    not a sum; every other field is cumulative work actually performed.
    """

    return RunUsage(
        model_calls=base.model_calls + add.model_calls,
        input_tokens=base.input_tokens + add.input_tokens,
        output_tokens=base.output_tokens + add.output_tokens,
        cached_input_tokens=base.cached_input_tokens + add.cached_input_tokens,
        cache_creation_input_tokens=base.cache_creation_input_tokens
        + add.cache_creation_input_tokens,
        estimated_cost_usd=base.estimated_cost_usd + add.estimated_cost_usd,
        tool_calls=base.tool_calls + add.tool_calls,
        tool_calls_started=base.tool_calls_started + add.tool_calls_started,
        tool_calls_completed=base.tool_calls_completed + add.tool_calls_completed,
        tool_calls_failed=base.tool_calls_failed + add.tool_calls_failed,
        tool_calls_cancelled=base.tool_calls_cancelled + add.tool_calls_cancelled,
        ttft_ms=base.ttft_ms if base.ttft_ms is not None else add.ttft_ms,
        elapsed_seconds=base.elapsed_seconds + add.elapsed_seconds,
        read_chars=base.read_chars + add.read_chars,
        read_tokens=base.read_tokens + add.read_tokens,
    )


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
