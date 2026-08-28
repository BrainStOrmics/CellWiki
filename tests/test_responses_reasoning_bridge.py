# =============================================================================
# Responses 推理流桥接契约测试（逐 token 流式提案的实施守卫）
# =============================================================================
# 覆盖：reasoning_text.* → 标准 summary 事件的翻译语义、未知事件形态的
# fail-open 透传、同步/异步流门面的迭代协议、build_model 的开关接线，
# 以及合成事件能通过 langchain-openai 私有转换器产出 reasoning content-block
# （该私有契约由 pyproject 的 langchain-openai>=1.3.5,<2 钉住，此处守卫）。
# =============================================================================

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputItemAddedEvent,
    ResponseReasoningSummaryPartAddedEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningTextDeltaEvent,
    ResponseReasoningTextDoneEvent,
    ResponseTextDeltaEvent,
)

from cellwiki.adapters.openai_reasoning_bridge import (
    ReasoningResponsesProxy,
    _ReasoningTranslationState,
    _TranslatingAsyncStream,
    _TranslatingStream,
    attach_reasoning_stream_bridge,
    reasoning_stream_proxy_attached,
    translate_reasoning_text_event,
)


def _reasoning_delta(item_id: str = "rs_1", text: str = "思考", seq: int = 5) -> ResponseReasoningTextDeltaEvent:
    return ResponseReasoningTextDeltaEvent(
        content_index=0, delta=text, item_id=item_id,
        output_index=0, sequence_number=seq,
        type="response.reasoning_text.delta",
    )


def _reasoning_done(item_id: str = "rs_1", text: str = "思考全文") -> ResponseReasoningTextDoneEvent:
    return ResponseReasoningTextDoneEvent(
        content_index=0, item_id=item_id, output_index=0,
        sequence_number=9, text=text, type="response.reasoning_text.done",
    )


def _output_text_delta(text: str = "答案") -> ResponseTextDeltaEvent:
    return ResponseTextDeltaEvent(
        content_index=0, delta=text, item_id="msg_1",
        logprobs=[], output_index=1, sequence_number=20,
        type="response.output_text.delta",
    )


def _translate(events: list[Any]) -> list[Any]:
    state = _ReasoningTranslationState()
    out: list[Any] = []
    for event in events:
        out.extend(translate_reasoning_text_event(event, state))
    return out


def test_first_reasoning_delta_opens_summary_part_then_deltas_follow():
    translated = _translate(
        [_reasoning_delta(text="想A", seq=1), _reasoning_delta(text="想B", seq=2)]
    )
    assert [type(e) for e in translated] == [
        ResponseReasoningSummaryPartAddedEvent,
        ResponseReasoningSummaryTextDeltaEvent,
        ResponseReasoningSummaryTextDeltaEvent,
    ]
    part_added = translated[0]
    assert part_added.item_id == "rs_1" and part_added.summary_index == 0
    assert part_added.part.text == "" and part_added.part.type == "summary_text"
    assert [e.delta for e in translated[1:]] == ["想A", "想B"]
    # sequence numbers are preserved so downstream ordering stays faithful
    assert [e.sequence_number for e in translated] == [1, 1, 2]


def test_second_reasoning_item_reopens_summary_part():
    translated = _translate(
        [_reasoning_delta(item_id="rs_1", seq=1), _reasoning_delta(item_id="rs_2", seq=2)]
    )
    assert [type(e) for e in translated] == [
        ResponseReasoningSummaryPartAddedEvent,
        ResponseReasoningSummaryTextDeltaEvent,
        ResponseReasoningSummaryPartAddedEvent,
        ResponseReasoningSummaryTextDeltaEvent,
    ]


def test_reasoning_text_done_is_swallowed():
    translated = _translate([_reasoning_delta(), _reasoning_done()])
    assert len(translated) == 2  # part_added + delta; done dropped
    assert all(not isinstance(e, ResponseReasoningTextDoneEvent) for e in translated)


def test_empty_delta_dropped_without_opening_part():
    translated = _translate([_reasoning_delta(text="")])
    assert translated == []


def test_other_events_pass_through_verbatim():
    text_delta = _output_text_delta()
    added = ResponseOutputItemAddedEvent(
        item=ResponseFunctionToolCall(name="noop", arguments="", call_id="c1", type="function_call"),
        output_index=0, sequence_number=1,
        type="response.output_item.added",
    )
    translated = _translate([text_delta, added])
    assert translated[0] is text_delta and translated[1] is added


