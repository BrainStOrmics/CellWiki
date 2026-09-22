# -*- coding: utf-8 -*-
"""CellWiki compaction middleware: watermark check, LLM summary, overflow recovery.

This middleware owns the compaction *decision* for the coordinator graph. The
runtime remains the only *writer* of the model transcript: the middleware
reports a compaction through the custom stream channel, and the runtime persists
the summary plus retained tail as the new transcript boundary. This module never
touches SQLite.

Contract (2026-09-22 alignment work; see the accepted design proposal):

- the watermark is checked before every model call (``before_model``);
- watermark = ``count_tokens_approximately(use_usage_metadata_scaling=True)``
  over the graph messages: it anchors on the most recent AI message's reported
  ``usage_metadata`` and estimates the delta after it;
- threshold = ``effective_limit - COMPACTION_RESERVE_TOKENS`` (absolute
  reserve, never a window ratio);
- the summary is one nested LLM call on the coordinator model, tagged
  ``cellwiki:summarizer`` so the runtime strips it from the outward stream;
- the deterministic six-category summary is the fallback; three consecutive
  LLM failures trip a per-thread breaker until one succeeds again;
- provider overflow errors compact and retry the step once, and the graph
  state is only rewritten when the retry succeeds;
- provider-native compaction models skip this middleware entirely.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ExtendedModelResponse
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.modifier import RemoveMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.types import Command

from cellwiki.services.prompt_layers import calibration_ratio, summarize_excerpts

logger = logging.getLogger(__name__)

REMOVE_ALL_MESSAGES = "__remove_all__"
SUMMARIZER_TAG = "cellwiki:summarizer"
SUMMARIZER_ROLE = "summarizer"
SUMMARY_MAX_OUTPUT_TOKENS = 20_000
SUMMARY_INPUT_SOFT_LIMIT = 380_000
COMPACTION_FAILURE_LIMIT = 3
SUMMARY_MESSAGE_ID = "compaction-summary"
SUMMARY_MESSAGE_PREFIX = "[Compacted context]"

SUMMARY_SYSTEM_PROMPT = (
    "You compact an agent conversation into a structured handoff summary. "
    "Respond in the language of the conversation. Keep every section header, "
    "even when empty. Preserve exact file paths, page ids, commit subjects, "
    "commands, error strings and identifiers verbatim. Do not mention the "
    "summarization process."
)

SUMMARY_TEMPLATE = """Output exactly the Markdown structure below and keep the section order.

## Objective
## Constraints and preferences
## Completed (pages changed, commits)
## In progress
## Blocked and open
## Key decisions
## Next steps
## Evidence and file paths

Rules:
- Keep every section, even when empty (write "(none)").
- Long-lived instructions from the user must be carried over verbatim, not paraphrased.
- Prefer terse bullets over prose.
- Preserve exact path/symbol/commit/identifier strings.
"""

SHORTER_HINT = "\nYour previous answer was truncated: produce a shorter version that fits.\n"

UPDATE_RULES = """The <previous-summary> is the authoritative baseline for everything before the conversation above. Merge it with the new conversation:

