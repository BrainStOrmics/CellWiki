# =============================================================================
# Agent 过程可视性契约测试（P0 后端事件管线增强）
# =============================================================================
# 覆盖：reasoning_delta 事件、usage_metadata 输入/输出/缓存采集、工具调用
# 参数与结果摘要、逐轮 AgentSpan 写入、thread_usage_summary 线程累计。
# =============================================================================

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from cellwiki.config import settings
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import AgentEventType, AgentRunStatus
from cellwiki.services.agent_runtime import (
    AgentRuntimeManager,
    RuntimeSignal,
    _signals_from_stream_item,
    _tool_args_display,
    _tool_result_preview,
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
        assert span.duration_ms is not None and span.duration_ms >= 0

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


def test_stream_item_emits_reasoning_delta_from_responses_content_blocks():
    """Responses/v1 streaming surfaces reasoning as content blocks with a
    summary list; the runtime must translate them incrementally too."""
    chunk = AIMessageChunk(
        content=[
            {
                "type": "reasoning",
                "id": "rs_1",
                "index": 0,
                "summary": [{"index": 0, "type": "summary_text", "text": "一步步推理"}],
            }
        ],
        id="call_block",
    )
    signals = list(_signals_from_stream_item(("messages", (chunk, {}))))
    reasoning = next(
        signal for signal in signals if signal.type == AgentEventType.REASONING_DELTA
    )
    assert reasoning.message == "一步步推理"
    assert reasoning.model_call_id == "call_block"
    assert not any(
        signal.type == AgentEventType.MESSAGE_DELTA for signal in signals
    )


def test_reasoning_delta_keeps_word_boundaries_across_chunks():
    """逐 delta 抽取不得 strip：英文的词间空格正好落在 delta 边界上。

    回归桌面端实测问题 J——think 卡片正文出现 "Ineed to run twogloboperationsto"。
    前端是逐字拼接的，这里被吃掉的空格在下游补不回来；纯空白 delta 若被整条丢弃，
    边界空格同样消失。中文没有词间空格，所以该缺陷只腐蚀英文思考。
    """

    def reasoning_chunk(text: str) -> AIMessageChunk:
        return AIMessageChunk(
            content=[
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "index": 0,
                    "summary": [{"index": 0, "type": "summary_text", "text": text}],
                }
            ],
            id="call_block",
        )

    fragments = ["I need ", "to run", " ", "two glob operations", " "]
    reconstructed = ""
    for fragment in fragments:
        chunk = reasoning_chunk(fragment)
        messages = [
            signal.message
            for signal in _signals_from_stream_item(("messages", (chunk, {})))
            if signal.type == AgentEventType.REASONING_DELTA
        ]
        # 纯空白分片也必须产出一条事件，否则边界空格随事件一起消失。
        assert messages == [fragment]
        reconstructed += messages[0]

    assert reconstructed == "I need to run two glob operations "


def test_stream_item_projects_tool_args_display():
    """tool_started carries a bounded whitelisted args_display projection."""
    call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "run_powershell",
                "args": {"command": "Get-Location; Get-ChildItem -Force"},
                "id": "call_pwsh",
                "type": "tool_call",
            },
            {
                "name": "read_file",
                "args": {"path": "wiki/cell-a.md"},
                "id": "call_read",
                "type": "tool_call",
            },
        ],
    )
    started = [
        signal
        for signal in _signals_from_stream_item(("messages", (call, {})))
        if signal.type == AgentEventType.TOOL_STARTED
    ]
    pwsh = started[0].data["args_display"]
    assert pwsh["command"] == "Get-Location; Get-ChildItem -Force"
    assert pwsh["title"] == "Get-Location; Get-ChildItem -Force"
    read = started[1].data["args_display"]
    assert read["path"] == "wiki/cell-a.md"
    assert read["title"] == "cell-a.md"


def test_stream_item_projects_bounded_result_preview():
    """tool_completed carries a head/tail bounded result_preview projection."""
    stdout = "\n".join(f"line {index}" for index in range(120))
    result = list(
        _signals_from_stream_item(
            (
                "messages",
                (
                    ToolMessage(
                        content=json.dumps({"stdout": stdout, "returncode": 0}),
                        tool_call_id="call_pwsh",
                        name="run_powershell",
                    ),
                    {},
                ),
            )
        )
    )
    preview = result[0].data["result_preview"]
    assert preview["kind"] == "text"
    assert preview["truncated"] is True
    assert preview["total_chars"] == len(stdout)
    assert preview["head"].startswith("line 0")
    assert preview["tail"].endswith("line 119")
    assert len(preview["head"]) + len(preview["tail"]) <= 8_000


