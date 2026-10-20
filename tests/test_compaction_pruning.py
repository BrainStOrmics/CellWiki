"""Contract tests for the compaction alignment work: pruning + overflow + split.

Covers the accepted proposal's regression list (2026-09-22):
- write-time previewing thresholds;
- cold-spot pruning (keep 5, constant placeholder, monotone, protected tools);
- overflow classification (the 2026-09-16 tool-pairing 400 must never trigger);
- turn-boundary tail split that never orphans a tool result.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from cellwiki.agent.compaction import (
    SUMMARY_MESSAGE_PREFIX,
    bound_post_compact_tool_results,
    build_compacted_messages,
    find_tail_start,
    is_overflow_error,
    latest_summary_text,
    microcompact_messages,
)
from cellwiki.services.prompt_cache import resolve_prompt_cache_policy
from cellwiki.services.model_transcript import (
    PRUNED_TOOL_PLACEHOLDER,
    TOOL_RESULT_CHAR_THRESHOLD,
    preview_tool_result,
    prune_transcript_for_model,
)


def _tool_record(
    call_id: str, text: str, *, name: str = "read_file", sequence: int = 0
) -> dict[str, Any]:
    return {
        "message_id": f"model_{call_id}",
        "sequence": sequence,
        "kind": "tool_result",
        "role": "tool",
        "name": name,
        "tool_call_id": call_id,
        "content": {"text": text, "tool_call_id": call_id, "name": name},
        "content_text": text,
    }


def _user_record(text: str, sequence: int = 0) -> dict[str, Any]:
    return {
        "message_id": f"model_user_{sequence}",
        "sequence": sequence,
        "kind": "user",
        "role": "user",
        "content": {"text": text},
        "content_text": text,
    }


# -- write-time previewing --------------------------------------------------


def test_preview_leaves_small_results_untouched():
    text = "x" * (TOOL_RESULT_CHAR_THRESHOLD - 1)
    assert (
        preview_tool_result(text, run_id="r1", tool_name="read_file", tool_call_id="c1")
        == text
    )


def test_preview_truncates_oversized_results_with_retrieval_path():
    text = "y" * (TOOL_RESULT_CHAR_THRESHOLD + 500)
    preview = preview_tool_result(
        text, run_id="r1", tool_name="lint_knowledge_base", tool_call_id="c9"
    )
    assert preview.startswith("[tool result preview: lint_knowledge_base]")
    assert "data/runtime/tool-results/r1/c9.txt" in preview
    assert "re-run the tool" in preview
    assert len(preview) < len(text)


# -- cold-spot pruning ------------------------------------------------------


def test_prune_keeps_the_recent_window_and_uses_constant_placeholder():
    records = [_user_record("q")] + [
        _tool_record(f"c{i}", f"payload {i} " * 30, sequence=i + 1)
        for i in range(8)
    ]
    pruned, count = prune_transcript_for_model(records, keep_recent=5)
    assert count == 3
    tools = [r for r in pruned if r["kind"] == "tool_result"]
    assert [r["content_text"] for r in tools[:3]] == [PRUNED_TOOL_PLACEHOLDER] * 3
    assert all("payload" in r["content_text"] for r in tools[3:])
    # message count and order unchanged
    assert [r["message_id"] for r in pruned] == [r["message_id"] for r in records]


def test_prune_is_monotone_and_idempotent():
    records = [_tool_record(f"c{i}", "z" * 400, sequence=i) for i in range(7)]
    once, count = prune_transcript_for_model(records, keep_recent=5)
    assert count == 2
    twice, count2 = prune_transcript_for_model(once, keep_recent=5)
    assert count2 == 0
    assert [r["content_text"] for r in twice] == [r["content_text"] for r in once]


def test_prune_protects_ask_user_question_and_tiny_results():
    records = [
        _tool_record("c1", "user decision text " * 20, name="ask_user_question"),
        _tool_record("c2", "small", name="grep"),
        _tool_record("c3", "big " * 100, name="read_file"),
        _tool_record("c4", "big " * 100, name="read_file"),
        _tool_record("c5", "big " * 100, name="read_file"),
        _tool_record("c6", "big " * 100, name="read_file"),
        _tool_record("c7", "big " * 100, name="read_file"),
        _tool_record("c8", "big " * 100, name="read_file"),
    ]
    pruned, _count = prune_transcript_for_model(records, keep_recent=5)
    by_id = {r["tool_call_id"]: r["content_text"] for r in pruned}
    # protected tool keeps its text
    assert "user decision text" in by_id["c1"]
    # a ≤100-char result is never worth replacing
    assert by_id["c2"] == "small"


# -- overflow classification ------------------------------------------------


def test_tool_pairing_400_never_classifies_as_overflow():
    """2026-09-16 事故原文：结构错误绝不能触发压缩重试。"""

    error = ValueError(
        "Error code: 400 - An assistant message with 'tool_calls' must be "
        "followed by tool messages responding to each 'tool_call_id'. "
        "(insufficient tool messages following tool_calls message)"
    )
    assert is_overflow_error(error) is False


def test_context_window_errors_classify_as_overflow():
    samples = [
        "This model's maximum context length is 128000 tokens",
        "prompt is too long: 200000 tokens > 128000 maximum",
        "context_length_exceeded",
        "input is too long for the model",
    ]
    for sample in samples:
        assert is_overflow_error(ValueError(sample)) is True, sample


def test_unrelated_errors_do_not_classify_as_overflow():
    assert is_overflow_error(ValueError("invalid api key")) is False
    assert is_overflow_error(TimeoutError("read timed out")) is False


# -- tail split -------------------------------------------------------------


def test_tail_split_never_starts_with_a_tool_message():
    messages = [
        HumanMessage(content="q1"),
        AIMessage(content="a1"),
        ToolMessage(content="t1", tool_call_id="c1", name="read_file"),
        HumanMessage(content="q2"),
        AIMessage(content="a2"),
        ToolMessage(content="t2", tool_call_id="c2", name="grep"),
    ]
    start = find_tail_start(messages, retained_tokens=20)
    assert start > 0
    assert not isinstance(messages[start], ToolMessage)


def test_tail_split_at_zero_when_everything_fits():
    messages = [HumanMessage(content="q"), AIMessage(content="a")]
    assert find_tail_start(messages, retained_tokens=1_000_000) == 0


def test_tail_split_uses_assistant_tool_groups_without_a_later_user_message():
    messages = [
        HumanMessage(content="ingest"),
        AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "read_file", "args": {"path": "a.md"}}],
        ),
        ToolMessage(content="first result " * 100, tool_call_id="c1", name="read_file"),
        AIMessage(
            content="",
            tool_calls=[{"id": "c2", "name": "read_file", "args": {"path": "b.md"}}],
        ),
        ToolMessage(content="second result " * 100, tool_call_id="c2", name="read_file"),
    ]

    start = find_tail_start(messages, retained_tokens=500)

    assert start == 3
    assert isinstance(messages[start], AIMessage)
    assert [getattr(message, "tool_call_id", None) for message in messages[start + 1 :]] == [
        "c2"
    ]


def test_tail_split_keeps_parallel_tool_results_with_their_assistant_call():
    messages = [
        HumanMessage(content="ingest"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "c1", "name": "read_file", "args": {"path": "a.md"}},
                {"id": "c2", "name": "read_file", "args": {"path": "b.md"}},
            ],
        ),
        ToolMessage(content="a" * 400, tool_call_id="c1", name="read_file"),
        ToolMessage(content="b" * 400, tool_call_id="c2", name="read_file"),
        AIMessage(content="finished"),
    ]

    start = find_tail_start(messages, retained_tokens=30)

    assert start == 4
    assert messages[start].content == "finished"


def test_summary_message_round_trips_through_latest_summary_text():
    messages = [HumanMessage(content="q1"), AIMessage(content="a1")]
    replacement, tail = build_compacted_messages(
        messages, "## Objective\n- keep", retained_tokens=1
    )
    summary_message = replacement[1]
    assert summary_message.content.startswith(SUMMARY_MESSAGE_PREFIX)
    assert latest_summary_text(replacement) is not None
    # 迭代合并的输入就是上一个摘要的原文
    assert "keep" in (latest_summary_text(replacement) or "")
    assert tail == []


def test_microcompact_clears_only_old_tool_results_and_preserves_pairing():
    messages = [HumanMessage(content="ingest")]
    for index in range(8):
        call_id = f"c{index}"
        messages.extend(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": call_id,
                            "name": "read_file",
                            "args": {"path": f"{index}.md"},
                        }
                    ],
                ),
                ToolMessage(
                    content=f"payload {index} " * 50,
                    tool_call_id=call_id,
                    name="read_file",
                ),
            ]
        )

    compacted, replacements = microcompact_messages(messages, keep_recent=3)

    assert len(compacted) == len(messages)
    assert len(replacements) == 5
    assert [message.tool_call_id for message in compacted if isinstance(message, ToolMessage)] == [
        f"c{index}" for index in range(8)
    ]
    tool_contents = [
        message.content for message in compacted if isinstance(message, ToolMessage)
    ]
    assert tool_contents[:5] == [PRUNED_TOOL_PLACEHOLDER] * 5
    assert tool_contents[-3:] != [PRUNED_TOOL_PLACEHOLDER] * 3


def test_microcompact_waits_for_a_minimum_batch():
    messages = [HumanMessage(content="ingest")]
    for index in range(8):
        call_id = f"c{index}"
        messages.extend(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": call_id,
                            "name": "read_file",
                            "args": {"path": f"{index}.md"},
                        }
                    ],
                ),
                ToolMessage(
                    content="payload " * 50,
                    tool_call_id=call_id,
                    name="read_file",
                ),
            ]
        )

    compacted, replacements = microcompact_messages(
        messages,
        keep_recent=3,
        min_replacements=20,
    )

    assert compacted is messages
    assert replacements == []


def test_post_compact_tail_bounds_a_large_recent_read_and_keeps_the_group():
    messages = [
        HumanMessage(content="ingest"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "c1",
                    "name": "read_file",
                    "args": {"path": "raw/paper.md"},
                }
            ],
        ),
        ToolMessage(
            content="HEAD " + ("evidence " * 5_000) + " TAIL",
            tool_call_id="c1",
            name="read_file",
        ),
    ]

    bounded = bound_post_compact_tool_results(messages)
    tool_result = bounded[2]

    assert isinstance(tool_result, ToolMessage)
    assert len(str(tool_result.content)) < len(str(messages[2].content))
    assert "trimmed for compaction tail" in str(tool_result.content)
    start = find_tail_start(bounded, retained_tokens=3_065)
    assert start == 1
    assert not isinstance(bounded[start], ToolMessage)


def test_fallback_policy_clamps_retained_below_threshold_and_summary_budget():
    policy = resolve_prompt_cache_policy(
        protocol="responses",
        model_id="deepseek-flash-v4.1",
        base_url="https://example.invalid/v1",
    )

    assert policy.compact_threshold == 32_536
    assert policy.summary_output_tokens == 20_000
    assert policy.retained_tokens == 8_536
    assert policy.summary_input_tokens == 45_536

# -- stream hygiene ---------------------------------------------------------


def test_summarizer_chunks_are_stripped_from_runtime_signals():
    """受控摘要调用绝不进旁白/事件（2026-09 泄漏事故的回归锁）。"""

    from langchain_core.messages import AIMessageChunk

    from cellwiki.domain.runs import AgentEventType
    from cellwiki.services.agent_runtime import _signals_from_stream_item

    chunk = AIMessageChunk(content="SESSION INTENT / SUMMARY / NEXT STEPS ...")
    item = (
        (),
        "messages",
        (
            chunk,
            {
                "tags": ["cellwiki:summarizer"],
                "cellwiki_role": "summarizer",
            },
        ),
    )
    assert _signals_from_stream_item(item) == []

    normal = (
        (),
        "messages",
        (AIMessageChunk(content="real answer"), {"tags": []}),
    )
    signals = _signals_from_stream_item(normal)
    assert any(
        signal.type == AgentEventType.MESSAGE_DELTA and signal.message == "real answer"
        for signal in signals
    )


def test_reinjected_summary_and_remove_messages_are_not_emitted():
    """中间件重注入的摘要/RemoveMessage 不再产生旁白事件（按 id 去重）。"""

    from langchain_core.messages import RemoveMessage

    from cellwiki.services.agent_runtime import _signals_from_stream_item

    remove = (
        (),
        "messages",
        (RemoveMessage(id="__remove_all__"), {}),
    )
    assert _signals_from_stream_item(remove) == []

    summary = (
        (),
        "messages",
        (
            HumanMessage(id="compaction-summary", content="[Compacted context]\n..."),
            {},
        ),
    )
    assert _signals_from_stream_item(summary) == []


def test_custom_compaction_signals_become_started_and_completed() -> None:
    """custom 通道的压缩通知被翻译成 started/completed 信号（runtime 落库入口）。"""

    from cellwiki.domain.runs import AgentEventType
    from cellwiki.services.agent_runtime import _signals_from_stream_item

    started = _signals_from_stream_item(
        (
            (),
            "custom",
            {
                "kind": "context_compaction",
                "phase": "started",
                "compaction_id": "cmp_1",
                "reason": "threshold",
                "estimated_tokens": 500_000,
                "threshold": 479_000,
            },
        )
    )
    assert [s.type for s in started] == [AgentEventType.CONTEXT_COMPACTION_STARTED]
    assert started[0].data["mode"] == "local"
    assert started[0].data["compaction_id"] == "cmp_1"
    assert started[0].data["reason"] == "threshold"

    completed = _signals_from_stream_item(
        (
            (),
            "custom",
            {
                "kind": "context_compaction",
                "phase": "completed",
                "compaction_id": "cmp_1",
                "reason": "threshold",
                "summary_source": "llm",
                "summary": "## Objective\n- keep",
                "tail": [],
                "retained_messages": 0,
                "retained_groups": 0,
                "boundary_type": "summary_only",
                "forced": True,
                "pre_tokens": 500_000,
                "post_tokens": 9_000,
                "tail_tokens": 0,
                "estimated_tokens": 500_000,
                "threshold": 479_000,
                "effective_context_limit": 512_000,
                "window_source": "configured",
                "ptl_attempts": 1,
            },
        )
    )
    assert [s.type for s in completed] == [AgentEventType.CONTEXT_COMPACTION_COMPLETED]
    assert completed[0].data["compaction_id"] == "cmp_1"
    assert completed[0].data["summary_source"] == "llm"
    assert completed[0].data["summary"].startswith("## Objective")
    assert completed[0].data["post_tokens"] == 9_000
    assert completed[0].data["boundary_type"] == "summary_only"
    assert completed[0].data["forced"] is True
    assert completed[0].data["window_source"] == "configured"
    assert completed[0].data["ptl_attempts"] == 1


def test_microcompact_signal_is_internal_and_carries_replacements() -> None:
    from cellwiki.domain.runs import AgentEventType
    from cellwiki.services.agent_runtime import _signals_from_stream_item

    signals = _signals_from_stream_item(
        (
            (),
            "custom",
            {
                "kind": "context_microcompact",
                "pre_tokens": 80_000,
                "post_tokens": 20_000,
                "threshold": 32_536,
                "replacements": [
                    {
                        "tool_call_id": "call_1",
                        "name": "read_file",
                        "text": PRUNED_TOOL_PLACEHOLDER,
                    }
                ],
            },
        )
    )

    assert [signal.type for signal in signals] == [AgentEventType.PROGRESS]
    assert signals[0].data["_internal_kind"] == "context_microcompact"
    assert signals[0].data["replacements"][0]["tool_call_id"] == "call_1"


def test_two_compactions_in_one_run_get_distinct_dedup_keys() -> None:
    """同一 run 内多次压缩：事件去重键必须按 compaction_id 区分。"""

    from cellwiki.services.agent_runtime import _signal_key, RuntimeSignal
    from cellwiki.domain.runs import AgentEventType

    first = RuntimeSignal(
        type=AgentEventType.CONTEXT_COMPACTION_COMPLETED,
        message="Context compacted.",
        data={"mode": "local", "compaction_id": "cmp_1"},
    )
    second = RuntimeSignal(
        type=AgentEventType.CONTEXT_COMPACTION_COMPLETED,
        message="Context compacted.",
        data={"mode": "local", "compaction_id": "cmp_2"},
    )
    assert _signal_key("seg", first) != _signal_key("seg", second)
