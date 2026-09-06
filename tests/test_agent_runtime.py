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
        yield RuntimeSignal(type=AgentEventType.MESSAGE_DELTA, message="完成")

    def close(self) -> None:
        self.release.set()


def _context(thread_id: str = "thread_test") -> WikiAgentContext:
    return WikiAgentContext(project_id="cellwiki", thread_id=thread_id)


# 这些等待跨后台线程做真实的 git/SQLite/图执行工作。桌面同时跑 dev server + sidecar
# 时，WAITING_CONFIRMATION 一类状态转移实测要 5-11s，写死的 5s 墙会误报失败
# （HEAD 上同样复现），统一放宽到同一个常量。
WAIT_TIMEOUT = 20.0


def _wait_for_status(
    manager: AgentRuntimeManager,
    run_id: str,
    statuses: set[AgentRunStatus],
    timeout: float = WAIT_TIMEOUT,
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
    adapter = ScriptedAdapter([signals, [RuntimeSignal(type=AgentEventType.MESSAGE_DELTA, message="继续完成", model_call_id="resume_model")]])
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


def test_budget_abort_still_records_usage_and_model_spans(tmp_path: Path):
    """中止段落的记账必须落盘，且跨 resume 累加而不是覆盖。

    回归：预算/墙钟异常从消费循环内部抛出，循环之后的 model spans 与
    ``update_usage`` 因此被整段跳过 —— 实测一个跑了几百次模型调用的 run 最终
    ``model_calls=0``、一条 model span 都没有，观测面板与成本统计全盲。
    """
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
    adapter = ScriptedAdapter(
        [
            signals,
            [
                RuntimeSignal(
                    type=AgentEventType.MESSAGE_DELTA,
                    message="继续完成",
                    model_call_id="resume_model",
                    input_tokens=10,
                    output_tokens=10,
                )
            ],
        ]
    )
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_accounting",
            message="超预算",
            context=_context("thread_accounting"),
            budget=RunBudget(max_model_calls=3),
        )
        _wait_for_status(
            manager, started.run_id, {AgentRunStatus.UNFINISHED}
        )
        paused = manager.store.get_run(started.run_id)
        assert paused is not None
        # 被中止的 3 次调用全部记账，第 4 次从未开始所以不计。
        assert paused.usage.model_calls == 3
        assert paused.usage.input_tokens == 30
        assert paused.usage.output_tokens == 30
        assert any(
            span.kind == "model" for span in manager.store.list_spans(started.run_id)
        )

        manager.resume(started.run_id)
        completed = _wait_for_status(
            manager, started.run_id, {AgentRunStatus.SUCCEEDED}
        )
        # 累加而非覆盖：中止段 3 次 + 恢复段 1 次。
        assert completed.usage.model_calls == 4
        assert completed.usage.input_tokens == 40
        assert completed.usage.output_tokens == 40
    finally:
        manager.close()


def test_cancel_releases_gate_for_budget_parked_run(tmp_path: Path):
    """预算暂停的 run 必须仍可取消，否则严格串行门永远解不开。

    回归：finalize_run 见 finished_at 非空就抛 InvalidRunTransitionError，而暂停态
    本身已写过 finished_at，于是取消 parked run 的唯一入口恒失败（实测 POST
    /cancel 返回 500，工作区被永久卡住，只剩"继续"一条路）。
    """
    adapter = ScriptedAdapter(
        [
            [
                RuntimeSignal(
                    type=AgentEventType.MESSAGE_DELTA,
                    message="token",
                    model_call_id=f"model_call_{index}",
                )
                for index in range(6)
            ],
            [
                RuntimeSignal(
                    type=AgentEventType.FINAL_RESPONSE,
                    message="Done.",
                    data={"answer": "Done.", "file_paths": []},
                )
            ],
        ]
    )
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_parked",
            message="超预算",
            context=_context("thread_parked"),
            budget=RunBudget(max_model_calls=3),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.UNFINISHED})

        cancelled = manager.cancel(started.run_id)
        assert cancelled.status == AgentRunStatus.CANCELLED
        assert cancelled.finished_at is not None

        # 门确实开了：同一工作区再起一个 run 能跑完，而不是撞 AgentRunInProgressError。
        follow_up = manager.start(
            thread_id="thread_after_park",
            message="暂停之后继续用",
            context=_context("thread_after_park"),
        )
        completed = _wait_for_status(
            manager, follow_up.run_id, {AgentRunStatus.SUCCEEDED}
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


def test_signals_from_stream_item_emits_tool_lifecycle_and_text_chunks():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "read_wiki_page", "args": {}, "id": "call_x", "type": "tool_call"}]),
        ToolMessage(content='{"results": ["wiki/a.md"]}', tool_call_id="call_x", name="ls"),
    ]
    signals = list(_signals_from_stream_item(("messages", (messages[0], {}))))
    signals += list(_signals_from_stream_item(("messages", (messages[1], {}))))
    types = [signal.type for signal in signals]
    assert AgentEventType.TOOL_STARTED in types
    assert AgentEventType.TOOL_COMPLETED in types
    completed = next(signal for signal in signals if signal.type == AgentEventType.TOOL_COMPLETED)
    # 工具结果按设计只保留一行人类可读摘要，原始输出不落事件
    assert "1 results" in completed.message
    assert "wiki/a.md" not in completed.message

    text_signals = list(_signals_from_stream_item((
        "messages",
        (AIMessageChunk(content="普通回答"), {"thread_id": "t"}),
    )))
    assert len(text_signals) == 1
    assert text_signals[0].type == AgentEventType.MESSAGE_DELTA
    assert text_signals[0].message == "普通回答"


