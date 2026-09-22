"""Render the append-only model transcript into provider-neutral messages."""

from __future__ import annotations

import json
from typing import Any

from cellwiki.services.prompt_layers import summarize_excerpts

CHARS_PER_TOKEN = 4

# 剪枝层（2026-09-22 对齐工作）：
# - 创建时预览化：超大工具结果在**第一次进入上下文前**就截成预览 + 取回路径，
#   因此从诞生起就是小形态，缓存零损失（对齐 Claude Code toolResultStorage）。
# - 冷点剪枝：缓存已过期（run 空闲超过阈值）或压缩触发时，把保留窗口之外的旧
#   工具结果替换为恒定占位符；剪枝集合只增不减、占位符恒定，保证前缀稳定。
PREVIEW_CHAR_LIMIT = 2_000
TOOL_RESULT_CHAR_THRESHOLD = 50_000
TOOL_RESULT_BATCH_CHAR_THRESHOLD = 200_000
PRUNE_KEEP_RECENT = 5
PRUNE_MIN_CHARS = 100
PRUNED_TOOL_PLACEHOLDER = "[Old tool result content cleared]"
PRUNE_PROTECTED_TOOLS = frozenset({"ask_user_question"})
PRUNE_RELATIVE_DIR = "data/runtime/tool-results"


def _text(record: dict[str, Any]) -> str:
    content = record.get("content")
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
    return str(record.get("content_text") or "")


def preview_tool_result(
    text: str,
    *,
    run_id: str,
    tool_name: str,
    tool_call_id: str,
    limit: int = PREVIEW_CHAR_LIMIT,
) -> str:
    """Return the model-visible form of one tool result.

    Results at or below ``TOOL_RESULT_CHAR_THRESHOLD`` pass through unchanged;
    oversized ones become a bounded head preview plus the retrieval path. The
    caller writes the full text to disk before swapping it in, so the model can
    still re-read or re-run the tool. Because this happens before the record is
    ever sent, the cached prefix never shrinks later.
    """

    if len(text) <= TOOL_RESULT_CHAR_THRESHOLD:
        return text
    head = text[:limit]
    relative = f"{PRUNE_RELATIVE_DIR}/{run_id}/{tool_call_id or tool_name}.txt"
    return (
        f"[tool result preview: {tool_name}]\n"
        f"{head}\n\n"
        f"[Output truncated: {len(text)} chars total. Full output: {relative} — "
        f"re-run the tool or read the file when the full content is needed.]"
    )


def prune_transcript_for_model(
    records: list[dict[str, Any]],
    *,
    keep_recent: int = PRUNE_KEEP_RECENT,
) -> tuple[list[dict[str, Any]], int]:
    """Replace old tool results with the constant placeholder (cold-spot pruning).

    Only ``tool_result`` content is replaced; message count, order and the
    tool_call/tool_result pairing are untouched. The pruning set only grows:
    an already-placeholder record stays a placeholder, so the visible prefix
    changes at most once per record. Returns the new records plus how many
    entries were pruned.
    """

    results: list[int] = [
        index
        for index, record in enumerate(records)
        if str(record.get("kind") or "") == "tool_result"
    ]
    protected = [
        index
        for index in results
        if str(records[index].get("name") or "") in PRUNE_PROTECTED_TOOLS
    ]
    candidates = [index for index in results if index not in protected]
    to_prune = candidates[:-keep_recent] if keep_recent > 0 else candidates
    if not to_prune:
        return records, 0
    pruned = 0
    updated: list[dict[str, Any]] = list(records)
    for index in to_prune:
        record = updated[index]
        text = _text(record)
        if text == PRUNED_TOOL_PLACEHOLDER:
            continue
        if len(text) <= PRUNE_MIN_CHARS:
            continue
        copied = dict(record)
        copied["content"] = {**_content_dict(record), "text": PRUNED_TOOL_PLACEHOLDER}
        copied["content_text"] = PRUNED_TOOL_PLACEHOLDER
        updated[index] = copied
        pruned += 1
    return updated, pruned


def _content_dict(record: dict[str, Any]) -> dict[str, Any]:
    content = record.get("content")
    return dict(content) if isinstance(content, dict) else {}


def _tool_calls_text(record: dict[str, Any]) -> str:
    """Serialize assistant tool_calls for token accounting.

    tool_calls 参数 JSON 与 content 文本一样按字面发给 provider，但旧估算只看
    content.text，实测同一 thread 因此低估 2.4 倍。
    """

    content = record.get("content")
    if not isinstance(content, dict):
        return ""
    calls = content.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return ""
    return json.dumps(calls, ensure_ascii=False, default=str)


