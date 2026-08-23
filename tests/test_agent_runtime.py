# =============================================================================
# 智能体运行时测试 —— 工作区版运行的契约测试
# =============================================================================
# 覆盖：run 生命周期（成功/失败/重试/取消）、预算门控、事件与用量持久化、
# 会话上下文注入、线程删除、流信号解析。阶段 4 将补充 unfinished / 继续 /
# 超时预算与严格串行门禁的契约测试。
# =============================================================================

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Iterable
import pytest
from datetime import UTC, datetime

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.pending_diff import PendingDiffStatus
from cellwiki.services.git_executor import GitExecutor
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentEventType,
    AgentRun,
    AgentRunStatus,
    RunBudget,
)
from cellwiki.services.agent_runtime import (
    AgentRunInProgressError,
    InvalidRunTransitionError,
    AgentRuntimeManager,
    RuntimeSignal,
    _signals_from_stream_item,
    _new_run_id,
    classify_agent_error,
    is_retryable_run,
)


class ScriptedAdapter:
    """Small framework-free adapter used to verify CellWiki's own runtime contract."""

    def __init__(self, scripts: list[list[RuntimeSignal] | Exception]):
        self.scripts = scripts
        self.calls: list[object] = []
        self.thread_ids: list[str] = []
        self.contexts: list[WikiAgentContext] = []

    def execute(self, *, thread_id: str, message, context) -> Iterable[RuntimeSignal]:
        self.thread_ids.append(thread_id)
        self.calls.append(message)
        self.contexts.append(context)
        script = self.scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        yield from script

    def close(self) -> None:
        return None


class BlockingAdapter:
    def __init__(self):
        self.release = threading.Event()

    def execute(self, *, thread_id: str, message, context) -> Iterable[RuntimeSignal]:
        self.release.wait(timeout=2)
        yield RuntimeSignal(type=AgentEventType.PROGRESS, progress=50)

    def close(self) -> None:
        self.release.set()


def _context(thread_id: str = "thread_test") -> WikiAgentContext:
    return WikiAgentContext(project_id="cellwiki", thread_id=thread_id)


def _wait_for_status(
    manager: AgentRuntimeManager,
    run_id: str,
    statuses: set[AgentRunStatus],
    timeout: float = 5.0,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = manager.store.get_run(run_id)
        if run.status in statuses:
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {statuses}")


def test_successful_run_persists_events_message_and_usage(tmp_path: Path):
    adapter = ScriptedAdapter([[
        RuntimeSignal(
            type=AgentEventType.TOOL_STARTED,
            message="read_wiki_page started.",
            data={"tool_name": "read_wiki_page", "tool_call_id": "call_1"},
            model_call_id="model_call_1",
            input_tokens=100,
            output_tokens=20,
            tool_calls=1,
        ),
        RuntimeSignal(
            type=AgentEventType.TOOL_COMPLETED,
            message="read_wiki_page completed.",
            data={"tool_name": "read_wiki_page", "tool_call_id": "call_1"},
        ),
        RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="Done.",
            data={"answer": "Done.", "file_paths": ["wiki/cell_types/foo.md"]},
        ),
    ]])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_test",
            message="引用了哪些工具？",
            context=_context(),
        )
        completed = _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})

        assert completed.status == AgentRunStatus.SUCCEEDED
        assert completed.usage.tool_calls_started == 1
        assert completed.usage.tool_calls_completed == 1
        assert completed.usage.model_calls >= 1
        assert completed.usage.input_tokens >= 100
        events = manager.store.list_events(started.run_id)
        types = [event.type for event in events]
        assert AgentEventType.TOOL_STARTED in types
        assert AgentEventType.TOOL_COMPLETED in types
        assert AgentEventType.FINAL_RESPONSE in types
        messages = manager.store.list_messages(started.thread_id)
        assert messages[-1]["role"] == "assistant"
        assert "Done." in messages[-1]["content"]
        # 会话上下文把当前用户消息注入为 list 输入
        assert isinstance(adapter.calls[0], list)
    finally:
        manager.close()


def test_failed_run_is_marked_failed_and_retryable(tmp_path: Path):
    adapter = ScriptedAdapter([RuntimeError("provider exploded")])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_fail",
            message="会失败吗？",
            context=_context("thread_fail"),
        )
        failed = _wait_for_status(manager, started.run_id, {AgentRunStatus.FAILED})
        assert failed.error_type == AgentErrorType.SYSTEM
        assert is_retryable_run(failed) is True
        assert "provider exploded" in (failed.error_message or "")
    finally:
        manager.close()