def test_streamed_text_is_preserved_as_final_response(tmp_path: Path):
    adapter = ScriptedAdapter([[
        RuntimeSignal(
            type=AgentEventType.MESSAGE_DELTA,
            message="第一段 ",
            model_call_id="model_1",
        ),
        RuntimeSignal(
            type=AgentEventType.MESSAGE_DELTA,
            message="最终答案",
            model_call_id="model_1",
        ),
    ]])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_text_answer",
            message="直接回答",
            context=_context("thread_text_answer"),
        )
        completed = _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        assert completed.usage.model_calls == 1
        messages = manager.store.list_context_messages("thread_text_answer")
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"] == "第一段 最终答案"
        events = manager.store.list_events(started.run_id)
        assert [event.type for event in events].count(AgentEventType.MESSAGE_DELTA) == 2
        final = next(event for event in events if event.type == AgentEventType.FINAL_RESPONSE)
        assert final.message == "第一段 最终答案"
        assert final.data["label_args"]["answer"] == "第一段 最终答案"
    finally:
        manager.close()


def test_run_without_textual_answer_is_failed(tmp_path: Path):
    manager = AgentRuntimeManager(
        tmp_path,
        adapter=ScriptedAdapter([[RuntimeSignal(type=AgentEventType.PROGRESS, progress=100)]]),
    )
    try:
        started = manager.start(
            thread_id="thread_empty_answer",
            message="没有答案",
            context=_context("thread_empty_answer"),
        )
        failed = _wait_for_status(manager, started.run_id, {AgentRunStatus.FAILED})
        assert failed.error_type == AgentErrorType.SYSTEM
        assert failed.error_message == "Agent completed without a textual answer."
        assert not any(
            item["role"] == "assistant"
            for item in manager.store.list_context_messages("thread_empty_answer")
        )
    finally:
        manager.close()


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


