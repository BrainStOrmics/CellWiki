"""Provider protocol values shared without importing runtime configuration."""

from __future__ import annotations

from typing import Literal, cast


OPENAI_PROTOCOL_CHAT_COMPLETIONS = "chat_completions"
OPENAI_PROTOCOL_RESPONSES = "responses"
OpenAIProtocol = Literal["chat_completions", "responses"]
SUPPORTED_OPENAI_PROTOCOLS = frozenset(
    {OPENAI_PROTOCOL_CHAT_COMPLETIONS, OPENAI_PROTOCOL_RESPONSES}
)


def normalize_openai_protocol(value: str) -> OpenAIProtocol:
    """Validate the explicit wire protocol without importing provider SDKs."""

    normalized = value.strip().lower()
    if normalized not in SUPPORTED_OPENAI_PROTOCOLS:
        supported = ", ".join(sorted(SUPPORTED_OPENAI_PROTOCOLS))
        raise ValueError(f"OpenAI API protocol must be one of: {supported}")
    return cast(OpenAIProtocol, normalized)
