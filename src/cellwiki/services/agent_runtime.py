# =============================================================================
# 简化 Agent 运行时 —— 工作区版（阶段 4）
# =============================================================================
# 生命周期：QUEUED -> RUNNING -> SUCCEEDED / FAILED / UNFINISHED / CANCELLED；
# 预算/超时进入 UNFINISHED（记录 checkpoint，可继续/恢复），失败可 retry。
# - 严格串行门禁：同时只允许 1 个 active run，新 run 请求返回 409。
# - pending diff：run 开始时记录 git 快照点；结束时该 run 的全部 commit 汇成
#   待确认 diff 持久化；accept / reject（逐个 revert run 内 commit，保留后续
#   commit）/ reopen 由运行时执行。
# - P4 审计：工具输入（label_args 白名单键）与输出（payload sha256）由运行时
#   Seam 记录，完整参数不离开本边界。
# =============================================================================

from __future__ import annotations

import hashlib
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, cast

from langchain_core.messages import AIMessage, ToolMessage

from cellwiki.agent.app import build_wiki_agent
from cellwiki.config import settings
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.pending_diff import PendingDiff, PendingDiffStatus
from cellwiki.domain.questions import PendingQuestion
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentEventType,
    AgentRun,
    AgentRunOutcome,
    AgentRunStatus,
    RunBudget,
    RunUsage,
)
from cellwiki.services.conversation_context import ConversationContextView
from cellwiki.services.prompt_layers import (
    build_layer_b_snapshot,
    build_r1_r5_block,
    compact_transcript,
    warn_if_narrow_window,
)
from cellwiki.agent.executor import clear_attachment_resolver, set_attachment_resolver
from cellwiki.services.attachment_store import AttachmentFileStore
from cellwiki.services.git_executor import GitCommandError, GitExecutor
from cellwiki.services.logging_context import log_context
from cellwiki.services.runtime_store import InvalidRunTransitionError, RuntimeStore

# 墙钟超时下限（秒）：避免测试中预算/超时语义被极小值绕过
MAX_RUN_SECONDS_FLOOR = 10

_TOOL_ACTIVITY_CODES = {
    "read_file": "reading_page",
    "write_file": "editing",
    "edit_file": "editing",
    "glob": "searching",
    "grep": "searching",
    "git": "versioning",
    "run_powershell": "running_tool",
    "lint_knowledge_base": "checking_quality",
    "submit_agent_answer": "completed",
}


class AgentRuntimeError(RuntimeError):
    """Base error for the simplified agent runtime."""


class AgentRunNotFoundError(AgentRuntimeError):
    """Raised when a run_id does not exist."""


class AgentRunInProgressError(AgentRuntimeError):
    """Raised by the strict serial gate when another run is active."""


class AgentBudgetExceeded(AgentRuntimeError):
    """Raised internally when a run exceeds its model-call budget."""


class AgentRetryLimitExceeded(AgentRuntimeError):
    """Raised internally when a run exceeds its retry budget."""


class _RunTimeoutError(AgentRuntimeError):
    """Raised internally when a run exceeds its wall-clock budget."""


# 兼容别名：API 仍在使用旧名（严格串行门禁语义）
AgentRuntimeBusyError = AgentRunInProgressError


def is_retryable_run(run: AgentRun) -> bool:
    """Whether a failed/unfinished run can be retried (system/provider errors only)."""
    if run.status not in {AgentRunStatus.FAILED, AgentRunStatus.UNFINISHED}:
        return False
    if run.retry_count >= run.budget.max_retries:
        return False
    return run.error_type in {
        AgentErrorType.SYSTEM,
        AgentErrorType.RATE_LIMIT,
        AgentErrorType.TIMEOUT,
    }


def classify_agent_error(error: Exception) -> AgentErrorType:
    """Map an adapter/provider exception to a stable error category."""
    message = str(error).lower()
    if isinstance(error, TimeoutError) or "timed out" in message or "timeout" in message:
        return AgentErrorType.TIMEOUT
    if "429" in message or "rate limit" in message or "quota" in message:
        return AgentErrorType.RATE_LIMIT
    if "authentication" in message or "api key" in message or "401" in message:
        return AgentErrorType.AUTHENTICATION
    if "budget" in message or "max_model_calls" in message:
        return AgentErrorType.BUDGET
    return AgentErrorType.SYSTEM