def test_pending_diff_lifecycle_accept_reject_are_irreversible(tmp_path: Path):
    """一个 run 一份判定：接受与拒绝各自终结自己的单元，判定之后不可回退。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    counter = {"n": 0}

    class WritingAdapter:
        def execute(self, *, thread_id, message, context) -> Any:
            counter["n"] += 1
            name = f"note_{counter['n']}.md"
            (repo / name).write_text(f"agent note {counter['n']}", encoding="utf-8")
            git = GitExecutor(repo)
            git.run("add", name)
            git.run("commit", "-m", f"agent change {counter['n']}")
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
        assert diff.diff_id == f"diff_{started.run_id}_1"
        assert diff.status == PendingDiffStatus.PENDING
        assert diff.commits, "运行产出的 commit 应被收集"
        patch = manager.pending_diff_patch(diff.diff_id)
        assert "note_1.md" in patch and "agent note 1" in patch
        assert (repo / "note_1.md").exists()
        # accept：commit 保留，审计生效；判定不可回退（reopen / reject 都拒绝）
        accepted = manager.accept_pending_diff(diff.diff_id)
        assert accepted.status == PendingDiffStatus.ACCEPTED
        assert (repo / "note_1.md").exists()
        with pytest.raises(InvalidRunTransitionError):
            manager.reopen_pending_diff(diff.diff_id)
        with pytest.raises(InvalidRunTransitionError):
            manager.reject_pending_diff(diff.diff_id)
        with pytest.raises(InvalidRunTransitionError):
            manager.accept_pending_diff(diff.diff_id)
        assert manager.store.get_pending_diff(diff.diff_id).status == (
            PendingDiffStatus.ACCEPTED
        )

        # 第二个 run 产生自己独立的单元；reject 逐个 revert 本单元 commit。
        second = manager.start(thread_id="t_diff", message="再写一篇", context=_context("t_diff"))
        _wait_for_status(manager, second.run_id, {AgentRunStatus.SUCCEEDED})
        second_diff = _wait_for_diff(manager, second.run_id)[0]
        assert second_diff.diff_id == f"diff_{second.run_id}_1"
        rejected = manager.reject_pending_diff(second_diff.diff_id)
        assert rejected.status == PendingDiffStatus.REJECTED
        assert not (repo / "note_2.md").exists(), "reject 后 note_2.md 应被回滚删除"
        assert (repo / "note_1.md").exists(), "reject 只撤销本单元，不伤已批准内容"
        with pytest.raises(InvalidRunTransitionError):
            manager.reject_pending_diff(second_diff.diff_id)
        with pytest.raises(InvalidRunTransitionError):
            manager.reopen_pending_diff(second_diff.diff_id)
    finally:
        manager.close()


def test_budget_park_publishes_one_approval_unit_per_verdict(tmp_path: Path):
    """预算暂停的 run 每段一个审批单元：已批准的提交不再出现在后续单元里。

    回归：diff 固定一行、基线停在 run 起点，于是"暂停 -> 接受 -> 继续"的 run
    第二次发布的 diff 仍包含第一段已批准的 commit（实测 4 段 run 的待判 diff
    列出 7 个 commit、其中 5 个已批准过），点"拒绝"连带回滚已批准页面。
    方案 B 下每次判定后的重发布生成 `diff_<run_id>_<n+1>` 新行，基线 = 上一单元
    head；拒绝严格限定在自己的提交上。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    class SegmentWriter:
        """每段写一个新页面，段内超出模型调用预算而被中止（模拟批量 ingest）。"""

        def __init__(self) -> None:
            self.segment = 0

        def execute(self, *, thread_id, message, context) -> Any:
            self.segment += 1
            name = f"note_{self.segment}.md"
            (repo / name).write_text(f"segment {self.segment}", encoding="utf-8")
            git = GitExecutor(repo)
            git.run("add", name)
            git.run("commit", "-m", f"agent change {self.segment}")
            # 3 次调用 > 预算 2：第 3 次前中止，保证两段都以 unfinished 结束。
            for index in range(3):
                yield RuntimeSignal(
                    type=AgentEventType.MESSAGE_DELTA,
                    message="token",
                    data={},
                    model_call_id=f"seg{self.segment}_call{index}",
                    input_tokens=5,
                    output_tokens=5,
                )

    manager = AgentRuntimeManager(repo, adapter=SegmentWriter())
    try:
        started = manager.start(
            thread_id="thread_units",
            message="逐段导入",
            context=_context("thread_units"),
            budget=RunBudget(max_model_calls=2),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.UNFINISHED})
        first = _wait_for_diff(manager, started.run_id)[0]
        assert first.diff_id == f"diff_{started.run_id}_1"
        assert len(first.commits) == 1, first.commits

        accepted = manager.accept_pending_diff(first.diff_id)
        assert accepted.status == PendingDiffStatus.ACCEPTED
        # 接受必须幂等：重复接受不得再产生一次判定与维护记录。
        with pytest.raises(InvalidRunTransitionError):
            manager.accept_pending_diff(first.diff_id)

        manager.resume(started.run_id)
        _wait_for_status(manager, started.run_id, {AgentRunStatus.UNFINISHED})
        # 第二单元是独立新行；等待的是"出现序号 2 的行"，不是旧行内容被换掉。
        deadline = time.monotonic() + WAIT_TIMEOUT
        units = manager.store.list_pending_diffs(run_id=started.run_id)
        while time.monotonic() < deadline and len(units) < 2:
            time.sleep(0.05)
            units = manager.store.list_pending_diffs(run_id=started.run_id)
        assert len(units) == 2, units
        second = manager.store.get_pending_diff(f"diff_{started.run_id}_2")
        assert second.status == PendingDiffStatus.PENDING
        assert second.diff_id != first.diff_id
        # 上一单元保持 accepted，不被重发布改写。
        assert manager.store.get_pending_diff(first.diff_id).status == (
            PendingDiffStatus.ACCEPTED
        )
        assert len(second.commits) == 1, second.commits
        assert second.commits != first.commits
        assert second.snapshot_commit == first.head_commit
        # 用结构化 files 断言：补丁文本里维护日志可能提到已批准的文件名。
        assert any(path.endswith("note_2.md") for path in second.files)
        assert not any(path.endswith("note_1.md") for path in second.files), (
            "已批准内容不得重新进入待判 diff"
        )
        # 任一时刻最多一个未判定单元（严格串行不变量）。
        current_units = manager.store.list_pending_diffs(run_id=started.run_id)
        pending_now = [d for d in current_units if d.status == PendingDiffStatus.PENDING]
        assert [d.diff_id for d in pending_now] == [second.diff_id]

        # 拒绝单元 2 只撤销单元 2：单元 1（已批准）必须活下来。
        manager.reject_pending_diff(second.diff_id)
        assert (repo / "note_1.md").exists(), "拒绝不应回滚已批准内容"
        assert not (repo / "note_2.md").exists()
        # 拒绝生成的 revert 提交记入单元行，供后续单元排除。
        rejected_second = manager.store.get_pending_diff(second.diff_id)
        revert_shas = rejected_second.data.get("revert_commits")
        assert revert_shas, rejected_second.data

        # 继续第三段：单元 3 不得装入单元 2 的 revert 提交，否则"拒绝单元 3"
        # 会把"单元 2 的回滚"再次回滚（note_2.md 复活 = 撤销已判定内容）。
        manager.resume(started.run_id)
        _wait_for_status(manager, started.run_id, {AgentRunStatus.UNFINISHED})
        # 发布在状态落库之后的 finally 里（还要跑 git），轮询等单元 3 出现。
        deadline = time.monotonic() + WAIT_TIMEOUT
        third_id = f"diff_{started.run_id}_3"
        while True:
            try:
                third = manager.store.get_pending_diff(third_id)
                break
            except KeyError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        assert third.status == PendingDiffStatus.PENDING
        assert third.snapshot_commit == second.head_commit
        assert len(third.commits) == 1, third.commits
        assert set(third.commits).isdisjoint(revert_shas)
        assert any(path.endswith("note_3.md") for path in third.files)
        manager.reject_pending_diff(third.diff_id)
        assert not (repo / "note_3.md").exists()
        assert not (repo / "note_2.md").exists(), "拒绝单元 3 不得回滚单元 2 的撤销"
        assert (repo / "note_1.md").exists()
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


