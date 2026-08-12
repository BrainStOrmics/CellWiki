# =============================================================================
# 智能体运行时测试 —— 验证智能体运行和事件存储
# =============================================================================

from __future__ import annotations

import threading
import time
import sqlite3
from pathlib import Path
from typing import Iterable, TypedDict

import pytest
from langgraph.types import Command
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentEventType,
    AgentRunStatus,
    RunBudget,
)
from cellwiki.domain.memory import MemoryCandidate, MemoryKind
from cellwiki.services.agent_runtime import (
    AgentRuntimeManager,
    DeepAgentsExecutionAdapter,
    RuntimeSignal,
    _allows_attachment_promotion,
    _signals_from_stream_item,
    classify_agent_error,
)
from cellwiki.services.memory import MemoryStore
from cellwiki.services.attachments import AttachmentService
from cellwiki.services.operations import (
    CancellationRegistry,
    OperationCancelled,
    current_agent_run_id,
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


def test_attachment_promotion_intent_requires_an_explicit_mutating_request():
    assert not _allows_attachment_promotion("这篇文章里提到了什么细胞类型？")
    assert not _allows_attachment_promotion(
        "请只根据附件回答，不要注册 source，不要 ingest，不要创建 ChangeSet。"
    )
    assert _allows_attachment_promotion("请把这个附件注册为 source 并 ingest。")


def test_runtime_persists_and_injects_referenced_attachment_context(tmp_path: Path):
    thread_id = "thread_" + "1" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 marks regulatory T cells.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    adapter = ScriptedAdapter([[
        RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="Done.",
            data={"answer": "Done.", "knowledge_scope": "attachment"},
        ),
    ]])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id=thread_id,
            message="这篇文章里有什么细胞类型？",
            context=WikiAgentContext(
                project_id="cellwiki",
                thread_id=thread_id,
                attachment_ids=[attachment.attachment_id],
            ),
        )
        completed = _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})

        assert completed.attachment_ids == [attachment.attachment_id]
        assert adapter.calls
        first_message = adapter.calls[0][0]
        assert first_message["role"] == "system"
        assert attachment.attachment_id in first_message["content"]
        assert "read_attachment_excerpt" in first_message["content"]
        assert adapter.contexts[0].allow_attachment_promotion is False
    finally:
        manager.close()


def test_runtime_reuses_attachment_from_prior_message_without_reupload(tmp_path: Path):
    thread_id = "thread_" + "2" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 marks regulatory T cells.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    adapter = ScriptedAdapter([
        [RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="First answer.")],
        [RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="Follow-up answer.")],
    ])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        first = manager.start(
            thread_id=thread_id,
            message="What cell type is mentioned?",
            context=WikiAgentContext(
                project_id="cellwiki",
                thread_id=thread_id,
                attachment_ids=[attachment.attachment_id],
            ),
        )
        _wait_for_status(manager, first.run_id, {AgentRunStatus.SUCCEEDED})

        second = manager.start(
            thread_id=thread_id,
            message="Where is that evidence in the same paper?",
            context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
        )
        completed = _wait_for_status(manager, second.run_id, {AgentRunStatus.SUCCEEDED})

        assert completed.attachment_ids == [attachment.attachment_id]
        assert len(adapter.calls) == 2
        assert attachment.attachment_id in adapter.calls[1][0]["content"]
        messages = manager.store.list_messages(thread_id)
        assert messages[0]["data"]["attachments"][0]["attachment_id"] == attachment.attachment_id
        assert messages[2]["data"] == {}
    finally:
        manager.close()