def test_retry_submits_another_execution(tmp_path: Path):
    adapter = ScriptedAdapter([
        RuntimeError("provider exploded"),
        [
            RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE,
                message="Retried OK.",
                data={"answer": "Retried OK.", "file_paths": []},
            )
        ],
    ])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_retry",
            message="失败后重试",
            context=_context("thread_retry"),
        )
        failed = _wait_for_status(manager, started.run_id, {AgentRunStatus.FAILED})
        retried = manager.retry(failed.run_id)
        assert retried.status == AgentRunStatus.RETRYING
        completed = _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        assert completed.retry_count == 1
        assert len(adapter.calls) == 2
    finally:
        manager.close()


def test_cancel_waits_for_safe_event_boundary(tmp_path: Path):
    adapter = BlockingAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_cancel",
            message="取消我",
            context=_context("thread_cancel"),
        )
        running = _wait_for_status(manager, started.run_id, {AgentRunStatus.RUNNING})
        cancelling = manager.cancel(running.run_id)
        assert cancelling.status == AgentRunStatus.CANCELLING
        # 释放适配器，让运行在安全事件边界被取消
        adapter.release.set()
        cancelled = _wait_for_status(manager, started.run_id, {AgentRunStatus.CANCELLED})
        assert cancelled.status == AgentRunStatus.CANCELLED
    finally:
        manager.close()


def test_budget_gate_marks_run_as_unfinished_and_resume_advances(tmp_path: Path):
    # 阶段 4：预算耗尽进入 unfinished（非 failed），可继续/恢复推进会话
    signals = [
        RuntimeSignal(
            type=AgentEventType.MESSAGE_DELTA,
            message="token",
            data={},
            model_call_id=f"model_call_{index}",
            input_tokens=10,
            output_tokens=10,
        )
        for index in range(6)
    ]
    adapter = ScriptedAdapter([signals, []])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_budget",
            message="超预算",
            context=_context("thread_budget"),
            budget=RunBudget(max_model_calls=3),
        )
        unfinished = _wait_for_status(manager, started.run_id, {AgentRunStatus.UNFINISHED})
        assert unfinished.error_type == AgentErrorType.BUDGET
        assert is_retryable_run(unfinished) is False
        # 继续/恢复推进会话：unfinished -> running -> succeeded
        resumed = manager.resume(started.run_id)
        assert resumed.status == AgentRunStatus.RUNNING
        completed = _wait_for_status(
            manager, started.run_id, {AgentRunStatus.SUCCEEDED}
        )
        assert completed.status == AgentRunStatus.SUCCEEDED
    finally:
        manager.close()


def test_delete_thread_removes_complete_conversation(tmp_path: Path):
    adapter = ScriptedAdapter([[
        RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="Done.",
            data={"answer": "Done.", "file_paths": []},
        )
    ]])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_delete",
            message="删除我",
            context=_context("thread_delete"),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        deleted = manager.delete_thread("thread_delete")
        assert deleted >= 1
        assert manager.store.list_runs(thread_id="thread_delete", limit=100) == []
    finally:
        manager.close()


def test_signals_from_stream_item_emits_tool_lifecycle_and_final_response():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "read_wiki_page", "args": {}, "id": "call_x", "type": "tool_call"}]),
        ToolMessage(content='{"answer": "plain result", "file_paths": []}', tool_call_id="call_x", name="submit_agent_answer"),
    ]
    signals = list(_signals_from_stream_item(("messages", (messages[0], {}))))
    signals += list(_signals_from_stream_item(("messages", (messages[1], {}))))
    types = [signal.type for signal in signals]
    assert AgentEventType.TOOL_STARTED in types
    # submit_agent_answer 只发 FINAL_RESPONSE（阶段 4 简化：不重复发完成事件）
    assert AgentEventType.TOOL_COMPLETED not in types
    final = next(signal for signal in signals if signal.type == AgentEventType.FINAL_RESPONSE)
    assert "plain result" in final.message


def test_classify_agent_error_maps_timeout_and_rate_limit():
    assert classify_agent_error(TimeoutError("timed out")) == AgentErrorType.TIMEOUT
    assert classify_agent_error(RuntimeError("429 rate limit")) == AgentErrorType.RATE_LIMIT

