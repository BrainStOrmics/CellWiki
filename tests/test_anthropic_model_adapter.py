# =============================================================================
# 原生 Anthropic 协议适配测试 —— Messages API 形状与目录链路合同
# =============================================================================
# 覆盖：spec 构建与协议分发、base_url 默认、overrides 映射（字段键/请求体
# 扩展键/保留键）、root_client 生命周期句柄与每实例连接池隔离、/v1/models
# 拉取头与清洗、探测分支（JSON 指令 + 宽松解析）、harness profile 注册。
# 真实供应商行为（tool_use 往返、thinking）不在本文件：需要 key 的沙箱
# smoke，见 design/archive/2026-09-15-three-protocol-token-streaming.md。
# =============================================================================

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from cellwiki.adapters.anthropic_model import (
    ANTHROPIC_DEFAULT_BASE_URL,
    ANTHROPIC_VERSION,
    ChatAnthropicWithRootClient,
    build_anthropic_model_from_spec,
    fetch_anthropic_models,
)
from cellwiki.adapters.openai_model import build_model_from_spec, fetch_provider_models
from cellwiki.domain.model_provider import WIRE_PROTOCOL_ANTHROPIC
from cellwiki.domain.model_providers import ResolvedModelSpec
from cellwiki.services.environment import EnvironmentSettingsService, _extract_json_object


def _spec(**overrides) -> ResolvedModelSpec:
    values: dict = {
        "provider_id": "claude",
        "model_id": "claude-sonnet-4-5-20250929",
        "base_url": "https://gw.example/anthropic",
        "protocol": WIRE_PROTOCOL_ANTHROPIC,
        "api_key": "sk-ant-test",
        "request_overrides": {},
    }
    values.update(overrides)
    return ResolvedModelSpec(**values)


# ---------------------------------------------------------------------------
# 工厂与协议分发
# ---------------------------------------------------------------------------
def test_spec_build_dispatches_to_chat_anthropic() -> None:
    model = build_model_from_spec(_spec(), timeout_seconds=45.0, max_retries=0)
    try:
        assert isinstance(model, ChatAnthropic)
        assert model.model == "claude-sonnet-4-5-20250929"
        assert model.anthropic_api_url == "https://gw.example/anthropic"
        assert model.temperature == 0
        assert model.max_retries == 0
        assert model.default_request_timeout == 45.0
        assert model.max_tokens and model.max_tokens > 0
    finally:
        model.root_client.close()


def test_anthropic_build_defaults_base_url_to_official_endpoint() -> None:
    model = build_anthropic_model_from_spec(_spec(base_url=""))
    try:
        assert model.anthropic_api_url == ANTHROPIC_DEFAULT_BASE_URL
    finally:
        model.root_client.close()


def test_anthropic_build_requires_key() -> None:
    with pytest.raises(RuntimeError, match="no API key"):
        build_anthropic_model_from_spec(_spec(api_key=""))