def test_runtime_reuses_attachment_after_manager_restart(tmp_path: Path):
    """A fresh runtime instance must recover attachment IDs from the transcript."""

    thread_id = "thread_" + "3" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 marks regulatory T cells.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )

    first_adapter = ScriptedAdapter([[
        RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="First answer."),
    ]])
    first_manager = AgentRuntimeManager(tmp_path, adapter=first_adapter)
    try:
        first = first_manager.start(
            thread_id=thread_id,
            message="What cell type is mentioned?",
            context=WikiAgentContext(
                project_id="cellwiki",
                thread_id=thread_id,
                attachment_ids=[attachment.attachment_id],
            ),
        )
        _wait_for_status(first_manager, first.run_id, {AgentRunStatus.SUCCEEDED})
    finally:
        first_manager.close()

    second_adapter = ScriptedAdapter([[
        RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="Follow-up answer."),
    ]])
    second_manager = AgentRuntimeManager(tmp_path, adapter=second_adapter)
    try:
        second = second_manager.start(
            thread_id=thread_id,
            message="Where is that evidence in the same paper?",
            context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
        )
        completed = _wait_for_status(second_manager, second.run_id, {AgentRunStatus.SUCCEEDED})

        assert completed.attachment_ids == [attachment.attachment_id]
        assert attachment.attachment_id in second_adapter.calls[0][0]["content"]
        assert second_manager.store.list_messages(thread_id)[0]["data"]["attachments"][0][
            "attachment_id"
        ] == attachment.attachment_id
    finally:
        second_manager.close()


def test_runtime_keeps_sent_attachment_metadata_when_run_fails(tmp_path: Path):
    thread_id = "thread_" + "f" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 marks regulatory T cells.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    manager = AgentRuntimeManager(tmp_path, adapter=ScriptedAdapter([RuntimeError("provider failed")]))
    try:
        started = manager.start(
            thread_id=thread_id,
            message="Read the attached notes.",
            context=WikiAgentContext(
                project_id="cellwiki",
                thread_id=thread_id,
                attachment_ids=[attachment.attachment_id],
            ),
        )
        failed = _wait_for_status(manager, started.run_id, {AgentRunStatus.FAILED})

        assert failed.status == AgentRunStatus.FAILED
        messages = manager.store.list_messages(thread_id)
        assert messages[0]["data"]["attachments"][0]["attachment_id"] == attachment.attachment_id
    finally:
        manager.close()


def test_runtime_keeps_sent_attachment_metadata_when_run_is_cancelled(tmp_path: Path):
    thread_id = "thread_" + "4" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 marks regulatory T cells.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    adapter = BlockingAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id=thread_id,
            message="Read the attached notes.",
            context=WikiAgentContext(
                project_id="cellwiki",
                thread_id=thread_id,
                attachment_ids=[attachment.attachment_id],
            ),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.RUNNING})
        manager.cancel(started.run_id)
        adapter.release.set()
        cancelled = _wait_for_status(manager, started.run_id, {AgentRunStatus.CANCELLED})

        assert cancelled.status == AgentRunStatus.CANCELLED
        assert manager.store.list_messages(thread_id)[0]["data"]["attachments"][0][
            "attachment_id"
        ] == attachment.attachment_id
    finally:
        manager.close()


def test_runtime_downgrades_unvalidated_final_answer_confidence(tmp_path: Path):
    thread_id = "thread_" + "c" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 marks regulatory T cells.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    adapter = ScriptedAdapter([[
        RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="The attachment mentions regulatory T cells.",
            data={
                "answer": "The attachment mentions regulatory T cells.",
                "citations": [{"attachment_id": attachment.attachment_id}],
                "confidence": "high",
                "knowledge_scope": "attachment",
                "verification_level": "unvalidated",
            },
        ),
    ]])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id=thread_id,
            message="Read the attached notes.",
            context=WikiAgentContext(
                project_id="cellwiki",
                thread_id=thread_id,
                attachment_ids=[attachment.attachment_id],
            ),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})

        assistant = manager.store.list_messages(thread_id)[1]
        assert assistant["data"]["confidence"] == "low"
        assert assistant["data"]["declared_confidence"] == "high"
        assert assistant["data"]["verification_level"] == "unvalidated"
    finally:
        manager.close()