# =============================================================================
# 阶段 4 契约：严格串行门禁 + pending diff 生命周期（真实 git 工作区）
# =============================================================================
def test_strict_serial_gate_rejects_second_active_run(tmp_path: Path):
    adapter = BlockingAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_gate",
            message="第一个运行",
            context=_context("thread_gate"),
        )
        running = _wait_for_status(manager, started.run_id, {AgentRunStatus.RUNNING})
        assert running.status == AgentRunStatus.RUNNING
        with pytest.raises(AgentRunInProgressError):
            manager.start(
                thread_id="thread_gate",
                message="第二个运行",
                context=_context("thread_gate"),
            )
        adapter.release.set()
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
    finally:
        adapter.release.set()
        manager.close()


def _init_git_repo(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "tests@cellwiki.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "CellWiki Tests"],
        check=True,
        capture_output=True,
    )
    (repo / "readme.md").write_text("base", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "--all"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "initial"], check=True, capture_output=True
    )


def test_pending_diff_lifecycle_accept_reject_reopen(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    class WritingAdapter:
        def execute(self, *, thread_id, message, context) -> Any:
            (repo / "note.md").write_text("agent note", encoding="utf-8")
            git = GitExecutor(repo)
            git.run("add", "note.md")
            git.run("commit", "-m", "agent change 1")
            yield RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE, message="done", data={}
            )

    manager = AgentRuntimeManager(repo, adapter=WritingAdapter())
    try:
        started = manager.start(thread_id="t_diff", message="写笔记", context=_context("t_diff"))
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        # pending diff 在运行终结后的收尾中发布，稍候片刻
        diffs = manager.store.list_pending_diffs(run_id=started.run_id)
        for _ in range(100):
            if diffs:
                break
            time.sleep(0.02)
            diffs = manager.store.list_pending_diffs(run_id=started.run_id)
        assert len(diffs) == 1, diffs
        diff = diffs[0]
        assert diff.status == PendingDiffStatus.PENDING
        assert diff.commits, "运行产出的 commit 应被收集"
        assert (repo / "note.md").exists()
        # accept：commit 保留，审计生效
        accepted = manager.accept_pending_diff(diff.diff_id)
        assert accepted.status == PendingDiffStatus.ACCEPTED
        assert (repo / "note.md").exists()
        # reopen：重新打开已解决的 diff
        reopened = manager.reopen_pending_diff(diff.diff_id)
        assert reopened.status == PendingDiffStatus.PENDING
        # reject：逐个 revert run 内 commit（保留后续 commit）
        rejected = manager.reject_pending_diff(diff.diff_id)
        assert rejected.status == PendingDiffStatus.REJECTED
        assert not (repo / "note.md").exists(), "reject 后 note.md 应被回滚删除"
        # 重复 reject 已解决 diff -> InvalidRunTransitionError
        with pytest.raises(InvalidRunTransitionError):
            manager.reject_pending_diff(diff.diff_id)
    finally:
        manager.close()


def test_recover_stale_runs_on_start_marks_orphans_unfinished(tmp_path: Path):
    # 第一次启动：阻塞运行（模拟真实 agent 未结束就崩溃）
    adapter = BlockingAdapter()
    first = AgentRuntimeManager(tmp_path, adapter=adapter)
    started = first.start(
        thread_id="thread_orphan",
        message="正在运行的任务",
        context=_context("thread_orphan"),
    )
    _wait_for_status(first, started.run_id, {AgentRunStatus.RUNNING})
    # 不释放、不关闭：模拟进程崩溃（worker 卡在适配器内）。
    # 第二次启动（同一工作区）：孤儿运行被恢复为 unfinished（可继续/恢复）。
    second = AgentRuntimeManager(tmp_path, adapter=BlockingAdapter())
    try:
        orphan = second.store.get_run(started.run_id)
        assert orphan.status == AgentRunStatus.UNFINISHED
        assert orphan.error_type == AgentErrorType.TIMEOUT
        # TIMEOUT 属瞬时错误：未完成运行既可继续（resume）也可重试（retry）
        assert is_retryable_run(second.store.get_run(started.run_id)) is True
    finally:
        second.close()
    # 释放旧 worker：僵尸 finalize 不得改写已恢复的运行
    adapter.release.set()
    time.sleep(1.0)
    final = first.store.get_run(started.run_id)
    assert final.status == AgentRunStatus.UNFINISHED, final.status
    first.close()