def test_anthropic_overrides_split_fields_and_request_body_extras() -> None:
    model = build_anthropic_model_from_spec(
        _spec(
            request_overrides={
                "thinking": {"type": "enabled", "budget_tokens": 1024},
                "max_tokens": 2048,
                "enable_thinking": False,
            }
        )
    )
    try:
        # 字段键（thinking/max_tokens）走构造参数；未知名走 model_kwargs 请求体扩展。
        assert model.thinking == {"type": "enabled", "budget_tokens": 1024}
        assert model.max_tokens == 2048
        assert model.model_kwargs == {"enable_thinking": False}
        payload = model._get_request_payload([HumanMessage(content="hi")])
        assert payload["max_tokens"] == 2048
        assert payload["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    finally:
        model.root_client.close()


def test_anthropic_cache_mode_override_is_not_forwarded() -> None:
    model = build_anthropic_model_from_spec(
        _spec(request_overrides={"cache_mode": "off", "enable_thinking": False})
    )
    try:
        assert model.model_kwargs == {"enable_thinking": False}
        assert "cache_mode" not in model.model_kwargs
    finally:
        model.root_client.close()


def test_anthropic_serializes_cache_control_on_system_and_tool_result() -> None:
    model = build_anthropic_model_from_spec(_spec())
    try:
        payload = model._get_request_payload(
            [
                SystemMessage(
                    content=[
                        {
                            "type": "text",
                            "text": "stable prefix",
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                ),
                HumanMessage(content="hi"),
                ToolMessage(
                    content=[
                        {
                            "type": "text",
                            "text": "tool output",
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tool_call_id="call_1",
                    name="ls",
                ),
            ]
        )
        assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
        tool_result = payload["messages"][0]["content"][-1]
        assert tool_result["type"] == "tool_result"
        assert tool_result["cache_control"] == {"type": "ephemeral"}
    finally:
        model.root_client.close()


def test_anthropic_reserved_overrides_are_rejected() -> None:
    with pytest.raises(ValueError, match="reserved"):
        build_anthropic_model_from_spec(
            _spec(request_overrides={"base_url": "https://evil.example"})
        )
    with pytest.raises(ValueError, match="reserved"):
        build_anthropic_model_from_spec(
            _spec(request_overrides={"timeout": 1})
        )


def test_root_client_handle_matches_runtime_contract() -> None:
    """看门狗强制断连与抽取取消监视依赖 getattr(model, "root_client").close()。"""
    model = build_anthropic_model_from_spec(_spec())
    client = getattr(model, "root_client", None)
    assert client is model._client
    client.close()


def test_harness_profile_registers_for_anthropic_provider() -> None:
    from deepagents.profiles.harness.harness_profiles import _harness_profile_for_model

    from cellwiki.agent.app import HARNESS_PROMPT, _register_cellwiki_harness_profile

    _register_cellwiki_harness_profile("claude-sonnet-4-5-20250929")
    model = ChatAnthropicWithRootClient(
        model="claude-sonnet-4-5-20250929", api_key="k"
    )
    try:
        profile = _harness_profile_for_model(model, None)
        assert profile.base_system_prompt == HARNESS_PROMPT
        assert profile.general_purpose_subagent is not None
        assert profile.general_purpose_subagent.enabled is False
        assert "execute" in profile.excluded_tools
    finally:
        model.root_client.close()


# ---------------------------------------------------------------------------
# /v1/models 拉取
# ---------------------------------------------------------------------------
def test_fetch_anthropic_models_uses_native_headers_and_v1_path(monkeypatch) -> None:
    seen: dict = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": [{"id": "claude-b"}, {"id": "claude-a"}, {"id": "claude-b"}],
                "has_more": False,
            }

    def fake_get(url, headers, params, timeout):
        seen.update(url=url, headers=headers, params=params, timeout=timeout)
        return _Response()

    monkeypatch.setattr("cellwiki.adapters.anthropic_model.httpx.get", fake_get)
    assert fetch_anthropic_models("", "sk-ant-live") == ["claude-a", "claude-b"]
    assert seen["url"] == f"{ANTHROPIC_DEFAULT_BASE_URL}/v1/models"
    assert seen["headers"] == {
        "x-api-key": "sk-ant-live",
        "anthropic-version": ANTHROPIC_VERSION,
    }
    assert "Authorization" not in seen["headers"]
    assert seen["params"] == {"limit": 1000}


def test_fetch_provider_models_dispatches_on_protocol(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_anthropic(base_url: str, api_key: str, *, timeout_seconds: float):
        calls.append((base_url, api_key))
        return ["claude-a"]

    monkeypatch.setattr(
        "cellwiki.adapters.openai_model.fetch_anthropic_models", fake_anthropic
    )
    assert (
        fetch_provider_models(
            "https://gw.example/anthropic",
            "sk-ant-live",
            protocol=WIRE_PROTOCOL_ANTHROPIC,
        )
        == ["claude-a"]
    )
    assert calls == [("https://gw.example/anthropic", "sk-ant-live")]


def test_fetch_anthropic_models_scrubs_key_from_errors(monkeypatch) -> None:
    def fake_get(url, headers, params, timeout):
        raise RuntimeError(f"connect failed for key {headers['x-api-key']}")

    monkeypatch.setattr("cellwiki.adapters.anthropic_model.httpx.get", fake_get)
    with pytest.raises(RuntimeError) as error:
        fetch_anthropic_models("https://gw.example/anthropic", "sk-ant-live")
    assert "sk-ant-live" not in str(error.value)


# ---------------------------------------------------------------------------
# 测试连接（探测）分支
# ---------------------------------------------------------------------------
def test_connection_probe_uses_instruction_json_for_anthropic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-secret\n", encoding="utf-8")
    model = MagicMock()
    model.invoke.return_value = AIMessage(content='```json\n{"status":"CELLWIKI_OK"}\n```')
    captured: dict = {}

    def fake_build(spec, **kwargs):
        captured["spec"] = spec
        captured["kwargs"] = kwargs
        return model

    monkeypatch.setattr(
        "cellwiki.adapters.openai_model.build_model_from_spec", fake_build
    )
    service = EnvironmentSettingsService(tmp_path)
    result = service.test_connection(
        openai_base_url="https://api.anthropic.com",
        openai_model="claude-sonnet-4-5-20250929",
        openai_api_key=None,
        openai_api_protocol="anthropic",
    )

    assert result["ok"] is True
    assert result["protocol"] == "anthropic"
    spec = captured["spec"]
    assert spec.protocol == "anthropic"
    assert spec.api_key == "test-secret"
    assert captured["kwargs"] == {
        "timeout_seconds": 20,
        "max_retries": 0,
        "purpose": "structured",
    }
    # Anthropic Messages API 没有 response_format；探测用 max_tokens 限界。
    assert model.invoke.call_args.kwargs == {"max_tokens": 80}
    model.root_client.close.assert_called_once_with()
    assert "test-secret" not in str(result)


def test_connection_probe_fails_on_non_json_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-secret\n", encoding="utf-8")
    model = MagicMock()
    model.invoke.return_value = AIMessage(content="I cannot comply with that request.")

    monkeypatch.setattr(
        "cellwiki.adapters.openai_model.build_model_from_spec",
        lambda spec, **kwargs: model,
    )
    service = EnvironmentSettingsService(tmp_path)
    # test_connection 直接抛错；API 层（/test、/settings/test）把它转成 ok=False。
    with pytest.raises(RuntimeError) as error:
        service.test_connection(
            openai_base_url="https://api.anthropic.com",
            openai_model="claude-sonnet-4-5-20250929",
            openai_api_key=None,
            openai_api_protocol="anthropic",
        )
    assert "test-secret" not in str(error.value)


@pytest.mark.parametrize(
    "text",
    [
        '{"status":"CELLWIKI_OK"}',
        '```json\n{"status":"CELLWIKI_OK"}\n```',
        'Sure! {"status":"CELLWIKI_OK"}',
    ],
)
def test_extract_json_object_accepts_wrapped_json(text: str) -> None:
    assert _extract_json_object(text) == {"status": "CELLWIKI_OK"}


def test_extract_json_object_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        _extract_json_object("[1, 2, 3]")


def test_anthropic_instances_do_not_share_one_http_client() -> None:
    """强制断连只断开本实例：共享连接池会让同进程后续 run 全部失败。"""

    first = build_anthropic_model_from_spec(_spec(), timeout_seconds=45.0)
    second = build_anthropic_model_from_spec(_spec(), timeout_seconds=45.0)
    try:
        assert first.root_client is not second.root_client
        first.root_client.close()
        assert first.root_client.is_closed() is True
        # 运行时的看门狗就是靠 root_client.close() 断开挂起的流；共享客户端的
        # 话这里会是 True，后续每个 run 都会立刻抛 "client has been closed"。
        assert second.root_client.is_closed() is False
    finally:
        second.root_client.close()