def _wait_for_status(
    manager: AgentRuntimeManager,
    run_id: str,
    statuses: set[AgentRunStatus],
    timeout: float = 3,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = manager.store.get_run(run_id)
        if run.status in statuses:
            return run
        time.sleep(0.01)
    raise AssertionError(f"run did not reach {statuses}: {manager.store.get_run(run_id).status}")


def test_runtime_redacts_tool_payloads_and_records_accurate_spans(tmp_path: Path):
    adapter = ScriptedAdapter([[
        RuntimeSignal(
            type=AgentEventType.TOOL_STARTED,
            message="raw start",
            data={
                "tool_name": "read_wiki_page",
                "tool_call_id": "call_1",
                "namespace": ["private-node"],
                "metadata": {"authorization": "Bearer secret"},
                "tool_call": {
                    "id": "call_1",
                    "name": "read_wiki_page",
                    "args": {"page_id": "t_cell", "api_key": "secret"},
                },
            },
            model_call_id="model_1",
            input_tokens=12,
        ),
        RuntimeSignal(
            type=AgentEventType.TOOL_COMPLETED,
            message='{"raw":"full page text"}',
            data={"tool_name": "read_wiki_page", "tool_call_id": "call_1"},
            tool_calls=1,
        ),
        RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="Done",
            data={"answer": "Done", "knowledge_scope": "general"},
            model_call_id="model_2",
            output_tokens=3,
        ),
    ]])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        run = manager.start(
            thread_id="thread_observation",
            message="inspect",
            context=_context("thread_observation"),
        )
        completed = _wait_for_status(manager, run.run_id, {AgentRunStatus.SUCCEEDED})
        tool_events = [
            event
            for event in manager.store.list_events(run.run_id)
            if event.type in {AgentEventType.TOOL_STARTED, AgentEventType.TOOL_COMPLETED}
        ]
        serialized = str([event.model_dump(mode="json") for event in tool_events])
        assert "Bearer secret" not in serialized
        assert "full page text" not in serialized
        assert "tool_call" not in tool_events[0].data
        assert tool_events[0].data["label_args"] == {"page_id": "t_cell"}
        assert completed.usage.tool_calls_started == 1
        assert completed.usage.tool_calls_completed == 1
        spans = manager.store.list_spans(run.run_id)
        assert {span.kind for span in spans} == {"router", "model", "tool"}
        assert next(span for span in spans if span.kind == "tool").status == "completed"
    finally:
        manager.close()


def test_new_runs_use_isolated_checkpoints(tmp_path: Path):
    adapter = ScriptedAdapter([
        [RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="first")],
        [RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="second")],
    ])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        first = manager.start(
            thread_id="thread_isolated",
            message="first",
            context=_context("thread_isolated"),
        )
        _wait_for_status(manager, first.run_id, {AgentRunStatus.SUCCEEDED})
        second = manager.start(
            thread_id="thread_isolated",
            message="second",
            context=_context("thread_isolated"),
        )
        _wait_for_status(manager, second.run_id, {AgentRunStatus.SUCCEEDED})

        assert adapter.thread_ids == [first.run_id, second.run_id]
    finally:
        manager.close()


def test_agent_runtime_streams_stable_events_and_persists_usage(tmp_path: Path):
    adapter = ScriptedAdapter(
        [[
            RuntimeSignal(
                type=AgentEventType.MESSAGE_DELTA,
                message="grounded ",
                model_call_id="call_1",
                input_tokens=10,
            ),
            RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE,
                message="answer",
                data={"answer": "answer", "citations": []},
                model_call_id="call_1",
                output_tokens=4,
            ),
        ]]
    )
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(thread_id="thread_test", message="question", context=_context())
        completed = _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        events = manager.store.list_events(started.run_id)

        assert completed.usage.model_calls == 1
        assert completed.usage.input_tokens == 10
        assert completed.usage.output_tokens == 4
        assert completed.usage.elapsed_seconds >= 0
        assert AgentEventType.MESSAGE_DELTA in {event.type for event in events}
        assert AgentEventType.FINAL_RESPONSE in {event.type for event in events}
        assert events[-1].data["status"] == "succeeded"
    finally:
        manager.close()


