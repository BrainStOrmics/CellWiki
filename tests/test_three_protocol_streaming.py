# =============================================================================
# 三种线协议统一逐 token 流式契约测试
# =============================================================================
# 覆盖：chat_completions 流式 chunk 的 reasoning_content 提取（provider 子类）、
# anthropic 原生 thinking 块到 reasoning_delta 的映射，以及正文增量在两种形状下
# 都不被吞掉。决策与范围见 design/archive/2026-09-15-three-protocol-token-streaming.md。
# =============================================================================

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk

from cellwiki.adapters.openai_model import build_model_from_spec
from cellwiki.adapters.openai_reasoning_content import ChatOpenAIWithReasoningContent
from cellwiki.domain.model_providers import ResolvedModelSpec
from cellwiki.domain.runs import AgentEventType
from cellwiki.services.agent_runtime import _reasoning_text, _signals_from_stream_item


@pytest.fixture()
def _no_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # ChatOpenAI honors HTTP(S)_PROXY at construction time; keep it offline-deterministic.
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)


def _spec(protocol: str) -> ResolvedModelSpec:
    return ResolvedModelSpec(
        provider_id="unit",
        model_id="unit-test-model",
        base_url="https://unit.test.invalid/v1",
        protocol=protocol,
        api_key="unit-test-key",
        request_overrides={},
    )


def _chat_model() -> ChatOpenAIWithReasoningContent:
    return ChatOpenAIWithReasoningContent(
        model="unit-test-model",
        api_key="unit-test-key",
        base_url="https://unit.test.invalid/v1",
    )


def _chunk(delta: dict) -> dict:
    return {"choices": [{"index": 0, "delta": delta}]}


def test_catalog_chat_completions_uses_reasoning_content_subclass(_no_proxy_env):
    model = build_model_from_spec(
        _spec("chat_completions"),
        purpose="coordinator",
        disable_streaming=False,
        stream_usage=True,
    )
    assert isinstance(model, ChatOpenAIWithReasoningContent)
    assert model.disable_streaming is False


def test_catalog_responses_keeps_plain_chat_openai(_no_proxy_env):
    model = build_model_from_spec(
        _spec("responses"),
        purpose="coordinator",
        disable_streaming=False,
        stream_usage=True,
    )
    assert not isinstance(model, ChatOpenAIWithReasoningContent)
    assert model.use_responses_api is True


def test_chat_completions_reasoning_delta_lands_in_additional_kwargs(_no_proxy_env):
    generation = _chat_model()._convert_chunk_to_generation_chunk(
        _chunk({"reasoning_content": "想A"}), AIMessageChunk, None
    )
    assert generation is not None
    assert generation.message.additional_kwargs["reasoning_content"] == "想A"
    assert _reasoning_text(generation.message) == "想A"


def test_chat_completions_reasoning_alias_is_kept(_no_proxy_env):
    generation = _chat_model()._convert_chunk_to_generation_chunk(
        _chunk({"reasoning": "别名思考"}), AIMessageChunk, None
    )
    assert generation is not None
    assert _reasoning_text(generation.message) == "别名思考"


def test_chat_completions_text_delta_is_untouched(_no_proxy_env):
    generation = _chat_model()._convert_chunk_to_generation_chunk(
        _chunk({"content": "答案"}), AIMessageChunk, None
    )
    assert generation is not None
    assert generation.message.content == "答案"
    assert generation.message.additional_kwargs == {}


def test_stream_item_emits_reasoning_delta_for_anthropic_thinking_block():
    chunk = AIMessageChunk(
        content=[{"type": "thinking", "thinking": "先看文件", "index": 0}],
        id="call_1",
    )
    signals = list(_signals_from_stream_item(("messages", (chunk, {}))))
    reasoning = [
        signal for signal in signals if signal.type is AgentEventType.REASONING_DELTA
    ]
    assert [signal.message for signal in reasoning] == ["先看文件"]
    assert not [
        signal for signal in signals if signal.type is AgentEventType.MESSAGE_DELTA
    ]


def test_stream_item_keeps_anthropic_text_block_out_of_reasoning():
    chunk = AIMessageChunk(
        content=[{"type": "text", "text": "正文增量", "index": 1}],
        id="call_1",
    )
    signals = list(_signals_from_stream_item(("messages", (chunk, {}))))
    text = [signal for signal in signals if signal.type is AgentEventType.MESSAGE_DELTA]
    assert [signal.message for signal in text] == ["正文增量"]
    assert not [
        signal for signal in signals if signal.type is AgentEventType.REASONING_DELTA
    ]


def test_anthropic_signature_only_delta_is_not_reasoning_text():
    chunk = AIMessageChunk(
        content=[{"type": "thinking", "signature": "sig", "index": 0}], id="call_1"
    )
    assert _reasoning_text(chunk) is None


def test_anthropic_thinking_delta_keeps_whitespace_delta():
    chunk = AIMessageChunk(
        content=[{"type": "thinking", "thinking": " "}], id="call_1"
    )
    assert _reasoning_text(chunk) == " "
