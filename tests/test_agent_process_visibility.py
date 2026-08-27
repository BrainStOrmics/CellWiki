# =============================================================================
# Agent 过程可视性契约测试（P0 后端事件管线增强）
# =============================================================================
# 覆盖：reasoning_delta 事件、usage_metadata 输入/输出/缓存采集、工具调用
# 参数与结果摘要、逐轮 AgentSpan 写入、thread_usage_summary 线程累计。
# =============================================================================

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import AgentEventType, AgentRunStatus
from cellwiki.services.agent_runtime import (
    AgentRuntimeManager,
    RuntimeSignal,
    _signals_from_stream_item,
)


class _ScriptedAdapter:
    """Minimal adapter emitting pre-built runtime signals (framework-free)."""

    def __init__(self, scripts: list[list[RuntimeSignal]]):
        self.scripts = scripts

    def execute(self, *, thread_id: str, message: Any, context: Any) -> Iterable[RuntimeSignal]:
        yield from self.scripts.pop(0)

    def close(self) -> None:
        return None


def _context(thread_id: str = "thread_vis") -> WikiAgentContext:
    return WikiAgentContext(project_id="cellwiki", thread_id=thread_id)


def _wait_for_status(
    manager: AgentRuntimeManager,
    run_id: str,
    statuses: set[AgentRunStatus],
    timeout: float = 5.0,
) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = manager.store.get_run(run_id)
        if run.status in statuses:
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {statuses}")


def test_stream_item_emits_reasoning_delta():
    chunk = AIMessageChunk(
        content="回答",
        id="call_1",
        additional_kwargs={"reasoning_content": "思考过程"},
    )
    signals = list(_signals_from_stream_item(("messages", (chunk, {}))))
    types = [signal.type for signal in signals]
    assert AgentEventType.REASONING_DELTA in types
    assert AgentEventType.MESSAGE_DELTA in types
    reasoning = next(signal for signal in signals if signal.type == AgentEventType.REASONING_DELTA)
    assert reasoning.message == "思考过程"
    assert reasoning.data.get("source") == "reasoning"
    text = next(signal for signal in signals if signal.type == AgentEventType.MESSAGE_DELTA)
    assert text.message == "回答"


def test_stream_item_captures_usage_and_cache():
    chunk = AIMessageChunk(
        content="你好",
        id="call_1",
        usage_metadata={
            "input_tokens": 120,
            "output_tokens": 40,
            "total_tokens": 160,
            "input_token_details": {"cached_tokens": 80},
        },
    )
    signals = list(_signals_from_stream_item(("messages", (chunk, {}))))
    text = next(signal for signal in signals if signal.type == AgentEventType.MESSAGE_DELTA)
    assert text.model_call_id == "call_1"
    assert text.input_tokens == 120
    assert text.output_tokens == 40
    assert text.cached_input_tokens == 80


def test_stream_item_captures_cache_fallback_and_degrades_to_zero():
    chunk = AIMessageChunk(
        content="x",
        id="call_2",
        usage_metadata={"input_tokens": 5, "output_tokens": 1, "total_tokens": 6},
    )
    signals = list(_signals_from_stream_item(("messages", (chunk, {}))))
    text = next(signal for signal in signals if signal.type == AgentEventType.MESSAGE_DELTA)
    assert text.input_tokens == 5
    assert text.cached_input_tokens == 0


def test_stream_item_summarizes_tool_arguments_and_results():
    call = AIMessage(
        content="",
        tool_calls=[
            {"name": "read_file", "args": {"path": "wiki/a.md"}, "id": "call_x", "type": "tool_call"}
        ],
    )
    started = list(_signals_from_stream_item(("messages", (call, {}))))
    assert started[0].type == AgentEventType.TOOL_STARTED
    assert started[0].message == 'read_file · {"path": "wiki/a.md"}'
    assert started[0].data["tool_call_id"] == "call_x"

    result = list(
        _signals_from_stream_item(
            (
                "messages",
                (
                    ToolMessage(
                        content='{"matches": [{"file": "wiki/a.md", "line": 3}]}',
                        tool_call_id="call_x",
                        name="grep",
                    ),
                    {},
                ),
            )
        )
    )
    assert result[0].type == AgentEventType.TOOL_COMPLETED
    assert result[0].message == "grep → 1 matches"
    assert "wiki/a.md" not in result[0].message