def test_enabled_memory_is_bounded_context_and_records_only_observable_outcome(tmp_path: Path):
    memory = MemoryStore(tmp_path)
    memory.admit(
        MemoryCandidate(
            candidate_id="seed_preference",
            project_id="cellwiki",
            kind=MemoryKind.STABLE,
            key="answer_format",
            content="Use an evidence table for comparison answers.",
            confidence=0.9,
        )
    )
    adapter = ScriptedAdapter(
        [[RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="Grounded final answer")]]
    )
    manager = AgentRuntimeManager(
        tmp_path,
        adapter=adapter,
        memory_store=memory,
        memory_enabled=True,
    )
    try:
        started = manager.start(
            thread_id="thread_memory",
            message="Use evidence table format",
            context=_context("thread_memory"),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})

        assert isinstance(adapter.calls[0], list)
        assert "<governed_memory_context>" in adapter.calls[0][-1]["content"]
        assert "not scientific evidence" in adapter.calls[0][-1]["content"]
        events = manager.store.list_events(started.run_id)
        assert AgentEventType.MEMORY_RECALLED in {event.type for event in events}
        assert AgentEventType.MEMORY_CANDIDATE in {event.type for event in events}
        episodes = memory.list("cellwiki", kind=MemoryKind.EPISODE)
        assert episodes[0].content == (
            "Request: Use evidence table format Outcome: Grounded final answer"
        )
    finally:
        manager.close()


def test_waiting_approval_survives_manager_restart_and_can_resume(tmp_path: Path):
    first_adapter = ScriptedAdapter(
        [[RuntimeSignal(
            type=AgentEventType.REVIEW_REQUIRED,
            data={"interrupt": {"change_set_id": "cs_review"}},
        )]]
    )
    first = AgentRuntimeManager(tmp_path, adapter=first_adapter)
    started = first.start(thread_id="thread_review", message="publish", context=_context("thread_review"))
    _wait_for_status(first, started.run_id, {AgentRunStatus.WAITING_APPROVAL})
    first.close()

    second_adapter = ScriptedAdapter(
        [[RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="committed")]]
    )
    second = AgentRuntimeManager(tmp_path, adapter=second_adapter)
    try:
        assert second.store.get_run(started.run_id).status == AgentRunStatus.WAITING_APPROVAL
        second.resume(started.run_id, decision="approve")
        completed = _wait_for_status(second, started.run_id, {AgentRunStatus.SUCCEEDED})
        assert completed.status == AgentRunStatus.SUCCEEDED
        assert isinstance(second_adapter.calls[0], Command)
    finally:
        second.close()


def test_cancel_waits_for_a_safe_event_boundary(tmp_path: Path):
    adapter = BlockingAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(thread_id="thread_cancel", message="work", context=_context("thread_cancel"))
        _wait_for_status(manager, started.run_id, {AgentRunStatus.RUNNING})
        cancelling = manager.cancel(started.run_id)
        assert cancelling.status == AgentRunStatus.CANCELLING
        adapter.release.set()
        cancelled = _wait_for_status(manager, started.run_id, {AgentRunStatus.CANCELLED})
        assert cancelled.status == AgentRunStatus.CANCELLED
    finally:
        manager.close()


def test_cancel_interrupts_a_cooperative_domain_operation_before_graph_output(tmp_path: Path):
    """A blocking tool must observe cancellation without waiting for another graph event."""

    started = threading.Event()
    registry = CancellationRegistry.for_project(tmp_path)

    class CooperativeAdapter:
        def execute(self, *, thread_id: str, message, context) -> Iterable[RuntimeSignal]:
            run_id = current_agent_run_id()
            assert run_id is not None
            started.set()
            while not registry.token(run_id).wait(0.01):
                pass
            raise OperationCancelled("model-bearing operation was cancelled")

        def close(self) -> None:
            return None

    manager = AgentRuntimeManager(tmp_path, adapter=CooperativeAdapter())
    try:
        run = manager.start(
            thread_id="thread_cooperative_cancel",
            message="ingest",
            context=_context("thread_cooperative_cancel"),
        )
        assert started.wait(timeout=1)
        manager.cancel(run.run_id)

        cancelled = _wait_for_status(
            manager,
            run.run_id,
            {AgentRunStatus.CANCELLED},
            timeout=1,
        )
        assert cancelled.error_type is None
    finally:
        manager.close()


def test_budget_failure_is_classified_and_not_retried(tmp_path: Path):
    adapter = ScriptedAdapter(
        [[
            RuntimeSignal(type=AgentEventType.MESSAGE_DELTA, model_call_id="call_1"),
            RuntimeSignal(type=AgentEventType.MESSAGE_DELTA, model_call_id="call_2"),
        ]]
    )
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_budget",
            message="work",
            context=_context("thread_budget"),
            budget=RunBudget(max_model_calls=1),
        )
        failed = _wait_for_status(manager, started.run_id, {AgentRunStatus.FAILED})
        assert failed.error_type == AgentErrorType.BUDGET
        assert failed.retry_count == 0
    finally:
        manager.close()


