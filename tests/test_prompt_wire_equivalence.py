"""Contract tests: the model wire prefix must not depend on message provenance.

2026-09-24 诊断（thread_ad275210d4c2424cb299065347c06ea1）：run 内图内 checkpoint
产生的 assistant 消息把 reasoning 与 function_call 放进 ``content`` 列表，并携带
``msg_*`` item id；跨 run 重建的 transcript 只有纯文本加 ``tool_calls``。两者在
Responses wire 上不同，provider 的 prefix cache 因此在中间 assistant 处断开
（公共前缀停在第 21 条 assistant）。

本文件锁定两件事：差异确实存在（缺陷证据），以及请求规范化后两者逐项一致。
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware.types import ModelRequest
from langchain_anthropic.chat_models import _format_messages as _format_anthropic_messages
from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import _construct_responses_api_input

from cellwiki.agent.app import _CellWikiToolBoundaryMiddleware


class _FakeAnthropicModel:
    """Stands in for ChatAnthropic; only the module path matters to _model_identity."""


_FakeAnthropicModel.__module__ = "langchain_anthropic.chat_models"


def _responses_model() -> ChatOpenAI:
    return ChatOpenAI(
        model="gpt-5.6",
        api_key="test-key",
        base_url="http://127.0.0.1:1/v1",
        use_responses_api=True,
        output_version="responses/v1",
    )


def _run_in_assistant(text: str, tool_calls: list[dict[str, Any]]) -> AIMessage:
    """Shape produced inside a run: reasoning + text + function_call blocks with item ids."""

    content: list[dict[str, Any]] = [
        {
            "type": "reasoning",
            "id": "msg_reasoning",
            "index": 0,
            "summary": [{"index": 0, "type": "summary_text", "text": "hidden thought"}],
            "content": [],
        }
    ]
    if text:
        content.append({"type": "text", "id": "msg_text", "index": 1, "text": text})
    for index, call in enumerate(tool_calls):
        content.append(
            {
                "type": "function_call",
                "id": f"msg_call_{index}",
                "name": call["name"],
                "arguments": json.dumps(call["args"]),
                "call_id": call["id"],
            }
        )
    return AIMessage(content=content, tool_calls=tool_calls)


def _rebuilt_assistant(text: str, tool_calls: list[dict[str, Any]]) -> AIMessage:
    """Shape produced by render_model_messages(): plain text plus tool_calls."""

    return AIMessage(content=text, tool_calls=tool_calls)


def _filter(
    model: Any,
    messages: list[Any],
    *,
    reasoning_replay: str = "none",
) -> list[Any]:
    middleware = _CellWikiToolBoundaryMiddleware(
        append_reminder=False,
        cache_policy=None,
        reasoning_replay=reasoning_replay,
    )
    request = ModelRequest(
        model=model,
        messages=list(messages),
        system_message=SystemMessage(content="system"),
        tools=[],
    )
    return list(middleware._filter_request(request).messages)


TOOL_CALLS: list[dict[str, Any]] = [
    {"name": "glob", "args": {"pattern": "raw/*/*"}, "id": "call_1"},
    {"name": "read_file", "args": {"path": "schema.md"}, "id": "call_2"},
]


def _call_signature(calls: list[dict[str, Any]]) -> list[tuple[str, Any, str]]:
    """LangChain normalizes tool_calls with an extra ``type`` key; compare the contract."""

    return [(call["name"], call["args"], call["id"]) for call in calls]


def test_run_in_and_rebuilt_shapes_differ_on_the_raw_wire() -> None:
    """缺陷证据：未规范化时两种来源的 wire 不同，缓存前缀必然断开。"""

    run_in = _run_in_assistant("answer", TOOL_CALLS)
    rebuilt = _rebuilt_assistant("answer", TOOL_CALLS)
    assert _construct_responses_api_input([run_in]) != _construct_responses_api_input(
        [rebuilt]
    )


def test_responses_wire_is_identical_after_normalization() -> None:
    model = _responses_model()
    run_in = _run_in_assistant("answer", TOOL_CALLS)
    rebuilt = _rebuilt_assistant("answer", TOOL_CALLS)

    filtered = _filter(model, [run_in])
    assert _construct_responses_api_input(filtered) == _construct_responses_api_input(
        [rebuilt]
    )


def test_normalization_drops_reasoning_and_keeps_tool_calls() -> None:
    model = _responses_model()
    filtered = _filter(model, [_run_in_assistant("answer", TOOL_CALLS)])
    (message,) = filtered
    assert isinstance(message, AIMessage)
    assert message.content == "answer"
    assert _call_signature(message.tool_calls) == _call_signature(TOOL_CALLS)
    wire = _construct_responses_api_input(filtered)
    assert [item["type"] for item in wire] == ["message", "function_call", "function_call"]
    assert "id" not in wire[0]
    assert all("id" not in item for item in wire)


def test_normalization_handles_reasoning_only_turns() -> None:
    """纯工具调用轮只有 reasoning 块、没有文本，规范化后与重建形状一致。"""

    model = _responses_model()
    filtered = _filter(model, [_run_in_assistant("", TOOL_CALLS)])
    (message,) = filtered
    assert isinstance(message, AIMessage)
    assert message.content == ""
    assert _construct_responses_api_input(filtered) == _construct_responses_api_input(
        [_rebuilt_assistant("", TOOL_CALLS)]
    )


def test_opaque_mode_leaves_the_request_untouched() -> None:
    model = _responses_model()
    run_in = _run_in_assistant("answer", TOOL_CALLS)
    filtered = _filter(model, [run_in], reasoning_replay="opaque")
    assert filtered[0].content == run_in.content


def test_non_responses_protocols_are_not_normalized() -> None:
    """Responses 压平不作用于 Anthropic：reasoning/function_call 块原样保留。

    空（无正文）thinking 块的清理是另一条 anthropic 专项守卫，见下方用例。
    """

    run_in = _run_in_assistant("answer", TOOL_CALLS)
    filtered = _filter(_FakeAnthropicModel(), [run_in])
    assert filtered[0].content == run_in.content


def _vendor_anthropic_assistant(thinking_text: str | None) -> AIMessage:
    """DeepSeek Anthropic 路由流回的形状：thinking 块 + tool_use。

    ``thinking_text=None`` 建模退化块（只有签名、没有正文），这是引发
    "missing field `thinking`" 422 的原始形状（2026-10-14 事故）。
    """

    block: dict[str, Any] = {"type": "thinking", "index": 0, "signature": "sig_1"}
    if thinking_text is not None:
        block["thinking"] = thinking_text
    return AIMessage(
        content=[
            block,
            {"type": "tool_use", "index": 1, "id": "call_1", "name": "git", "input": {}},
        ],
        tool_calls=[{"name": "git", "args": {}, "id": "call_1"}],
    )


def test_anthropic_drops_signature_only_thinking_blocks() -> None:
    """退化 thinking 块（只有签名）会被 DeepSeek 拒绝回放，必须在发出前丢掉。"""

    message = _vendor_anthropic_assistant(None)
    (filtered,) = _filter(_FakeAnthropicModel(), [message])
    assert [block["type"] for block in filtered.content] == ["tool_use"]
    _system, wire = _format_anthropic_messages([filtered])
    assert [block["type"] for block in wire[0]["content"]] == ["tool_use"]


def test_anthropic_keeps_thinking_blocks_with_text() -> None:
    """带正文的签名块是 Anthropic 的回传契约（整体剥离会 400），必须原样保留。"""

    original = _vendor_anthropic_assistant("need to commit")
    (filtered,) = _filter(_FakeAnthropicModel(), [original])
    assert filtered.content == original.content


def test_anthropic_thinking_only_message_falls_back_to_empty_text() -> None:
    """整条消息只有一个退化 thinking 块时，回退为重建形状的空文本。"""

    message = AIMessage(content=[{"type": "thinking", "index": 0, "signature": "sig"}])
    (filtered,) = _filter(_FakeAnthropicModel(), [message])
    assert filtered.content == ""
    _system, wire = _format_anthropic_messages([filtered])
    assert wire[0]["content"] == ""


def test_anthropic_wire_never_carries_textless_thinking_blocks() -> None:
    """wire 级合同：规范化后不存在缺 thinking 正文的 thinking 块。"""

    messages = [
        _vendor_anthropic_assistant(None),
        _vendor_anthropic_assistant("kept"),
        _rebuilt_assistant("plain", TOOL_CALLS),
    ]
    filtered = _filter(_FakeAnthropicModel(), messages)
    _system, wire = _format_anthropic_messages(filtered)
    for message in wire:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "thinking":
                assert block.get("thinking")


def test_rebuilt_shape_is_a_fixed_point() -> None:
    """重建形状再规范化一次不变，保证跨 run 反复渲染稳定。"""

    model = _responses_model()
    rebuilt = _rebuilt_assistant("answer", TOOL_CALLS)
    filtered = _filter(model, [rebuilt])
    assert filtered[0].content == "answer"
    assert _call_signature(filtered[0].tool_calls) == _call_signature(TOOL_CALLS)


def test_provider_native_compaction_items_are_preserved() -> None:
    """opaque compaction item 是允许跨 run 重放的例外，规范化必须整条跳过。"""

    model = _responses_model()
    item = {"type": "compaction", "id": "cmp_1", "encrypted_content": "opaque"}
    message = AIMessage(content=[item])
    filtered = _filter(model, [message])
    assert filtered[0].content == [item]


def test_normalization_clears_the_coordinator_name() -> None:
    """图内消息带协调器名，重建形状没有；它不进 wire，但会让请求指纹误报。"""

    model = _responses_model()
    run_in = _run_in_assistant("answer", TOOL_CALLS).model_copy(
        update={"name": "cellwiki-agent"}
    )
    filtered = _filter(model, [run_in])
    assert filtered[0].name is None
    assert _construct_responses_api_input(filtered) == _construct_responses_api_input(
        [_rebuilt_assistant("answer", TOOL_CALLS)]
    )