def test_recover_stale_runs_handles_cancelling_and_queued(tmp_path: Path):
    # CANCELLING -> CANCELLED；QUEUED -> UNFINISHED（重启恢复语义）
    adapter = BlockingAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        cancelling = manager.start(
            thread_id="thread_recover_2",
            message="取消中的任务",
            context=_context("thread_recover_2"),
        )
        _wait_for_status(manager, cancelling.run_id, {AgentRunStatus.RUNNING})
        manager.cancel(cancelling.run_id)  # CANCELLING
        queued = AgentRun(
            run_id=_new_run_id(),
            thread_id="thread_recover_2",
            project_id="cellwiki",
            status=AgentRunStatus.QUEUED,
            input_message="排队未开始的任务",
            budget=RunBudget(max_model_calls=5, max_runtime_seconds=30),
            created_at=datetime.now(UTC),
        )
        manager.store.create_run(queued)
    finally:
        manager.close()
    adapter.release.set()
    time.sleep(1.0)  # 旧 worker 收敛：CANCELLING -> CANCELLED
    recovered = AgentRuntimeManager(tmp_path, adapter=BlockingAdapter())
    try:
        assert recovered.store.get_run(cancelling.run_id).status == AgentRunStatus.CANCELLED
        assert recovered.store.get_run(queued.run_id).status == AgentRunStatus.UNFINISHED
    finally:
        recovered.close()
        manager.close()


class QuestionCapableAdapter:
    """ScriptedAdapter + ask_user_question resume 支持（协议层 resume= 参数）。"""

    def __init__(
        self, scripts: list[list[RuntimeSignal]], resume_script: list[RuntimeSignal]
    ):
        self.scripts = scripts
        self.resume_script = resume_script
        self.calls: list[tuple[object | None, object | None]] = []

    def execute(
        self, *, thread_id: str, message, context, resume: object | None = None
    ) -> Iterable[RuntimeSignal]:
        self.calls.append((message, resume))
        if resume is not None:
            yield from self.resume_script
            return
        script = self.scripts.pop(0)
        yield from script

    def close(self) -> None:
        return None


def test_ask_user_question_pauses_waits_and_resumes(tmp_path: Path):
    # 阶段 4：5+1 契约 —— interrupt 挂起 -> WAITING_CONFIRMATION -> 回复 -> 续跑到成功
    adapter = QuestionCapableAdapter(
        scripts=[
            [
                RuntimeSignal(type=AgentEventType.TOOL_STARTED, message="ask_user_question"),
                RuntimeSignal(
                    type=AgentEventType.TASK_CONFIRMATION_REQUIRED,
                    message="Waiting for the user: 继续吗？",
                    data={
                        "interrupt": {
                            "question": "继续吗？",
                            "options": ["是", "否"],
                            "required": True,
                        }
                    },
                ),
            ],
        ],
        resume_script=[
            RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="已完成"),
        ],
    )
    runtime = AgentRuntimeManager(tmp_path, adapter=adapter)
    thread_id = f"thread_q_{abs(hash(tmp_path)) & 0xFFFF}"
    started = runtime.start(
        thread_id=thread_id,
        message="开始",
        context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
    )

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = runtime.store.get_run(started.run_id)
        assert current is not None
        if current.status == AgentRunStatus.WAITING_CONFIRMATION:
            break
        time.sleep(0.02)
    assert runtime.store.get_run(started.run_id).status == AgentRunStatus.WAITING_CONFIRMATION

    question = runtime.store.get_open_question(started.run_id)
    assert question is not None
    assert question["run_id"] == started.run_id
    assert question["question"] == "继续吗？"
    assert question["options"] == ["是", "否"]
    assert question["required"] is True

    # 必答问题空回复必须拒绝
    with pytest.raises(ValueError, match="required"):
        runtime.answer_question(started.run_id, [])

    result = runtime.answer_question(started.run_id, ["是"])
    assert result["status"] == AgentRunStatus.SUCCEEDED.value
    assert adapter.calls[-1] == (None, ["是"])
    answered = runtime.store.list_questions(started.run_id)[0]
    assert answered["status"] == "answered"
    assert answered["answers"] == ["是"]
    # 挂起问题已清空，可再次启动新 run（严格串行门禁解除）
    assert runtime.store.get_open_question(started.run_id) is None
    messages = runtime.store.list_context_messages(thread_id)
    assert any("已完成" == item["content"] for item in messages)


def test_answer_question_rejects_non_waiting_run(tmp_path: Path):
    from cellwiki.domain.contracts import WikiAgentContext

    adapter = ScriptedAdapter(
        scripts=[[RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="ok")]]
    )
    runtime = AgentRuntimeManager(tmp_path, adapter=adapter)
    thread_id = f"thread_q_{abs(hash(tmp_path)) & 0xFFFF}"
    run = runtime.start(
        thread_id=thread_id,
        message="hi",
        context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
    )
    _wait_for_status(runtime, run.run_id, AgentRunStatus.SUCCEEDED)
    with pytest.raises(InvalidRunTransitionError):
        runtime.answer_question(run.run_id, "x")