def test_runtime_timeout_is_classified_at_the_next_safe_boundary(tmp_path: Path):
    class SlowAdapter:
        def execute(self, *, thread_id: str, message, context) -> Iterable[RuntimeSignal]:
            time.sleep(1.05)
            yield RuntimeSignal(type=AgentEventType.PROGRESS, progress=10)

        def close(self) -> None:
            return None

    manager = AgentRuntimeManager(tmp_path, adapter=SlowAdapter())
    try:
        started = manager.start(
            thread_id="thread_timeout",
            message="work",
            context=_context("thread_timeout"),
            budget=RunBudget(max_runtime_seconds=1),
        )
        failed = _wait_for_status(manager, started.run_id, {AgentRunStatus.FAILED})
        assert failed.error_type == AgentErrorType.TIMEOUT
    finally:
        manager.close()


def test_provider_timed_out_message_is_classified_as_timeout():
    assert classify_agent_error(Exception("Request timed out.")) == AgentErrorType.TIMEOUT


def test_shutdown_ignores_a_run_that_finishes_before_cancellation_transition(
    tmp_path: Path,
    monkeypatch,
):
    manager = AgentRuntimeManager(tmp_path, adapter=ScriptedAdapter([]))
    try:
        monkeypatch.setattr(manager, "_submit", lambda *args: None)
        run = manager.start(
            thread_id="thread_shutdown_race",
            message="work",
            context=_context("thread_shutdown_race"),
        )
        manager.store.transition(run.run_id, AgentRunStatus.RUNNING)
        original_transition = manager.store.transition
        raced = False

        def finish_before_shutdown_transition(run_id, status, **kwargs):
            nonlocal raced
            if status == AgentRunStatus.CANCELLING and not raced:
                raced = True
                original_transition(
                    run_id,
                    AgentRunStatus.FAILED,
                    message="The run finished before shutdown cancellation.",
                )
            return original_transition(run_id, status, **kwargs)

        monkeypatch.setattr(manager.store, "transition", finish_before_shutdown_transition)

        manager.request_shutdown()

        assert manager.store.get_run(run.run_id).status == AgentRunStatus.FAILED
    finally:
        manager.close()


def test_active_thread_cannot_be_deleted(tmp_path: Path):
    manager = AgentRuntimeManager(tmp_path, adapter=ScriptedAdapter([]))
    try:
        run = manager.start(
            thread_id="thread_active_delete",
            message="work",
            context=_context("thread_active_delete"),
        )
        manager.store.transition(run.run_id, AgentRunStatus.RUNNING)

        with pytest.raises(ValueError, match="active"):
            manager.delete_thread("thread_active_delete")
    finally:
        manager.close()


def test_retry_resumes_checkpoint_without_replaying_input(tmp_path: Path):
    adapter = ScriptedAdapter(
        [RuntimeError("temporary provider failure"), [RuntimeSignal(type=AgentEventType.FINAL_RESPONSE)]]
    )
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(thread_id="thread_retry", message="work", context=_context("thread_retry"))
        _wait_for_status(manager, started.run_id, {AgentRunStatus.FAILED})
        manager.retry(started.run_id)
        completed = _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        assert completed.retry_count == 1
        assert adapter.calls[0][-1] == {"role": "user", "content": "work"}
        assert adapter.calls[1] is None
    finally:
        manager.close()


def test_deep_agents_chunks_are_adapted_to_stable_tool_and_changeset_events():
    started = list(_signals_from_stream_item((
        (),
        "messages",
        (AIMessage(
            content="",
            tool_calls=[{"name": "prepare_ingest_change_set", "args": {}, "id": "tool_1"}],
            usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
        ), {}),
    )))
    completed = list(_signals_from_stream_item((
        (),
        "messages",
        (ToolMessage(
            content='{"change_set_id": "cs_fixture"}',
            tool_call_id="tool_1",
            name="prepare_ingest_change_set",
        ), {}),
    )))

    assert started[0].type == AgentEventType.TOOL_STARTED
    assert started[0].data["tool_name"] == "prepare_ingest_change_set"
    assert started[0].input_tokens == 12
    assert started[0].output_tokens == 3
    assert [signal.type for signal in completed] == [
        AgentEventType.TOOL_COMPLETED,
        AgentEventType.CHANGESET_READY,
        AgentEventType.REVIEW_REQUIRED,
    ]
    assert completed[-1].data["change_set_id"] == "cs_fixture"