def test_unknown_shape_reasoning_delta_forwards_verbatim():
    broken = SimpleNamespace(type="response.reasoning_text.delta")
    translated = _translate([broken])
    assert translated == [broken]


def test_synthetic_events_convert_to_reasoning_content_blocks():
    """Contract guard: langchain's converter must accept the synthesized pair."""
    from langchain_openai.chat_models.base import (
        _convert_responses_chunk_to_generation_chunk,
    )

    translated = _translate([_reasoning_delta(text="想A", seq=1)])
    index = output_index = sub_index = -1
    generation = None
    for event in translated:
        index, output_index, sub_index, generation = (
            _convert_responses_chunk_to_generation_chunk(
                event,
                index,
                output_index,
                sub_index,
                schema=None,
                metadata=None,
                has_reasoning=True,
                output_version="responses/v1",
            )
        )
    assert generation is not None
    blocks = generation.message.content
    assert isinstance(blocks, list) and blocks[0]["type"] == "reasoning"
    assert blocks[0]["summary"] == [{"index": 0, "type": "summary_text", "text": "想A"}]


class _FakeSyncStream:
    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self.exited = False

    def __enter__(self) -> "_FakeSyncStream":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.exited = True

    def close(self) -> None:  # pragma: no cover - exercised via __exit__ path
        pass

    def __iter__(self) -> Any:
        return iter(self._events)


class _FakeAsyncStream:
    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self.exited = False

    async def __aenter__(self) -> "_FakeAsyncStream":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.exited = True

    async def close(self) -> None:  # pragma: no cover
        pass

    async def __aiter__(self) -> Any:
        for event in self._events:
            yield event


def test_sync_facade_translates_and_delegates_context():
    inner = _FakeSyncStream([_reasoning_delta(), _output_text_delta()])
    with _TranslatingStream(inner) as facade:
        collected = list(facade)
    assert [type(e) for e in collected] == [
        ResponseReasoningSummaryPartAddedEvent,
        ResponseReasoningSummaryTextDeltaEvent,
        ResponseTextDeltaEvent,
    ]
    assert inner.exited is True


def test_async_facade_aenter_returns_facade_not_inner():
    async def run() -> list[Any]:
        inner = _FakeAsyncStream([_reasoning_delta(), _output_text_delta()])
        async with _TranslatingAsyncStream(inner) as facade:
            assert isinstance(facade, _TranslatingAsyncStream)
            return [event async for event in facade]

    collected = asyncio.run(run())
    assert [type(e) for e in collected] == [
        ResponseReasoningSummaryPartAddedEvent,
        ResponseReasoningSummaryTextDeltaEvent,
        ResponseTextDeltaEvent,
    ]


class _FakeResponsesResource:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return "PLAIN"

    @property
    def marker(self) -> str:
        return "inner-marker"


def test_proxy_intercepts_only_streaming_create():
    inner = _FakeResponsesResource()
    proxy = ReasoningResponsesProxy(inner)
    assert proxy.create(model="m") == "PLAIN"
    assert proxy.marker == "inner-marker"  # __getattr__ delegation
    assert inner.calls == [{"model": "m"}]


def _settings(**overrides: Any):
    from cellwiki.config import Settings

    base = dict(
        _env_file=None,
        openai_api_key="unit-test-key",
        openai_base_url="https://unit.test.invalid/v1",
        openai_model="unit-test-model",
        openai_api_protocol="responses",
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture()
def _no_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # ChatOpenAI would honor HTTP(S)_PROXY env vars at construction time;
    # keep client construction offline-deterministic.
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)


def test_build_model_enables_streaming_bridge_for_responses(_no_proxy_env):
    from cellwiki.agent.app import build_model

    model = build_model(_settings(agent_streaming=True))
    assert model.disable_streaming is False
    assert model.stream_usage is True
    assert reasoning_stream_proxy_attached(model)
    assert attach_reasoning_stream_bridge(model) is model  # idempotent
    assert isinstance(model.root_client.responses, ReasoningResponsesProxy)


def test_build_model_respects_kill_switch(_no_proxy_env):
    from cellwiki.agent.app import build_model

    model = build_model(_settings(agent_streaming=False))
    assert model.disable_streaming == "tool_calling"
    assert not reasoning_stream_proxy_attached(model)


def test_build_model_keeps_blocking_on_chat_protocol(_no_proxy_env):
    from cellwiki.agent.app import build_model

    model = build_model(
        _settings(agent_streaming=True, openai_api_protocol="chat_completions")
    )
    assert model.disable_streaming == "tool_calling"
    assert not reasoning_stream_proxy_attached(model)
