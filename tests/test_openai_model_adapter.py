"""Contract tests for the two OpenAI protocol shapes supported by CellWiki."""

from types import SimpleNamespace
from unittest.mock import patch

import httpx
from langchain_core.messages import HumanMessage

from cellwiki.adapters.openai_extraction import OpenAIChunkExtractor
from cellwiki.adapters.openai_model import (
    OPENAI_PROTOCOL_CHAT_COMPLETIONS,
    OPENAI_PROTOCOL_RESPONSES,
    build_openai_chat_model,
    provider_request_options,
)
from cellwiki.config import Settings


def _settings(protocol: str) -> Settings:
    """Create an isolated provider configuration without reading the developer .env."""

    return Settings(
        _env_file=None,
        openai_api_key="test-key",
        openai_base_url="https://provider.example/v1",
        openai_model="provider-model",
        openai_api_protocol=protocol,
    )


def test_default_timeout_covers_verified_long_structured_requests() -> None:
    configuration = Settings(_env_file=None)

    assert configuration.openai_request_timeout_seconds >= 60


def test_model_instances_do_not_share_default_http_client() -> None:
    configuration = _settings(OPENAI_PROTOCOL_CHAT_COMPLETIONS)
    first = build_openai_chat_model(configuration)
    second = build_openai_chat_model(configuration)

    try:
        assert isinstance(first.request_timeout, httpx.Timeout)
        assert isinstance(second.request_timeout, httpx.Timeout)
        assert first.root_client._client is not second.root_client._client
    finally:
        first.root_client.close()
        second.root_client.close()


def test_chat_completions_protocol_keeps_chat_payload_shape() -> None:
    model = build_openai_chat_model(_settings(OPENAI_PROTOCOL_CHAT_COMPLETIONS))

    payload = model._get_request_payload(
        [HumanMessage(content="Return JSON")],
        response_format={"type": "json_object"},
        max_completion_tokens=500,
    )

    assert model.use_responses_api is False
    assert "messages" in payload
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_completion_tokens"] == 500
    assert "input" not in payload


def test_responses_protocol_uses_langchain_payload_translation() -> None:
    model = build_openai_chat_model(_settings(OPENAI_PROTOCOL_RESPONSES))

    payload = model._get_request_payload(
        [HumanMessage(content="Return JSON")],
        response_format={"type": "json_object"},
        max_completion_tokens=500,
    )

    assert model.use_responses_api is True
    assert model.output_version == "responses/v1"
    assert "input" in payload
    assert payload["text"] == {"format": {"type": "json_object"}}
    assert payload["max_output_tokens"] == 500
    assert "messages" not in payload
    assert "response_format" not in payload


def test_responses_protocol_flattens_chat_completion_tool_schema() -> None:
    model = build_openai_chat_model(_settings(OPENAI_PROTOCOL_RESPONSES))
    chat_tool = {
        "type": "function",
        "function": {
            "name": "search_wiki",
            "description": "Search published Wiki pages.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }

    payload = model._get_request_payload(
        [HumanMessage(content="Find T cells")],
        tools=[chat_tool],
        tool_choice="auto",
    )

    assert payload["tools"] == [
        {
            "type": "function",
            "name": "search_wiki",
            "description": "Search published Wiki pages.",
            "parameters": chat_tool["function"]["parameters"],
        }
    ]
    assert payload["tool_choice"] == "auto"


def test_provider_specific_options_are_owned_by_the_shared_adapter() -> None:
    assert provider_request_options(
        "https://token.sensenova.cn/v1",
        "deepseek-v4-flash",
        purpose="structured",
    ) == {"thinking": {"type": "disabled"}}
    assert provider_request_options(
        "https://token.sensenova.cn/v1",
        "other-model",
        purpose="structured",
    ) == {"thinking": {"enabled": False}}
    assert provider_request_options(
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "qwen3.8-max-preview",
        purpose="structured",
    ) == {"thinking_budget": 1000}
    assert provider_request_options(
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "qwen3.8-max-preview",
        purpose="agent",
    ) is None


def test_extraction_cache_identity_changes_with_endpoint_and_protocol() -> None:
    compatible = _settings(OPENAI_PROTOCOL_CHAT_COMPLETIONS)
    responses = compatible.model_copy(
        update={
            "openai_base_url": "https://responses.example/v1",
            "openai_api_protocol": OPENAI_PROTOCOL_RESPONSES,
        }
    )

    compatible_identity = OpenAIChunkExtractor(compatible).cache_identity
    responses_identity = OpenAIChunkExtractor(responses).cache_identity

    assert compatible_identity != responses_identity
    assert compatible.openai_api_key not in compatible_identity
    assert compatible.openai_base_url not in compatible_identity


def test_chunk_extractor_passes_its_configuration_to_structured_adapter() -> None:
    configuration = _settings(OPENAI_PROTOCOL_RESPONSES)
    extractor = OpenAIChunkExtractor(configuration)
    expected = object()

    with patch(
        "cellwiki.adapters.openai_extraction.extract_cell_types_from_chunk",
        return_value=expected,
    ) as extract:
        result = extractor.extract(
            SimpleNamespace(text="bounded evidence"),
            SimpleNamespace(stored_path="paper.pdf"),
        )

    assert result is expected
    assert extract.call_args.kwargs["configuration"] is configuration
    assert provider_request_options(
        "https://provider.example/v1",
        "provider-model",
        purpose="structured",
    ) is None