def _signal_payload(
    segment: str,
    message: str,
    metadata: dict[str, Any],
    *,
    model_call_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict[str, Any]:
    """Build the persisted, redacted event payload (P4 audit boundary)."""
    raw_data = {k: str(v)[:500] for k, v in metadata.items()}
    safe_keys = {
        "tool_call_id",
        "page_id",
        "query",
        "path",
        "file",
        "thread_id",
        "run_id",
        "status",
        "answer",
        "decision",
        "project_id",
        "model_name",
    }
    label_args = {k: v for k, v in raw_data.items() if k in safe_keys}
    payload = hashlib.sha256(
        f"{segment}\x00{message}\x00{raw_data}".encode("utf-8")
    ).hexdigest()
    return {
        "payload": payload,
        "label_args": label_args,
        "model_call_id": model_call_id,
        "token_usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


@dataclass
class _ConsumeOutcome:
    """Result of consuming one stream: terminal info + whether a question paused the run."""

    final_answer: str | None = None
    cancelled: bool = False
    question_pending: bool = False


@dataclass
class RuntimeSignal:
    """One normalized stream item passed from the adapter to the runtime."""

    type: AgentEventType
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    progress: int = 0
    model_call_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0


def _extract_final_answer(content: Any) -> str:
    """submit_agent_answer 的内容可能是 {"answer": ...} JSON 或普通文本。"""
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (ValueError, TypeError):
            return content
        if isinstance(parsed, dict) and isinstance(parsed.get("answer"), str):
            return parsed["answer"]
        return content
    if isinstance(content, dict) and isinstance(content.get("answer"), str):
        return content["answer"]
    return str(content)


def _noticed(event_type: AgentEventType) -> bool:
    """Whether the event should reach the desktop UI (avoid chat noise)."""
    return event_type in {
        AgentEventType.RUN_STATUS,
        AgentEventType.PROGRESS,
        AgentEventType.TOOL_STARTED,
        AgentEventType.TOOL_COMPLETED,
        AgentEventType.FINAL_RESPONSE,
        AgentEventType.TASK_CONFIRMATION_REQUIRED,
        AgentEventType.ERROR,
    }


def _interrupt_payload(value: Any) -> dict[str, Any]:
    """Extract the plain payload from langgraph's Interrupt object (nested config wrapper tolerated)."""
    payload = getattr(value, "value", value)
    if isinstance(payload, dict) and "value" in payload and "config" in payload:
        payload = payload["value"]
    return payload if isinstance(payload, dict) else {}


def _signals_from_interrupt(value: Any) -> list[RuntimeSignal]:
    """Turn one langgraph interrupt value into an ask_user_question confirmation signal."""
    payload = _interrupt_payload(value)
    question = str(payload.get("question") or "")[:2_000]
    if not question:
        return []
    options = [str(option)[:120] for option in (payload.get("options") or [])][:5]
    return [
        RuntimeSignal(
            type=AgentEventType.TASK_CONFIRMATION_REQUIRED,
            message=f"Waiting for the user: {question[:180]}",
            data={
                "interrupt": {
                    "question": question,
                    "options": options,
                    "required": bool(payload.get("required", True)),
                    "tool_call_id": str(payload.get("tool_call_id") or "") or None,
                }
            },
        )
    ]


def _signals_from_stream_item(
    item: tuple[str, tuple[Any, dict[str, Any]] | Any] | Any,
) -> list[RuntimeSignal]:
    """Translate one LangGraph/DeepAgents stream item into runtime signals."""
    responses: list[RuntimeSignal] = []
    if not isinstance(item, tuple) or len(item) < 2:
        return responses
    # LangGraph 子图流：(() , "messages"|"updates", payload) 三元组
    if len(item) == 3 and isinstance(item[1], str) and item[1] in {"messages", "updates"}:
        name, payload = item[1], item[2]
    else:
        name, payload = item[0], item[1]
    if name == "__interrupt__":
        # ask_user_question 挂起：langgraph 在 updates 流产生的 interrupt 层
        if isinstance(payload, (list, tuple)):
            payload = payload[0] if payload else None
        return _signals_from_interrupt(payload)

    if name == "messages":
        if not isinstance(payload, tuple) or not payload:
            return responses
        message = payload[0]
        if isinstance(message, AIMessage):
            tool_calls = getattr(message, "tool_calls", []) or []
            if tool_calls:
                tool_name = tool_calls[0].get("name", "tool")
                tool_call_id = tool_calls[0].get("id", "")
                responses.append(
                    RuntimeSignal(
                        type=AgentEventType.TOOL_STARTED,
                        message=f"{tool_name} started.",
                        data={"tool_name": tool_name, "tool_call_id": tool_call_id},
                    )
                )
            else:
                content = message.content or ""
                text = content if isinstance(content, str) else str(content)
                if text.strip():
                    responses.append(
                        RuntimeSignal(
                            type=AgentEventType.MESSAGE_DELTA,
                            message=text,
                            data={},
                        )
                    )
        elif isinstance(message, ToolMessage):
            tool_name = message.name or "tool"
            tool_call_id = message.tool_call_id or ""
            content = message.content or ""
            if tool_name == "submit_agent_answer":
                responses.append(
                    RuntimeSignal(
                        type=AgentEventType.FINAL_RESPONSE,
                        message=_extract_final_answer(content),
                        data={"tool_name": tool_name, "tool_call_id": tool_call_id},
                    )
                )
            else:
                responses.append(
                    RuntimeSignal(
                        type=AgentEventType.TOOL_COMPLETED,
                        message=content if isinstance(content, str) else str(content),
                        data={"tool_name": tool_name, "tool_call_id": tool_call_id},
                    )
                )
    elif name == "updates" and isinstance(payload, dict):
        for node_name, update in payload.items():
            if node_name == "__interrupt__":
                value = update
                if isinstance(value, (list, tuple)):
                    value = value[0] if value else None
                responses.extend(_signals_from_interrupt(value))
            elif node_name == "agent" and isinstance(update, dict):
                for key, value in update.items():
                    if key == "messages" and isinstance(value, list):
                        for message in value:
                            responses.extend(
                                _signals_from_stream_item(("messages", (message, {})))
                            )
    return responses


class _CancellationGate:
    """Small threading-safe cancellation gate (avoids asyncio in worker threads)."""

    def __init__(self) -> None:
        self._flag = False

    def set(self) -> None:
        self._flag = True

    def is_set(self) -> bool:
        return self._flag


class AgentRuntimeManager:
    """Serialize every agent run and own the lifecycle + approval boundary."""

    def __init__(
        self,
        project_root: Path,
        adapter: Any = None,
        *,
        max_retries: int = 2,
        seed: str | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.max_retries = max_retries
        self.seed = seed
        self.store = RuntimeStore(self.project_root)
        # 启动时收敛孤儿运行（重启窗口：running -> unfinished 可继续/恢复）
        self.store.recover_stale_runs()
        self.adapter = adapter
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="cellwiki-agent",
        )
        self._thread_lock = RLock()
        self._built_adapter: Any | None = None
        self._cancellations: dict[str, _CancellationGate] = {}
        self._running_run_id: str | None = None
        self._git: GitExecutor | None = None
        warn_if_narrow_window(
            settings.openai_model.casefold(), settings.agent_context_max_tokens
        )

    # ---- 公共生命周期 ----
    def start(
        self,
        thread_id: str,
        message: str,
        context: WikiAgentContext,
        budget: RunBudget | None = None,
        *,
        attachment_ids: list[str] | None = None,
    ) -> AgentRun:
        """Start exactly one run; reject any second active run (strict serial gate)."""
        active = self._ensure_single_active_run()
        if active is not None:
            raise AgentRunInProgressError(
                f"another agent run is active: {active.run_id} ({active.status.value})"
            )
        pending = [
            diff
            for diff in self.store.list_pending_diffs(limit=50)
            if diff.status == PendingDiffStatus.PENDING
        ]
        if pending:
            raise AgentRunInProgressError(
                f"a pending diff requires review before a new run: {pending[0].diff_id}"
            )
        run_id = _new_run_id()
        snapshot = self._git_snapshot()
        budget = budget or RunBudget(
            max_model_calls=settings.agent_max_tool_steps,
            max_runtime_seconds=max(settings.agent_run_max_seconds, MAX_RUN_SECONDS_FLOOR),
        )
        run = AgentRun(
            run_id=run_id,
            thread_id=thread_id,
            project_id=context.project_id,
            status=AgentRunStatus.QUEUED,
            input_message=message.strip()[:60_000],
            budget=budget,
            created_at=datetime.now(UTC),
            snapshot_commit=snapshot,
            attachment_ids=list(dict.fromkeys(attachment_ids or [])),
        )
        self.store.create_run(run)
        with self._thread_lock:
            self._cancellations[run_id] = _CancellationGate()
        self._executor.submit(
            self._execute, run_id, thread_id, message, context, budget
        )
        return run

    def retry(self, run_id: str, *, reason: str = "retry") -> AgentRun:
        """Retry a failed run with the same input message."""
        return self._claim_and_submit(run_id, AgentRunStatus.RETRYING, reason)

    def resume(self, run_id: str, *, reason: str = "resume") -> AgentRun:
        """Resume an unfinished run from its recorded checkpoint."""
        claimed = self.store.claim_resume_unfinished(run_id)
        with self._thread_lock:
            self._cancellations[claimed.run_id] = _CancellationGate()
        self._executor.submit(
            self._execute,
            claimed.run_id,
            claimed.thread_id,
            claimed.input_message,
            WikiAgentContext(project_id=claimed.project_id, thread_id=claimed.thread_id),
            claimed.budget,
        )
        return claimed

    def cancel(self, run_id: str) -> AgentRun:
        """Cancel at the next safe event boundary; unfinished runs cancel directly."""
        run = self.store.get_run(run_id)
        if run.status == AgentRunStatus.UNFINISHED:
            return self.store.finalize_run(
                run.run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.CANCELLED,
                    message="Unfinished run cancelled by the user.",
                ),
            )
        if run.status == AgentRunStatus.QUEUED:
            return self.store.finalize_run(
                run.run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.CANCELLED,
                    message="Queued run cancelled before execution started.",
                ),
            )
        if run.status in {AgentRunStatus.RUNNING, AgentRunStatus.RETRYING}:
            cancelled = self.store.transition(
                run_id,
                AgentRunStatus.CANCELLING,
                message="Cancellation requested; waiting for a safe boundary.",
            )
            with self._thread_lock:
                gate = self._cancellations.get(run_id)
                if gate is not None:
                    gate.set()
            return cancelled
        raise InvalidRunTransitionError(
            f"cannot cancel run {run_id}: status {run.status.value}"
        )

    def delete_thread(self, thread_id: str) -> int:
        """Delete runs, events, spans and pending diffs for one thread."""
        return self.store.delete_thread(thread_id)

    # ---- pending diff 审批 ----
    def accept_pending_diff(self, diff_id: str) -> PendingDiff:
        """Accept a run's diff: commits stay, decision is recorded."""
        return self.store.update_pending_diff(
            diff_id, status=PendingDiffStatus.ACCEPTED, resolution="accepted"
        )

    def reject_pending_diff(self, diff_id: str) -> PendingDiff:
        """Reject a run's diff: revert every run commit, newest-first."""
        diff = self.store.get_pending_diff(diff_id)
        if diff.status != PendingDiffStatus.PENDING:
            raise InvalidRunTransitionError(
                f"diff {diff_id} is already {diff.status.value}"
            )
        git = self._git_executor()
        if git is not None and diff.commits:
            git.revert_commits(diff.commits)
        return self.store.update_pending_diff(
            diff_id, status=PendingDiffStatus.REJECTED, resolution="rejected"
        )

    def reopen_pending_diff(self, diff_id: str) -> PendingDiff:
        """Reopen a resolved diff (commits remain in the repo either way)."""
        return self.store.update_pending_diff(
            diff_id, status=PendingDiffStatus.PENDING, resolution=None
        )

    # ---- 内部执行 ----
    def _execute(
        self,
        run_id: str,
        thread_id: str,
        message: str,
        context: WikiAgentContext,
        budget: RunBudget,
    ) -> None:
        try:
            with log_context(run_id=run_id, thread_id=thread_id):
                self._execute_bound(run_id, thread_id, message, context, budget)
        finally:
            clear_attachment_resolver()
            with self._thread_lock:
                if self._running_run_id == run_id:
                    self._running_run_id = None
                self._cancellations.pop(run_id, None)
            self._maybe_publish_pending_diff(run_id)

    def _execute_bound(
        self,
        run_id: str,
        thread_id: str,
        message: str,
        context: WikiAgentContext,
        budget: RunBudget,
    ) -> None:
        run = self.store.get_run(run_id)
        if run.status == AgentRunStatus.QUEUED:
            run = self.store.transition(
                run_id, AgentRunStatus.RUNNING, message="Run started."
            )
        elif run.status == AgentRunStatus.RETRYING:
            run = self.store.transition(
                run_id, AgentRunStatus.RUNNING, message="Retry started."
            )
        with self._thread_lock:
            self._running_run_id = run_id

        set_attachment_resolver(
            lambda attachment_id: self.resolve_attachment_path(run.thread_id, attachment_id)
        )
        adapter = self.adapter or self._built_adapter or _instantiate_agent(self.project_root)
        self._built_adapter = adapter
        started_at = time.monotonic()
        seen: set[tuple[str, AgentEventType]] = set()
        try:
            view = ConversationContextView(self.store)
            # 会话上下文先持久化当前用户消息，再交给适配器（conversation-first）
            self.store.append_message(
                thread_id=thread_id,
                run_id=run_id,
                role="user",
                content=message,
                data={"source": "agent_runtime"},
            )
            messages_in = view.build(
                thread_id=thread_id,
                current_run_id=run_id,
                current_content=message or "",
            )
            # 阶段 5：512K/80% 阈值压缩 -> 六类摘要 + 保留窗口 32K，并注入 R1-R5
            compacted = compact_transcript(
                messages_in,
                max_tokens=settings.agent_context_max_tokens,
                auto_compact_ratio=settings.agent_context_auto_compact_ratio,
                retained_tokens=settings.agent_context_retained_tokens,
            )
            if compacted.compacted:
                r1_r5 = build_r1_r5_block(
                    git_status=self._git_status_text(),
                    pending_question=None,
                    recent_lint=None,
                    run_goal=message,
                )
                messages_in = [
                    {
                        "role": "system",
                        "content": compacted.summary_text + "\n\n" + r1_r5,
                    },
                    *compacted.retained,
                ]
            # 阶段 5：Layer B run 动态快照（git 状态 + 打开页面元数据/大纲）
            layer_b = build_layer_b_snapshot(
                current_message=message,
                git_status=self._git_status_text(),
                open_page=self._open_page_snapshot(context.page_id),
                recent_transcript=self.store.list_context_messages(thread_id)[-4:],
            )
            if layer_b:
                messages_in = [
                    {"role": "system", "content": layer_b},
                    *messages_in,
                ]
            stream = self._open_stream(adapter, thread_id, messages_in, context)
            outcome = self._consume_stream(
                run_id,
                thread_id,
                stream,
                budget,
                started_at=started_at,
                seen=seen,
            )
            if outcome.question_pending:
                # ask_user_question 挂起：保持 WAITING_CONFIRMATION 直到用户回复；
                # answer_question() 以 Command(resume=answers) 续跑。
                try:
                    self._maybe_publish_pending_diff(run_id)
                except (GitCommandError, OSError):
                    pass
                return
            if outcome.final_answer:
                self.store.append_message(
                    thread_id=thread_id,
                    run_id=run_id,
                    role="assistant",
                    content=outcome.final_answer,
                    data={"source": "agent_runtime"},
                )
            if outcome.cancelled:
                self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.CANCELLED,
                        message="Run cancelled at a safe event boundary.",
                    ),
                )
            else:
                self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.SUCCEEDED,
                        message="Run completed.",
                    ),
                )
            # 尽早发布 pending diff（幂等：git 异常不影响运行结果）
            try:
                self._maybe_publish_pending_diff(run_id)
            except (GitCommandError, OSError):
                pass
        except _RunTimeoutError as error:
            self._finalize_unfinished(run_id, AgentErrorType.TIMEOUT, str(error))
        except AgentBudgetExceeded as error:
            self._finalize_unfinished(run_id, AgentErrorType.BUDGET, str(error))
        except AgentRetryLimitExceeded as error:
            self._finalize_unfinished(run_id, AgentErrorType.BUDGET, str(error))
        except Exception as error:  # noqa: BLE001 - 边界必须收敛所有异常
            self._finish_failed(run_id, error)

    def _consume_stream(
        self,
        run_id: str,
        thread_id: str,
        stream: Any,
        budget: RunBudget,
        *,
        started_at: float,
        seen: set[tuple[str, AgentEventType]],
    ) -> _ConsumeOutcome:
        """消费一条流：统计用量、收集最终回答、持久化挂起问题，返回结局。"""
        final_answer: str | None = None
        input_tokens = 0
        output_tokens = 0
        tool_calls_started = 0
        tool_calls_completed = 0
        steps_at_end = 0
        question_pending = False
        for segment, signals, steps in self._iterate_safe(
            stream, budget, started_at
        ):
            with self._thread_lock:
                gate = self._cancellations.get(run_id)
                if gate is not None and gate.is_set():
                    break
            for signal in signals:
                steps_at_end = steps
                input_tokens += signal.input_tokens
                output_tokens += signal.output_tokens
                if signal.type == AgentEventType.TOOL_STARTED:
                    tool_calls_started += 1
                if signal.type == AgentEventType.TOOL_COMPLETED:
                    tool_calls_completed += 1
                if signal.type == AgentEventType.FINAL_RESPONSE and final_answer is None:
                    final_answer = signal.message
                if signal.type == AgentEventType.TASK_CONFIRMATION_REQUIRED:
                    self._persist_question(run_id, thread_id, signal)
                    question_key: tuple[str, AgentEventType] = (segment, signal.type)
                    if question_key not in seen:
                        self.store.append_event(
                            run_id,
                            signal.type,
                            message=signal.message,
                            progress=signal.progress,
                            data=_signal_payload(
                                segment,
                                signal.message,
                                signal.data,
                                model_call_id=signal.model_call_id,
                            ),
                        )
                        seen.add(question_key)
                    question_pending = True
                    break
                key: tuple[str, AgentEventType] = (segment, signal.type)
                if key in seen:
                    continue
                if signal.type == AgentEventType.MESSAGE_DELTA:
                    seen.add(key)
                    continue
                self.store.append_event(
                    run_id,
                    signal.type,
                    message=signal.message,
                    progress=signal.progress,
                    data=_signal_payload(
                        segment,
                        signal.message,
                        signal.data,
                        model_call_id=signal.model_call_id,
                        input_tokens=signal.input_tokens,
                        output_tokens=signal.output_tokens,
                    ),
                )
                seen.add(key)
            if question_pending:
                break
        self.store.update_usage(
            run_id,
            RunUsage(
                model_calls=steps_at_end,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tool_calls=tool_calls_started,
                tool_calls_started=tool_calls_started,
                tool_calls_completed=tool_calls_completed,
                elapsed_seconds=time.monotonic() - started_at,
            ),
        )
        cancelled = False
        with self._thread_lock:
            gate = self._cancellations.get(run_id)
            cancelled = gate is not None and gate.is_set()
        return _ConsumeOutcome(
            final_answer=final_answer,
            cancelled=cancelled,
            question_pending=question_pending,
        )


    def _persist_question(
        self, run_id: str, thread_id: str, signal: RuntimeSignal
    ) -> None:
        """持久化挂起问题并转入 WAITING_CONFIRMATION（非终态，等待用户回复）。"""
        payload = (signal.data or {}).get("interrupt") or {}
        question = PendingQuestion(
            question_id=f"q_{uuid.uuid4().hex}",
            run_id=run_id,
            thread_id=thread_id,
            tool_call_id=payload.get("tool_call_id"),
            question=str(payload.get("question") or "")[:2_000],
            options=[str(option)[:120] for option in (payload.get("options") or [])][:5],
            required=bool(payload.get("required", True)),
        )
        self.store.save_pending_question(question)
        self.store.transition(
            run_id,
            AgentRunStatus.WAITING_CONFIRMATION,
            message="Waiting for the user to answer a question.",
            data={"question_id": question.question_id},
        )


    def _open_stream_resume(
        self, adapter: Any, thread_id: str, context: WikiAgentContext, *, answers: list[str]
    ) -> Any:
        """以用户答案续跑：graph adapter 用 Command(resume)，协议 adapter 用 execute(resume=)。"""
        if hasattr(adapter, "execute"):
            return adapter.execute(
                thread_id=thread_id,
                message=None,
                context=context,
                resume=answers,
            )
        from langgraph.types import Command

        return adapter.stream(
            Command(resume={"answers": answers}),
            config={"configurable": {"thread_id": thread_id}},
            stream_mode=["messages", "updates"],
            subgraphs=True,
        )


    def answer_question(
        self, run_id: str, answers: object, *, timed_out: bool = False
    ) -> dict[str, Any]:
        """回复挂起问题并续跑（5+1：string | array）；timed_out 则按超时收尾。"""
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        if run.status != AgentRunStatus.WAITING_CONFIRMATION:
            raise InvalidRunTransitionError(
                f"run {run_id} is not waiting for a question ({run.status.value})"
            )
        question = self.store.get_open_question(run_id)
        if question is None:
            raise ValueError(f"run {run_id} has no open question")
        if isinstance(answers, str):
            answers_list = [str(answers).strip()[:2_000]]
        elif answers is None:
            answers_list = []
        else:
            answers_list = [
                str(item).strip()[:2_000]
                for item in cast(Iterable[Any], answers)
            ]
        if question.get("required") and not answers_list:
            raise ValueError("required question needs at least one answer")
        if timed_out:
            self.store.answer_question(run_id, [], timed_out=True)
            self._finalize_unfinished(run_id, AgentErrorType.TIMEOUT, "question timed out")
            return self.store.get_run(run_id).model_dump(mode="json")  # type: ignore[union-attr]
        self.store.answer_question(run_id, answers_list)
        self.store.transition(
            run_id, AgentRunStatus.RUNNING, message="Answer received. Resuming the run."
        )
        thread_id = run.thread_id
        context = WikiAgentContext(project_id=run.project_id, thread_id=thread_id)
        adapter = self.adapter or self._built_adapter or _instantiate_agent(self.project_root)
        self._built_adapter = adapter
        with self._thread_lock:
            self._running_run_id = run_id
        set_attachment_resolver(
            lambda attachment_id: self.resolve_attachment_path(thread_id, attachment_id)
        )
        try:
            stream = self._open_stream_resume(adapter, thread_id, context, answers=answers_list)
            seen: set[tuple[str, AgentEventType]] = set()
            outcome = self._consume_stream(
                run_id,
                thread_id,
                stream,
                run.budget,
                started_at=time.monotonic(),
                seen=seen,
            )
            if outcome.question_pending:
                return self.store.get_run(run_id).model_dump(mode="json")  # type: ignore[union-attr]
            if outcome.final_answer:
                self.store.append_message(
                    thread_id=thread_id,
                    run_id=run_id,
                    role="assistant",
                    content=outcome.final_answer,
                    data={"source": "agent_runtime"},
                )
            if outcome.cancelled:
                self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.CANCELLED,
                        message="Run cancelled at a safe event boundary.",
                    ),
                )
            else:
                self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.SUCCEEDED,
                        message="Run completed.",
                    ),
                )
            try:
                self._maybe_publish_pending_diff(run_id)
            except (GitCommandError, OSError):
                pass
        except _RunTimeoutError as error:
            self._finalize_unfinished(run_id, AgentErrorType.TIMEOUT, str(error))
        except AgentBudgetExceeded as error:
            self._finalize_unfinished(run_id, AgentErrorType.BUDGET, str(error))
        except InvalidRunTransitionError:
            raise
        except Exception as error:
            self.store.append_event(
                run_id,
                AgentEventType.ERROR,
                message=f"Resume failed: {error}",
            )
            self._finalize_unfinished(run_id, AgentErrorType.SYSTEM, str(error))
        finally:
            clear_attachment_resolver()
            with self._thread_lock:
                if self._running_run_id == run_id:
                    self._running_run_id = None
                self._cancellations.pop(run_id, None)
        return self.store.get_run(run_id).model_dump(mode="json")  # type: ignore[union-attr]


    def _iterate_safe(
        self,
        stream: Iterable[Any],
        budget: RunBudget,
        started_at: float,
    ) -> Iterable[tuple[str, list[RuntimeSignal], int]]:
        """Bound the stream by model-call budget and wall-clock timeout."""
        model_calls = 0
        for item in stream:
            if time.monotonic() - started_at > max(
                budget.max_runtime_seconds, MAX_RUN_SECONDS_FLOOR
            ):
                raise _RunTimeoutError(
                    "run exceeded the wall-clock budget and was interrupted"
                )
            signals = (
                [item]
                if isinstance(item, RuntimeSignal)
                else _signals_from_stream_item(item)
            )
            if not signals:
                continue
            # 每个信号计量为一个"工具步"（agent_max_tool_steps 语义）
            model_calls += 1
            if model_calls > budget.max_model_calls:
                raise AgentBudgetExceeded(
                    f"run exceeded the model-call budget ({budget.max_model_calls})"
                )
            yield ("agent", signals, model_calls)

    # ---- 终结 ----
    def _finalize_unfinished(
        self, run_id: str, error_type: AgentErrorType, message: str
    ) -> AgentRun:

        # transition 一次写入状态 + 错误字段 + finished_at：任何时刻读到
        # UNFINISHED 的行都带完整信息；没有后续覆盖写，resume（claim）不会被
        # 迟到的写回退。
        return self.store.transition(
            run_id,
            AgentRunStatus.UNFINISHED,
            error_type=error_type,
            error_message=message[:2000],
            message=f"Run paused: {message}. Resume to continue.",
            data={"reason": "budget_or_timeout"},
            finished_at=datetime.now(UTC),
        )

    def _finish_failed(self, run_id: str, error: Exception) -> AgentRun:
        # 僵尸 worker 防改写：运行已被恢复/终结时不再落盘 FAILED
        current = self.store.get_run(run_id)
        if current.status not in {
            AgentRunStatus.RUNNING,
            AgentRunStatus.RETRYING,
        }:
            return current
        error_type = classify_agent_error(error)
        return self.store.finalize_run(
            run_id,
            AgentRunOutcome(
                status=AgentRunStatus.FAILED,
                message=str(error)[:2000],
                error_type=error_type,
                error_message=str(error)[:2000],
            ),
        )

    # ---- pending diff 发布 ----
    def _maybe_publish_pending_diff(self, run_id: str) -> None:
        """Collect the run's git commits into a pending diff, if any exist."""
        run = self.store.get_run(run_id)
        if run is None:
            return
        git = self._git_executor()
        if git is None:
            return
        try:
            # snapshot 为 None = run 前工作区尚无提交：取该 run 产出的首个 commit(s)
            commits = git.commits_since(run.snapshot_commit)
        except GitCommandError:
            return
        if not commits:
            return
        refs = frozenset({"HEAD"})
        if run.snapshot_commit is not None:
            refs = frozenset({run.snapshot_commit, "HEAD"})
        diff = git.diff_between(run.snapshot_commit, enabled_refs=refs)
        pending = PendingDiff(
            diff_id=f"diff_{run.run_id}",
            run_id=run.run_id,
            thread_id=run.thread_id,
            project_id=run.project_id,
            snapshot_commit=run.snapshot_commit,
            head_commit=git.current_head(),
            commits=commits,
            files=diff.files,
            insertions=diff.insertions,
            deletions=diff.deletions,
        )
        self.store.save_pending_diff(pending)
        self.store.update_run(
            run.model_copy(update={"pending_diff_id": pending.diff_id})
        )

    # ---- 内部工具 ----
    def _ensure_single_active_run(self) -> AgentRun | None:
        active_statuses = {
            AgentRunStatus.QUEUED,
            AgentRunStatus.RUNNING,
            AgentRunStatus.RETRYING,
            AgentRunStatus.UNFINISHED,
            AgentRunStatus.CANCELLING,
            AgentRunStatus.WAITING_CONFIRMATION,
        }
        for run in self.store.list_runs(limit=10_000):
            if run.status in active_statuses:
                return run
        return None

    def _claim_and_submit(
        self, run_id: str, status: AgentRunStatus, reason: str
    ) -> AgentRun:
        current = self._ensure_single_active_run()
        if current is not None and current.run_id != run_id:
            raise AgentRunInProgressError(
                f"another agent run is active: {current.run_id}"
            )
        if status == AgentRunStatus.RETRYING:
            claimed = self.store.claim_retry(run_id)
        else:
            raise InvalidRunTransitionError(f"unsupported claim status: {status}")
        with self._thread_lock:
            self._cancellations[run_id] = _CancellationGate()
        self._executor.submit(
            self._execute,
            claimed.run_id,
            claimed.thread_id,
            claimed.input_message,
            WikiAgentContext(project_id=claimed.project_id, thread_id=claimed.thread_id),
            claimed.budget,
        )
        return claimed

    def _open_stream(
        self,
        adapter: Any,
        thread_id: str,
        messages_in: list[dict[str, Any]],
        context: WikiAgentContext,
    ) -> Any:
        """Normalize adapters: protocol objects (execute) or LangGraph graphs (stream)."""
        if hasattr(adapter, "execute"):
            return adapter.execute(
                thread_id=thread_id, message=messages_in, context=context
            )
        # build_wiki_agent 返回的编译图：stream_mode=["messages","updates"]，
        # 输出交给 _signals_from_stream_item 归一化；输入必须是 dict 形状
        graph_input: Any = {"messages": messages_in}
        return adapter.stream(
            graph_input,
            config={"configurable": {"thread_id": thread_id}},
            stream_mode=["messages", "updates"],
            subgraphs=True,
        )

    def resolve_attachment_path(self, thread_id: str, attachment_id: str) -> Path | None:
        """Resolve one thread-scoped attachment file; None when not owned by the thread."""
        if self.store.get_attachment(thread_id, attachment_id) is None:
            return None
        return AttachmentFileStore(self.project_root).path_for(thread_id, attachment_id)

    def _git_status_text(self) -> str | None:
        """Short git status for Layer B / R1 (guarded; empty workspace tolerated)."""
        if not self.project_root.exists():
            return None
        try:
            from cellwiki.services.workspace import ensure_workspace

            ensure_workspace(self.project_root)
            status = GitExecutor(self.project_root).run("status", "--short")
            return (status or "")[:1_500] or None
        except Exception:
            return None

    def _open_page_snapshot(self, page_id: str | None) -> dict | None:
        """Layer B：打开页面仅取元数据 + 大纲（不注入整页内容）。"""
        if not page_id:
            return None
        try:
            from cellwiki.api.reader import WikiReader

            return WikiReader(self.project_root).read_page(page_id)
        except Exception:
            return None

    def _git_snapshot(self) -> str | None:
        git = self._git_executor()
        if git is None:
            return None
        try:
            return git.current_head() if git.has_commits() else None
        except GitCommandError:
            return None

    def _git_executor(self) -> GitExecutor | None:
        if self._git is None:
            if not (self.project_root / ".git").exists():
                return None
            self._git = GitExecutor(self.project_root)
        return self._git

    def close(self) -> None:
        self._executor.shutdown(wait=True)
        if self.adapter is not None and hasattr(self.adapter, "close"):
            self.adapter.close()


def _new_run_id() -> str:
    return f"run_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _instantiate_agent(project_root: Path) -> Any:
    """System-owned lazy agent instantiation (kept for tests and sidecars)."""
    return build_wiki_agent(project_root)
