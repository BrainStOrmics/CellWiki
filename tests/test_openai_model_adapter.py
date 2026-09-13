"""Contract tests for the two OpenAI protocol shapes supported by CellWiki."""


import httpx
from langchain_core.messages import HumanMessage

from cellwiki.adapters.openai_model import (
    OPENAI_PROTOCOL_CHAT_COMPLETIONS,
    OPENAI_PROTOCOL_RESPONSES,
    build_model_from_spec,
    build_openai_chat_model,
    fetch_provider_models,
    provider_request_options,
)
from cellwiki.domain.model_providers import ResolvedModelSpec
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
    assert provider_request_options(
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "qwen3.8-max-preview",
        purpose="page_query",
    ) == {"thinking_budget": 512}
    assert provider_request_options(
        "https://unknown-provider.example/v1",
        "qwen3-compatible-name",
        purpose="router",
    ) is None



# ---------------------------------------------------------------------------
# 供应商目录 spec 构建与 /models 拉取
# ---------------------------------------------------------------------------
def _spec(protocol: str = OPENAI_PROTOCOL_CHAT_COMPLETIONS, **overrides) -> ResolvedModelSpec:
    values = {
        "provider_id": "gw",
        "model_id": "provider-model",
        "base_url": "https://provider.example/v1",
        "protocol": protocol,
        "api_key": "test-key",
        "request_overrides": {},
    }
    values.update(overrides)
    return ResolvedModelSpec(**values)


def test_spec_build_honors_explicit_protocol_and_overrides() -> None:
    model = build_model_from_spec(
        _spec(
            OPENAI_PROTOCOL_RESPONSES,
            request_overrides={"thinking_budget": 512},
        ),
        purpose="structured_extraction",
    )
    try:
        assert model.use_responses_api is True
        assert model.extra_body == {"thinking_budget": 512}
    finally:
        model.root_client.close()


def test_spec_build_overrides_win_over_sniffed_specialization() -> None:
    # SenseNova + deepseek-v4 会嗅探出 thinking disabled；用户 overrides 必须覆盖它。
    model = build_model_from_spec(
        _spec(
            base_url="https://api.sensenova.cn/compatible-mode/v1",
            model_id="deepseek-v4-flash",
            request_overrides={"thinking": {"type": "enabled"}},
        ),
        purpose="structured_extraction",
    )
    try:
        assert model.extra_body == {"thinking": {"type": "enabled"}}
    finally:
        model.root_client.close()


def test_spec_build_requires_key() -> None:
    import pytest

    with pytest.raises(RuntimeError, match="no API key"):
        build_model_from_spec(_spec(api_key=""))


def test_fetch_provider_models_parses_sorted_unique_ids(monkeypatch) -> None:
    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-b"}]}

    def fake_get(url, headers, timeout):
        assert url == "https://provider.example/v1/models"
        assert headers["Authorization"] == "Bearer sk-live"
        return _Response()

    monkeypatch.setattr("cellwiki.adapters.openai_model.httpx.get", fake_get)
    assert fetch_provider_models("https://provider.example/v1", "sk-live") == [
        "model-a",
        "model-b",
    ]


def test_fetch_provider_models_scrubs_key_from_errors(monkeypatch) -> None:
    def fake_get(url, headers, timeout):
        raise RuntimeError(f"connect failed for key {headers['Authorization']}")

    monkeypatch.setattr("cellwiki.adapters.openai_model.httpx.get", fake_get)
    try:
        fetch_provider_models("https://provider.example/v1", "sk-live")
    except RuntimeError as error:
        assert "sk-live" not in str(error)
    else:
        raise AssertionError("expected RuntimeError")