def test_model_spans_and_usage_are_recorded(tmp_path: Path):
    signals = [
        RuntimeSignal(
            type=AgentEventType.MESSAGE_DELTA,
            message="a",
            model_call_id="m1",
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=60,
        ),
        RuntimeSignal(
            type=AgentEventType.MESSAGE_DELTA,
            message="b",
            model_call_id="m1",
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=60,
        ),
        RuntimeSignal(
            type=AgentEventType.REASONING_DELTA,
            message="想一想",
            model_call_id="m1",
        ),
        RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="完成",
            model_call_id="m1",
        ),
    ]
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter([signals]))
    try:
        started = manager.start(
            thread_id="t1", message="hi", context=_context("t1")
        )
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        run = manager.store.get_run(started.run_id)
        assert run.usage.model_calls >= 1
        assert run.usage.input_tokens == 100
        assert run.usage.output_tokens == 20
        assert run.usage.cached_input_tokens == 60

        spans = manager.store.list_spans(started.run_id)
        assert len(spans) == 1
        span = spans[0]
        assert span.kind == "model"
        assert span.name
        assert span.input_tokens == 100
        assert span.output_tokens == 20
        assert span.cached_input_tokens == 60
        assert span.ttft_ms is None

        summary = manager.store.thread_usage_summary("t1")
        assert summary["run_count"] == 1
        assert summary["total_input_tokens"] == 100
        assert summary["total_output_tokens"] == 20
        assert summary["total_cached_input_tokens"] == 60
        assert summary["avg_cache_hit_rate"] == 0.6

        events = manager.store.list_events(started.run_id)
        assert AgentEventType.REASONING_DELTA in [event.type for event in events]
    finally:
        manager.close()
def test_stream_item_reads_langchain_normalized_cache_read():
    chunk = AIMessageChunk(
        content="hi",
        id="call_cr",
        usage_metadata={
            "input_tokens": 120,
            "output_tokens": 40,
            "total_tokens": 160,
            "input_token_details": {"cache_read": 80},
        },
    )
    signals = list(_signals_from_stream_item(("messages", (chunk, {}))))
    text = next(signal for signal in signals if signal.type == AgentEventType.MESSAGE_DELTA)
    assert text.cached_input_tokens == 80


def test_stream_item_reads_deepseek_cache_from_response_metadata():
    chunk = AIMessageChunk(
        content="hi",
        id="call_ds",
        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        response_metadata={
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "total_tokens": 110,
                "prompt_cache_hit_tokens": 70,
            }
        },
    )
    signals = list(_signals_from_stream_item(("messages", (chunk, {}))))
    text = next(signal for signal in signals if signal.type == AgentEventType.MESSAGE_DELTA)
    assert text.cached_input_tokens == 70


def test_stream_item_reads_raw_responses_cache_read_tokens():
    chunk = AIMessageChunk(
        content="hi",
        id="call_rs",
        usage_metadata={
            "input_tokens": 90,
            "output_tokens": 5,
            "total_tokens": 95,
            "cache_read_input_tokens": 60,
        },
    )
    signals = list(_signals_from_stream_item(("messages", (chunk, {}))))
    text = next(signal for signal in signals if signal.type == AgentEventType.MESSAGE_DELTA)
    assert text.cached_input_tokens == 60

def test_stream_item_emits_started_for_every_tool_call_in_batch():
    call = AIMessage(
        content="",
        tool_calls=[
            {"name": "ls", "args": {"path": "/"}, "id": "call_a", "type": "tool_call"},
            {"name": "glob", "args": {"pattern": "**/*.md"}, "id": "call_b", "type": "tool_call"},
        ],
    )
    signals = list(_signals_from_stream_item(("messages", (call, {}))))
    started = [signal for signal in signals if signal.type == AgentEventType.TOOL_STARTED]
    assert [signal.data["tool_call_id"] for signal in started] == ["call_a", "call_b"]
    assert started[0].message == 'ls · {"path": "/"}'
    assert started[1].message == 'glob · {"pattern": "**/*.md"}'