def test_blocked_generic_tool_failure_is_marked_recoverable():
    signals = list(_signals_from_stream_item((
        (),
        "messages",
        (ToolMessage(
            content=(
                "Tool 'read_file' is not available to CellWiki agents. "
                "Use the visible CellWiki tools instead of generic filesystem tools."
            ),
            tool_call_id="blocked_tool_1",
            name="read_file",
            status="error",
        ), {}),
    )))

    assert signals[0].type is AgentEventType.TOOL_FAILED
    assert signals[0].data["blocked_tool"] is True


def test_proposal_tool_content_blocks_surface_review_boundary():
    signals = list(_signals_from_stream_item((
        (),
        "messages",
        (ToolMessage(
            content=[
                {
                    "type": "text",
                    "text": (
                        '{"change_set":{"change_set_id":"cs_blocks"},'
                        '"requires_human_review":true}'
                    ),
                }
            ],
            tool_call_id="proposal_blocks_1",
            name="prepare_ingest_change_set",
        ), {}),
    )))

    assert [signal.type for signal in signals] == [
        AgentEventType.TOOL_COMPLETED,
        AgentEventType.CHANGESET_READY,
        AgentEventType.REVIEW_REQUIRED,
    ]
    assert signals[-1].data == {
        "change_set_id": "cs_blocks",
        "requires_human_review": True,
    }


def test_runtime_continues_after_blocked_generic_tool_failure(tmp_path: Path):
    adapter = ScriptedAdapter([[
        RuntimeSignal(
            type=AgentEventType.TOOL_FAILED,
            message="Read File failed.",
            data={
                "tool_name": "read_file",
                "tool_call_id": "blocked_tool_1",
                "blocked_tool": True,
            },
        ),
        RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="The requested operation is unavailable through CellWiki tools.",
        ),
    ]])
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id="thread_blocked_tool",
            message="Analyze the source.",
            context=_context("thread_blocked_tool"),
        )
        completed = _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        assert completed.status is AgentRunStatus.SUCCEEDED
        assert completed.usage.tool_calls_failed == 1
    finally:
        manager.close()


def test_runtime_persists_attachment_context_and_exposes_a_manifest_to_the_model(
    tmp_path: Path,
):
    thread_id = "thread_" + "d" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 marks regulatory T cells.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    adapter = ScriptedAdapter(
        [[RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="Grounded final answer")]]
    )
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        started = manager.start(
            thread_id=thread_id,
            message="What cell types are in this paper?",
            context=WikiAgentContext(
                project_id="cellwiki",
                thread_id=thread_id,
                attachment_ids=[attachment.attachment_id],
            ),
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})

        persisted = manager.store.get_run(started.run_id)
        assert persisted.attachment_ids == [attachment.attachment_id]
        restored_context = manager._context_for(persisted)
        assert restored_context.attachment_ids == [attachment.attachment_id]
        assert isinstance(adapter.calls[0], list)
        manifest = adapter.calls[0][0]["content"]
        assert attachment.attachment_id in manifest
        assert "notes.txt" in manifest
        assert "never ask the user for thread_id" in manifest
    finally:
        manager.close()


def test_runtime_does_not_inject_thread_archive_when_no_attachment_is_referenced(
    tmp_path: Path,
):
    thread_id = "thread_" + "e" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 marks regulatory T cells.", encoding="utf-8")
    AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    manager = AgentRuntimeManager(tmp_path, adapter=ScriptedAdapter([]))
    try:
        context = WikiAgentContext(project_id="cellwiki", thread_id=thread_id)
        messages = [{"role": "user", "content": "What is this?"}]
        assert manager._with_attachment_context(messages, context) == messages
    finally:
        manager.close()