def estimate_transcript_tokens(records: list[dict[str, Any]]) -> int:
    """Fixed fallback estimate: content text + assistant tool_calls JSON."""

    total_chars = sum(
        len(_text(record)) + len(_tool_calls_text(record)) for record in records
    )
    return max(0, total_chars // CHARS_PER_TOKEN)


def summarize_transcript(records: list[dict[str, Any]]) -> str:
    """Build the deterministic fallback compaction summary."""

    excerpts = [f"{record.get('role', '?')}: {_text(record)}" for record in records]
    return summarize_excerpts(excerpts)


def split_for_compaction(
    records: list[dict[str, Any]],
    *,
    retained_tokens: int,
    calibration: float = 1.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split active records into the summarized prefix and retained tail.

    `calibration` 是 provider 实测 prompt 与固定估算的比值（由
    `prompt_layers.calibration_ratio` 解析）：固定估算只覆盖消息体，真实请求
    还含 system/工具 schema 与按 provider 计费的 token 密度差异，因此保留窗口
    按该比值缩放后再累计。无实测时 calibration=1.0，退回纯估算语义。
    """

    tail: list[dict[str, Any]] = []
    used = 0.0
    for record in reversed(records):
        tokens = estimate_transcript_tokens([record]) * calibration
        if tail and used + tokens > retained_tokens:
            break
        tail.append(record)
        used += tokens
    tail.reverse()
    return records[: len(records) - len(tail)], tail


def render_model_messages(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge semantic records into the exact message order sent to the graph.

    User and run_context are adjacent records but one user message. This keeps
    Anthropic's single-system-message invariant and makes the turn context a
    tail attachment rather than a second system prompt.

    Tool calls and results are normalized into adjacent pairs. The append-only
    store can legitimately contain a synthetic result after a later user
    message when an interrupted question is repaired by Deep Agents; providers
    reject that raw order, so rendering restores the protocol-valid pairing.
    """

    results_by_call: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if str(record.get("kind") or "") != "tool_result":
            continue
        call_id = str(record.get("tool_call_id") or "")
        if call_id:
            results_by_call.setdefault(call_id, []).append(record)

    consumed_results: set[str] = set()
    messages: list[dict[str, Any]] = []
    index = 0
    while index < len(records):
        record = records[index]
        kind = str(record.get("kind") or "")
        content = record.get("content")
        if kind == "user":
            text = _text(record)
            next_record = records[index + 1] if index + 1 < len(records) else None
            if next_record is not None and str(next_record.get("kind")) == "run_context":
                context_text = _text(next_record)
                if context_text:
                    text = f"{text}\n\n{context_text}" if text else context_text
                index += 1
            messages.append({"role": "user", "content": text})
        elif kind == "run_context":
            context_text = _text(record)
            if context_text:
                messages.append({"role": "user", "content": context_text})
        elif kind == "assistant":
            text = ""
            tool_calls: list[dict[str, Any]] = []
            if isinstance(content, dict):
                text = str(content.get("text") or "")
                raw_calls = content.get("tool_calls")
                if isinstance(raw_calls, list):
                    tool_calls = [call for call in raw_calls if isinstance(call, dict)]
            message: dict[str, Any] = {"role": "assistant", "content": text}
            if tool_calls:
                message["tool_calls"] = tool_calls
            messages.append(message)
            for tool_call in tool_calls:
                call_id = str(tool_call.get("id") or "")
                tool_name = str(tool_call.get("name") or "tool")
                candidates = results_by_call.get(call_id, [])
                result = next(
                    (
                        candidate
                        for candidate in candidates
                        if str(candidate.get("message_id") or "")
                        not in consumed_results
                    ),
                    None,
                )
                if result is not None:
                    consumed_results.add(str(result.get("message_id") or ""))
                    messages.append(
                        {
                            "role": "tool",
                            "content": _text(result),
                            "tool_call_id": result.get("tool_call_id"),
                            "name": result.get("name"),
                        }
                    )
                else:
                    messages.append(_synthetic_tool_result(call_id, tool_name))
        elif kind == "tool_result":
            # A tool result is emitted next to its assistant tool_call above.
            # Results without a matching active assistant call are ignored:
            # emitting a bare tool message is itself protocol-invalid.
            pass
        elif kind == "compaction":
            item = content.get("item") if isinstance(content, dict) else None
            if isinstance(item, dict):
                messages.append({"role": "assistant", "content": [item]})
            else:
                summary = _text(record) or "Compacted history."
                messages.append(
                    {"role": "user", "content": f"[Compacted context]\n{summary}"}
                )
        index += 1
    return messages


def _synthetic_tool_result(call_id: str, tool_name: str) -> dict[str, Any]:
    """Build the deterministic repair result used for an orphan tool call."""

    if tool_name == "ask_user_question":
        text = (
            f"Tool call ask_user_question with id {call_id} was cancelled - "
            "another message came in before it could be completed."
        )
    else:
        text = (
            f"Tool call {tool_name} with id {call_id} was cancelled or did not "
            "produce a result."
        )
    return {
        "role": "tool",
        "content": text,
        "tool_call_id": call_id,
        "name": tool_name,
    }


__all__ = [
    "PREVIEW_CHAR_LIMIT",
    "PRUNED_TOOL_PLACEHOLDER",
    "PRUNE_KEEP_RECENT",
    "PRUNE_PROTECTED_TOOLS",
    "TOOL_RESULT_CHAR_THRESHOLD",
    "estimate_transcript_tokens",
    "preview_tool_result",
    "prune_transcript_for_model",
    "render_model_messages",
    "split_for_compaction",
    "summarize_transcript",
]