def test_pending_diff_patch_not_truncated_for_large_diff(tmp_path: Path):
    """审查 UI 的 patch 使用独立 executor，不被 Agent 默认 200KB 输出上限截断。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    class BulkAdapter:
        def execute(self, *, thread_id, message, context) -> Any:
            lines = [f"line {i:08d} payload" for i in range(20_000)]
            (repo / "large.md").write_text("\n".join(lines), encoding="utf-8")
            git = GitExecutor(repo)
            git.run("add", "large.md")
            git.run("commit", "-m", "bulk change")
            yield RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE, message="done", data={}
            )

    manager = AgentRuntimeManager(repo, adapter=BulkAdapter())
    try:
        started = manager.start(thread_id="t_bulk", message="写入大文件", context=_context("t_bulk"))
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        diffs = manager.store.list_pending_diffs(run_id=started.run_id)
        for _ in range(100):
            if diffs:
                break
            time.sleep(0.02)
            diffs = manager.store.list_pending_diffs(run_id=started.run_id)
        assert len(diffs) == 1, diffs
        patch = manager.pending_diff_patch(diffs[0].diff_id)
        # 补丁超过默认 200KB 上限仍应完整返回（含尾部内容，证明未被截断）
        assert len(patch) > 200_000
        assert "line 00019999 payload" in patch
    finally:
        manager.close()


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

    deadline = time.monotonic() + WAIT_TIMEOUT
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
    # 阶段 E：答题只登记答案并把 run 转回 RUNNING 就返回，续跑在执行器线程上跑完。
    assert result["status"] == AgentRunStatus.RUNNING.value
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        if runtime.store.get_run(started.run_id).status == AgentRunStatus.SUCCEEDED:
            break
        time.sleep(0.02)
    assert runtime.store.get_run(started.run_id).status == AgentRunStatus.SUCCEEDED
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
    deadline = time.monotonic() + WAIT_TIMEOUT
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


def test_cancel_waiting_confirmation_closes_question_and_releases_gate(tmp_path: Path):
    # 用户主动取消等待回答的 run：问题关闭、run 直接终结为 CANCELLED，串行闸门释放
    adapter = QuestionCapableAdapter(
        scripts=[
            [
                RuntimeSignal(
                    type=AgentEventType.TASK_CONFIRMATION_REQUIRED,
                    message="Waiting for the user: 是否继续？",
                    data={
                        "interrupt": {
                            "question": "是否继续？",
                            "options": ["是", "否"],
                            "required": True,
                        }
                    },
                ),
            ],
            [RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="ok")],
        ],
        resume_script=[],
    )
    runtime = AgentRuntimeManager(tmp_path, adapter=adapter)
    thread_id = f"thread_q_{abs(hash(tmp_path)) & 0xFFFF}"
    try:
        started = runtime.start(
            thread_id=thread_id,
            message="开始",
            context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
        )
        deadline = time.monotonic() + WAIT_TIMEOUT
        while time.monotonic() < deadline:
            current = runtime.store.get_run(started.run_id)
            if current is not None and current.status == AgentRunStatus.WAITING_CONFIRMATION:
                break
            time.sleep(0.02)
        assert runtime.store.get_run(started.run_id).status == AgentRunStatus.WAITING_CONFIRMATION

        cancelled = runtime.cancel(started.run_id)
        assert cancelled.status == AgentRunStatus.CANCELLED
        assert runtime.store.get_run(started.run_id).status == AgentRunStatus.CANCELLED
        # 未回答的问题被关闭，不再作为 open question 阻塞
        assert runtime.store.get_open_question(started.run_id) is None

        # 串行闸门释放：可再次启动新 run 并正常结束
        again = runtime.start(
            thread_id=thread_id,
            message="再来",
            context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
        )
        _wait_for_status(runtime, again.run_id, {AgentRunStatus.SUCCEEDED})
    finally:
        runtime.close()


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
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="已按你的选择完成")
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
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        current = runtime.store.get_run(run.run_id)
        if current is not None and current.status == AgentRunStatus.WAITING_CONFIRMATION:
            break
        time.sleep(0.02)
    assert runtime.store.get_run(run.run_id).status == AgentRunStatus.WAITING_CONFIRMATION
    question = runtime.store.get_open_question(run.run_id)
    assert question is not None and question["question"] == "继续吗？"

    result = runtime.answer_question(run.run_id, "是")
    # 阶段 E：答题立即返回，续跑段在执行器线程上跑完。
    assert result["status"] == AgentRunStatus.RUNNING.value
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        if runtime.store.get_run(run.run_id).status == AgentRunStatus.SUCCEEDED:
            break
        time.sleep(0.02)
    assert runtime.store.get_run(run.run_id).status == AgentRunStatus.SUCCEEDED
    messages = runtime.store.list_context_messages(thread_id)
    assert any("已按你的选择完成" in item["content"] for item in messages)

def test_pending_diff_published_when_workspace_had_no_commits(tmp_path: Path):
    """Bug 回归：fresh 工作区（无初始 commit）的首个 Agent 提交也必须发布待确认 diff。"""
    from cellwiki.services.workspace import ensure_workspace

    repo = tmp_path / "repo"
    repo.mkdir()
    ensure_workspace(repo)  # 初始化但无初始 commit -> run 快照为 None

    class FirstWritingAdapter:
        def execute(self, *, thread_id, message, context) -> Any:
            (repo / "note.md").write_text("agent first change", encoding="utf-8")
            git = GitExecutor(repo)
            git.run("add", "note.md")
            git.run("commit", "-m", "first agent change")
            yield RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE, message="done", data={}
            )

    manager = AgentRuntimeManager(repo, adapter=FirstWritingAdapter())
    try:
        started = manager.start(
            thread_id="t_first", message="写笔记", context=_context("t_first")
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        diffs = manager.store.list_pending_diffs(run_id=started.run_id)
        for _ in range(100):
            if diffs:
                break
            time.sleep(0.02)
            diffs = manager.store.list_pending_diffs(run_id=started.run_id)
        assert len(diffs) == 1, diffs
        diff = diffs[0]
        assert diff.snapshot_commit is None
        assert diff.commits, "首个 commit 应被收集"
        assert (repo / "note.md").exists()
        accepted = manager.accept_pending_diff(diff.diff_id)
        assert accepted.status == PendingDiffStatus.ACCEPTED
    finally:
        manager.close()

def test_pending_diff_blocks_new_run_until_resolved(tmp_path: Path):
    """pending diff 门禁：存在未审 PENDING diff 时，新 run（含只读）被拒绝；
    接受 diff 后可以继续。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    class WritingAdapter:
        def execute(self, *, thread_id, message, context) -> Any:
            (repo / "note.md").write_text("agent note", encoding="utf-8")
            git = GitExecutor(repo)
            git.run("add", "note.md")
            git.run("commit", "-m", "agent change")
            yield RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE, message="done", data={}
            )

    manager = AgentRuntimeManager(repo, adapter=WritingAdapter())
    try:
        started = manager.start(
            thread_id="t_gate_diff", message="写笔记", context=_context("t_gate_diff")
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        diffs = manager.store.list_pending_diffs(run_id=started.run_id)
        for _ in range(100):
            if diffs:
                break
            time.sleep(0.02)
            diffs = manager.store.list_pending_diffs(run_id=started.run_id)
        assert len(diffs) == 1
        # PENDING diff 阻塞新 run
        with pytest.raises(AgentRunInProgressError):
            manager.start(
                thread_id="t_gate_diff2", message="只读", context=_context("t_gate_diff2")
            )
        # 接受后放行
        manager.accept_pending_diff(diffs[0].diff_id)
        read_only = manager.start(
            thread_id="t_gate_diff3", message="只读", context=_context("t_gate_diff3")
        )
        assert read_only.status in (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING)
    finally:
        manager.close()


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ADR-0009：判定时维护 + 系统维护 commit
# ---------------------------------------------------------------------------


def _wait_for_diff(manager: AgentRuntimeManager, run_id: str):
    diffs = manager.store.list_pending_diffs(run_id=run_id)
    for _ in range(int(WAIT_TIMEOUT / 0.02)):
        if diffs:
            return diffs
        time.sleep(0.02)
        diffs = manager.store.list_pending_diffs(run_id=run_id)
    return diffs


def _wait_for_file_text(path: Path, fragment: str) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for _ in range(int(WAIT_TIMEOUT / 0.02)):
        if fragment in text:
            return text
        time.sleep(0.02)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    return text


def _wait_for_maintenance_subject(repo: Path, fragment: str) -> list[str]:
    subjects: list[str] = []
    # 每轮都要跑一次 git log，用 0.1s 间隔凑满同一个等待上限，避免空转打满 CPU。
    for _ in range(int(WAIT_TIMEOUT / 0.1)):
        subjects = [
            line.split(" ", 1)[-1]
            for line in GitExecutor(repo).run("log", "--oneline").splitlines()
            if line.split(" ", 1)[-1].startswith("chore(system): maintenance")
        ]
        if any(fragment in line for line in subjects):
            return subjects
        time.sleep(0.1)
    return subjects


class _MaintenanceWritingAdapter:
    """Write one wiki page with distinct content per call, commit, then finish."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.calls = 0

    def execute(self, *, thread_id, message, context) -> Any:
        self.calls += 1
        wiki = self.repo / "wiki" / "cell_types"
        wiki.mkdir(parents=True, exist_ok=True)
        (wiki / "alpha-cell.md").write_text(
            f"# Alpha Cell\n\nbody-{self.calls}\n", encoding="utf-8"
        )
        git = GitExecutor(self.repo)
        git.run("add", "wiki/cell_types/alpha-cell.md")
        git.run("commit", "-m", f"agent change {self.calls}")
        yield RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="done", data={})


def test_accept_publishes_pending_diff_without_system_files_and_runs_maintenance(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    manager = AgentRuntimeManager(repo, adapter=_MaintenanceWritingAdapter(repo))
    try:
        started = manager.start(
            thread_id="t_maint", message="写条目", context=_context("t_maint")
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        diffs = _wait_for_diff(manager, started.run_id)
        assert len(diffs) == 1, diffs
        diff = diffs[0]
        # 待审补丁不含任何系统维护文件
        patch = manager.pending_diff_patch(diff.diff_id)
        for name in ("overview.md", "statistics.md", "log.md", "audit_report.md"):
            assert name not in patch, name
        assert "alpha-cell.md" in patch
        # 强制 lint 快照已追加到 audit_report.md（run 收尾线程异步，轮询等待）
        audit = _wait_for_file_text(
            repo / "audit_report.md", started.run_id
        )
        assert "Audit snapshot" in audit
        # 接受 -> 派生重建 + log 记录 + 系统维护 commit
        accepted = manager.accept_pending_diff(diff.diff_id)
        assert accepted.status == PendingDiffStatus.ACCEPTED
        assert "知识条目总数" in (repo / "overview.md").read_text(encoding="utf-8")
        assert "| **总计** |" in (repo / "statistics.md").read_text(encoding="utf-8")
        assert f"accepted | run {started.run_id}" in (repo / "log.md").read_text(encoding="utf-8")
        subjects = _wait_for_maintenance_subject(repo, "(accepted)")
        assert any("run " + started.run_id in line for line in subjects)
        events = manager.store.list_events(started.run_id)
        assert any(ev.data.get("kind") == "maintenance" for ev in events)
    finally:
        manager.close()


def test_reject_reverts_agent_commits_and_keeps_audit_record(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    manager = AgentRuntimeManager(repo, adapter=_MaintenanceWritingAdapter(repo))
    try:
        started = manager.start(
            thread_id="t_rej", message="写条目", context=_context("t_rej")
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        diffs = _wait_for_diff(manager, started.run_id)
        assert len(diffs) == 1, diffs
        diff = diffs[0]
        # 等审计快照落盘后再读基线
        _wait_for_file_text(repo / "audit_report.md", started.run_id)
        audit_before = (repo / "audit_report.md").read_text(encoding="utf-8")
        rejected = manager.reject_pending_diff(diff.diff_id)
        assert rejected.status == PendingDiffStatus.REJECTED
        # Agent 内容被回滚，审计记录与 log 拒绝记录保留
        assert not (repo / "wiki" / "cell_types" / "alpha-cell.md").exists()
        assert (repo / "audit_report.md").read_text(encoding="utf-8") == audit_before
        assert f"rejected | run {started.run_id}" in (repo / "log.md").read_text(encoding="utf-8")
    finally:
        manager.close()


def test_unfinished_run_appends_pause_log(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
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
    adapter = ScriptedAdapter([signals])
    manager = AgentRuntimeManager(repo, adapter=adapter)
    try:
        started = manager.start(
            thread_id="t_uf",
            message="超预算",
            context=_context("t_uf"),
            budget=RunBudget(max_model_calls=3),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.UNFINISHED})
        log = _wait_for_file_text(repo / "log.md", f"unfinished | run {started.run_id}")
        assert "unfinished" in log
    finally:
        manager.close()


def test_maintenance_failure_does_not_block_verdict_and_retries_at_next_start(
    tmp_path: Path,
    monkeypatch,
):
    from cellwiki.services import agent_runtime as runtime_mod

    original = runtime_mod.maintain_after_accept
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    manager = AgentRuntimeManager(repo, adapter=_MaintenanceWritingAdapter(repo))
    try:
        started = manager.start(
            thread_id="t_fail", message="写条目", context=_context("t_fail")
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        diffs = _wait_for_diff(manager, started.run_id)
        assert len(diffs) == 1, diffs
        diff = diffs[0]

        def boom(*args, **kwargs):
            raise RuntimeError("simulated maintenance failure")

        monkeypatch.setattr(runtime_mod, "maintain_after_accept", boom)
        accepted = manager.accept_pending_diff(diff.diff_id)
        # 判定不被维护失败阻塞
        assert accepted.status == PendingDiffStatus.ACCEPTED
        marked = manager.store.get_pending_diff(diff.diff_id)
        assert marked.data["maintenance"]["status"] == "failed"
        events = manager.store.list_events(started.run_id)
        assert any(ev.data.get("kind") == "maintenance_failed" for ev in events)
        # 六根文件存在但仅模板：维护重建标记未写入
        overview = (repo / "overview.md").read_text(encoding="utf-8")
        assert "知识条目总数" not in overview

        # 恢复维护函数，下一次 run 启动自动重试成功
        monkeypatch.setattr(runtime_mod, "maintain_after_accept", original)
        resumed = manager.start(
            thread_id="t_retry", message="触发重试", context=_context("t_retry")
        )
        _wait_for_file_text(repo / "overview.md", "知识条目总数")
        assert f"accepted | run {started.run_id}" in (repo / "log.md").read_text(encoding="utf-8")
        marked = manager.store.get_pending_diff(diff.diff_id)
        assert marked.data["maintenance"]["status"] == "ok"
        _wait_for_status(manager, resumed.run_id, {AgentRunStatus.SUCCEEDED})
    finally:
        manager.close()

def test_foreign_staged_does_not_block_accept_and_warning_is_actionable(
    tmp_path: Path,
):
    """方案 D 现场回归：中止 run 留下的外来暂存不再卡死接受判定与维护。

    实测：批量 ingest 预算中止时 index 里留有 staged 文件，之后每次接受都
    maintenance_failed（"unexpected staged changes"），派生文件永久过期。
    现在维护提交路径限定：自己的派生文件照常 commit，stray 原样留在暂存区，
    事件里带文件清单（可执行提示），而不是笼统的 "will retry"。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    manager = AgentRuntimeManager(repo, adapter=_MaintenanceWritingAdapter(repo))
    try:
        started = manager.start(
            thread_id="t_foreign", message="写条目", context=_context("t_foreign")
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        diff = _wait_for_diff(manager, started.run_id)[0]

        git = GitExecutor(repo)
        (repo / "stray.md").write_text("user staged", encoding="utf-8")
        git.run("add", "stray.md")

        accepted = manager.accept_pending_diff(diff.diff_id)
        assert accepted.status == PendingDiffStatus.ACCEPTED
        marked = manager.store.get_pending_diff(diff.diff_id)
        marker = marked.data["maintenance"]
        assert marker["status"] == "ok", marker
        assert "stray.md" in marker.get("foreign_staged", []), marker
        # 派生文件真的被维护重建并提交了。
        assert "知识条目总数" in (repo / "overview.md").read_text(encoding="utf-8")
        # stray 没有被系统提交，也仍留在暂存区。
        status = git.run("status", "--short")
        assert any(
            line.startswith("A ") and line[3:] == "stray.md"
            for line in status.splitlines()
        ), status
        events = manager.store.list_events(started.run_id)
        maintenance_events = [
            ev for ev in events if ev.data.get("kind") == "maintenance"
        ]
        assert any("stray.md" in ev.message for ev in maintenance_events), [
            ev.message for ev in maintenance_events
        ]
    finally:
        manager.close()


class _TypewriterFakeModel(BaseChatModel):
    """逐 token 流式回归样板：每次调用按多个 chunk 吐出正文。

    模拟流式打开后的真实行为：chunk 共享同一消息 id（聚合与去重依赖它），
    运行时必须把每个 chunk 落成独立的 message_delta 事件。
    """

    @property
    def _llm_type(self) -> str:
        return "typewriter-fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(content="第一句第二句第三句", id="call_typewriter")
                )
            ]
        )

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for token in ("第一句", "第二句", "第三句"):
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=token, id="call_typewriter")
            )


def test_real_graph_streams_multiple_message_deltas(tmp_path: Path):
    """逐 token 流式契约（design/active/2026-08-27-agent-token-streaming.md）：
    模型按多 chunk 流式输出时，事件表必须出现多条 message_delta，
    而不是旧行为里每次调用一条聚合块。"""
    from cellwiki.agent.app import build_wiki_agent

    (tmp_path / "wiki").mkdir(parents=True, exist_ok=True)
    graph = build_wiki_agent(tmp_path, model=_TypewriterFakeModel())
    runtime = AgentRuntimeManager(tmp_path, adapter=graph)
    try:
        thread_id = "thread_typewriter"
        run = runtime.start(
            thread_id=thread_id,
            message="流式说一句",
            context=_context(thread_id),
        )
        _wait_for_status(runtime, run.run_id, {AgentRunStatus.SUCCEEDED})
        events = runtime.store.list_events(run.run_id)
        deltas = [event for event in events if event.type == AgentEventType.MESSAGE_DELTA]
        assert len(deltas) >= 3, [event.message for event in deltas]
        assert "".join(event.message for event in deltas) == "第一句第二句第三句"
    finally:
        runtime.close()