def test_runtime_injects_explicit_page_context_for_model_queries(tmp_path: Path):
    manager = AgentRuntimeManager(tmp_path, adapter=ScriptedAdapter([]))
    try:
        messages = [{"role": "user", "content": "What is this page?"}]
        injected = manager._with_page_context(
            messages,
            WikiAgentContext(project_id="cellwiki", page_id="t_cell"),
        )

        assert injected[0]["role"] == "system"
        assert "<cellwiki_page_context>" in injected[0]["content"]
        assert '"page_id": "t_cell"' in injected[0]["content"]
        assert injected[1:] == messages
    finally:
        manager.close()


def test_top_level_json_message_becomes_validated_final_response():
    signals = list(_signals_from_stream_item((
        (),
        "messages",
        (AIMessage(content=(
            '{"answer":"Grounded answer","citations":[{"page_id":"t_cell"}],'
            '"confidence":"high","missing_evidence":[]}'
        )), {}),
    )))

    final = next(signal for signal in signals if signal.type == AgentEventType.FINAL_RESPONSE)
    assert final.message == "Grounded answer"
    assert final.data == {
        "answer": "Grounded answer",
        "citations": [{"page_id": "t_cell", "source_id": None, "locator": None, "evidence_id": None}],
        "confidence": "high",
        "declared_confidence": None,
        "missing_evidence": [],
        "knowledge_scope": "formal",
        "knowledge_version": None,
        "verification_level": "unvalidated",
        "validation_issues": [],
        "validation_warnings": [],
    }


def test_submit_agent_answer_tool_result_becomes_final_response():
    signals = list(_signals_from_stream_item((
        (),
        "messages",
        (ToolMessage(
            content=(
                '{"answer":"Grounded answer","citations":[{"page_id":"t_cell"}],'
                '"confidence":"high","missing_evidence":[]}'
            ),
            tool_call_id="tool_final",
            name="submit_agent_answer",
        ), {}),
    )))

    assert [signal.type for signal in signals] == [
        AgentEventType.TOOL_COMPLETED,
        AgentEventType.FINAL_RESPONSE,
    ]
    assert signals[-1].data["citations"] == [
        {"page_id": "t_cell", "source_id": None, "locator": None, "evidence_id": None}
    ]


def test_sqlite_checkpoint_resumes_interrupt_after_connection_restart(tmp_path: Path):
    class State(TypedDict):
        decision: str

    def review(state: State):
        return {"decision": interrupt({"change_set_id": "cs_checkpoint"})}

    def build(checkpointer: SqliteSaver):
        workflow = StateGraph(State)
        workflow.add_node("review", review)
        workflow.add_edge(START, "review")
        workflow.add_edge("review", END)
        return workflow.compile(checkpointer=checkpointer)

    database = tmp_path / "checkpoints.sqlite"
    config = {"configurable": {"thread_id": "thread_checkpoint"}}
    first_connection = sqlite3.connect(database, check_same_thread=False)
    first_saver = SqliteSaver(first_connection)
    first_saver.setup()
    interrupted = build(first_saver).invoke({"decision": ""}, config)
    first_connection.close()

    second_connection = sqlite3.connect(database, check_same_thread=False)
    second_saver = SqliteSaver(second_connection)
    second_saver.setup()
    resumed = build(second_saver).invoke(Command(resume="approved"), config)
    second_connection.close()

    assert interrupted["__interrupt__"]
    assert resumed["decision"] == "approved"


def test_deep_agents_adapter_deletes_all_thread_checkpoints(tmp_path: Path):
    class State(TypedDict):
        value: str

    def step(state: State):
        return {"value": "checkpointed"}

    adapter = DeepAgentsExecutionAdapter(tmp_path)
    try:
        workflow = StateGraph(State)
        workflow.add_node("step", step)
        workflow.add_edge(START, "step")
        workflow.add_edge("step", END)
        graph = workflow.compile(checkpointer=adapter.checkpointer)
        config = {"configurable": {"thread_id": "thread_delete_checkpoint"}}
        graph.invoke({"value": "before"}, config)
        assert adapter.checkpointer.get_tuple(config) is not None

        adapter.delete_thread("thread_delete_checkpoint")

        assert adapter.checkpointer.get_tuple(config) is None
    finally:
        adapter.close()
