"""Shared LangChain model construction for OpenAI-shaped provider protocols."""

from __future__ import annotations

from typing import Literal

import httpx
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from cellwiki.config import Settings
from cellwiki.domain.model_provider import (
    OPENAI_PROTOCOL_CHAT_COMPLETIONS,
    OPENAI_PROTOCOL_RESPONSES,
    normalize_openai_protocol,
)

__all__ = [
    "OPENAI_PROTOCOL_CHAT_COMPLETIONS",
    "OPENAI_PROTOCOL_RESPONSES",
    "build_openai_chat_model",
    "normalize_openai_protocol",
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
    """Return provider extensions only for the request purpose that needs them."""

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


def build_openai_chat_model(
    configuration: Settings,
    *,
    timeout_seconds: float | None = None,
    max_retries: int = 1,
    disable_streaming: bool | Literal["tool_calling"] = "tool_calling",
    purpose: Literal[
        "agent",
        "structured",
        "coordinator",
        "router",
        "page_query",
        "structured_extraction",
    ] = "agent",
) -> ChatOpenAI:
    """Build one LangChain chat model for either supported OpenAI wire protocol.

    LangChain owns the message, tool-call, token-limit, and structured-output
    translation between Chat Completions and Responses API. CellWiki only makes
    the protocol choice explicit and supplies provider-specific request options.
    """

    if not configuration.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required to run the CellWiki agent")

    protocol = normalize_openai_protocol(configuration.openai_api_protocol)
    extra_body = provider_request_options(
        configuration.openai_base_url,
        configuration.openai_model,
        purpose=purpose,
    )
    # langchain-openai caches its default httpx client when the timeout is
    # hashable. Each extraction chunk closes its model client after completion,
    # so use an unhashable timeout to keep that lifecycle isolated per model.
    request_timeout = httpx.Timeout(
        timeout_seconds or configuration.openai_request_timeout_seconds
    )
    return ChatOpenAI(
        model=configuration.openai_model,
        api_key=SecretStr(configuration.openai_api_key),
        base_url=configuration.openai_base_url or None,
        temperature=0,
        timeout=request_timeout,
        max_retries=max_retries,
        disable_streaming=disable_streaming,
        extra_body=extra_body,
        # Explicit booleans prevent model-name heuristics from silently switching
        # a third-party compatible endpoint to the Responses API.
        use_responses_api=protocol == OPENAI_PROTOCOL_RESPONSES,
        output_version=(
            "responses/v1" if protocol == OPENAI_PROTOCOL_RESPONSES else None
        ),
    )
