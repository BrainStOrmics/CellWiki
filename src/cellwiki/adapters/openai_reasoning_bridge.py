"""Bridge nonstandard reasoning SSE events into the Responses streaming protocol.

The configured gateway streams reasoning text as
``response.reasoning_text.delta`` / ``response.reasoning_text.done`` events.
These are *not* part of the Responses streaming contract langchain-openai
converts (it only understands ``response.reasoning_summary_part.added`` /
``response.reasoning_summary_text.delta``), so without a bridge the reasoning
text is silently dropped the moment request-level streaming is enabled
(design/active/2026-08-27-agent-token-streaming.md, evidence 4).

The bridge installs a proxy on the ChatOpenAI root clients' ``responses``
resource (verified shadowable as an instance attribute over the SDK's
``cached_property``) and wraps every streamed ``create`` result in a
translating stream: gateway-specific reasoning deltas are rewritten into the
standard summary-part lifecycle, ``reasoning_text.done`` is swallowed
(replaying its aggregate text would duplicate the reasoning content), and all
other events pass through untouched. Non-streaming calls (structured parsing)
return the SDK object verbatim.

Translation is deliberately fail-open: unknown event shapes are forwarded
verbatim, so an evolving provider protocol degrades reasoning back to
coarse-grained blocks without ever breaking answer streaming.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any

import openai
from langchain_openai import ChatOpenAI

__all__ = [
    "ReasoningResponsesProxy",
    "attach_reasoning_stream_bridge",
    "reasoning_stream_proxy_attached",
    "translate_reasoning_text_event",
]

_DELTA_EVENT = "response.reasoning_text.delta"
_DONE_EVENT = "response.reasoning_text.done"
_PART_ADDED = "response.reasoning_summary_part.added"
_PART_DELTA = "response.reasoning_summary_text.delta"


@dataclass(slots=True)
class _ReasoningItemState:
    """Per-reasoning-item translation state (has the summary part opened yet)."""

    part_opened: bool = False


@dataclass(slots=True)
class _ReasoningTranslationState:
    items: dict[str, _ReasoningItemState] = field(default_factory=dict)


def _synthetic_part_added(
    event: Any,
) -> openai.types.responses.ResponseReasoningSummaryPartAddedEvent:
    from openai.types.responses.response_reasoning_summary_part_added_event import Part

    return openai.types.responses.ResponseReasoningSummaryPartAddedEvent(
        item_id=str(event.item_id),
        output_index=int(event.output_index),
        part=Part(text="", type="summary_text"),
        sequence_number=int(event.sequence_number),
        summary_index=0,
        type=_PART_ADDED,
    )


def _synthetic_text_delta(
    event: Any, delta: str
) -> openai.types.responses.ResponseReasoningSummaryTextDeltaEvent:
    return openai.types.responses.ResponseReasoningSummaryTextDeltaEvent(
        delta=delta,
        item_id=str(event.item_id),
        output_index=int(event.output_index),
        sequence_number=int(event.sequence_number),
        summary_index=0,
        type=_PART_DELTA,
    )


def translate_reasoning_text_event(
    event: Any, state: _ReasoningTranslationState
) -> Iterator[Any]:
    """Yield zero or more stream events replacing one incoming event.

    Each ``reasoning_text.delta`` becomes one standard summary-part delta,
    preceded (once per reasoning item) by the part-added lifecycle event the
    langchain converter expects. The raw delta and ``reasoning_text.done``
    are consumed; every other event passes through unchanged.
    """

    event_type = getattr(event, "type", None)
    if event_type == _DONE_EVENT:
        return
    if event_type != _DELTA_EVENT:
        yield event
        return

    try:
        key = str(event.item_id)
        delta = str(event.delta)
        int(event.output_index)
        int(event.sequence_number)
    except (AttributeError, TypeError, ValueError):
        # Unknown event shape: forward verbatim rather than guess.
        yield event
        return
    if not delta:
        return

    item = state.items.setdefault(key, _ReasoningItemState())
    if not item.part_opened:
        item.part_opened = True
        yield _synthetic_part_added(event)
    yield _synthetic_text_delta(event, delta)


class _TranslatingStream:
    """Sync Stream facade that translates events while iterating."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __enter__(self) -> "_TranslatingStream":
        self._inner.__enter__()
        return self

    def __exit__(self, *exc_info: Any) -> Any:
        return self._inner.__exit__(*exc_info)

    def close(self) -> None:
        self._inner.close()

    def __iter__(self) -> Iterator[Any]:
        state = _ReasoningTranslationState()
        for event in self._inner:
            yield from translate_reasoning_text_event(event, state)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _TranslatingAsyncStream:
    """Async AsyncStream facade that translates events while iterating.

    ``__aenter__`` must return the facade (not the inner stream) because
    langchain-openai iterates the value bound by ``async with``.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def __aenter__(self) -> "_TranslatingAsyncStream":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc_info: Any) -> Any:
        return await self._inner.__aexit__(*exc_info)

    async def close(self) -> None:
        await self._inner.close()

    async def __aiter__(self) -> AsyncIterator[Any]:
        state = _ReasoningTranslationState()
        async for event in self._inner:
            for translated in translate_reasoning_text_event(event, state):
                yield translated

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class ReasoningResponsesProxy:
    """``client.responses`` proxy: translates streamed create() results."""

    def __init__(self, inner: Any, *, async_api: bool = False) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_async_api", async_api)

    def create(self, *args: Any, **kwargs: Any) -> Any:
        result = self._inner.create(*args, **kwargs)
        if self._async_api:
            return self._wrap_async(result)
        if kwargs.get("stream"):
            return _TranslatingStream(result)
        return result

    async def _wrap_async(self, awaited: Any) -> Any:
        stream = await awaited
        # The openai SDK returns an AsyncStream only for stream=True; for
        # blocking calls the parsed response is passed through untouched.
        if hasattr(stream, "__aiter__"):
            return _TranslatingAsyncStream(stream)
        return stream

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_inner"), name)


def attach_reasoning_stream_bridge(model: ChatOpenAI) -> ChatOpenAI:
    """Wrap both available root clients' ``responses`` resources with the proxy.

    Streaming flags (``disable_streaming``/``stream_usage``) are the caller's
    responsibility; this only installs the event translator. Idempotent.
    """

    for attr, async_api in (
        ("root_client", False),
        ("root_async_client", True),
    ):
        client = getattr(model, attr, None)
        if client is None:
            continue
        current = client.responses
        if isinstance(current, ReasoningResponsesProxy):
            continue
        client.responses = ReasoningResponsesProxy(current, async_api=async_api)
    return model


def reasoning_stream_proxy_attached(model: ChatOpenAI) -> bool:
    """Return True when both available root clients are bridged."""

    attached = 0
    considered = 0
    for attr in ("root_client", "root_async_client"):
        client = getattr(model, attr, None)
        if client is None:
            continue
        considered += 1
        if isinstance(client.responses, ReasoningResponsesProxy):
            attached += 1
    return considered > 0 and attached == considered
