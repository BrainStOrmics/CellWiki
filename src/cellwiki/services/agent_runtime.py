# =============================================================================
# 智能体运行时 —— 持久化智能体执行和桌面产品的事件适配
# =============================================================================

"""Durable Agent execution and stable event adaptation for the desktop product."""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Protocol

from filelock import FileLock, Timeout
from pydantic import TypeAdapter

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from cellwiki.config import settings
from cellwiki.domain.contracts import ApprovalDecision, AgentAnswer, WikiAgentContext
from cellwiki.domain.memory import MemoryCandidate, MemoryKind
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentEventType,
    AgentRun,
    AgentRunOutcome,
    AgentSpan,
    AgentRunStatus,
    RunBudget,
    RunUsage,
)
from cellwiki.domain.tasks import AgentTask
from cellwiki.services.runtime_store import InvalidRunTransitionError, RuntimeStore
from cellwiki.services.approvals import ApprovalRepository
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.central_writer import CentralWriter
from cellwiki.services.conversation_context import ConversationContextView
from cellwiki.services.memory import MemoryStore
from cellwiki.services.logging_context import log_context
from cellwiki.services.operations import (
    CancellationRegistry,
    OperationCancelled,
    bind_agent_run,
)
from cellwiki.services.task_router import TaskRouter
from cellwiki.services.page_query import PageQueryExecutionAdapter, PageQueryRouter
from cellwiki.services.agent_runtime_types import AgentInput
from cellwiki.services.typed_tasks import TypedTaskExecutor
from cellwiki.services.quality import inspect_projection
from cellwiki.services.pipeline import KnowledgePipelineHarness


# ---------------------------------------------------------------------------
# RuntimeSignal —— 运行时信号
# 将 Deep Agents/LangGraph 输出的原始块转换为稳定的运行时信号值，
# 供桌面端 UI 消费。包含事件类型、消息、进度、token 用量等字段。
# 所有计算相关的字段（input_tokens, output_tokens, tool_calls）都在
# 信号级别累加，避免下游重复计算。
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RuntimeSignal:
    type: AgentEventType          # 事件类型（工具调用、消息增量、审批等）
    message: str = ""             # 人类可读的描述
    progress: int | None = None   # 进度百分比（0-100）
    data: dict[str, Any] = field(default_factory=dict)  # 附加数据
    model_call_id: str | None = None  # 模型调用 ID，用于去重
    input_tokens: int = 0         # 本次信号的输入 token 数
    output_tokens: int = 0        # 本次信号的输出 token 数
    tool_calls: int = 0           # 本次信号的工具调用次数


# ---------------------------------------------------------------------------
# AgentExecutionAdapter —— 智能体执行适配器协议
# 抽象接口，将持久化的 CellWiki 运行与具体的 Agent 框架实现解耦。
# 目前只有 DeepAgentsExecutionAdapter 一个实现，
# 未来可以替换为其他框架适配器。
# ---------------------------------------------------------------------------
class AgentExecutionAdapter(Protocol):
    """Execution seam separating persistent CellWiki runs from one Agent framework adapter."""

    def execute(
        self,
        *,
        thread_id: str,
        message: AgentInput,
        context: WikiAgentContext,
    ) -> Iterable[RuntimeSignal]: ...

    def close(self) -> None: ...

    def delete_thread(self, thread_id: str) -> None: ...


class AgentRuntimeBusyError(RuntimeError):
    """Raised when another process owns the project's Agent runtime."""