def test_question_timeout_finalizes_unfinished(tmp_path: Path):
    adapter = QuestionCapableAdapter(
        scripts=[
            [
                RuntimeSignal(
                    type=AgentEventType.TASK_CONFIRMATION_REQUIRED,
                    message="Waiting for the user: 是否继续？",
                    data={
                        "interrupt": {
                            "question": "是否继续？",
                            "options": [],
                            "required": False,
                        }
                    },
                ),
            ],
        ],
        resume_script=[],
    )
    runtime = AgentRuntimeManager(tmp_path, adapter=adapter)
    thread_id = f"thread_q_{abs(hash(tmp_path)) & 0xFFFF}"
    run = runtime.start(
        thread_id=thread_id,
        message="开始",
        context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = runtime.store.get_run(run.run_id)
        if current is not None and current.status == AgentRunStatus.WAITING_CONFIRMATION:
            break
        time.sleep(0.02)
    result = runtime.answer_question(run.run_id, [], timed_out=True)
    assert result["status"] == AgentRunStatus.UNFINISHED.value
    assert runtime.store.get_run(run.run_id).status == AgentRunStatus.UNFINISHED
    question = runtime.store.list_questions(run.run_id)[0]
    assert question["status"] == "timed_out"


def test_interrupt_signal_parsing_translates_to_confirmation():
    # langgraph Interrupt 对象（含 value 包装）转 TASK_CONFIRMATION_REQUIRED 信号
    from cellwiki.services.agent_runtime import _signals_from_interrupt

    class FakeInterrupt:
        def __init__(self, value):
            self.value = value

    signals = _signals_from_interrupt(
        FakeInterrupt(
            {"type": "ask_user_question", "question": "继续吗？", "options": ["是", "否"], "required": True}
        )
    )
    assert len(signals) == 1
    assert signals[0].type == AgentEventType.TASK_CONFIRMATION_REQUIRED
    assert signals[0].data["interrupt"]["options"] == ["是", "否"]
    # 截断与清洗
    signals2 = _signals_from_interrupt(
        FakeInterrupt({"question": "x" * 2_500})
    )
    assert len(signals2[0].data["interrupt"]["question"]) <= 2_000


class _InterruptFakeModel(BaseChatModel):
    """真实 langgraph 图所用的假模型：第一次只发 ask_user_question 工具调用，续跑后发最终回答。"""

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "interrupt-fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_calls=[
                        {
                            "name": "ask_user_question",
                            "args": {"question": "继续吗？", "options": ["是", "否"]},
                            "id": "call_interrupt",
                            "type": "tool_call",
                        }
                    ],
                )
            )
        else:
            # 与真实协调器一致：最终回答走 submit_agent_answer（return_direct 工具）
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_calls=[
                        {
                            "name": "submit_agent_answer",
                            "args": {"answer": "已按你的选择完成", "file_paths": []},
                            "id": "call_final",
                            "type": "tool_call",
                        }
                    ],
                )
            )


def test_real_graph_interrupt_pause_and_command_resume(tmp_path: Path):
    # 端到端：生产路径 —— 真实 langgraph 图 + 工具 interrupt + Command(resume) 续跑
    from cellwiki.agent.app import build_wiki_agent

    (tmp_path / "wiki" / "cell_types").mkdir(parents=True, exist_ok=True)
    (tmp_path / "wiki" / "cell_types" / "a.md").write_text("# Alpha cell\n", encoding="utf-8")
    graph = build_wiki_agent(tmp_path, model=_InterruptFakeModel())
    runtime = AgentRuntimeManager(tmp_path, adapter=graph)
    thread_id = f"thread_graph_{abs(hash(str(tmp_path))) & 0xFFFF}"

    run = runtime.start(
        thread_id=thread_id,
        message="分析 alpha cell 后问我是否继续",
        context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = runtime.store.get_run(run.run_id)
        if current is not None and current.status == AgentRunStatus.WAITING_CONFIRMATION:
            break
        time.sleep(0.02)
    assert runtime.store.get_run(run.run_id).status == AgentRunStatus.WAITING_CONFIRMATION
    question = runtime.store.get_open_question(run.run_id)
    assert question is not None and question["question"] == "继续吗？"

    result = runtime.answer_question(run.run_id, "是")
    assert result["status"] == AgentRunStatus.SUCCEEDED.value
    messages = runtime.store.list_context_messages(thread_id)
    assert any("已按你的选择完成" in item["content"] for item in messages)
