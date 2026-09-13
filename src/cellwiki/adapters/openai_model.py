"""Shared LangChain model construction for provider wire protocols."""

from __future__ import annotations

from typing import Any, Literal

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from cellwiki.adapters.anthropic_model import (
    build_anthropic_model_from_spec,
    fetch_anthropic_models,
)
from cellwiki.config import Settings
from cellwiki.domain.model_provider import (
    WIRE_PROTOCOL_ANTHROPIC,
    WIRE_PROTOCOL_CHAT_COMPLETIONS,
    WIRE_PROTOCOL_RESPONSES,
    normalize_wire_protocol,
)
from cellwiki.domain.model_providers import ResolvedModelSpec

__all__ = [
    "WIRE_PROTOCOL_ANTHROPIC",
    "WIRE_PROTOCOL_CHAT_COMPLETIONS",
    "WIRE_PROTOCOL_RESPONSES",
    "build_model_from_spec",
    "build_openai_chat_model",
    "fetch_provider_models",
    "normalize_wire_protocol",
    "provider_request_options",
]


def provider_request_options(
    base_url: str,
    model: str,
    *,
    purpose: Literal[
        "agent",
        "structured",
        "coordinator",
        "router",
        "page_query",
        "structured_extraction",
    ] = "agent",
) -> dict | None:
    """Return OpenAI-shape provider extensions for the request purpose that needs them.

    仅服务于 OpenAI 形状的两种协议；原生 Anthropic（Messages API）不走嗅探，
    只认供应商自己的 ``request_overrides``。
    """

    structured_purpose = purpose in {"structured", "structured_extraction"}
    low_reasoning_purpose = purpose in {"router", "page_query"}
    if not structured_purpose and not low_reasoning_purpose:
        return None

    normalized_url = base_url.lower()
    normalized_model = model.lower()
    if "sensenova.cn" in normalized_url:
        if normalized_model.startswith("deepseek-v4"):
            # DeepSeek V4 uses a typed thinking switch on this provider route.
            return {"thinking": {"type": "disabled"}}
        return {"thinking": {"enabled": False}}
    if "maas.aliyuncs.com/compatible-mode" in normalized_url and normalized_model.startswith(
        "qwen3"
    ):
        if low_reasoning_purpose:
            return {"thinking_budget": 512}
        # Current Qwen thinking-only models reject enable_thinking=false. A bounded
        # reasoning budget leaves enough output capacity for the extraction JSON.
        return {"thinking_budget": 1000}
    return None


def build_model_from_spec(
    spec: ResolvedModelSpec,
    *,
    timeout_seconds: float | None = None,
    max_retries: int = 1,
    disable_streaming: bool | Literal["tool_calling"] = "tool_calling",
    stream_usage: bool | None = None,
    purpose: Literal[
        "agent",
        "structured",
        "coordinator",
        "router",
        "page_query",
        "structured_extraction",
    ] = "agent",
) -> BaseChatModel:
    """Build one chat model from a fully resolved provider-catalog selection.

    按协议分发：``anthropic`` 走原生 Messages API 工厂
    （``adapters/anthropic_model.py``），其余走 ChatOpenAI。OpenAI 形状下
    内置的 URL/模型名嗅探特化保留为兜底；供应商的 ``request_overrides``
    总是最后合并、覆盖嗅探结果——用户显式配置拥有最高优先级。
    """

    if not spec.api_key:
        raise RuntimeError(f"provider {spec.provider_id} has no API key configured")

    protocol = normalize_wire_protocol(spec.protocol)
    if protocol == WIRE_PROTOCOL_ANTHROPIC:
        return build_anthropic_model_from_spec(
            spec,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            disable_streaming=disable_streaming,
            stream_usage=stream_usage,
        )

    extra_body: dict[str, Any] = dict(
        provider_request_options(spec.base_url, spec.model_id, purpose=purpose) or {}
    )
    for key, value in spec.request_overrides.items():
        extra_body[key] = value
    # langchain-openai caches its default httpx client when the timeout is
    # hashable. Each extraction chunk closes its model client after completion,
    # so use an unhashable timeout to keep that lifecycle isolated per model.
    request_timeout = httpx.Timeout(timeout_seconds or 90.0)
    return ChatOpenAI(
        model=spec.model_id,
        api_key=SecretStr(spec.api_key),
        base_url=spec.base_url or None,
        temperature=0,
        timeout=request_timeout,
        max_retries=max_retries,
        disable_streaming=disable_streaming,
        stream_usage=stream_usage,
        extra_body=extra_body or None,
        # Explicit booleans prevent model-name heuristics from silently switching
        # a third-party compatible endpoint to the Responses API.
        use_responses_api=protocol == WIRE_PROTOCOL_RESPONSES,
        output_version=(
            "responses/v1" if protocol == WIRE_PROTOCOL_RESPONSES else None
        ),
    )


def build_openai_chat_model(
    configuration: Settings,
    *,
    timeout_seconds: float | None = None,
    max_retries: int = 1,
    disable_streaming: bool | Literal["tool_calling"] = "tool_calling",
    stream_usage: bool | None = None,
    purpose: Literal[
        "agent",
        "structured",
        "coordinator",
        "router",
        "page_query",
        "structured_extraction",
    ] = "agent",
) -> BaseChatModel:
    """Build one LangChain chat model from the legacy single-provider settings.

    LangChain owns the message, tool-call, token-limit, and structured-output
    translation between Chat Completions, Responses API, and the native
    Anthropic Messages API. CellWiki only makes the protocol choice explicit
    and supplies provider-specific request options.
    """

    if not configuration.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required to run CewiPilot")

    spec = ResolvedModelSpec(
        provider_id="",
        model_id=configuration.openai_model,
        base_url=configuration.openai_base_url,
        protocol=configuration.openai_api_protocol,
        api_key=configuration.openai_api_key,
        request_overrides={},
    )
    return build_model_from_spec(
        spec,
        timeout_seconds=timeout_seconds or configuration.openai_request_timeout_seconds,
        max_retries=max_retries,
        disable_streaming=disable_streaming,
        stream_usage=stream_usage,
        purpose=purpose,
    )


def fetch_provider_models(
    base_url: str,
    api_key: str,
    *,
    protocol: str = WIRE_PROTOCOL_CHAT_COMPLETIONS,
    timeout_seconds: float = 15.0,
) -> list[str]:
    """Fetch the model list from a provider endpoint, branching on the wire protocol.

    仅供后端代理调用：key 只随本请求发往该供应商自身的 base_url。
    Anthropic 的 base_url 遵循 SDK 语义（API 根，官方端点可留空），端点
    路径为 ``/v1/models``。
    """

    if normalize_wire_protocol(protocol) == WIRE_PROTOCOL_ANTHROPIC:
        return fetch_anthropic_models(
            base_url, api_key, timeout_seconds=timeout_seconds
        )
    if not base_url:
        raise RuntimeError("a base URL is required to fetch models")
    if not api_key:
        raise RuntimeError("an API key is required to fetch models")
    url = base_url.rstrip("/") + "/models"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_seconds),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as error:
        # 供应商错误可能回显请求头/URL；出栈前把 key 从消息里洗掉。
        raise RuntimeError(str(error).replace(api_key, "***")[:600]) from None
    entries = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise RuntimeError("provider returned an unexpected /models payload shape")
    models = sorted(
        {
            str(entry.get("id")).strip()
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("id") or "").strip()
        }
    )
    return models