def test_result_preview_keeps_error_and_results_kinds():
    error_preview = _tool_result_preview(
        "grep", json.dumps({"error": "path_outside_workspace"})
    )
    assert error_preview["kind"] == "error"
    assert "path_outside_workspace" in error_preview["head"]
    results_preview = _tool_result_preview(
        "grep",
        json.dumps({"results": [{"file": "a.md", "line": 1}, {"file": "b.md", "line": 2}]}),
    )
    assert results_preview["kind"] == "results"
    assert results_preview["count"] == 2
    assert "a.md" in results_preview["head"]


def test_args_display_caps_command_length():
    long_command = "Get-ChildItem " + ("x" * 3_000)
    display = _tool_args_display("run_powershell", {"command": long_command})
    assert len(display["command"]) <= 2_000
    assert display["title"] == long_command[:120]


def test_timeline_card_projections_persist_through_events(tmp_path: Path):
    """args_display / result_preview survive the durable event payload seam."""
    signals = [
        RuntimeSignal(
            type=AgentEventType.TOOL_STARTED,
            message="read_file · {\"path\": \"wiki/a.md\"}",
            data={
                "tool_name": "read_file",
                "tool_call_id": "call_x",
                "args_display": {"path": "wiki/a.md", "title": "a.md"},
            },
            model_call_id="m1",
        ),
        RuntimeSignal(
            type=AgentEventType.TOOL_COMPLETED,
            message="read_file → wiki/a.md",
            data={
                "tool_name": "read_file",
                "tool_call_id": "call_x",
                "result_preview": {
                    "head": "# Cell A",
                    "tail": "",
                    "total_chars": 7,
                    "truncated": False,
                    "kind": "text",
                },
            },
        ),
        RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="完成", model_call_id="m1"),
    ]
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter([signals]))
    try:
        started = manager.start(thread_id="t_card", message="hi", context=_context("t_card"))
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        events = manager.store.list_events(started.run_id)
        by_type = {event.type: event for event in events}
        assert by_type[AgentEventType.TOOL_STARTED].data["args_display"]["title"] == "a.md"
        assert by_type[AgentEventType.TOOL_COMPLETED].data["result_preview"]["head"] == "# Cell A"
    finally:
        manager.close()


def test_tool_spans_record_call_timing(tmp_path: Path):
    """Each completed tool call writes one kind="tool" span with duration."""
    signals = [
        RuntimeSignal(
            type=AgentEventType.TOOL_STARTED,
            message="grep started.",
            data={"tool_name": "grep", "tool_call_id": "call_1"},
            model_call_id="m1",
        ),
        RuntimeSignal(
            type=AgentEventType.TOOL_COMPLETED,
            message="grep → 2 matches",
            data={"tool_name": "grep", "tool_call_id": "call_1"},
        ),
        RuntimeSignal(
            type=AgentEventType.TOOL_STARTED,
            message="glob started.",
            data={"tool_name": "glob", "tool_call_id": "call_2"},
            model_call_id="m1",
        ),
        RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="完成", model_call_id="m1"),
    ]
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter([signals]))
    try:
        started = manager.start(thread_id="t_span", message="hi", context=_context("t_span"))
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        tool_spans = [s for s in manager.store.list_spans(started.run_id) if s.kind == "tool"]
        by_name = {span.name: span for span in tool_spans}
        assert set(by_name) == {"grep", "glob"}
        assert by_name["grep"].status == "completed"
        assert by_name["grep"].duration_ms is not None
        # The never-completed call is flushed as cancelled so totals stay honest.
        assert by_name["glob"].status == "cancelled"
        assert by_name["glob"].duration_ms is not None
        run = manager.store.get_run(started.run_id)
        assert run.usage.tool_calls_started == 2
        assert run.usage.tool_calls_completed == 1
    finally:
        manager.close()


def test_run_records_model_name(tmp_path: Path):
    """Diagnostics reads run.model_name; create must persist the configured model."""
    signals = [RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="完成", model_call_id="m1")]
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter([signals]))
    try:
        started = manager.start(thread_id="t_model", message="hi", context=_context("t_model"))
        _wait_for_status(manager, started.run_id, {AgentRunStatus.SUCCEEDED})
        run = manager.store.get_run(started.run_id)
        assert run.model_name == settings.openai_model
    finally:
        manager.close()