# ---------------------------------------------------------------------------
# DeepAgentsExecutionAdapter —— Deep Agents/LangGraph 执行适配器
# 将 Deep Agents 框架的流式输出转换为稳定的 RuntimeSignal。
# 使用 SQLite 检查点器实现状态持久化，支持中断恢复。
# 线程安全：使用 _execution_lock 序列化图访问，避免并发游标争用，
# 同时允许 Product API 请求和 SSE 读取并行执行。
# ---------------------------------------------------------------------------
class DeepAgentsExecutionAdapter:
    """Translate Deep Agents/LangGraph chunks into stable RuntimeSignal values."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        # 检查点 SQLite 数据库路径
        checkpoint_path = self.project_root / "data" / "runtime" / "checkpoints.sqlite"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        # 创建 SQLite 连接，check_same_thread=False 允许跨线程访问
        self.connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection)
        self.checkpointer.setup()
        self._graph = None                        # 延迟加载的编译图
        self._graph_lock = threading.Lock()        # 图加载的互斥锁
        self._execution_lock = threading.Lock()    # 图执行的序列化锁

    # 执行智能体图，返回 RuntimeSignal 迭代器
    def execute(
        self,
        *,
        thread_id: str,
        message: AgentInput,
        context: WikiAgentContext,
    ) -> Iterable[RuntimeSignal]:
        graph = self._get_graph()
        # 将输入消息转换为图可接受的格式
        graph_input: Any
        if message is None or isinstance(message, Command):
            # None 表示从检查点恢复，Command 用于中断恢复
            graph_input = message
        elif isinstance(message, list):
            graph_input = {"messages": message}
        else:
            # 普通字符串消息包装为 LangChain 消息格式
            graph_input = {"messages": [{"role": "user", "content": message}]}
        # SqliteSaver 拥有一个连接，序列化图访问避免并发游标争用，
        # 同时仍允许 Product API 请求和 SSE 读取并行执行
        with self._execution_lock:
            # 流式执行图，同时获取消息更新和状态更新
            stream = graph.stream(
                graph_input,
                config={"configurable": {"thread_id": thread_id}},
                context=context,
                stream_mode=["messages", "updates"],
                subgraphs=True,       # 支持子图事件
                durability="sync",     # 同步持久化检查点
            )
            for item in stream:
                # 将每个流项转换为 RuntimeSignal
                yield from _signals_from_stream_item(item)

    def close(self) -> None:
        self.connection.close()

    def delete_thread(self, thread_id: str) -> None:
        """Remove all LangGraph checkpoints and writes for one conversation."""
        with self._execution_lock:
            self.checkpointer.delete_thread(thread_id)

    # 延迟加载编译图，避免在 AgentRuntimeManager 构造时
    # 就加载所有依赖（包括 LLM 模型）
    def _get_graph(self):
        if self._graph is not None:
            return self._graph
        with self._graph_lock:
            if self._graph is None:
                from cellwiki.agent.app import build_wiki_agent

                self._graph = build_wiki_agent(
                    project_root=self.project_root,
                    checkpointer=self.checkpointer,
                )
        return self._graph


# ---------------------------------------------------------------------------
# AgentRuntimeManager —— 智能体运行时管理器
# 负责智能体运行的生命周期管理，包括：
# - 运行启动、恢复、重试、取消
# - 预算门控（最大运行时间、最大模型调用次数）
# - 取消令牌管理
# - 持久化运行状态和事件
# - 后台线程池执行
# - 记忆上下文注入
# - 运行恢复（应用重启后恢复未完成的运行）
# ---------------------------------------------------------------------------
class AgentRuntimeManager:
    """Own run lifecycle, budget gates, cancellation, persistence, and background execution."""

    def __init__(
        self,
        project_root: Path,
        *,
        adapter: AgentExecutionAdapter | None = None,
        store: RuntimeStore | None = None,
        memory_store: MemoryStore | None = None,
        memory_enabled: bool | None = None,
        task_router: TaskRouter | None = None,
        page_query_adapter: AgentExecutionAdapter | None = None,
        page_query_router: PageQueryRouter | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        owner_path = self.project_root / "data" / "runtime" / "agent-runtime.lock"
        owner_path.parent.mkdir(parents=True, exist_ok=True)
        self._runtime_owner_lock = FileLock(str(owner_path), timeout=0)
        try:
            self._runtime_owner_lock.acquire()
        except Timeout as error:
            raise AgentRuntimeBusyError(
                "another AgentRuntimeManager already owns this project"
            ) from error
        try:
            # 运行时存储（SQLite，持久化运行记录和事件）
            self.store = store or RuntimeStore(self.project_root)
            # 执行适配器（默认使用 Deep Agents）
            self.adapter = adapter or DeepAgentsExecutionAdapter(self.project_root)
            self.task_router = task_router or TaskRouter()
            self.page_query_adapter = page_query_adapter or PageQueryExecutionAdapter(
                self.project_root
            )
            self.page_query_router = page_query_router or PageQueryRouter()
            self.conversation_context = ConversationContextView(self.store)
            # 记忆功能是否启用
            self.memory_enabled = (
                settings.enable_agent_memory if memory_enabled is None else memory_enabled
            )
            self.memory = memory_store or (
                MemoryStore(self.project_root) if self.memory_enabled else None
            )
            # 取消注册表（用于协作式取消）
            self.cancellations = CancellationRegistry.for_project(self.project_root)
            # 后台执行线程池（最多 2 个并发智能体）
            self.executor = ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix="cellwiki-agent",
            )
            self._futures: set[Future[None]] = set()
            self._futures_lock = threading.Lock()
            self._thread_operation_lock = threading.RLock()
            self._closed = False
            # 独占 owner lock 后，所有残留活跃状态都来自崩溃进程，可以安全恢复。
            self._recover_persisted_runs()
        except Exception:
            self._runtime_owner_lock.release()
            raise

    # ---- 启动新的智能体运行 ----
    def start(
        self,
        *,
        thread_id: str,
        message: str,
        context: WikiAgentContext,
        budget: RunBudget | None = None,
    ) -> AgentRun:
        # 验证消息不为空
        if not message.strip():
            raise ValueError("agent message cannot be empty")
        # Natural language is the only product entry point. The coordinator
        # decides whether this is a query, ingest, lint, revision, or a request
        # for clarification; deterministic routers remain available solely for
        # legacy/internal callers and are deliberately not consulted here.
        with self._thread_operation_lock:
            # 创建运行记录
            run_id = f"run_{uuid.uuid4().hex}"
            run = AgentRun(
                run_id=run_id,
                thread_id=thread_id,
                project_id=context.project_id,
                source_id=context.source_id,
                page_id=context.page_id,
                selected_text=context.selected_text,
                input_message=message.strip(),
                checkpoint_id=run_id,
                model_name=settings.openai_model,
                budget=budget or RunBudget(),
            )
            # 持久化运行记录
            self.store.create_run(run)
            self._record_route_span(run, "coordinator", {"task_kind": "conversation"})
            # 注册取消令牌
            self.cancellations.register(run.run_id)
            # 提交到后台线程执行
            # Bind logging context for this run
        with log_context(run_id=run.run_id, thread_id=run.thread_id, project_id=run.project_id):
            self._submit(self._execute, run.run_id, message, context)
        return run

    def _start_page_query(
        self,
        *,
        thread_id: str,
        message: str,
        context: WikiAgentContext,
        budget: RunBudget | None,
    ) -> AgentRun:
        """Start the deterministic single-page read path outside LangGraph."""

        with self._thread_operation_lock:
            run = AgentRun(
                run_id=f"run_{uuid.uuid4().hex}",
                thread_id=thread_id,
                project_id=context.project_id,
                source_id=context.source_id,
                page_id=context.page_id,
                selected_text=context.selected_text,
                input_message=message,
                model_role="page-query",
                model_name=settings.openai_model,
                budget=budget or RunBudget(),
            )
            self.store.create_run(run)
            self._record_route_span(run, "page_query", {"page_id": context.page_id})
            self.cancellations.register(run.run_id)
        with log_context(run_id=run.run_id, thread_id=run.thread_id, project_id=run.project_id):
            self._submit(
                self._execute,
                run.run_id,
                message,
                context,
                AgentRunStatus.SUCCEEDED,
                self.page_query_adapter,
            )
        return run

    def start_task(
        self,
        *,
        thread_id: str,
        task: AgentTask,
        context: WikiAgentContext,
        budget: RunBudget | None = None,
        input_message: str | None = None,
    ) -> AgentRun:
        """Persist and execute a typed domain task without Coordinator routing."""

        task_payload = task.model_dump(mode="json")
        persisted_message = input_message or f"Typed CellWiki task: {task_payload['kind']}"
        with self._thread_operation_lock:
            run = AgentRun(
                run_id=f"run_{uuid.uuid4().hex}",
                thread_id=thread_id,
                project_id=context.project_id,
                source_id=getattr(task, "source_id", context.source_id),
                page_id=context.page_id,
                selected_text=context.selected_text,
                input_message=persisted_message,
                task_kind=task_payload["kind"],
                task_payload=task_payload,
                model_role="typed-task-adapter",
                model_name="",
                budget=budget or RunBudget(),
            )
            self.store.create_run(run)
            self._record_route_span(
                run,
                "typed_task",
                {"task_kind": task_payload["kind"]},
            )
            self.cancellations.register(run.run_id)
        with log_context(run_id=run.run_id, thread_id=run.thread_id, project_id=run.project_id):
            self._submit(self._execute_typed_task, run.run_id, task, context)
        return run

    def _stage_task_confirmation(
        self,
        *,
        thread_id: str,
        task: AgentTask,
        context: WikiAgentContext,
        message: str,
        reason: str,
        budget: RunBudget | None,
    ) -> AgentRun:
        """Persist a mutating TaskProposal without starting its implementation."""

        task_payload = task.model_dump(mode="json")
        run = AgentRun(
            run_id=f"run_{uuid.uuid4().hex}",
            thread_id=thread_id,
            project_id=context.project_id,
            source_id=getattr(task, "source_id", context.source_id),
            page_id=context.page_id,
            selected_text=context.selected_text,
            input_message=message,
            task_kind=str(task_payload["kind"]),
            task_payload=task_payload,
            model_role="task-router",
            model_name="",
            budget=budget or RunBudget(),
        )
        with self._thread_operation_lock:
            self.store.create_run(run)
            self._record_route_span(
                run,
                "task_confirmation",
                {"task_kind": task_payload["kind"]},
            )
            self.store.append_event(
                run.run_id,
                AgentEventType.TASK_CONFIRMATION_REQUIRED,
                message=reason,
                progress=0,
                data={"task": task_payload, "reason": reason},
            )
            return self.store.finalize_run(
                run.run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.WAITING_CONFIRMATION,
                    message="Task parameters require user confirmation.",
                ),
            )

    def confirm_task(self, run_id: str, *, decision: str) -> AgentRun:
        """Execute or cancel a persisted natural-language task proposal."""

        run = self.store.get_run(run_id)
        if run.status is not AgentRunStatus.WAITING_CONFIRMATION:
            raise ValueError("only a waiting-confirmation run can be resolved")
        if decision not in {"execute", "cancel"}:
            raise ValueError("decision must be execute or cancel")
        claimed = self.store.claim_task_confirmation(run_id, decision=decision)
        if decision == "cancel":
            self.store.transition(
                run_id,
                AgentRunStatus.CANCELLING,
                message="The proposed task was cancelled before execution.",
            )
            return self.store.finalize_run(
                run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.CANCELLED,
                    message="The proposed task was not executed.",
                ),
            )
        task: AgentTask = TypeAdapter(AgentTask).validate_python(claimed.task_payload)
        self.cancellations.register(run_id)
        self._submit(self._execute_typed_task, run_id, task, self._context_for(claimed))
        return claimed

    def delete_thread(self, thread_id: str) -> int:
        """Delete a complete conversation after confirming no run is active."""
        active_statuses = {
            AgentRunStatus.QUEUED,
            AgentRunStatus.RUNNING,
            AgentRunStatus.WAITING_CONFIRMATION,
            AgentRunStatus.WAITING_APPROVAL,
            AgentRunStatus.APPLYING,
            AgentRunStatus.VERIFYING,
            AgentRunStatus.RETRYING,
            AgentRunStatus.CANCELLING,
        }
        with self._thread_operation_lock:
            runs = self.store.list_runs(thread_id=thread_id, limit=10_000)
            if any(run.status in active_statuses for run in runs):
                raise ValueError("active agent run cannot be deleted")
            delete_checkpoint = getattr(self.adapter, "delete_thread", None)
            if delete_checkpoint is not None:
                checkpoint_ids = {
                    run.checkpoint_id or run.thread_id
                    for run in runs
                    if run.task_kind == "conversation" and run.model_role != "page-query"
                }
                for checkpoint_id in checkpoint_ids:
                    delete_checkpoint(checkpoint_id)
            return self.store.delete_thread(thread_id)

    # ---- 恢复等待审批的运行 ----
    # 用户做出 approve/reject 决定后，恢复被中断的图执行
    def resume(self, run_id: str, *, decision: str) -> AgentRun:
        run = self.store.get_run(run_id)
        # 只有处于 WAITING_APPROVAL 状态的运行才能恢复
        if run.status != AgentRunStatus.WAITING_APPROVAL:
            raise ValueError("only a waiting-approval run can be resumed")
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        changesets = ChangeSetRepository(self.project_root)
        approvals = ApprovalRepository(self.project_root)
        matching = sorted(
            (item for item in changesets.list() if item.run_id == run_id),
            key=lambda item: item.created_at,
            reverse=True,
        )
        if run.task_kind != "conversation" and not matching:
            raise ValueError("typed task has no ChangeSet to review")
        if matching and approvals.get(matching[0].change_set_id) is None:
            approvals.save(
                matching[0].change_set_id,
                ApprovalDecision(
                    approved=decision == "approve",
                    decided_by="desktop-user",
                    reason=f"User selected {decision} for the pending ChangeSet.",
                ),
            )
        claimed = self.store.claim_resume(run_id, decision=decision)
        self.cancellations.register(run_id)
        if matching:
            self._submit(
                self._execute_approval_continuation,
                run_id,
                matching[0].change_set_id,
                decision,
            )
            return claimed
        if run.task_kind != "conversation":
            self._submit(
                self._execute_typed_continuation,
                run_id,
                matching[0].change_set_id,
                decision,
            )
            return claimed
        # Legacy graph interrupts without a persisted ChangeSet are retained
        # only for recovery of pre-Model-led runs. New proposals always use the
        # CentralWriter continuation above.
        if decision == "reject":
            command: Command[Any] = Command(
                resume={
                    "decisions": [
                        {
                            "type": "reject",
                            "message": "The user rejected this ChangeSet after review.",
                        }
                    ]
                }
            )
        else:
            command = Command(resume={"decisions": [{"type": "approve"}]})
        # 恢复运行上下文
        context = WikiAgentContext(
            project_id=run.project_id,
            source_id=run.source_id,
            page_id=run.page_id,
            selected_text=run.selected_text,
            thread_id=run.thread_id,
        )
        terminal_status = (
            AgentRunStatus.REJECTED if decision == "reject" else AgentRunStatus.SUCCEEDED
        )
        self._submit(
            self._execute,
            run_id,
            command,
            context,
            terminal_status,
        )
        return claimed

    # ---- 重试失败的运行 ----
    # 从持久化检查点恢复，不重放用户输入
    def retry(self, run_id: str) -> AgentRun:
        """Resume a failed graph from its durable checkpoint without replaying user input."""

        run = self.store.get_run(run_id)
        # 检查是否可重试（状态、重试次数、错误类型）
        if not is_retryable_run(run):
            raise ValueError("run is not retryable or has exhausted its retry budget")
        updated = self.store.claim_retry(run_id)
        context = self._context_for(updated)
        self.cancellations.register(run_id)
        if updated.task_kind != "conversation":
            task: AgentTask = TypeAdapter(AgentTask).validate_python(updated.task_payload)
            self._submit(self._execute_typed_task, run_id, task, context)
            return updated
        if updated.model_role == "page-query":
            self._submit(
                self._execute,
                run_id,
                updated.input_message,
                context,
                AgentRunStatus.SUCCEEDED,
                self.page_query_adapter,
            )
            return updated
        # message=None 表示从检查点恢复，不重放用户输入
        self._submit(self._execute, run_id, None, context)
        return updated

    # ---- 取消运行 ----
    # 先发送取消信号，再更新状态。
    # 活跃的 HTTP 客户端观察到取消令牌后协作式关闭传输。
    def cancel(self, run_id: str) -> AgentRun:
        run = self.store.get_run(run_id)
        # 在等待下一个 LangGraph 事件之前向深层工具发送取消信号
        self.cancellations.cancel(run_id)
        if run.status in {
            AgentRunStatus.WAITING_CONFIRMATION,
            AgentRunStatus.WAITING_APPROVAL,
        }:
            # 等待用户决定的运行没有活跃执行，可以直接进入终态。
            updated = self.store.finalize_run(
                run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.CANCELLED,
                    message="Run cancelled while waiting for user confirmation.",
                ),
            )
        elif run.status in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING}:
            # 队列中的运行可直接取消，运行中的需要等待安全事件边界
            target = (
                AgentRunStatus.CANCELLED
                if run.status == AgentRunStatus.QUEUED
                else AgentRunStatus.CANCELLING
            )
            if target == AgentRunStatus.CANCELLED:
                updated = self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.CANCELLED,
                        message="Queued run cancelled.",
                    ),
                )
            else:
                updated = self.store.transition(
                    run_id,
                    target,
                    message="Cancellation requested; waiting for a safe event boundary.",
                )
        else:
            raise ValueError(f"run in {run.status.value} cannot be cancelled")
        return updated

    # ---- 关闭运行时 ----
    # 取消所有活动，等待后台任务完成，关闭适配器和线程池
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.request_shutdown()
            # 框架适配器可能拥有阻塞流或检查点连接，
            # 在取消后关闭它们为等待提供第二条退出路径
            self.adapter.close()
            if self.page_query_adapter is not self.adapter:
                self.page_query_adapter.close()
            with self._futures_lock:
                futures = set(self._futures)
            wait(futures, timeout=3)
            self.executor.shutdown(wait=False, cancel_futures=True)
        finally:
            if self._runtime_owner_lock.is_locked:
                self._runtime_owner_lock.release()

    # ---- 请求关闭 ----
    # 取消所有活动而不等待，用于桌面端关闭端点
    def request_shutdown(self) -> None:
        """Cancel active work without waiting, for the desktop shutdown endpoint."""

        self.cancellations.cancel_all()
        # 将所有排队中的运行标记为已取消，运行中的标记为取消中
        for run in self.store.list_runs(limit=10_000):
            if run.status == AgentRunStatus.QUEUED:
                try:
                    self.store.finalize_run(
                        run.run_id,
                        AgentRunOutcome(
                            status=AgentRunStatus.CANCELLED,
                            message="Queued run cancelled during application shutdown.",
                        ),
                    )
                except InvalidRunTransitionError:
                    # A worker may claim the queued run between list and finalize.
                    try:
                        self.store.transition(
                            run.run_id,
                            AgentRunStatus.CANCELLING,
                            message="Application shutdown requested cancellation.",
                        )
                    except InvalidRunTransitionError:
                        continue
            elif run.status in {
                AgentRunStatus.RUNNING,
                AgentRunStatus.RETRYING,
            }:
                try:
                    self.store.transition(
                        run.run_id,
                        AgentRunStatus.CANCELLING,
                        message="Application shutdown requested cancellation.",
                    )
                except InvalidRunTransitionError:
                    # The worker may finish between list_runs() and this write.
                    # Shutdown is best-effort, so a terminal or later-stage
                    # state wins over a stale cancellation request.
                    continue

    # ---- 提交后台任务 ----
    # 追踪后台工作，以便关闭时可以等待有限时间
    def _submit(self, callback, *args) -> None:
        """Track background work so shutdown can wait for a bounded interval."""

        future = self.executor.submit(callback, *args)
        with self._futures_lock:
            self._futures.add(future)

        # 任务完成后的清理回调
        def discard(completed: Future[None]) -> None:
            with self._futures_lock:
                self._futures.discard(completed)

        future.add_done_callback(discard)

    def _execute_approval_continuation(
        self,
        run_id: str,
        change_set_id: str,
        decision: str,
    ) -> None:
        """Apply or reject a reviewed proposal through the one write boundary.

        Model-led runs have no publication tool and therefore cannot resume a
        framework interrupt to perform a write. The desktop decision resumes
        the durable run here, where CentralWriter owns approval, apply, and
        verification as one auditable operation.
        """

        self.cancellations.register(run_id, reset=False)
        try:
            with bind_agent_run(run_id):
                if decision == "reject":
                    message = "The ChangeSet was rejected; no formal knowledge changed."
                    self.store.append_event(
                        run_id,
                        AgentEventType.FINAL_RESPONSE,
                        message=message,
                        progress=100,
                        data={"answer": message, "change_set_id": change_set_id},
                    )
                    self._append_assistant_result(
                        run_id,
                        message,
                        {"answer": message, "change_set_id": change_set_id},
                    )
                    self.store.finalize_run(
                        run_id,
                        AgentRunOutcome(
                            status=AgentRunStatus.REJECTED,
                            message=message,
                            progress=100,
                        ),
                    )
                    return

                self.store.transition(
                    run_id,
                    AgentRunStatus.APPLYING,
                    message="Approval received; CentralWriter is applying the ChangeSet.",
                )
                commit = CentralWriter(self.project_root).commit(
                    change_set_id,
                    approval=None,
                )
                self.store.transition(
                    run_id,
                    AgentRunStatus.VERIFYING,
                    message="CentralWriter applied the ChangeSet; verification is running.",
                )
                quality = inspect_projection(self.project_root)
                verification = {
                    "change_set_id": change_set_id,
                    "commit_id": commit.commit_id,
                    "snapshot_id": commit.snapshot_id,
                    "quality": {
                        key: quality.get(key)
                        for key in (
                            "status",
                            "page_count",
                            "issue_count",
                            "error_count",
                            "warning_count",
                        )
                    },
                }
                self.store.append_event(
                    run_id,
                    AgentEventType.VERIFICATION,
                    message="CentralWriter verification completed.",
                    progress=96,
                    data=verification,
                )
                message = "The approved ChangeSet was published and passed verification."
                answer_data = {"answer": message, **verification}
                self.store.append_event(
                    run_id,
                    AgentEventType.FINAL_RESPONSE,
                    message=message,
                    progress=100,
                    data=answer_data,
                )
                self._append_assistant_result(run_id, message, answer_data)
                self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.SUCCEEDED,
                        message=message,
                        progress=100,
                    ),
                )
        except Exception as error:
            try:
                error_type = classify_agent_error(error)
                run = self.store.get_run(run_id)
                retryable = is_retryable_run(
                    run.model_copy(
                        update={
                            "status": AgentRunStatus.FAILED,
                            "error_type": error_type,
                        }
                    )
                )
                self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.FAILED,
                        message="Approved ChangeSet publication failed.",
                        error_type=error_type,
                        error_message=_safe_error_text(error),
                        retryable=retryable,
                    ),
                )
            except (KeyError, InvalidRunTransitionError):
                pass
        finally:
            self.cancellations.clear(run_id)

    def _execute_typed_task(
        self,
        run_id: str,
        task: AgentTask,
        context: WikiAgentContext,
    ) -> None:
        self.cancellations.register(run_id, reset=False)
        task_started_at = datetime.now(UTC)
        try:
            with bind_agent_run(run_id):
                self.store.transition(run_id, AgentRunStatus.RUNNING, message="Typed task started.")
                result = TypedTaskExecutor(self.project_root).execute(task, run_id=run_id)
                task_finished_at = datetime.now(UTC)
                self.store.upsert_span(
                    AgentSpan(
                        span_id=f"task:{run_id}",
                        run_id=run_id,
                        kind="tool",
                        name=task.kind,
                        status="completed",
                        started_at=task_started_at,
                        finished_at=task_finished_at,
                        duration_ms=(
                            task_finished_at - task_started_at
                        ).total_seconds()
                        * 1000,
                        data={
                            "artifact_ref": result.data.get("full_report_ref"),
                            "artifact_sha256": result.data.get("full_report_sha256"),
                            "artifact_bytes": result.data.get("full_report_size"),
                            "finding_count": len(result.data.get("findings", [])),
                        },
                    )
                )
                if result.change_set_id:
                    self.store.append_event(
                        run_id,
                        AgentEventType.CHANGESET_READY,
                        message=result.message,
                        data={"change_set_id": result.change_set_id, **result.data},
                    )
                self.store.append_event(
                    run_id,
                    AgentEventType.FINAL_RESPONSE,
                    message=result.message,
                    progress=100,
                    data={
                        "answer": result.message,
                        "knowledge_scope": "general",
                        "verification_level": "unvalidated",
                        **result.data,
                    },
                )
                self._append_assistant_result(
                    run_id,
                    result.message,
                    {
                        "answer": result.message,
                        "knowledge_scope": "general",
                        "verification_level": "unvalidated",
                        **result.data,
                    },
                )
                if result.status == "waiting_approval":
                    self.store.finalize_run(
                        run_id,
                        AgentRunOutcome(
                            status=AgentRunStatus.WAITING_APPROVAL,
                            message=result.message,
                            progress=90,
                        ),
                    )
                else:
                    self.store.finalize_run(
                        run_id,
                        AgentRunOutcome(
                            status=AgentRunStatus.SUCCEEDED,
                            message=result.message,
                            progress=100,
                        ),
                    )
        except Exception as error:
            try:
                task_finished_at = datetime.now(UTC)
                self.store.upsert_span(
                    AgentSpan(
                        span_id=f"task:{run_id}",
                        run_id=run_id,
                        kind="tool",
                        name=task.kind,
                        status="failed",
                        started_at=task_started_at,
                        finished_at=task_finished_at,
                        duration_ms=(
                            task_finished_at - task_started_at
                        ).total_seconds()
                        * 1000,
                        data={"error_type": classify_agent_error(error).value},
                    )
                )
                error_type = classify_agent_error(error)
                run = self.store.get_run(run_id)
                retryable = is_retryable_run(
                    run.model_copy(
                        update={
                            "status": AgentRunStatus.FAILED,
                            "error_type": error_type,
                        }
                    )
                )
                self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.FAILED,
                        message="Typed task failed.",
                        error_type=error_type,
                        error_message=_safe_error_text(error),
                        retryable=retryable,
                    ),
                )
            except (KeyError, InvalidRunTransitionError):
                pass
        finally:
            self.cancellations.clear(run_id)

    def _execute_typed_continuation(
        self,
        run_id: str,
        change_set_id: str,
        decision: str,
    ) -> None:
        """Finish a typed task from its persisted approval without LangGraph."""

        self.cancellations.register(run_id, reset=False)
        try:
            with bind_agent_run(run_id):
                if decision == "reject":
                    message = "The typed task ChangeSet was rejected; no formal knowledge changed."
                    self.store.append_event(
                        run_id,
                        AgentEventType.FINAL_RESPONSE,
                        message=message,
                        progress=100,
                        data={"answer": message, "change_set_id": change_set_id},
                    )
                    self._append_assistant_result(
                        run_id,
                        message,
                        {"answer": message, "change_set_id": change_set_id},
                    )
                    self.store.finalize_run(
                        run_id,
                        AgentRunOutcome(
                            status=AgentRunStatus.REJECTED,
                            message=message,
                            progress=100,
                        ),
                    )
                    return
                result = TypedTaskExecutor(self.project_root).publish_existing(change_set_id)
                self.store.append_event(
                    run_id,
                    AgentEventType.FINAL_RESPONSE,
                    message=result.message,
                    progress=100,
                    data={"answer": result.message, **result.data},
                )
                self._append_assistant_result(
                    run_id,
                    result.message,
                    {"answer": result.message, **result.data},
                )
                self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.SUCCEEDED,
                        message=result.message,
                        progress=100,
                    ),
                )
        except Exception as error:
            try:
                error_type = classify_agent_error(error)
                run = self.store.get_run(run_id)
                retryable = is_retryable_run(
                    run.model_copy(
                        update={
                            "status": AgentRunStatus.FAILED,
                            "error_type": error_type,
                        }
                    )
                )
                self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.FAILED,
                        message="Typed task approval failed.",
                        error_type=error_type,
                        error_message=_safe_error_text(error),
                        retryable=retryable,
                    ),
                )
            except (KeyError, InvalidRunTransitionError):
                pass
        finally:
            self.cancellations.clear(run_id)

    # ---- 执行包装器 ----
    # 注册取消令牌，绑定运行 ID，执行后清理取消令牌
    def _execute(
        self,
        run_id: str,
        message: AgentInput,
        context: WikiAgentContext,
        terminal_status: AgentRunStatus = AgentRunStatus.SUCCEEDED,
        execution_adapter: AgentExecutionAdapter | None = None,
    ) -> None:
        self.cancellations.register(run_id, reset=False)
        try:
            # bind_agent_run 将运行 ID 绑定到当前线程的上下文
            with bind_agent_run(run_id):
                self._execute_bound(
                    run_id,
                    message,
                    context,
                    terminal_status,
                    execution_adapter or self.adapter,
                )
        finally:
            self.cancellations.clear(run_id)

    # ---- 核心执行逻辑 ----
    # 处理信号流，更新状态和用量，检查预算边界和取消信号
    def _execute_bound(
        self,
        run_id: str,
        message: AgentInput,
        context: WikiAgentContext,
        terminal_status: AgentRunStatus,
        execution_adapter: AgentExecutionAdapter,
    ) -> None:
        started = time.monotonic()
        started_at = datetime.now(UTC)
        model_calls: set[str] = set()       # 去重的模型调用 ID
        model_token_totals: dict[str, tuple[int, int]] = {}
        open_tool_spans: dict[str, AgentSpan] = {}
        pending_change_sets: dict[str, bool] = {}
        base_usage = RunUsage()              # 基础用量（从持久化恢复）
        final_response = ""                  # 最终回答
        try:
            current = self.store.get_run(run_id)
            # 如果运行已经处于终态，直接返回
            if current.status in {
                AgentRunStatus.CANCELLED,
                AgentRunStatus.REJECTED,
                AgentRunStatus.SUCCEEDED,
            }:
                return
            base_usage = current.usage
            # 标记运行为"运行中"
            self.store.transition(
                run_id,
                AgentRunStatus.RUNNING,
                message="Run started.",
                progress=1,
            )
            # 如果是审批恢复，标记为"正在应用"
            if _is_approval_resume(message):
                # 提交工具在执行前被中断。只有在收到明确的 approve 命令后才开始应用，
                # 绝不会在模型仅提出建议时应用
                self.store.transition(
                    run_id,
                    AgentRunStatus.APPLYING,
                    message="Approval received; applying the ChangeSet atomically.",
                )
            waiting_for_review = False
            # 注入记忆上下文（如果启用）
            execution_message = self._recall_context(run_id, message, context)
            if isinstance(execution_message, str):
                execution_message = self.conversation_context.build(
                    thread_id=current.thread_id,
                    current_run_id=run_id,
                    current_content=execution_message,
                )
            # 流式执行智能体图
            for signal in execution_adapter.execute(
                # New runs get isolated graph state. Approval resume keeps the
                # same run_id and therefore resumes the same checkpoint.
                thread_id=current.checkpoint_id or current.thread_id,
                message=execution_message,
                context=context,
            ):
                signal = _observable_signal(signal)
                run = self.store.get_run(run_id)
                # 检查取消信号
                if run.status == AgentRunStatus.CANCELLING:
                    cancelled_tools = _finish_open_tool_spans(
                        self.store,
                        open_tool_spans,
                        status="cancelled",
                    )
                    if cancelled_tools:
                        self.store.update_usage(
                            run_id,
                            run.usage.model_copy(
                                update={
                                    "tool_calls_cancelled": (
                                        run.usage.tool_calls_cancelled + cancelled_tools
                                    )
                                }
                            ),
                        )
                    self.store.finalize_run(
                        run_id,
                        AgentRunOutcome(
                            status=AgentRunStatus.CANCELLED,
                            message="Run cancelled at a safe event boundary.",
                        ),
                    )
                    return
                # 检查运行时间预算
                elapsed = base_usage.elapsed_seconds + (time.monotonic() - started)
                if elapsed > run.budget.max_runtime_seconds:
                    raise TimeoutError("run exceeded its maximum runtime")
                # 去重模型调用，计算总调用次数
                if signal.model_call_id:
                    model_calls.add(signal.model_call_id)
                    previous_tokens = model_token_totals.get(signal.model_call_id, (0, 0))
                    model_token_totals[signal.model_call_id] = (
                        previous_tokens[0] + signal.input_tokens,
                        previous_tokens[1] + signal.output_tokens,
                    )
                    model_input, model_output = model_token_totals[signal.model_call_id]
                    elapsed_ms = (time.monotonic() - started) * 1000
                    self.store.upsert_span(
                        AgentSpan(
                            span_id=f"model:{run_id}:{signal.model_call_id}",
                            run_id=run_id,
                            kind="model",
                            name=run.model_role,
                            status="completed",
                            started_at=started_at,
                            finished_at=datetime.now(UTC),
                            duration_ms=elapsed_ms,
                            ttft_ms=elapsed_ms,
                            input_tokens=model_input,
                            output_tokens=model_output,
                            data={
                                "model": run.model_name,
                                "profile": run.model_role,
                                "prompt_template_version": "agent-v2",
                                "prompt_template_hash": _prompt_template_hash(run.model_role),
                            },
                        )
                    )
                total_model_calls = base_usage.model_calls + len(model_calls)
                if total_model_calls > run.budget.max_model_calls:
                    raise AgentBudgetExceeded("run exceeded its model-call budget")
                # 更新用量统计
                usage = RunUsage(
                    model_calls=total_model_calls,
                    input_tokens=run.usage.input_tokens + signal.input_tokens,
                    output_tokens=run.usage.output_tokens + signal.output_tokens,
                    estimated_cost_usd=run.usage.estimated_cost_usd,
                    tool_calls=run.usage.tool_calls + signal.tool_calls,
                    tool_calls_started=run.usage.tool_calls_started
                    + int(signal.type == AgentEventType.TOOL_STARTED),
                    tool_calls_completed=run.usage.tool_calls_completed
                    + int(
                        signal.type == AgentEventType.TOOL_COMPLETED
                        and bool(signal.data.get("tool_call_id"))
                    ),
                    tool_calls_failed=run.usage.tool_calls_failed
                    + int(
                        signal.type == AgentEventType.TOOL_FAILED
                        and bool(signal.data.get("tool_call_id"))
                    ),
                    tool_calls_cancelled=run.usage.tool_calls_cancelled,
                    ttft_ms=(
                        run.usage.ttft_ms
                        if run.usage.ttft_ms is not None
                        else (
                            (time.monotonic() - started) * 1000
                            if signal.model_call_id
                            else None
                        )
                    ),
                    elapsed_seconds=elapsed,
                )
                self.store.update_usage(run_id, usage)
                tool_name = str(signal.data.get("tool_name", ""))
                tool_call_id = str(signal.data.get("tool_call_id", "") or "")
                if signal.type == AgentEventType.TOOL_STARTED and tool_call_id:
                    tool_span = AgentSpan(
                        span_id=f"tool:{run_id}:{tool_call_id}",
                        run_id=run_id,
                        kind="tool",
                        name=tool_name or "tool",
                        status="running",
                        started_at=datetime.now(UTC),
                        data={
                            "activity_code": signal.data.get("activity_code"),
                            "label_args": signal.data.get("label_args", {}),
                        },
                    )
                    open_tool_spans[tool_call_id] = tool_span
                    self.store.upsert_span(tool_span)
                elif signal.type in {
                    AgentEventType.TOOL_COMPLETED,
                    AgentEventType.TOOL_FAILED,
                } and tool_call_id in open_tool_spans:
                    tool_span = open_tool_spans.pop(tool_call_id)
                    finished_at = datetime.now(UTC)
                    self.store.upsert_span(
                        tool_span.model_copy(
                            update={
                                "status": (
                                    "failed"
                                    if signal.type == AgentEventType.TOOL_FAILED
                                    else "completed"
                                ),
                                "finished_at": finished_at,
                                "duration_ms": (
                                    finished_at - tool_span.started_at
                                ).total_seconds()
                                * 1000,
                                "data": {
                                    **tool_span.data,
                                    "result_bytes": signal.data.get("result_bytes", 0),
                                    "result_sha256": signal.data.get("result_sha256"),
                                },
                            }
                        )
                    )
                # 持久化事件
                self.store.append_event(
                    run_id,
                    signal.type,
                    message=signal.message,
                    progress=signal.progress,
                    data=signal.data,
                )
                # 处理各种信号类型
                if signal.type == AgentEventType.FINAL_RESPONSE:
                    final_response = signal.message or str(signal.data.get("answer", ""))
                    self.store.append_message(
                        thread_id=run.thread_id,
                        run_id=run_id,
                        role="assistant",
                        content=final_response,
                        data=signal.data,
                    )
                if signal.type == AgentEventType.TOOL_FAILED and not signal.data.get(
                    "blocked_tool"
                ):
                    raise RuntimeError(signal.message or f"tool {tool_name or 'unknown'} failed")
                if signal.type == AgentEventType.TOOL_COMPLETED and tool_name == "commit_change_set":
                    # ChangeSet 提交完成，进行验证
                    self.store.transition(
                        run_id,
                        AgentRunStatus.VERIFYING,
                        message="ChangeSet applied; verifying projection and quality state.",
                    )
                    self.store.append_event(
                        run_id,
                        AgentEventType.VERIFICATION,
                        message="CentralWriter verification completed.",
                        progress=96,
                        data={"change_set_id": signal.data.get("change_set_id")},
                    )
                if signal.type == AgentEventType.REVIEW_REQUIRED:
                    change_set_id = signal.data.get("change_set_id")
                    if isinstance(change_set_id, str) and change_set_id:
                        try:
                            ChangeSetRepository(self.project_root).get(change_set_id)
                        except (KeyError, ValueError):
                            # A legacy framework interrupt may carry a logical
                            # ID without a persisted CellWiki ChangeSet.
                            pass
                        else:
                            pending_change_sets[change_set_id] = bool(
                                signal.data.get("requires_human_review", True)
                            )
                    waiting_for_review = waiting_for_review or bool(
                        signal.data.get("requires_human_review", True)
                    )
            # 执行完成后的处理
            if pending_change_sets:
                policy = KnowledgePipelineHarness(self.project_root)
                decisions = {
                    change_set_id: policy.approval_for(
                        change_set_id,
                        reviewer="default-reviewer",
                    )
                    for change_set_id in pending_change_sets
                }
                if decisions and all(decision.approved for decision in decisions.values()):
                    self.store.transition(
                        run_id,
                        AgentRunStatus.APPLYING,
                        message="Configured approval policy accepted the ChangeSet; applying it atomically.",
                    )
                    commits = [
                        CentralWriter(self.project_root).commit(
                            change_set_id,
                            approval=decision,
                        )
                        for change_set_id, decision in decisions.items()
                    ]
                    self.store.transition(
                        run_id,
                        AgentRunStatus.VERIFYING,
                        message="Policy-approved ChangeSet applied; verification is running.",
                    )
                    quality = inspect_projection(self.project_root)
                    self.store.append_event(
                        run_id,
                        AgentEventType.VERIFICATION,
                        message="CentralWriter verification completed.",
                        progress=96,
                        data={
                            "change_set_ids": list(decisions),
                            "commit_ids": [commit.commit_id for commit in commits],
                            "quality": {
                                key: quality.get(key)
                                for key in (
                                    "status",
                                    "page_count",
                                    "issue_count",
                                    "error_count",
                                    "warning_count",
                                )
                            },
                        },
                    )
                    waiting_for_review = False
            elapsed = base_usage.elapsed_seconds + (time.monotonic() - started)
            run = self.store.get_run(run_id)
            if elapsed > run.budget.max_runtime_seconds:
                raise TimeoutError("run exceeded its maximum runtime")
            self.store.update_usage(
                run_id,
                run.usage.model_copy(update={"elapsed_seconds": elapsed}),
            )
            current = self.store.get_run(run_id)
            if current.status == AgentRunStatus.CANCELLING:
                cancelled_tools = _finish_open_tool_spans(
                    self.store,
                    open_tool_spans,
                    status="cancelled",
                )
                if cancelled_tools:
                    self.store.update_usage(
                        run_id,
                        current.usage.model_copy(
                            update={
                                "tool_calls_cancelled": (
                                    current.usage.tool_calls_cancelled + cancelled_tools
                                )
                            }
                        ),
                    )
                self.store.finalize_run(
                    run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.CANCELLED,
                        message="Run cancelled after reaching a safe completion boundary.",
                    ),
                )
                return
            # 确定终态
            if waiting_for_review:
                status = AgentRunStatus.WAITING_APPROVAL
                message_text = "Run is waiting for human approval."
            else:
                status = terminal_status
                message_text = (
                    "Run was rejected without publishing changes."
                    if status == AgentRunStatus.REJECTED
                    else "Run completed."
                )
            # 记录情景记忆
            if status == AgentRunStatus.SUCCEEDED and final_response:
                self._record_episode(run_id, final_response)
            current = self.store.get_run(run_id)
            if current.status == AgentRunStatus.APPLYING:
                self.store.transition(
                    run_id,
                    AgentRunStatus.VERIFYING,
                    message="Atomic apply completed; final verification is running.",
                )
            unfinished_tools = _finish_open_tool_spans(
                self.store,
                open_tool_spans,
                status="failed",
            )
            if unfinished_tools:
                current = self.store.get_run(run_id)
                self.store.update_usage(
                    run_id,
                    current.usage.model_copy(
                        update={
                            "tool_calls_failed": (
                                current.usage.tool_calls_failed + unfinished_tools
                            )
                        }
                    ),
                )
            # 最终状态转换
            self.store.finalize_run(
                run_id,
                AgentRunOutcome(
                    status=status,
                    message=message_text,
                    progress=100 if status == AgentRunStatus.SUCCEEDED else None,
                ),
            )
        except Exception as error:
            # ---- 异常处理 ----
            error_type: AgentErrorType | None = classify_agent_error(error)
            current = self.store.get_run(run_id)
            elapsed = base_usage.elapsed_seconds + (time.monotonic() - started)
            self.store.update_usage(
                run_id,
                current.usage.model_copy(update={"elapsed_seconds": elapsed}),
            )
            current = self.store.get_run(run_id)
            # 如果运行已经处于终态，不覆盖
            if current.status in {
                AgentRunStatus.CANCELLED,
                AgentRunStatus.REJECTED,
                AgentRunStatus.SUCCEEDED,
            } or current.finished_at is not None:
                return
            # The cooperative operation may observe the cancellation event
            # before cancel() persists CANCELLING; the exception closes that race.
            if current.status == AgentRunStatus.CANCELLING or isinstance(
                error, OperationCancelled
            ):
                target = AgentRunStatus.CANCELLED
                error_type = None
            else:
                target = AgentRunStatus.FAILED
            retryable = (
                target == AgentRunStatus.FAILED
                and is_retryable_run(
                    current.model_copy(
                        update={
                            "status": AgentRunStatus.FAILED,
                            "error_type": error_type,
                        }
                    )
                )
            )
            unfinished_tools = _finish_open_tool_spans(
                self.store,
                open_tool_spans,
                status="cancelled" if target == AgentRunStatus.CANCELLED else "failed",
            )
            if unfinished_tools:
                current = self.store.get_run(run_id)
                usage_field = (
                    "tool_calls_cancelled"
                    if target == AgentRunStatus.CANCELLED
                    else "tool_calls_failed"
                )
                self.store.update_usage(
                    run_id,
                    current.usage.model_copy(
                        update={
                            usage_field: getattr(current.usage, usage_field)
                            + unfinished_tools
                        }
                    ),
                )
            self.store.finalize_run(
                run_id,
                AgentRunOutcome(
                    status=target,
                    error_type=error_type,
                    error_message=(
                        _safe_error_text(error)
                        if target == AgentRunStatus.FAILED
                        else None
                    ),
                    retryable=retryable,
                    message=(
                        "Run cancelled at a safe failure boundary."
                        if target == AgentRunStatus.CANCELLED
                        else "Run failed."
                    ),
                ),
            )

    # ---- 注入记忆上下文 ----
    # 在保持原始持久化输入的同时，注入受控的项目记忆。
    # 记忆是可选的，如果不可用，核心证据工作流不会中断。
    def _recall_context(
        self,
        run_id: str,
        message: AgentInput,
        context: WikiAgentContext,
    ) -> AgentInput:
        """Inject bounded governed memory while preserving the original persisted input."""

        # 记忆未启用或消息不是字符串（Command/Native）时不注入
        if not self.memory_enabled or self.memory is None or not isinstance(message, str):
            return message
        try:
            records, recall = self.memory.recall(
                context.project_id,
                message,
                limit=6,
                token_budget=settings.memory_recall_token_budget,
            )
        except Exception as error:
            # 可选记忆绝不能使核心证据工作流不可用
            self.store.append_event(
                run_id,
                AgentEventType.MEMORY_RECALLED,
                message="Governed memory recall was unavailable; continuing without memory.",
                data={"memory_ids": [], "warning": _safe_error_text(error, limit=300)},
            )
            return message
        # 记录记忆召回事件
        self.store.append_event(
            run_id,
            AgentEventType.MEMORY_RECALLED,
            message=f"Recalled {len(records)} governed project memories.",
            data={
                "recall_id": recall.recall_id,
                "memory_ids": recall.memory_ids,
                "estimated_tokens": recall.estimated_tokens,
            },
        )
        if not records:
            return message
        # 将记忆转换为 JSON 并追加到消息中
        memory_payload = [
            {
                "memory_id": record.memory_id,
                "kind": record.kind.value,
                "content": record.content,
                "confidence": record.confidence,
                "tags": record.tags,
            }
            for record in records
        ]
        return (
            f"{message}\n\n<governed_memory_context>\n"
            "The following project memories are workflow context only. They are not "
            "scientific evidence and must never be cited.\n"
            f"{json.dumps(memory_payload, ensure_ascii=False)}\n"
            "</governed_memory_context>"
        )

    # ---- 记录情景记忆 ----
    # 只持久化可观察的请求/结果对，绝不保存模型私有推理
    def _record_episode(self, run_id: str, final_response: str) -> None:
        """Persist only the observable request/outcome pair, never private model reasoning."""

        if not self.memory_enabled or self.memory is None:
            return
        run = self.store.get_run(run_id)
        # 构造记忆内容：请求 + 结果
        content = (
            f"Request: {run.input_message[:1200]}\n"
            f"Outcome: {final_response[:2600]}"
        )
        try:
            record = self.memory.admit(
                MemoryCandidate(
                    candidate_id=f"episode_{run_id}",
                    project_id=run.project_id,
                    kind=MemoryKind.EPISODE,
                    content=content,
                    run_id=run_id,
                    confidence=0.7,
                    tags=["agent_outcome"],
                )
            )
            self.store.append_event(
                run_id,
                AgentEventType.MEMORY_CANDIDATE,
                message="Observable run outcome was admitted as an episode memory.",
                data={"memory_id": record.memory_id, "status": record.status.value},
            )
        except Exception as error:
            self.store.append_event(
                run_id,
                AgentEventType.MEMORY_CANDIDATE,
                message="Episode memory candidate was rejected; the Agent result is unchanged.",
                data={"warning": _safe_error_text(error, limit=300)},
            )

    # ---- 从运行记录构造上下文 ----
    def _append_assistant_result(
        self,
        run_id: str,
        content: str,
        data: dict[str, Any],
    ) -> None:
        """Project one observable task result into the durable conversation."""

        run = self.store.get_run(run_id)
        self.store.append_message(
            thread_id=run.thread_id,
            run_id=run_id,
            role="assistant",
            content=content,
            data=data,
        )

    def _record_route_span(
        self,
        run: AgentRun,
        route_name: str,
        data: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC)
        self.store.upsert_span(
            AgentSpan(
                span_id=f"router:{run.run_id}",
                run_id=run.run_id,
                kind="router",
                name=route_name,
                status="completed",
                started_at=now,
                finished_at=now,
                duration_ms=0,
                data=data,
            )
        )

    def _context_for(self, run: AgentRun) -> WikiAgentContext:
        return WikiAgentContext(
            project_id=run.project_id,
            source_id=run.source_id,
            page_id=run.page_id,
            selected_text=run.selected_text,
            thread_id=run.thread_id,
        )

    # ---- 恢复持久化的运行 ----
    # 应用重启后恢复未完成的运行。
    # 安全的运行状态恢复执行，不明确的运行标记为失败。
    def _recover_persisted_runs(self) -> None:
        """Recover safe states; ambiguous in-flight writes fail closed for user inspection."""

        for run in self.store.list_runs(limit=10_000):
            if run.status == AgentRunStatus.QUEUED and run.input_message:
                # 队列中的运行：恢复执行
                self.cancellations.register(run.run_id)
                if run.task_kind != "conversation":
                    task: AgentTask = TypeAdapter(AgentTask).validate_python(run.task_payload)
                    self._submit(
                        self._execute_typed_task,
                        run.run_id,
                        task,
                        self._context_for(run),
                    )
                else:
                    execution_adapter = (
                        self.page_query_adapter
                        if run.model_role == "page-query"
                        else self.adapter
                    )
                    self._submit(
                        self._execute,
                        run.run_id,
                        run.input_message,
                        self._context_for(run),
                        AgentRunStatus.SUCCEEDED,
                        execution_adapter,
                    )
            elif run.status == AgentRunStatus.RETRYING:
                # 重试中的运行：从检查点恢复
                self.cancellations.register(run.run_id)
                if run.model_role == "page-query":
                    self._submit(
                        self._execute,
                        run.run_id,
                        run.input_message,
                        self._context_for(run),
                        AgentRunStatus.SUCCEEDED,
                        self.page_query_adapter,
                    )
                else:
                    self._submit(self._execute, run.run_id, None, self._context_for(run))
            elif run.status == AgentRunStatus.CANCELLING:
                # 取消中的运行：标记为已取消
                self.store.finalize_run(
                    run.run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.CANCELLED,
                        message="Run was cancelled during application restart.",
                    ),
                )
            elif run.status in {
                AgentRunStatus.RUNNING,
                AgentRunStatus.APPLYING,
                AgentRunStatus.VERIFYING,
            }:
                # 运行中的运行：标记为失败，允许重试
                retryable = is_retryable_run(
                    run.model_copy(
                        update={
                            "status": AgentRunStatus.FAILED,
                            "error_type": AgentErrorType.SYSTEM,
                        }
                    )
                )
                self.store.finalize_run(
                    run.run_id,
                    AgentRunOutcome(
                        status=AgentRunStatus.FAILED,
                        error_type=AgentErrorType.SYSTEM,
                        error_message="Application stopped while the run was active.",
                        message="Run was interrupted by application restart.",
                        retryable=retryable,
                    ),
                )
# ---------------------------------------------------------------------------
# AgentBudgetExceeded —— 预算超限异常
# 在安全事件边界抛出，当运行超过其配置的预算时。
# ---------------------------------------------------------------------------
class AgentBudgetExceeded(RuntimeError):
    """Raised at a safe event boundary when a run crosses its configured budget."""


def _safe_error_text(error: Exception, *, limit: int = 1000) -> str:
    text = re.sub(r"(?i)bearer\s+[^\s,;]+", "Bearer [REDACTED]", str(error))
    if settings.openai_api_key:
        text = text.replace(settings.openai_api_key, "[REDACTED]")
    return text[:limit]


# ---------------------------------------------------------------------------
# 分类智能体错误
# 根据异常类型和错误信息文本，将异常映射到 AgentErrorType 枚举。
# 用于错误分类、重试策略和用户反馈。
# ---------------------------------------------------------------------------
def classify_agent_error(error: Exception) -> AgentErrorType:
    text = str(error).lower()
    if isinstance(error, AgentBudgetExceeded) or "budget" in text:
        return AgentErrorType.BUDGET
    if isinstance(error, TimeoutError) or "timeout" in text or "timed out" in text:
        return AgentErrorType.TIMEOUT
    if "rate limit" in text or "429" in text:
        return AgentErrorType.RATE_LIMIT
    if "api key" in text or "authentication" in text or "401" in text:
        return AgentErrorType.AUTHENTICATION
    if "permission" in text or "forbidden" in text or "403" in text:
        return AgentErrorType.PERMISSION
    if "structured" in text or "json" in text:
        return AgentErrorType.STRUCTURED_OUTPUT
    if "approval" in text or "interrupt" in text:
        return AgentErrorType.APPROVAL
    if "conflict" in text or "version" in text:
        return AgentErrorType.CONFLICT
    if isinstance(error, ValueError):
        return AgentErrorType.INPUT
    return AgentErrorType.SYSTEM


# ---------------------------------------------------------------------------
# 判断运行是否可重试
# 重试策略：仅限失败的运行，重试次数未用尽，且错误类型是可重试的
#（速率限制、超时、结构化输出错误、系统错误）。
# 输入错误、权限错误、审批拒绝等不可重试。
# ---------------------------------------------------------------------------
def is_retryable_run(run: AgentRun) -> bool:
    """Expose one retry policy shared by API responses, errors, and retry scheduling."""

    return (
        run.status == AgentRunStatus.FAILED
        and run.retry_count < run.budget.max_retries
        and run.error_type
        in {
            AgentErrorType.RATE_LIMIT,
            AgentErrorType.TIMEOUT,
            AgentErrorType.STRUCTURED_OUTPUT,
            AgentErrorType.SYSTEM,
        }
    )


_TOOL_ACTIVITY_CODES = {
    "read_wiki_page": "reading_page",
    "search_wiki": "searching",
    "search_wiki_pages": "searching",
    "run_quality_lint": "checking_quality",
    "submit_agent_answer": "completed",
    "list_change_sets": "checking_quality",
}


def _observable_signal(signal) -> RuntimeSignal:
    """Strip framework payloads before they cross the product event Seam."""

    if signal.type not in {
        AgentEventType.TOOL_STARTED,
        AgentEventType.TOOL_COMPLETED,
        AgentEventType.TOOL_FAILED,
        AgentEventType.SUBAGENT_STARTED,
        AgentEventType.SUBAGENT_COMPLETED,
        AgentEventType.MESSAGE_DELTA,
        AgentEventType.REVIEW_REQUIRED,
    }:
        return RuntimeSignal(
            type=signal.type,
            message=signal.message,
            progress=signal.progress,
            data=dict(signal.data),
            model_call_id=signal.model_call_id,
            input_tokens=signal.input_tokens,
            output_tokens=signal.output_tokens,
            tool_calls=signal.tool_calls,
        )

    if signal.type == AgentEventType.MESSAGE_DELTA:
        safe_data: dict[str, Any] = {}
        safe_message = signal.message
    elif signal.type == AgentEventType.REVIEW_REQUIRED:
        change_set_id = _find_key(signal.data, "change_set_id")
        requires_human_review = signal.data.get("requires_human_review", True)
        safe_data = {
            "activity_code": "waiting_approval",
            "change_set_id": change_set_id if isinstance(change_set_id, str) else None,
            "requires_human_review": bool(requires_human_review),
        }
        safe_message = signal.message or (
            "Human approval is required before formal knowledge can change."
            if requires_human_review
            else "ChangeSet passed the configured approval policy and will be published."
        )
    elif signal.type in {
        AgentEventType.SUBAGENT_STARTED,
        AgentEventType.SUBAGENT_COMPLETED,
    }:
        safe_data = {"activity_code": "searching"}
        safe_message = (
            "Knowledge query started."
            if signal.type == AgentEventType.SUBAGENT_STARTED
            else "Knowledge query completed."
        )
    else:
        raw_data = dict(signal.data)
        tool_name = str(raw_data.get("tool_name", "") or "tool")
        tool_call_id = str(raw_data.get("tool_call_id", "") or "")
        tool_call = raw_data.get("tool_call")
        arguments = (
            tool_call.get("args", {})
            if isinstance(tool_call, dict) and isinstance(tool_call.get("args"), dict)
            else {}
        )
        label_args: dict[str, Any] = {}
        for key in ("page_id", "source_id", "change_set_id", "snapshot_id"):
            value = arguments.get(key, raw_data.get(key))
            if isinstance(value, (str, int, float, bool)):
                label_args[key] = value
        finding_ids = arguments.get("finding_ids")
        if isinstance(finding_ids, list):
            label_args["finding_count"] = len(finding_ids)
        serialized = json.dumps(
            {"message": signal.message, "data": raw_data},
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        ).encode("utf-8")
        safe_data = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "activity_code": _TOOL_ACTIVITY_CODES.get(tool_name, "planning"),
            "label_args": label_args,
            "result_bytes": len(serialized),
            "result_sha256": hashlib.sha256(serialized).hexdigest(),
        }
        if raw_data.get("change_set_id"):
            safe_data["change_set_id"] = raw_data["change_set_id"]
        if raw_data.get("blocked_tool") is True:
            safe_data["blocked_tool"] = True
        verb = {
            AgentEventType.TOOL_STARTED: "started",
            AgentEventType.TOOL_COMPLETED: "completed",
            AgentEventType.TOOL_FAILED: "failed",
        }[signal.type]
        safe_message = f"{tool_name.replace('_', ' ').title()} {verb}."

    return RuntimeSignal(
        type=signal.type,
        message=safe_message,
        progress=signal.progress,
        data=safe_data,
        model_call_id=signal.model_call_id,
        input_tokens=signal.input_tokens,
        output_tokens=signal.output_tokens,
        tool_calls=signal.tool_calls,
    )


def _prompt_template_hash(model_role: str) -> str:
    template_identity = {
        "coordinator": "coordinator-read-only-v2",
        "page-query": "page-query-formal-v1",
        "task-router": "task-router-rules-v1",
        "typed-task-adapter": "typed-task-v1",
    }.get(model_role, f"{model_role}-v1")
    return hashlib.sha256(template_identity.encode("utf-8")).hexdigest()


def _finish_open_tool_spans(
    store: RuntimeStore,
    spans: dict[str, AgentSpan],
    *,
    status: str,
) -> int:
    finished_at = datetime.now(UTC)
    for span in list(spans.values()):
        store.upsert_span(
            span.model_copy(
                update={
                    "status": status,
                    "finished_at": finished_at,
                    "duration_ms": (
                        finished_at - span.started_at
                    ).total_seconds()
                    * 1000,
                }
            )
        )
    count = len(spans)
    spans.clear()
    return count


# ---------------------------------------------------------------------------
# 将流式输出项转换为 RuntimeSignal 序列
# 处理两种流模式：messages（消息级）和 updates（状态级）。
# 消息级：处理工具调用启动、工具完成、消息增量、中断信号
# 状态级：处理结构化响应、节点完成事件
# 注意：token 用量属于模型响应而非每个工具调用，
# 在第一个工具调用时附加一次，避免多工具消息重复计算。
# ---------------------------------------------------------------------------
def _signals_from_stream_item(item: Any) -> Iterable[RuntimeSignal]:
    namespace: tuple[str, ...] = ()
    mode = "updates"
    data = item
    # 解析流式项的三种可能格式
    if isinstance(item, tuple) and len(item) == 3:
        namespace, mode, data = item
    elif isinstance(item, tuple) and len(item) == 2 and item[0] in {"messages", "updates"}:
        mode, data = item

    # ---- 消息模式 ----
    if mode == "messages":
        message, metadata = data if isinstance(data, tuple) and len(data) == 2 else (data, {})
        message_type = type(message).__name__.lower()
        usage = getattr(message, "usage_metadata", None) or {}
        tool_calls = getattr(message, "tool_calls", None) or []
        # 处理每个工具调用启动事件
        for tool_index, tool_call in enumerate(tool_calls):
            serialized_call = _json_safe(tool_call)
            tool_name = str(serialized_call.get("name", "")) if isinstance(serialized_call, dict) else ""
            yield RuntimeSignal(
                type=AgentEventType.TOOL_STARTED,
                message=f"{tool_name or 'Tool'} started.",
                data={
                    "namespace": list(namespace),
                    "metadata": _json_safe(metadata),
                    "tool_name": tool_name,
                    "tool_call_id": (
                        str(serialized_call.get("id", ""))
                        if isinstance(serialized_call, dict)
                        else ""
                    ),
                    "tool_call": serialized_call,
                },
                model_call_id=getattr(message, "id", None),
                # 用量属于模型响应而非每个工具调用
                # 在第一个工具调用时附加一次，避免多工具消息重复计算
                input_tokens=int(usage.get("input_tokens", 0)) if tool_index == 0 else 0,
                output_tokens=int(usage.get("output_tokens", 0)) if tool_index == 0 else 0,
            )
        content = _text_content(getattr(message, "content", ""))
        # 处理工具完成/失败事件
        if "toolmessage" in message_type:
            tool_name = str(getattr(message, "name", "") or "")
            failed = str(getattr(message, "status", "success")).lower() == "error"
            event_type = AgentEventType.TOOL_FAILED if failed else AgentEventType.TOOL_COMPLETED
            change_set_id = _extract_change_set_id(content)
            event_data = {
                "namespace": list(namespace),
                "metadata": _json_safe(metadata),
                "tool_name": tool_name,
                "tool_call_id": getattr(message, "tool_call_id", None),
                "change_set_id": change_set_id,
            }
            if failed and "not available to CellWiki agents" in content:
                # A provider may emit a filtered generic tool call despite the
                # model-facing schema boundary. Keep the policy failure
                # observable, but let the coordinator recover and answer from
                # the resulting ToolMessage instead of failing the whole run.
                event_data["blocked_tool"] = True
            yield RuntimeSignal(
                type=event_type,
                message=content or f"{tool_name or 'Tool'} completed.",
                data=event_data,
                tool_calls=1,
            )
            if not failed and tool_name == "submit_agent_answer":
                answer = _parse_agent_answer(content)
                yield RuntimeSignal(
                    type=AgentEventType.FINAL_RESPONSE,
                    message=answer["answer"],
                    data=answer,
                )
            # Proposal tools never publish. Surface the immutable proposal to
            # the desktop and, when policy requires it, stop at one approval
            # boundary shared by ingest, revision, and lint repair.
            proposal_tools = {
                "prepare_ingest_change_set",
                "request_ingest_revision",
                "propose_lint_fix",
            }
            if not failed and tool_name in proposal_tools and change_set_id:
                requires_human_review = _extract_requires_human_review(
                    content
                )
                yield RuntimeSignal(
                    type=AgentEventType.CHANGESET_READY,
                    message=f"ChangeSet {change_set_id} is ready for review.",
                    data={
                        "change_set_id": change_set_id,
                        "requires_human_review": requires_human_review,
                    },
                )
                yield RuntimeSignal(
                    type=AgentEventType.REVIEW_REQUIRED,
                    message=(
                        "Human approval is required before formal knowledge can change."
                        if requires_human_review
                        else "ChangeSet passed the configured approval policy and will be published."
                    ),
                    data={
                        "change_set_id": change_set_id,
                        "requires_human_review": requires_human_review,
                    },
                )
            return
        # 处理消息增量（AI 流式响应片段）
        if content:
            yield RuntimeSignal(
                type=AgentEventType.MESSAGE_DELTA,
                message=content,
                data={"namespace": list(namespace), "metadata": _json_safe(metadata)},
                model_call_id=getattr(message, "id", None),
                input_tokens=int(usage.get("input_tokens", 0)) if not tool_calls else 0,
                output_tokens=int(usage.get("output_tokens", 0)) if not tool_calls else 0,
            )
        # Without LangChain's forced structured-output tool, the provider can
        # use normal tool choice. Validate only the terminal top-level message.
        if not namespace and message_type == "aimessage" and content and not tool_calls:
            answer = _parse_agent_answer(content)
            yield RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE,
                message=answer["answer"],
                data=answer,
            )
        return

    # ---- 更新模式 ----
    serialized = _json_safe(data)
    # 检查是否存在中断信号（需要人工审批）
    interrupt = _find_key(serialized, "__interrupt__")
    if interrupt is not None:
        yield RuntimeSignal(
            type=AgentEventType.REVIEW_REQUIRED,
            message="Human approval is required before the run can continue.",
            data={"namespace": list(namespace), "interrupt": interrupt},
        )
    # 检查是否存在结构化响应（最终回答）
    structured = _find_key(serialized, "structured_response")
    if structured:
        yield RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message=str(structured.get("answer", "")) if isinstance(structured, dict) else "",
            data=structured if isinstance(structured, dict) else {"value": structured},
        )
    # 遍历节点名称，处理工具和子图完成事件
    node_names = list(serialized) if isinstance(serialized, dict) else []
    for node_name in node_names:
        lowered = node_name.lower()
        if "tool" in lowered:
            # ToolMessage events already carry stable call IDs and outcomes.
            # Framework node updates would duplicate them without useful identity.
            continue
        elif namespace:
            yield RuntimeSignal(
                type=AgentEventType.SUBAGENT_COMPLETED,
                message=f"{node_name} completed.",
                data={"node": node_name, "namespace": list(namespace)},
            )


# ---------------------------------------------------------------------------
# 提取消息中的文本内容
# 处理多种格式：纯字符串、多块列表（含文本块）
# ---------------------------------------------------------------------------
def _text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for block in value:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return ""


def _parse_agent_answer(content: str) -> dict[str, Any]:
    """Validate provider JSON while preserving a readable plain-text fallback."""
    candidate = content.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        payload = json.loads(candidate)
        return AgentAnswer.model_validate(payload).model_dump(mode="json")
    except (json.JSONDecodeError, TypeError, ValueError):
        return AgentAnswer(answer=content).model_dump(mode="json")


# ---------------------------------------------------------------------------
# 从工具调用结果中提取 ChangeSet ID
# 递归搜索嵌套字典中的所有键，找到第一个 "change_set_id"
# ---------------------------------------------------------------------------
def _extract_change_set_id(value: Any) -> str | None:
    serialized = _json_safe(value)
    if isinstance(serialized, str):
        try:
            serialized = json.loads(serialized)
        except json.JSONDecodeError:
            return None
    found = _find_key(serialized, "change_set_id")
    return str(found) if found else None


def _extract_requires_human_review(value: Any) -> bool:
    """Read the proposal policy flag from a JSON tool result safely."""

    serialized = _json_safe(value)
    if isinstance(serialized, str):
        try:
            serialized = json.loads(serialized)
        except json.JSONDecodeError:
            return True
    found = _find_key(serialized, "requires_human_review")
    return found if isinstance(found, bool) else True


# ---------------------------------------------------------------------------
# 判断消息是否为审批恢复命令
# 检查 Command 中是否包含 "approve" 决策
# ---------------------------------------------------------------------------
def _is_approval_resume(message: AgentInput) -> bool:
    if not isinstance(message, Command):
        return False
    serialized = _json_safe(message)
    decisions = _find_key(serialized, "decisions")
    return bool(
        isinstance(decisions, list)
        and decisions
        and isinstance(decisions[0], dict)
        and decisions[0].get("type") == "approve"
    )


# ---------------------------------------------------------------------------
# 在嵌套字典/列表中递归查找指定键
# 使用深度优先搜索，适用于任何深度的嵌套结构
# ---------------------------------------------------------------------------
def _find_key(value: Any, target: str) -> Any:
    if isinstance(value, dict):
        if target in value:
            return value[target]
        for child in value.values():
            found = _find_key(child, target)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_key(child, target)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# 将任意值安全转换为 JSON 可序列化形式
# 处理 Pydantic 模型、字典、列表、元组和基本类型。
# 对于无法序列化的类型，先尝试 json.dumps 再回退到 str()。
# ---------------------------------------------------------------------------
def _json_safe(value: Any) -> Any:
    # Pydantic 模型转换为字典
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return json.loads(json.dumps(value, default=str))
    except TypeError:
        return str(value)