- Carry forward objectives, constraints, user directives, decisions and open threads from the previous summary even when the new conversation does not mention them.
- Where the conversation conflicts with the previous summary, the conversation wins: state the corrected fact and drop the old claim.
- Move finished work from "In progress" to "Completed".
- Update "Objective" and "Next steps" to reflect the current state.
- Nothing dropped from the previous summary can be recovered later: only drop what is finished and no longer needed.
"""

OVERFLOW_HINTS = (
    "context length",
    "context_length_exceeded",
    "prompt is too long",
    "prompt_too_long",
    "too many tokens",
    "maximum context",
    "max context",
    "exceeds the context window",
    "input is too long",
    "reduce the length",
)

_TRUNCATION_REASONS = {"max_tokens", "length", "max_output_tokens"}


def is_overflow_error(error: BaseException) -> bool:
    """Classify a provider error as a context-window overflow.

    Tool-pairing 400s (the 2026-09-16 incident class) are explicitly excluded:
    a transcript-structure error must never trigger a compaction retry.
    """

    code = ""
    for attr in ("code", "status_code_retry", "body"):
        value = getattr(error, attr, None)
        if value is not None:
            code += f" {value}"
    text = f"{code} {error}".lower()
    if "tool_calls" in text or "tool_call_id" in text:
        return False
    return any(hint in text for hint in OVERFLOW_HINTS)


def _text_of(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                for key in ("text", "content"):
                    value = block.get(key)
                    if isinstance(value, str):
                        parts.append(value)
        return "\n".join(parts)
    return ""


def _serialize_for_summary(messages: list[BaseMessage], *, aggressive: bool = False) -> str:
    """Render the compacted prefix for the summarizer prompt.

    Recent tool results stay verbatim; older ones collapse to a placeholder
    because tool output dominates byte volume while handoff facts live in user
    and assistant text plus tool_call arguments. ``aggressive`` keeps no tool
    results and truncates each message, for the retry after an overflow.
    """

    lines: list[str] = []
    tool_results = [m for m in messages if isinstance(m, ToolMessage)]
    kept_ids = set() if aggressive else {id(m) for m in tool_results[-3:]}
    for message in messages:
        role = getattr(message, "type", "unknown")
        if isinstance(message, ToolMessage):
            name = getattr(message, "name", None) or "tool"
            if id(message) in kept_ids:
                lines.append(f"[tool result: {name}]\n{_text_of(message)}")
            else:
                lines.append(f"[old tool result elided: {name}]")
            continue
        if isinstance(message, AIMessage):
            text = _text_of(message)
            calls = getattr(message, "tool_calls", None) or []
            rendered_calls = ", ".join(
                f"{call.get('name')}({call.get('args')})"
                for call in calls
                if isinstance(call, dict)
            )
            if rendered_calls:
                text = (
                    f"{text}\n[tool calls: {rendered_calls}]"
                    if text
                    else f"[tool calls: {rendered_calls}]"
                )
            if aggressive:
                text = text[:4_000]
            lines.append(f"[assistant]\n{text}")
            continue
        text = _text_of(message)
        if aggressive:
            text = text[:2_000]
        lines.append(f"[{role}]\n{text}")
    return "\n\n".join(lines)


def summary_prompt_text(
    messages: list[BaseMessage],
    previous_summary: str | None,
    *,
    aggressive: bool = False,
    shorter: bool = False,
) -> str:
    body = _serialize_for_summary(messages, aggressive=aggressive)
    if previous_summary:
        prompt = (
            f"<conversation>\n{body}\n</conversation>\n\n"
            f"<previous-summary>\n{previous_summary}\n</previous-summary>\n\n"
            f"{SUMMARY_TEMPLATE}\n{UPDATE_RULES}"
        )
    else:
        prompt = f"<conversation>\n{body}\n</conversation>\n\n{SUMMARY_TEMPLATE}"
    if shorter:
        prompt += SHORTER_HINT
    return prompt


def summarize_calibration(measured: int, messages: list[BaseMessage]) -> float:
    """Measured/estimated ratio used to cost each retained record.

    Reuses the existing clamping contract (0.5–4.0); a missing measurement
    yields 1.0, i.e. the plain estimate.
    """

    if measured <= 0 or not messages:
        return 1.0
    estimate = count_tokens_approximately(messages)
    return calibration_ratio(measured, estimate)


def current_watermark(messages: list[BaseMessage]) -> int:
    """Anchor + delta watermark over the graph messages."""

    if not messages:
        return 0
    return count_tokens_approximately(messages, use_usage_metadata_scaling=True)


def find_tail_start(
    messages: list[BaseMessage],
    retained_tokens: int,
    *,
    calibration: float = 1.0,
) -> int:
    """Pick a turn-boundary split that never orphans a tool result.

    Walks back accumulating approximate tokens (each record's estimate scaled by
    the measured/estimated calibration ratio, preserving the measured-first
    accounting contract) until the retained budget is reached, then snaps to the
    nearest user message at or before that point. A ToolMessage can never be the
    first message of the tail; 0 means no prefix can be split off.
    """

    if not messages:
        return 0
    used = 0.0
    start = len(messages)
    for index in range(len(messages) - 1, -1, -1):
        used += count_tokens_approximately([messages[index]]) * max(0.01, calibration)
        if used > retained_tokens and start != len(messages):
            break
        start = index
    # 向前吸附到最近的 user 边界：向后吸附会让 tail 超出预算、且常常一路退到
    # 0（等于无法切分）。取"预算位之后的第一个 user"，tail 只会更小不会更大。
    forward = next(
        (
            index
            for index in range(start, len(messages))
            if isinstance(messages[index], HumanMessage)
        ),
        None,
    )
    if forward is None:
        backward = next(
            (
                index
                for index in range(start, -1, -1)
                if isinstance(messages[index], HumanMessage)
            ),
            None,
        )
        start = backward if backward is not None else 0
    else:
        start = forward
    while start < len(messages) and isinstance(messages[start], ToolMessage):
        start += 1
    return start


def build_compacted_messages(
    messages: list[BaseMessage],
    summary: str,
    *,
    retained_tokens: int,
    calibration: float = 1.0,
) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """Build the add_messages replacement list plus the retained tail."""

    tail_start = find_tail_start(messages, retained_tokens, calibration=calibration)
    summary_message = HumanMessage(
        id=SUMMARY_MESSAGE_ID, content=f"{SUMMARY_MESSAGE_PREFIX}\n{summary}"
    )
    tail = list(messages[tail_start:])
    return [RemoveMessage(id=REMOVE_ALL_MESSAGES), summary_message, *tail], tail


def serialize_tail_records(tail: list[BaseMessage]) -> list[dict[str, Any]]:
    """Serialize retained tail messages into transcript record dicts.

    The runtime persists these verbatim after the new compaction boundary, so
    the next run replays exactly what this run's model saw (cache-first
    invariant). Only user/assistant/tool messages are retained: the summary
    message is persisted separately as the boundary itself.
    """

    records: list[dict[str, Any]] = []
    for message in tail:
        if isinstance(message, ToolMessage):
            records.append(
                {
                    "kind": "tool_result",
                    "role": "tool",
                    "content": {
                        "text": _text_of(message),
                        "tool_call_id": getattr(message, "tool_call_id", None) or None,
                        "name": getattr(message, "name", None) or "tool",
                    },
                    "tool_call_id": getattr(message, "tool_call_id", None) or None,
                    "name": getattr(message, "name", None) or "tool",
                }
            )
            continue
        if isinstance(message, AIMessage):
            calls = getattr(message, "tool_calls", None) or []
            records.append(
                {
                    "kind": "assistant",
                    "role": "assistant",
                    "content": {
                        "text": _text_of(message),
                        "tool_calls": [
                            {
                                "name": str(call.get("name") or ""),
                                "args": call.get("args") or {},
                                "id": str(call.get("id") or ""),
                            }
                            for call in calls
                            if isinstance(call, dict)
                        ],
                    },
                }
            )
            continue
        text = _text_of(message)
        if not text:
            continue
        records.append({"kind": "user", "role": "user", "content": {"text": text}})
    return records


def latest_summary_text(messages: list[BaseMessage]) -> str | None:
    """Find the most recent compaction summary carried in the message list."""

    for message in messages:
        if getattr(message, "id", None) == SUMMARY_MESSAGE_ID:
            text = _text_of(message)
            if text:
                return text
        text = _text_of(message)
        if text.startswith(SUMMARY_MESSAGE_PREFIX):
            return text
    return None


def _usage_of(response: Any) -> dict[str, int]:
    metadata = getattr(response, "usage_metadata", None) or {}
    if not isinstance(metadata, dict):
        return {}
    usage: dict[str, int] = {}
    for source, target in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        value = metadata.get(source)
        if isinstance(value, int) and value:
            usage[target] = value
    details = metadata.get("input_token_details")
    if isinstance(details, dict):
        cached = details.get("cache_read")
        if isinstance(cached, int) and cached:
            usage["cached_input_tokens"] = cached
    return usage


class CellWikiCompactionMiddleware(AgentMiddleware):
    """Watermark check, LLM summarization and provider-overflow recovery."""

    def __init__(
        self,
        *,
        model: Any,
        threshold: int,
        retained_tokens: int,
        provider_native: bool = False,
        baseline_provider: Any = None,
    ) -> None:
        super().__init__()
        self.model = model
        self.threshold = threshold
        self.retained_tokens = retained_tokens
        self.provider_native = provider_native
        # Optional callable(thread_id) -> last measured prompt tokens. The graph
        # state only carries usage metadata for AI messages produced inside the
        # current run; the cross-run measurement recorded by the runtime keeps
        # the watermark honest on the first call of a run.
        self.baseline_provider = baseline_provider
        # Per-thread consecutive summarizer failures; trips the deterministic
        # breaker until one LLM summary succeeds again.
        self._failure_counts: dict[str, int] = {}

    # -- summarizer ------------------------------------------------------

    def _invoke_summarizer(self, prompt: str) -> Any:
        bound: Any = self.model
        try:
            bound = self.model.bind(max_tokens=SUMMARY_MAX_OUTPUT_TOKENS)
        except Exception:  # noqa: BLE001 - model may not support binding limits
            logger.debug("summarizer max_tokens binding unsupported", exc_info=True)
        return bound.invoke(
            [
                SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ],
            config={
                "tags": [SUMMARIZER_TAG],
                "metadata": {"cellwiki_role": SUMMARIZER_ROLE},
            },
        )

    def _summarize(
        self,
        messages: list[BaseMessage],
        previous: str | None,
        failure_key: str,
    ) -> tuple[str, str, dict[str, int]]:
        """Return (summary, source, usage); source is "llm" or "deterministic"."""

        failures = self._failure_counts.get(failure_key, 0)
        if failures < COMPACTION_FAILURE_LIMIT:
            aggressive = False
            shorter = False
            for attempt in (1, 2):
                prompt = summary_prompt_text(
                    messages, previous, aggressive=aggressive, shorter=shorter
                )
                try:
                    response = self._invoke_summarizer(prompt)
                except Exception as error:  # noqa: BLE001 - fallback below
                    logger.warning(
                        "summarizer call failed (attempt %d): %s", attempt, error
                    )
                    if attempt == 1:
                        # 瞬时错误（超时、5xx、网络）原样重试一次；溢出错误则
                        # 在重试前把输入视图降级为激进剪枝。
                        aggressive = aggressive or is_overflow_error(error)
                        continue
                    break
                text = _text_of(response).strip()
                metadata = getattr(response, "response_metadata", None) or {}
                stop_reason = str(
                    metadata.get("stop_reason") or metadata.get("finish_reason") or ""
                ).lower()
                usage = _usage_of(response)
                if text and stop_reason not in _TRUNCATION_REASONS:
                    self._failure_counts.pop(failure_key, None)
                    return text, "llm", usage
                logger.warning(
                    "summarizer output unusable (attempt %d, stop_reason=%s, chars=%d)",
                    attempt,
                    stop_reason or "?",
                    len(text),
                )
                if attempt == 1:
                    shorter = stop_reason in _TRUNCATION_REASONS
                    aggressive = aggressive or is_overflow_error(
                        RuntimeError(stop_reason or "empty")
                    )
                    continue
                break
            self._failure_counts[failure_key] = failures + 1
            logger.warning(
                "summarizer falling back to deterministic summary (consecutive failures=%d)",
                failures + 1,
            )
        excerpts = [f"{getattr(m, 'type', '?')}: {_text_of(m)[:400]}" for m in messages]
        return summarize_excerpts(excerpts), "deterministic", {}

    # -- helpers ---------------------------------------------------------

    def _emit_compaction_signal(self, payload: dict[str, Any], runtime: Any = None) -> None:
        writer = getattr(runtime, "stream_writer", None)
        if writer is None:
            try:
                from langgraph.config import get_stream_writer

                writer = get_stream_writer()
            except Exception:  # noqa: BLE001 - the custom channel is best-effort
                logger.debug("custom stream writer unavailable", exc_info=True)
                return
        try:
            writer({"kind": "context_compaction", **payload})
        except Exception:  # noqa: BLE001 - the custom channel is best-effort
            logger.debug("custom stream write failed", exc_info=True)

    def _thread_id(self, runtime: Any) -> str:
        context = getattr(runtime, "context", None)
        thread_id = getattr(context, "thread_id", None)
        if thread_id:
            return str(thread_id)
        config = getattr(runtime, "config", None)
        if isinstance(config, dict):
            configurable = config.get("configurable") or {}
            if isinstance(configurable, dict):
                return str(configurable.get("thread_id") or "default")
        return "default"

    def _baseline_floor(self, runtime: Any) -> int:
        if self.baseline_provider is None:
            return 0
        try:
            value = self.baseline_provider(self._thread_id(runtime))
        except Exception:  # noqa: BLE001 - a missing baseline must not break the run
            return 0
        return int(value or 0)

    def _compact_now(
        self,
        messages: list[BaseMessage],
        *,
        reason: str,
        watermark: int,
        failure_key: str,
        compaction_id: str,
        runtime: Any = None,
    ) -> tuple[list[BaseMessage], list[BaseMessage], str, str, dict[str, int]]:
        previous = latest_summary_text(messages)
        summary, source, usage = self._summarize(messages, previous, failure_key)
        calibration = summarize_calibration(watermark, messages)
        if not summary.strip():
            # 兜底也产不出可用的摘要：放弃本次压缩，不写 boundary。
            self._emit_compaction_signal(
                {
                    "phase": "completed",
                    "compaction_id": compaction_id,
                    "reason": reason,
                    "summary_source": "none",
                    "changed": False,
                    "retained_messages": 0,
                    "estimated_tokens": watermark,
                    "threshold": self.threshold,
                },
                runtime,
            )
            return [], [], "", "none", usage
        new_messages, tail = build_compacted_messages(
            messages,
            summary,
            retained_tokens=self.retained_tokens,
            calibration=calibration,
        )
        self._emit_compaction_signal(
            {
                "phase": "completed",
                "compaction_id": compaction_id,
                "reason": reason,
                "summary_source": source,
                "summary": summary,
                "summary_usage": usage,
                "tail": serialize_tail_records(tail),
                "retained_messages": len(tail),
                "estimated_tokens": watermark,
                "threshold": self.threshold,
            },
            runtime,
        )
        return new_messages, tail, summary, source, usage

    def _can_split(self, messages: list[BaseMessage], *, calibration: float = 1.0) -> bool:
        return (
            find_tail_start(
                messages, self.retained_tokens, calibration=calibration
            )
            > 0
        )

    # -- middleware hooks ------------------------------------------------

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if self.provider_native:
            return None
        messages = list(state.get("messages") or [])
        watermark = max(current_watermark(messages), self._baseline_floor(runtime))
        if watermark <= self.threshold:
            return None
        if not self._can_split(messages):
            logger.info(
                "compaction skipped: retained tail would consume the whole history "
                "(watermark=%d threshold=%d)",
                watermark,
                self.threshold,
            )
            return None
        compaction_id = f"cmp_{uuid.uuid4().hex}"
        self._emit_compaction_signal(
            {
                "phase": "started",
                "compaction_id": compaction_id,
                "reason": "threshold",
                "estimated_tokens": watermark,
                "threshold": self.threshold,
            },
            runtime,
        )
        new_messages, _tail, summary, _source, _usage = self._compact_now(
            messages,
            reason="threshold",
            watermark=watermark,
            failure_key=self._thread_id(runtime),
            compaction_id=compaction_id,
            runtime=runtime,
        )
        if not summary:
            return None
        return {"messages": new_messages}

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.before_model(state, runtime)

    def _compact_for_overflow(self, request: Any, error: Exception) -> tuple[Any, list[BaseMessage]]:
        """Compact the request in place and return (retry_request, tail)."""

        messages = list(request.messages)
        watermark = current_watermark(messages)
        compaction_id = f"cmp_{uuid.uuid4().hex}"
        self._emit_compaction_signal(
            {
                "phase": "started",
                "compaction_id": compaction_id,
                "reason": "overflow",
                "estimated_tokens": watermark,
                "threshold": self.threshold,
            }
        )
        new_messages, tail, _summary, _source, _usage = self._compact_now(
            messages,
            reason="overflow",
            watermark=watermark,
            failure_key="default",
            compaction_id=compaction_id,
            runtime=request.runtime,
        )
        logger.info("compact-after-overflow retry (retained=%d)", len(tail))
        if not new_messages:
            return None, []
        return request.override(messages=new_messages[1:]), tail

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        try:
            return handler(request)
        except Exception as error:  # noqa: BLE001 - re-raised unless overflow
            if self.provider_native or not is_overflow_error(error):
                raise
            retry_request, tail = self._compact_for_overflow(request, error)
            if not retry_request:
                raise error
            try:
                response = handler(retry_request)
            except Exception:  # noqa: BLE001 - the original overflow wins
                raise error from None
            command: Command = Command(
                update={"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *retry_request.messages]}
            )
            return ExtendedModelResponse(model_response=response, command=command)

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        try:
            return await handler(request)
        except Exception as error:  # noqa: BLE001 - re-raised unless overflow
            if self.provider_native or not is_overflow_error(error):
                raise
            messages = list(request.messages)
            watermark = current_watermark(messages)
            compaction_id = f"cmp_{uuid.uuid4().hex}"
            self._emit_compaction_signal(
                {
                    "phase": "started",
                    "compaction_id": compaction_id,
                    "reason": "overflow",
                    "estimated_tokens": watermark,
                    "threshold": self.threshold,
                }
            )
            new_messages, tail, _summary, _source, _usage = self._compact_now(
                messages,
                reason="overflow",
                watermark=watermark,
                failure_key=self._thread_id(request.runtime),
                compaction_id=compaction_id,
                runtime=request.runtime,
            )
            logger.info("compact-after-overflow retry (retained=%d)", len(tail))
            retry_request = request.override(messages=new_messages[1:])
            try:
                response = await handler(retry_request)
            except Exception:  # noqa: BLE001 - the original overflow wins
                raise error from None
            command: Command = Command(
                update={
                    "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *retry_request.messages]
                }
            )
            return ExtendedModelResponse(model_response=response, command=command)


__all__ = [
    "COMPACTION_FAILURE_LIMIT",
    "REMOVE_ALL_MESSAGES",
    "SUMMARIZER_ROLE",
    "SUMMARIZER_TAG",
    "SUMMARY_MAX_OUTPUT_TOKENS",
    "SUMMARY_MESSAGE_ID",
    "SUMMARY_MESSAGE_PREFIX",
    "CellWikiCompactionMiddleware",
    "build_compacted_messages",
    "current_watermark",
    "find_tail_start",
    "is_overflow_error",
    "latest_summary_text",
    "serialize_tail_records",
    "summary_prompt_text",
]