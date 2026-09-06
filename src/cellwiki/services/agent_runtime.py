# =============================================================================
# 简化 Agent 运行时 —— 工作区版（阶段 4）
# =============================================================================
# 生命周期：QUEUED -> RUNNING -> SUCCEEDED / FAILED / UNFINISHED / CANCELLED；
# 预算/超时进入 UNFINISHED（记录 checkpoint，可继续/恢复），失败可 retry。
# - 严格串行门禁：同时只允许 1 个 active run，新 run 请求返回 409。
# - pending diff：一个 run 可产生一串审批单元（diff_<run_id>_<n>）。首单元基线 =
#   run 开始时记录的 git 快照点，其后单元基线 = 上一已判定单元的 head。单元边界 =
#   判定而非发布：上一单元仍未判定时重发布就地刷新该行（question 挂起/续跑不产生
#   第二行）。accept 记录判定，reject 逐个 revert **本单元** commit，二者之后的
#   判定不可回退（见 domain/pending_diff.py 合同注释）。
# - P4 审计：工具输入（label_args 白名单键）与输出（payload sha256）由运行时
#   Seam 记录。时间线卡片可携带有界展示投影（args_display 命令 ≤2000 字符、
#   其余键 ≤200 字符；result_preview head/tail ≤8KB；edit_diff_display 行级 diff
#   ≤80 行 / ≤6000 字符，带截断标记），完整参数与原始大输出仍不离开本边界。
# =============================================================================

from __future__ import annotations

import difflib
import hashlib
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Generator, Iterable, cast

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from cellwiki.agent.app import build_wiki_agent
from cellwiki.config import settings
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.pending_diff import PendingDiff, PendingDiffStatus
from cellwiki.domain.questions import PendingQuestion
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentEventType,
    AgentRun,
    AgentRunOutcome,
    AgentRunStatus,
    AgentSpan,
    RunBudget,
    RunUsage,
)
from cellwiki.services.checkpoints import (
    CheckpointMissingError,
    checkpoint_state_key,
    delete_run_checkpoints,
    has_run_checkpoint,
    latest_checkpoint_id,
)
from cellwiki.services.conversation_context import ConversationContextView
from cellwiki.services.prompt_layers import (
    LAYER_A_TEXT,
    build_layer_b_snapshot,
    build_r1_r5_block,
    compact_transcript,
    warn_if_narrow_window,
)
from cellwiki.agent.executor import (
    attachment_read_stats,
    clear_attachment_resolver,
    clear_attachment_scope,
    set_attachment_resolver,
    set_attachment_scope,
    set_promotion_handler,
)
from cellwiki.services.attachment_store import AttachmentFileStore
from cellwiki.services.git_executor import GitCommandError, GitExecutor
from cellwiki.services.logging_context import log_context
from cellwiki.services.quality import inspect_projection
from cellwiki.services.runtime_store import (
    InvalidRunTransitionError,
    RuntimeStore,
    SerialGateViolationError,
)
from cellwiki.services.workspace_maintenance import (
    MAINTENANCE_COMMIT_PREFIX,
    maintain_after_accept,
    maintain_after_lint,
    maintain_after_reject,
    maintain_after_unfinished,
    take_maintenance_warning,
)

# 墙钟超时下限（秒）：避免测试中预算/超时语义被极小值绕过
MAX_RUN_SECONDS_FLOOR = 10

_TOOL_ACTIVITY_CODES = {
    "read_file": "reading_page",
    "write_file": "editing",
    "edit_file": "editing",
    "glob": "searching",
    "grep": "searching",
    "git": "versioning",
    "run_powershell": "running_tool",
    "lint_knowledge_base": "checking_quality",
}


def prompt_configuration_hash(budget: RunBudget) -> str:
    """ADR-0010 决策 8：Layer A + model + budget 的短哈希，作为执行配置快照。

    历史 run 因此能说明自己是在哪份提示词与预算下跑的，不受之后的 .env 漂移影响。
    """
    digest = hashlib.sha256()
    digest.update(LAYER_A_TEXT.encode("utf-8"))
    digest.update((settings.openai_model or "").encode("utf-8"))
    digest.update(budget.model_dump_json().encode("utf-8"))
    return digest.hexdigest()[:16]


class AgentRuntimeError(RuntimeError):
    """Base error for the simplified agent runtime."""


class AgentRunNotFoundError(AgentRuntimeError):
    """Raised when a run_id does not exist."""


class AgentRunInProgressError(AgentRuntimeError):
    """Raised by the strict serial gate when another run is active."""


class AgentBudgetExceeded(AgentRuntimeError):
    """Raised internally when a run exceeds its model-call budget."""


class AgentRetryLimitExceeded(AgentRuntimeError):
    """Raised internally when a run exceeds its retry budget."""


class _RunTimeoutError(AgentRuntimeError):
    """Raised internally when a run exceeds its wall-clock budget."""


# 兼容别名：API 仍在使用旧名（严格串行门禁语义）
AgentRuntimeBusyError = AgentRunInProgressError


def is_retryable_run(run: AgentRun) -> bool:
    """Whether a failed/unfinished run can be retried (system/provider errors only)."""
    if run.status not in {AgentRunStatus.FAILED, AgentRunStatus.UNFINISHED}:
        return False
    if run.retry_count >= run.budget.max_retries:
        return False
    return run.error_type in {
        AgentErrorType.SYSTEM,
        AgentErrorType.RATE_LIMIT,
        AgentErrorType.TIMEOUT,
    }


def classify_agent_error(error: Exception) -> AgentErrorType:
    """Map an adapter/provider exception to a stable error category."""
    message = str(error).lower()
    if isinstance(error, TimeoutError) or "timed out" in message or "timeout" in message:
        return AgentErrorType.TIMEOUT
    if "429" in message or "rate limit" in message or "quota" in message:
        return AgentErrorType.RATE_LIMIT
    if "authentication" in message or "api key" in message or "401" in message:
        return AgentErrorType.AUTHENTICATION
    if "budget" in message or "max_model_calls" in message:
        return AgentErrorType.BUDGET
    return AgentErrorType.SYSTEM


def _signal_payload(
    segment: str,
    message: str,
    metadata: dict[str, Any],
    *,
    model_call_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict[str, Any]:
    """Build the persisted, redacted event payload (P4 audit boundary)."""
    raw_data = {k: str(v)[:500] for k, v in metadata.items()}
    safe_keys = {
        "tool_call_id",
        "page_id",
        "query",
        "path",
        "file",
        "thread_id",
        "run_id",
        "status",
        "answer",
        "decision",
        "project_id",
        "model_name",
    }
    label_args = {k: v for k, v in raw_data.items() if k in safe_keys}
    payload = hashlib.sha256(
        f"{segment}\x00{message}\x00{raw_data}".encode("utf-8")
    ).hexdigest()
    event_payload = {
        "payload": payload,
        "label_args": label_args,
        "model_call_id": model_call_id,
        "token_usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
    # Timeline card fields pass through at top level so the durable event
    # stream can rebuild tool cards after reload: tool identity for matching
    # started -> completed, plus the bounded projections from
    # _tool_args_display / _tool_result_preview.
    for key in ("tool_name", "tool_call_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            event_payload[key] = value
    for key in ("args_display", "result_preview", "edit_diff_display"):
        value = metadata.get(key)
        if isinstance(value, dict) and value:
            event_payload[key] = value
    return event_payload


@dataclass
class _ConsumeOutcome:
    """Result of consuming one stream: terminal info + whether a question paused the run."""

    final_answer: str | None = None
    cancelled: bool = False
    question_pending: bool = False


@dataclass
class RuntimeSignal:
    """One normalized stream item passed from the adapter to the runtime."""

    type: AgentEventType
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    progress: int = 0
    model_call_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    tool_calls: int = 0


def _message_text(content: Any) -> str:
    """Extract visible assistant text from string or provider content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if isinstance(block, dict):
                for key in ("text", "content", "output_text"):
                    value = block.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                        break
        return "".join(parts)
    return str(content or "")


def _usage_from_message(message: Any) -> tuple[int, int, int]:
    """Read input/output/cached token counts from AIMessage usage metadata.

    LangChain normalizes provider usage into `usage_metadata` and renames cache
    fields (`cached_tokens` -> `input_token_details.cache_read`; responses
    `cache_read_input_tokens` -> `cache_read`). DeepSeek/Aliyun gateways expose
    `prompt_cache_hit_tokens` that LangChain drops, so fall back to the raw
    `response_metadata` / `additional_kwargs` usage before reporting zero.
    """
    metadata = _as_dict(getattr(message, "usage_metadata", None))
    response_metadata = _as_dict(getattr(message, "response_metadata", None))
    extra = _as_dict(getattr(message, "additional_kwargs", None))
    input_tokens = _first_int(metadata, "input_tokens", "prompt_tokens")
    output_tokens = _first_int(metadata, "output_tokens", "completion_tokens")
    cached = _read_cached_tokens(metadata)
    if not cached:
        for ignored_key in ("token_usage", "usage"):
            nested = _dig(response_metadata, ignored_key)
            if isinstance(nested, dict):
                cached = _read_cached_tokens(nested)
                if cached:
                    break
    if not cached:
        cached = _read_cached_tokens(response_metadata)
    if not cached:
        cached = _read_cached_tokens(extra)
    return input_tokens, output_tokens, cached


def _as_dict(value: Any) -> dict[str, Any]:
    """Normalize pydantic/dict metadata to a plain dict."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _dig(source: dict[str, Any], *keys: str) -> Any:
    current: Any = source
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_int(source: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _read_cached_tokens(usage: dict[str, Any]) -> int:
    """Best-effort cache token lookup across chat/responses/DeepSeek shapes."""
    candidates = (
        _dig(usage, "input_token_details", "cache_read"),
        _dig(usage, "input_token_details", "cached_tokens"),
        _dig(usage, "prompt_tokens_details", "cached_tokens"),
        _dig(usage, "prompt_tokens_details", "cache_read"),
        usage.get("cache_read_input_tokens"),
        usage.get("prompt_cache_hit_tokens"),
        usage.get("cached_tokens"),
        usage.get("cache_read"),
    )
    for value in candidates:
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0


def _reasoning_text(message: Any) -> str | None:
    """Extract visible reasoning text from provider-specific channels, or None."""
    try:
        extra = getattr(message, "additional_kwargs", None) or {}
    except Exception:
        extra = {}
    if isinstance(extra, dict):
        for key in ("reasoning_content", "reasoning"):
            value = extra.get(key)
            if isinstance(value, str) and value.strip():
                return value
    content = getattr(message, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "reasoning":
                continue
            summary = block.get("summary")
            if isinstance(summary, list):
                parts.extend(
                    str(item.get("text", "")) for item in summary if isinstance(item, dict)
                )
            elif isinstance(summary, str):
                parts.append(summary)
            raw = block.get("text")
            if isinstance(raw, str):
                parts.append(raw)
        joined = "".join(parts).strip()
        if joined:
            return joined
    return None


def _tool_args_summary(tool_name: str, args: Any) -> str | None:
    """Compact one-line argument summary for a tool call (P4-safe, no raw dump)."""
    parsed: Any = args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except (TypeError, ValueError):
            parsed = None
        if parsed is None:
            one_line = " ".join(args.split())
            return one_line[:120] or None
    if not isinstance(parsed, dict):
        return None if parsed is None else str(parsed)[:120]
    picks: dict[str, Any] = {}
    for key in ("attachment_id", "command", "file", "name", "path", "pattern", "query", "url"):
        if key in parsed:
            value = parsed[key]
            picks[key] = value[:200] if isinstance(value, str) else value
    if "args" in parsed and isinstance(parsed["args"], list):
        picks["args"] = [str(item)[:120] for item in parsed["args"]][:8]
    if "content" in parsed and isinstance(parsed["content"], str):
        picks["content_chars"] = len(parsed["content"])
    return None if not picks else json.dumps(picks, ensure_ascii=False)[:160]


def _tool_result_summary(tool_name: str, content: str) -> str:
    """Short human summary of a tool result; the raw output is never persisted."""
    text = (content or "").strip()
    if not text:
        return f"{tool_name} completed."
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        if parsed.get("error"):
            return f"{tool_name} → error: {str(parsed['error'])[:120]}"
        if "results" in parsed and isinstance(parsed["results"], list):
            return f"{tool_name} → {len(parsed['results'])} results"
        if "matches" in parsed and isinstance(parsed["matches"], list):
            return f"{tool_name} → {len(parsed['matches'])} matches"
        if "chars" in parsed:
            return f"{tool_name} → {parsed['chars']} chars"
        if isinstance(parsed.get("stdout"), str):
            head = parsed["stdout"].strip().splitlines()
            first = (head[0] if head else "").strip()
            return f"{tool_name} → {first[:120]}" if first else f"{tool_name} → ok"
        if parsed.get("ok") is True:
            return f"{tool_name} → ok"
        path = str(parsed.get("path") or parsed.get("file") or "")
        if path:
            return f"{tool_name} → {path[:120]}"
        return f"{tool_name} → {json.dumps(parsed, ensure_ascii=False)[:140]}"
    one_line = " ".join(text.split())
    return f"{tool_name} → {one_line[:140]}"


# Bounded display projections for timeline tool cards (proposal
# design/active/2026-08-28-agent-timeline-tool-cards.md). These extend the P4
# audit payload with whitelisted, size-capped views of tool input/output; they
# never dump raw arguments or full results beyond the documented bounds.
_ARGS_COMMAND_MAX = 2_000
_RESULT_PREVIEW_LINE_MAX = 40
_RESULT_PREVIEW_BYTES = 8_000
_RESULT_TITLE_MAX = 120
# 裁决 #11：edit_file 真行级 diff 走**独立新字段** edit_diff_display，自带下面这组
# 上界与截断标记；上面 args_display 的 200 字符上界一字未动。
_EDIT_DIFF_CONTEXT = 2          # 每处改动保留的上下文行数
_EDIT_DIFF_LINE_MAX = 80        # 最多下发行数
_EDIT_DIFF_LINE_CHARS = 200     # 单行字符上限
_EDIT_DIFF_CHARS = 6_000        # 整个投影的字符预算


def _tool_display_title(tool_name: str, picks: dict[str, Any]) -> str:
    """Derive a one-line human title for a tool card from projected args."""
    command = picks.get("command")
    if isinstance(command, str) and command:
        head = command.strip().splitlines()[0] if command.strip() else ""
        return head[:_RESULT_TITLE_MAX]
    for key in ("path", "file", "pattern", "query", "folder", "attachment_id"):
        value = picks.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\\", "/").rsplit("/", 1)[-1] or value.strip()[:_RESULT_TITLE_MAX]
    args = picks.get("args")
    if isinstance(args, list) and args:
        return " ".join(str(item) for item in args)[:_RESULT_TITLE_MAX]
    return ""


def _tool_args_display(tool_name: str, args: Any) -> dict[str, Any] | None:
    """Whitelisted bounded projection of tool arguments for the timeline card.

    Returns None when nothing displayable survives the whitelist; the payload
    keeps only per-key caps (command <= 2000 chars, other strings <= 200).
    """
    parsed: Any = args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except (TypeError, ValueError):
            parsed = None
    if not isinstance(parsed, dict):
        return None
    picks: dict[str, Any] = {}
    for key in (
        "command",
        "path",
        "file",
        "pattern",
        "query",
        "folder",
        "page_id",
        # 附件卡的标识与晋升目标类型；同样吃 200 字符的既有上界，不新增放宽。
        "attachment_id",
        "source_type",
    ):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            cap = _ARGS_COMMAND_MAX if key == "command" else 200
            picks[key] = value[:cap]
    raw_args = parsed.get("args")
    if isinstance(raw_args, list):
        picks["args"] = [str(item)[:120] for item in raw_args][:8]
    # read_file range reads need the char offset so the card can number lines.
    for key in ("offset", "length"):
        value = parsed.get(key)
        if isinstance(value, int) and value > 0:
            picks[key] = value
    if not picks:
        return None
    display: dict[str, Any] = dict(picks)
    title = _tool_display_title(tool_name, picks)
    if title:
        display["title"] = title
    return display


def _tool_edit_diff_display(tool_name: str, args: Any) -> dict[str, Any] | None:
    """裁决 #11 批准的**新增有界投影**：``edit_file`` 的真行级 diff。

    卡片此前只有一个路径，用户看不到 Agent 到底改了什么。这里从工具自己的
    ``old_string`` / ``new_string`` 参数算 diff（stdlib difflib，不新增依赖），
    作为独立字段 ``edit_diff_display`` 下发，自带行数/字符上界与截断标记——
    **不放宽** ``_tool_args_display`` 里 200 字符的既有上界。
    """
    if tool_name != "edit_file":
        return None
    parsed: Any = args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except (TypeError, ValueError):
            parsed = None
    if not isinstance(parsed, dict):
        return None
    old = parsed.get("old_string")
    new = parsed.get("new_string")
    if not isinstance(old, str) or not isinstance(new, str):
        return None
    old_lines = old.splitlines()
    new_lines = new.splitlines()

    rows: list[dict[str, Any]] = []
    removed = added = 0
    truncated = False
    old_no = new_no = 0
    for tag, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(
        a=old_lines, b=new_lines, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            # 只保留紧邻改动的上下文行，长段未变内容折叠成一个计数行。
            unchanged = old_lines[old_start:old_end]
            keep = unchanged[:_EDIT_DIFF_CONTEXT] + unchanged[-_EDIT_DIFF_CONTEXT:]
            if len(unchanged) > len(keep):
                rows.append({"kind": "gap", "text": "", "count": len(unchanged) - len(keep)})
            for line in unchanged if len(unchanged) <= len(keep) else keep:
                old_no += 1
                new_no += 1
                rows.append(
                    {"kind": "context", "text": line[:_EDIT_DIFF_LINE_CHARS], "old_no": old_no, "new_no": new_no}
                )
            continue
        for line in old_lines[old_start:old_end]:
            old_no += 1
            removed += 1
            rows.append(
                {"kind": "removed", "text": line[:_EDIT_DIFF_LINE_CHARS], "old_no": old_no, "new_no": None}
            )
        for line in new_lines[new_start:new_end]:
            new_no += 1
            added += 1
            rows.append(
                {"kind": "added", "text": line[:_EDIT_DIFF_LINE_CHARS], "old_no": None, "new_no": new_no}
            )

    if len(rows) > _EDIT_DIFF_LINE_MAX:
        rows = rows[:_EDIT_DIFF_LINE_MAX]
        truncated = True
    budget = _EDIT_DIFF_CHARS
    kept: list[dict[str, Any]] = []
    for row in rows:
        cost = len(row["text"]) + 1
        if cost > budget:
            truncated = True
            break
        budget -= cost
        kept.append(row)
    if not kept:
        return None
    return {
        "lines": kept,
        "removed": removed,
        "added": added,
        "truncated": truncated,
    }


def _bounded_preview(text: str) -> dict[str, Any]:
    """Head+tail line-bounded preview capped at _RESULT_PREVIEW_BYTES chars."""
    lines = text.splitlines()
    total_chars = len(text)
    total_lines = len(lines)
    if total_lines <= _RESULT_PREVIEW_LINE_MAX * 2 and total_chars <= _RESULT_PREVIEW_BYTES:
        return {
            "head": text,
            "tail": "",
            "total_chars": total_chars,
            "total_lines": total_lines,
            "truncated": False,
        }
    head_lines = lines[:_RESULT_PREVIEW_LINE_MAX]
    tail_lines = lines[-_RESULT_PREVIEW_LINE_MAX:]
    head = "\n".join(head_lines)
    tail = "\n".join(tail_lines)
    budget = _RESULT_PREVIEW_BYTES - len(head)
    if budget <= 0:
        head, tail = head[:_RESULT_PREVIEW_BYTES], ""
    else:
        tail = tail[:budget]
    return {
        "head": head,
        "tail": tail,
        "total_chars": total_chars,
        "total_lines": total_lines,
        "truncated": True,
    }


def _lint_report_summary(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """lint_knowledge_base 报告的结论摘要（只有标量，不带 issue 正文）。

    报告本体几乎必然被预览上界截断，卡片因此读不出"过没过"。这里在截断**之前**
    摘出结论，且只摘 4 个计数与一个状态串，不放宽任何既有上界。
    """
    status = parsed.get("status")
    if not isinstance(status, str) or "issue_count" not in parsed:
        return None
    return {
        "status": status[:40],
        "page_count": int(parsed.get("page_count") or 0),
        "error_count": int(parsed.get("error_count") or 0),
        "warning_count": int(parsed.get("warning_count") or 0),
    }


def _tool_result_preview(tool_name: str, content: str) -> dict[str, Any] | None:
    """Bounded output preview attached to tool_completed events (P4-capped).

    For structured tool results the preview uses the meaningful text field
    (stdout / content / markdown) instead of the JSON envelope; errors keep
    their message so the failed card can show why.
    """
    text = (content or "").strip()
    if not text:
        return None
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        if parsed.get("error"):
            preview = _bounded_preview(str(parsed["error"])[:_RESULT_PREVIEW_BYTES])
            preview["kind"] = "error"
            return preview
        # lint_knowledge_base 的报告几乎总是超过预览上界；先把结论摘出来，
        # 卡片才不至于在截断之后只剩一坨读不出结果的 JSON。
        summary = _lint_report_summary(parsed)
        for key in ("stdout", "content", "markdown", "diff"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                preview = _bounded_preview(value)
                preview["kind"] = "text"
                return preview
        results = parsed.get("results")
        if isinstance(results, list):
            rendered = "\n".join(
                json.dumps(item, ensure_ascii=False) if not isinstance(item, str) else item
                for item in results
            )
            preview = _bounded_preview(rendered)
            preview["kind"] = "results"
            preview["count"] = len(results)
            return preview
        preview = _bounded_preview(text)
        preview["kind"] = "text"
        if summary:
            preview["summary"] = summary
        return preview
    preview = _bounded_preview(text)
    preview["kind"] = "text"
    return preview


def _signal_key(segment: str, signal: RuntimeSignal) -> tuple[str, AgentEventType]:
    """Build a stable deduplication key for non-streaming lifecycle signals."""
    tool_call_id = str((signal.data or {}).get("tool_call_id") or "")
    identity = tool_call_id or signal.message[:200] or segment
    return (f"{signal.type.value}:{identity}", signal.type)


def _interrupt_payload(value: Any) -> dict[str, Any]:
    """Extract the plain payload from langgraph's Interrupt object (nested config wrapper tolerated)."""
    payload = getattr(value, "value", value)
    if isinstance(payload, dict) and "value" in payload and "config" in payload:
        payload = payload["value"]
    return payload if isinstance(payload, dict) else {}


def _signals_from_interrupt(value: Any) -> list[RuntimeSignal]:
    """Turn one langgraph interrupt value into an ask_user_question confirmation signal."""
    payload = _interrupt_payload(value)
    question = str(payload.get("question") or "")[:2_000]
    if not question:
        return []
    options = [str(option)[:120] for option in (payload.get("options") or [])][:5]
    return [
        RuntimeSignal(
            type=AgentEventType.TASK_CONFIRMATION_REQUIRED,
            message=f"Waiting for the user: {question[:180]}",
            data={
                "interrupt": {
                    "question": question,
                    "options": options,
                    "required": bool(payload.get("required", True)),
                    "tool_call_id": str(payload.get("tool_call_id") or "") or None,
                }
            },
        )
    ]


def _signals_from_stream_item(
    item: tuple[str, tuple[Any, dict[str, Any]] | Any] | Any,
) -> list[RuntimeSignal]:
    """Translate LangGraph message/update chunks into runtime signals."""
    responses: list[RuntimeSignal] = []
    if not isinstance(item, tuple) or len(item) < 2:
        return responses
    # LangGraph 子图流：(() , "messages"|"updates", payload) 三元组
    if len(item) == 3 and isinstance(item[1], str) and item[1] in {"messages", "updates"}:
        name, payload = item[1], item[2]
    else:
        name, payload = item[0], item[1]
    if name == "__interrupt__":
        if isinstance(payload, (list, tuple)):
            payload = payload[0] if payload else None
        return _signals_from_interrupt(payload)

    if name == "messages":
        if not isinstance(payload, tuple) or not payload:
            return responses
        message = payload[0]
        metadata = payload[1] if len(payload) > 1 and isinstance(payload[1], dict) else {}
        if isinstance(message, (AIMessage, AIMessageChunk)):
            model_call_id = str(getattr(message, "id", "") or "") or None
            input_tokens, output_tokens, cached_tokens = _usage_from_message(message)
            reasoning = _reasoning_text(message)
            if reasoning:
                responses.append(
                    RuntimeSignal(
                        type=AgentEventType.REASONING_DELTA,
                        message=reasoning,
                        data={"source": "reasoning"},
                        model_call_id=model_call_id,
                    )
                )
            tool_calls = getattr(message, "tool_calls", []) or []
            if not tool_calls:
                tool_calls = getattr(message, "tool_call_chunks", []) or []
            for tool_call in tool_calls:
                tool_name = str(tool_call.get("name") or "").strip()
                if tool_name:
                    args_display = _tool_args_display(tool_name, tool_call.get("args"))
                    # Streamed chunks carry partial args; the updates branch
                    # emits the assembled tool call with a complete projection
                    # instead, so skip the incomplete chunk here.
                    if isinstance(message, AIMessageChunk) and args_display is None:
                        continue
                    args_summary = _tool_args_summary(tool_name, tool_call.get("args"))
                    display = (
                        f"{tool_name} · {args_summary}"
                        if args_summary
                        else f"{tool_name} started."
                    )
                    signal_data: dict[str, Any] = {
                        "tool_name": tool_name,
                        "tool_call_id": str(tool_call.get("id") or ""),
                    }
                    if args_display:
                        signal_data["args_display"] = args_display
                    edit_diff = _tool_edit_diff_display(tool_name, tool_call.get("args"))
                    if edit_diff:
                        signal_data["edit_diff_display"] = edit_diff
                    responses.append(
                        RuntimeSignal(
                            type=AgentEventType.TOOL_STARTED,
                            message=display,
                            data=signal_data,
                            model_call_id=model_call_id,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cached_input_tokens=cached_tokens,
                        )
                    )
            text = _message_text(getattr(message, "content", ""))
            # Streaming responses attach usage only to a final, text-empty
            # chunk; emit a delta signal for it anyway so run usage keeps
            # accumulating (the runtime persists message only when non-empty).
            if text or input_tokens or output_tokens or cached_tokens:
                responses.append(
                    RuntimeSignal(
                        type=AgentEventType.MESSAGE_DELTA,
                        message=text,
                        data={"source": "model", **metadata},
                        model_call_id=model_call_id,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cached_input_tokens=cached_tokens,
                    )
                )
        elif isinstance(message, ToolMessage):
            tool_name = message.name or "tool"
            tool_call_id = message.tool_call_id or ""
            result_text = _message_text(message.content)
            completed_data: dict[str, Any] = {
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
            }
            result_preview = _tool_result_preview(tool_name, result_text)
            if result_preview:
                completed_data["result_preview"] = result_preview
            responses.append(
                RuntimeSignal(
                    type=AgentEventType.TOOL_COMPLETED,
                    message=_tool_result_summary(tool_name, result_text),
                    data=completed_data,
                )
            )
    elif name == "updates" and isinstance(payload, dict):
        for node_name, update in payload.items():
            if node_name != "__interrupt__":
                # The messages stream already carries AIMessageChunk/ToolMessage
                # values. Do not parse the full update message again or text is
                # duplicated in the desktop transcript. Exception: streamed
                # tool-call chunks arrive with empty/partial args, so the model
                # node's assembled AIMessage is the only place a complete
                # args_display projection exists. TOOL_STARTED dedupes by
                # tool_call_id downstream, so re-emitting it is safe.
                if node_name == "model" and isinstance(update, dict):
                    node_messages = update.get("messages")
                    if isinstance(node_messages, (list, tuple)):
                        for node_message in node_messages:
                            if not isinstance(node_message, AIMessage):
                                continue
                            for tool_call in getattr(node_message, "tool_calls", []) or []:
                                tool_name = str(tool_call.get("name") or "").strip()
                                if not tool_name:
                                    continue
                                args_summary = _tool_args_summary(tool_name, tool_call.get("args"))
                                display = (
                                    f"{tool_name} · {args_summary}"
                                    if args_summary
                                    else f"{tool_name} started."
                                )
                                assembled_data: dict[str, Any] = {
                                    "tool_name": tool_name,
                                    "tool_call_id": str(tool_call.get("id") or ""),
                                }
                                args_display = _tool_args_display(tool_name, tool_call.get("args"))
                                if args_display:
                                    assembled_data["args_display"] = args_display
                                assembled_diff = _tool_edit_diff_display(
                                    tool_name, tool_call.get("args")
                                )
                                if assembled_diff:
                                    assembled_data["edit_diff_display"] = assembled_diff
                                responses.append(
                                    RuntimeSignal(
                                        type=AgentEventType.TOOL_STARTED,
                                        message=display,
                                        data=assembled_data,
                                        # No model_call_id here: the assembled
                                        # message id (resp_*) differs from the
                                        # streamed chunk id (lc_run_*), and
                                        # registering it would inflate model
                                        # spans and the per-round call count.
                                    )
                                )
                continue
            value = update
            if isinstance(value, (list, tuple)):
                value = value[0] if value else None
            responses.extend(_signals_from_interrupt(value))
    return responses


class _CancellationGate:
    """Small threading-safe cancellation gate (avoids asyncio in worker threads)."""

    def __init__(self) -> None:
        self._flag = False

    def set(self) -> None:
        self._flag = True

    def is_set(self) -> bool:
        return self._flag


class AgentRuntimeManager:
    """Serialize every agent run and own the lifecycle + approval boundary."""

    def __init__(
        self,
        project_root: Path,
        adapter: Any = None,
        *,
        max_retries: int = 2,
        seed: str | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.max_retries = max_retries
        self.seed = seed
        self.store = RuntimeStore(self.project_root)
        self.adapter = adapter
        # 启动时收敛孤儿运行（重启窗口：running -> unfinished 可继续/恢复）。
        # 决策 10：协议型 adapter 没有图状态，挂起态归外部服务，不参与 checkpoint 收敛。
        self.store.recover_stale_runs(
            graph_state_durable=adapter is None or not hasattr(adapter, "execute")
        )
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="cellwiki-agent",
        )
        self._thread_lock = RLock()
        self._built_adapter: Any | None = None
        self._cancellations: dict[str, _CancellationGate] = {}
        self._running_run_id: str | None = None
        self._git: GitExecutor | None = None
        # 系统维护（audit 快照与 accept/reject/unfinished 写入）串行化：
        # run 收尾线程的 lint 快照与 API 线程的判定维护互不交错提交。
        self._maintenance_lock = RLock()
        warn_if_narrow_window(
            settings.openai_model.casefold(), settings.agent_context_max_tokens
        )

    # ---- 公共生命周期 ----
    def start(
        self,
        thread_id: str,
        message: str,
        context: WikiAgentContext,
        budget: RunBudget | None = None,
        *,
        attachment_ids: list[str] | None = None,
        request_id: str | None = None,
    ) -> AgentRun:
        """Start exactly one run; reject any second active run (strict serial gate)."""
        run, _replayed = self.start_idempotent(
            thread_id,
            message,
            context,
            budget,
            attachment_ids=attachment_ids,
            request_id=request_id,
        )
        return run

    def start_idempotent(
        self,
        thread_id: str,
        message: str,
        context: WikiAgentContext,
        budget: RunBudget | None = None,
        *,
        attachment_ids: list[str] | None = None,
        request_id: str | None = None,
    ) -> tuple[AgentRun, bool]:
        """ADR-0010 决策 7/8：幂等提交 + 执行配置快照，返回 ``(run, replayed)``。

        命中同一 ``request_id`` 时返回既有 run 且 ``replayed=True``，调用方仍回 202。
        串行门禁的权威判定在 ``create_run_if_idle`` 的同一事务里；事务外的快速检查
        只为了给出更具体的错误消息，因此仅在**没有** ``request_id`` 时跑——否则重试
        风暴里原 run 还活动着，幂等命中会被误判成 409。
        """
        # 决策 7：带 request_id 时不在事务外做任何预检。重试风暴里原 run 往往还是
        # 活动的，预检会把"命中既有 run"误判成 409；权威判定（先查 replay、再查
        # 活动 run、最后插入）全在 create_run_if_idle 的同一 BEGIN IMMEDIATE 里。
        if request_id is None:
            active = self._ensure_single_active_run()
            if active is not None:
                raise AgentRunInProgressError(
                    f"another agent run is active: {active.run_id} ({active.status.value})"
                )
            pending = [
                diff
                for diff in self.store.list_pending_diffs(limit=50)
                if diff.status == PendingDiffStatus.PENDING
            ]
            if pending:
                raise AgentRunInProgressError(
                    f"a pending diff requires review before a new run: {pending[0].diff_id}"
                )
        # 重试上次失败的维护（best-effort，失败不阻塞新 run）
        self._retry_failed_maintenance()
        run_id = _new_run_id()
        snapshot = self._git_snapshot()
        budget = budget or RunBudget(
            max_model_calls=settings.agent_max_tool_steps,
            max_runtime_seconds=max(settings.agent_run_max_seconds, MAX_RUN_SECONDS_FLOOR),
        )
        run = AgentRun(
            run_id=run_id,
            thread_id=thread_id,
            project_id=context.project_id,
            # 直播看到的上下文必须落库：回放与诊断读的是这条记录，不是内存里的
            # context 对象。此前 API 把它们送进了 WikiAgentContext 却被这里丢掉。
            source_id=context.source_id,
            page_id=context.page_id,
            selected_text=context.selected_text,
            status=AgentRunStatus.QUEUED,
            input_message=message.strip()[:60_000],
            budget=budget,
            created_at=datetime.now(UTC),
            snapshot_commit=snapshot,
            attachment_ids=list(dict.fromkeys(attachment_ids or [])),
            # Diagnostics read run.model_name; without this write the field stays
            # empty even though model spans carry the name.
            model_name=settings.openai_model or "",
            # 决策 8：执行配置快照，使历史 run 不受 .env 漂移影响。
            prompt_hash=prompt_configuration_hash(budget),
            request_id=request_id,
        )
        try:
            created, replayed = self.store.create_run_if_idle(run, request_id=request_id)
        except SerialGateViolationError as error:
            raise AgentRunInProgressError(str(error)) from None
        if replayed:
            # 幂等命中：不提交第二个执行者，直接把既有 run 交回调用方。
            return created, True
        with self._thread_lock:
            self._cancellations[created.run_id] = _CancellationGate()
        self._executor.submit(
            self._execute, created.run_id, thread_id, message, context, budget
        )
        return created, False

    def retry(self, run_id: str, *, reason: str = "retry") -> AgentRun:
        """ADR-0010 决策 5：retry = 先删该 run 的状态键，再从有界 transcript 重放。

        仍是同一 ``run_id``（守 ``CONTEXT.md`` 不变量 7）；累计用量、已产生的 commit
        与审批单元关联保留。与 resume 分道：resume 不清状态、从 checkpoint 续跑。
        """
        run = self.store.get_run(run_id)
        if run is not None:
            delete_run_checkpoints(self.project_root, run.thread_id, run_id)
        return self._claim_and_submit(run_id, AgentRunStatus.RETRYING, reason)

    def _run_checkpoint_is_resumable(self, run: AgentRun) -> bool:
        """决策 4：字段非空只是必要条件，载体里还得真的存着该 run 的图状态。

        两类"不能续跑"都要挡住：升级前产生的 run 一律 ``checkpoint_id = NULL``；
        清过 ``data/`` 或换了机器的 run 则是"字段在、状态没了"。后者若只看字段，
        就会在空图上静默 ``Command(resume=...)``。回滚闸（``inmemory``）下没有可查
        的持久载体，图状态本就只活在本进程里，因此仍按字段判定。
        """
        if not run.checkpoint_id:
            return False
        if settings.agent_checkpointer != "sqlite":
            return True
        return has_run_checkpoint(self.project_root, run.thread_id, run.run_id)

    def resume(self, run_id: str, *, reason: str = "resume") -> AgentRun:
        """ADR-0010 决策 6：resume = 同一 run 回到 RUNNING、继承剩余预算，从 checkpoint 续跑。"""
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        adapter = self.adapter or self._built_adapter
        # adapter 为空意味着稍后会构建产品图，因此同样按图路径判定。
        graph_path = adapter is None or not hasattr(adapter, "execute")
        # 决策 4：升级前产生的 run 一律 checkpoint_id=NULL；显式失败（API 映射 409
        # 并提示重发消息），禁止在空图上静默重放。协议型 adapter 没有图状态，
        # 续跑就是按原输入重放，不受这道闸门约束。
        if graph_path and not self._run_checkpoint_is_resumable(run):
            raise CheckpointMissingError(
                f"run {run_id} has no usable checkpoint; resend the message to start a new run"
            )
        claimed = self.store.claim_resume_unfinished(run_id)
        with self._thread_lock:
            self._cancellations[claimed.run_id] = _CancellationGate()
        self._executor.submit(
            self._execute,
            claimed.run_id,
            claimed.thread_id,
            claimed.input_message,
            self._context_for_run(claimed),
            claimed.budget,
            continue_from_checkpoint=graph_path,
        )
        return claimed

    def cancel(self, run_id: str) -> AgentRun:
        """Cancel at the next safe event boundary; unfinished/paused-question runs cancel directly."""
        run = self.store.get_run(run_id)
        if run.status == AgentRunStatus.UNFINISHED:
            return self.store.finalize_run(
                run.run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.CANCELLED,
                    message="Unfinished run cancelled by the user.",
                ),
            )
        if run.status == AgentRunStatus.QUEUED:
            return self.store.finalize_run(
                run.run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.CANCELLED,
                    message="Queued run cancelled before execution started.",
                ),
            )
        if run.status == AgentRunStatus.WAITING_CONFIRMATION:
            # 用户主动取消挂起在问题上的 run：关闭未回答的问题并直接终结，
            # 串行闸门随即释放（与“超时跳过”不同，这里给明确的无条件取消语义）。
            self.store.answer_question(run_id, [], timed_out=True)
            return self.store.finalize_run(
                run.run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.CANCELLED,
                    message="Question cancelled by the user.",
                ),
            )
        if run.status in {AgentRunStatus.RUNNING, AgentRunStatus.RETRYING}:
            cancelled = self.store.transition(
                run_id,
                AgentRunStatus.CANCELLING,
                message="Cancellation requested; waiting for a safe boundary.",
            )
            with self._thread_lock:
                gate = self._cancellations.get(run_id)
                if gate is not None:
                    gate.set()
            return cancelled
        raise InvalidRunTransitionError(
            f"cannot cancel run {run_id}: status {run.status.value}"
        )

    def delete_thread(self, thread_id: str) -> int:
        """Delete runs, events, spans and pending diffs for one thread."""
        return self.store.delete_thread(thread_id)

    @staticmethod
    def _context_for_run(run: AgentRun) -> WikiAgentContext:
        """Rebuild one run's context from its durable record.

        续跑段（resume / retry / 答题续跑）此前用空的 WikiAgentContext 起图，
        于是首段看到的页面与选中文本在续跑段消失。上下文既然已随 run 落库，
        回放就必须读同一份。
        """
        return WikiAgentContext(
            project_id=run.project_id,
            source_id=run.source_id,
            page_id=run.page_id,
            selected_text=run.selected_text,
            thread_id=run.thread_id,
            attachment_ids=list(run.attachment_ids),
        )

    # ---- pending diff 审批 ----
    def pending_diff_patch(self, diff_id: str) -> str:
        """Return the unified patch text for one pending diff (review UI).

        Uses a dedicated git executor with a larger output cap: the review
        UI needs the complete patch, while agent-facing git calls keep the
        default 200 KB bound.
        """
        diff = self.store.get_pending_diff(diff_id)
        if diff is None:
            raise KeyError(diff_id)
        if self._git_executor() is None:
            return ""
        refs = frozenset({"HEAD"})
        if diff.snapshot_commit is not None:
            refs = frozenset({diff.snapshot_commit, "HEAD"})
        reviewer = GitExecutor(self.project_root, max_output_bytes=10_000_000)
        return reviewer.diff_between(
            diff.snapshot_commit, enabled_refs=refs
        ).patch

    def accept_pending_diff(self, diff_id: str) -> PendingDiff:
        """Accept one approval unit: its commits stay, the verdict is recorded,
        then system maintenance runs.

        判定不可回退：只有 PENDING 单元可以接受。审批单元边界即 diff 行本身
        （ADR-0007 修订），预算暂停—"继续"后的新提交落在序号更大的新单元里，
        因此不存在"重发布把已批准 commit 装回待判范围"的窗口。
        """
        with self._maintenance_lock:
            current = self.store.get_pending_diff(diff_id)
            if current.status != PendingDiffStatus.PENDING:
                raise InvalidRunTransitionError(
                    f"diff {diff_id} is already {current.status.value}"
                )
            diff = self.store.update_pending_diff(
                diff_id, status=PendingDiffStatus.ACCEPTED, resolution="accepted"
            )
            self._run_maintenance_locked("accept", diff)
        return diff

    def reject_pending_diff(self, diff_id: str) -> PendingDiff:
        """Reject one approval unit: revert **this unit's** commits, newest-first.

        revert 生成的提交 sha 记入 ``data.revert_commits``：它们物理上会位于后续
        单元的基线之后，排除集合让后续单元既不装入也不二次回滚它们。
        """
        diff = self.store.get_pending_diff(diff_id)
        if diff.status != PendingDiffStatus.PENDING:
            raise InvalidRunTransitionError(
                f"diff {diff_id} is already {diff.status.value}"
            )
        with self._maintenance_lock:
            git = self._git_executor()
            revert_shas: list[str] = []
            if git is not None and diff.commits:
                revert_shas = git.revert_commits(diff.commits)
            diff = self.store.update_pending_diff(
                diff_id,
                status=PendingDiffStatus.REJECTED,
                resolution="rejected",
                data={"revert_commits": revert_shas},
            )
            self._run_maintenance_locked("reject", diff)
        return diff

    def reopen_pending_diff(self, diff_id: str) -> PendingDiff:
        """No-op reopen for a still-pending unit; resolved units are immutable.

        接口保留兼容旧调用方，但"一行一次判定"之后不存在把已判定单元改回
        pending 的语义（撤销走 reject + 新 run 重做，而不是重开旧判定）。
        """
        current = self.store.get_pending_diff(diff_id)
        if current.status != PendingDiffStatus.PENDING:
            raise InvalidRunTransitionError(
                f"diff {diff_id} is already {current.status.value} and cannot be reopened"
            )
        return current

    # ---- 内部执行 ----
    def _persist_run_checkpoint(self, run_id: str, thread_id: str) -> None:
        """ADR-0010 决策 4：每段结束后把最新 checkpoint 标识写回 run。

        必须等图流真正关闭之后再读：中断段的 checkpoint 是底层流收敛时才落盘的，
        在记账钩子里读会拿到空值，于是可续跑的 run 反而被决策 4 判成无状态。
        best-effort——写回失败绝不能顶替真正的 run 错误。协议型 adapter 没有图状态。
        """
        adapter = self.adapter or self._built_adapter
        if adapter is None or hasattr(adapter, "execute"):
            return
        try:
            self.store.set_run_checkpoint(
                run_id, latest_checkpoint_id(adapter, thread_id, run_id)
            )
        except Exception:  # noqa: BLE001 - checkpoint 回写失败不得顶替 run 错误
            with suppress(Exception):
                self.store.append_event(
                    run_id,
                    AgentEventType.ERROR,
                    message="Checkpoint write-back failed for this segment.",
                )

    def _execute(
        self,
        run_id: str,
        thread_id: str,
        message: str,
        context: WikiAgentContext,
        budget: RunBudget,
        *,
        continue_from_checkpoint: bool = False,
    ) -> None:
        try:
            with log_context(run_id=run_id, thread_id=thread_id):
                self._execute_bound(
                    run_id,
                    thread_id,
                    message,
                    context,
                    budget,
                    continue_from_checkpoint=continue_from_checkpoint,
                )
        finally:
            self._persist_run_checkpoint(run_id, thread_id)
            clear_attachment_resolver()
            clear_attachment_scope()
            clear_attachment_scope()
            clear_attachment_scope()
            with self._thread_lock:
                if self._running_run_id == run_id:
                    self._running_run_id = None
                self._cancellations.pop(run_id, None)
            self._maybe_publish_pending_diff(run_id)

    def _execute_bound(
        self,
        run_id: str,
        thread_id: str,
        message: str,
        context: WikiAgentContext,
        budget: RunBudget,
        *,
        continue_from_checkpoint: bool = False,
    ) -> None:
        run = self.store.get_run(run_id)
        if run.status == AgentRunStatus.QUEUED:
            run = self.store.transition(
                run_id, AgentRunStatus.RUNNING, message="Run started."
            )
        elif run.status == AgentRunStatus.RETRYING:
            run = self.store.transition(
                run_id, AgentRunStatus.RUNNING, message="Retry started."
            )
        with self._thread_lock:
            self._running_run_id = run_id

        set_attachment_resolver(
            lambda attachment_id: self.resolve_attachment_path(run.thread_id, attachment_id)
        )
        files = AttachmentFileStore(self.project_root)
        set_attachment_scope(
            lambda attachment_id: self.resolve_attachment_path(run.thread_id, attachment_id),
            self.project_root,
            files._thread_dir(run.thread_id),
            settings.agent_attachment_read_budget_chars,
        )
        set_promotion_handler(
            lambda thread_id, attachment_id, source_id: self.store.mark_attachment_promoted(
                thread_id, attachment_id, source_id
            )
        )
        set_promotion_handler(
            lambda thread_id, attachment_id, source_id: self.store.mark_attachment_promoted(
                thread_id, attachment_id, source_id
            )
        )
        files = AttachmentFileStore(self.project_root)
        set_attachment_scope(
            lambda attachment_id: self.resolve_attachment_path(run.thread_id, attachment_id),
            self.project_root,
            files._thread_dir(run.thread_id),
            settings.agent_attachment_read_budget_chars,
        )
        files = AttachmentFileStore(self.project_root)
        set_attachment_scope(
            lambda attachment_id: self.resolve_attachment_path(run.thread_id, attachment_id),
            self.project_root,
            files._thread_dir(run.thread_id),
            settings.agent_attachment_read_budget_chars,
        )
        adapter = self.adapter or self._built_adapter or _instantiate_agent(self.project_root)
        self._built_adapter = adapter
        # ADR-0010 决策 8：墙钟预算跨段累计——续跑段继承已消耗的时间而不是重新计时，
        # "崩溃恢复继承剩余预算"因此可测。
        started_at = time.monotonic() - (
            run.usage.elapsed_seconds if continue_from_checkpoint else 0.0
        )
        seen: set[tuple[str, AgentEventType]] = set()
        try:
            if continue_from_checkpoint:
                # ADR-0010 决策 3/6：续跑段从该 run 自己的 checkpoint 继续，
                # 不重放 transcript，也不再落一条重复的用户消息。
                stream = self._open_stream_continue(
                    adapter, thread_id, message, context, run_id=run_id
                )
            else:
                view = ConversationContextView(self.store)
                # 会话上下文先持久化当前用户消息，再交给适配器（conversation-first）
                self.store.append_message(
                    thread_id=thread_id,
                    run_id=run_id,
                    role="user",
                    content=message,
                    data={"source": "agent_runtime"},
                )
                messages_in = view.build(
                    thread_id=thread_id,
                    current_run_id=run_id,
                    current_content=message or "",
                )
                # 阶段 5：512K/80% 阈值压缩 -> 六类摘要 + 保留窗口 32K，并注入 R1-R5
                compacted = compact_transcript(
                    messages_in,
                    max_tokens=settings.agent_context_max_tokens,
                    auto_compact_ratio=settings.agent_context_auto_compact_ratio,
                    retained_tokens=settings.agent_context_retained_tokens,
                )
                if compacted.compacted:
                    r1_r5 = build_r1_r5_block(
                        git_status=self._git_status_text(),
                        pending_question=None,
                        recent_lint=None,
                        run_goal=message,
                    )
                    messages_in = [
                        {
                            "role": "system",
                            "content": compacted.summary_text + "\n\n" + r1_r5,
                        },
                        *compacted.retained,
                    ]
                # 阶段 5：Layer B run 动态快照（git 状态 + 打开页面元数据/大纲 + 选中文本）
                layer_b = build_layer_b_snapshot(
                    current_message=message,
                    git_status=self._git_status_text(),
                    open_page=self._open_page_snapshot(context.page_id),
                    recent_transcript=self.store.list_context_messages(thread_id)[-4:],
                    attachments=self._attachment_manifest(run),
                    selected_text=context.selected_text,
                )
                if layer_b:
                    messages_in = [
                        {"role": "system", "content": layer_b},
                        *messages_in,
                    ]
                stream = self._open_stream(
                    adapter, thread_id, messages_in, context, run_id=run_id
                )
            outcome = self._consume_stream(
                run_id,
                thread_id,
                stream,
                budget,
                started_at=started_at,
                seen=seen,
                adapter=adapter,
            )
            if outcome.question_pending:
                # ask_user_question 挂起：保持 WAITING_CONFIRMATION 直到用户回复；
                # answer_question() 以 Command(resume=answers) 续跑。
                try:
                    self._maybe_publish_pending_diff(run_id)
                except (GitCommandError, OSError):
                    pass
                return
            self._finalize_stream_outcome(run_id, thread_id, outcome)
            # 尽早发布 pending diff（幂等：git 异常不影响运行结果）
            try:
                published = self._maybe_publish_pending_diff(run_id)
            except (GitCommandError, OSError):
                published = False
            if published:
                # 内容型 run：强制 lint 快照写入 audit_report.md（仅记录，不改门禁语义）
                self._forced_lint_audit(run_id)
        except _RunTimeoutError as error:
            self._finalize_unfinished(run_id, AgentErrorType.TIMEOUT, str(error))
        except AgentBudgetExceeded as error:
            self._finalize_unfinished(run_id, AgentErrorType.BUDGET, str(error))
        except AgentRetryLimitExceeded as error:
            self._finalize_unfinished(run_id, AgentErrorType.BUDGET, str(error))
        except Exception as error:  # noqa: BLE001 - 边界必须收敛所有异常
            self._finish_failed(run_id, error)

    def _finalize_stream_outcome(
        self, run_id: str, thread_id: str, outcome: _ConsumeOutcome
    ) -> None:
        """Persist the assistant text and make normal graph termination explicit."""
        if outcome.cancelled:
            self.store.finalize_run(
                run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.CANCELLED,
                    message="Run cancelled at a safe event boundary.",
                ),
            )
            return
        if outcome.final_answer and outcome.final_answer.strip():
            self.store.append_message(
                thread_id=thread_id,
                run_id=run_id,
                role="assistant",
                content=outcome.final_answer,
                data={"source": "agent_runtime"},
            )
            self.store.finalize_run(
                run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.SUCCEEDED,
                    message="Run completed.",
                ),
            )
            return
        self.store.finalize_run(
            run_id,
            AgentRunOutcome(
                status=AgentRunStatus.FAILED,
                message="Agent completed without a textual answer.",
                error_type=AgentErrorType.SYSTEM,
                error_message="Agent completed without a textual answer.",
            ),
        )

    def _consume_stream(
        self,
        run_id: str,
        thread_id: str,
        stream: Any,
        budget: RunBudget,
        *,
        started_at: float,
        seen: set[tuple[str, AgentEventType]],
        adapter: Any = None,
    ) -> _ConsumeOutcome:
        """消费一条流：统计用量、收集最终回答、持久化挂起问题，返回结局。"""
        final_answer: str | None = None
        assistant_text_parts: list[str] = []
        last_model_call_id: str | None = None
        call_usage: dict[str, list[int]] = {}
        call_started: dict[str, float] = {}
        call_seen_last: dict[str, float] = {}
        # First visible-content delta per model call -> TTFT for that round.
        call_first_token: dict[str, float] = {}
        # Open tool calls keyed by tool_call_id -> (name, started_monotonic).
        tool_open: dict[str, tuple[str, float]] = {}
        counted_tool_starts: set[str] = set()
        input_tokens = 0
        output_tokens = 0
        cached_input_tokens = 0
        tool_calls_started = 0
        tool_calls_completed = 0
        steps_at_end = 0
        question_pending = False
        accounting_flushed = False

        def _flush_accounting() -> None:
            """落盘本段 spans + usage，恰好一次，中止也不例外。

            预算/墙钟中止是从下面的迭代里抛出去的，循环之后的代码永远不执行；
            没有这个钩子，每次挂起段的模型调用与 token 就从 run 记账里凭空消失
            （实测：4 段跑完 model_calls=0、model span 一条没有）。记账属于
            best-effort，绝不能盖掉真正的 run 错误。
            """
            nonlocal accounting_flushed
            if accounting_flushed:
                return
            accounting_flushed = True
            try:
                self._record_model_spans(
                    run_id,
                    call_usage,
                    call_started,
                    call_seen_last,
                    call_first_token,
                )
                # Any tool call that never reported completion (cancelled/failed
                # run) still gets a span so the timeline totals reflect the time
                # it consumed.
                self._flush_open_tool_spans(run_id, tool_open)
                read_chars, read_tokens = attachment_read_stats()
                segment_usage = RunUsage(
                    model_calls=steps_at_end,
                    input_tokens=input_tokens
                    + sum(value[0] for value in call_usage.values()),
                    output_tokens=output_tokens
                    + sum(value[1] for value in call_usage.values()),
                    cached_input_tokens=cached_input_tokens
                    + sum(value[2] for value in call_usage.values()),
                    tool_calls=tool_calls_started,
                    tool_calls_started=tool_calls_started,
                    tool_calls_completed=tool_calls_completed,
                    elapsed_seconds=time.monotonic() - started_at,
                    read_chars=read_chars,
                    read_tokens=read_tokens,
                )
                updated_run = self.store.update_usage(
                    run_id,
                    segment_usage,
                    # 每段只报自己的计数；跨 resume/retry 累加才是 run 生命周期总量。
                    accumulate=True,
                )
                # 决策 9：每 run 用量进事件流，只在诊断面板展示，不进聊天气泡。
                self.store.append_event(
                    run_id,
                    AgentEventType.USAGE_UPDATED,
                    message="Run usage updated.",
                    data={
                        "segment": segment_usage.model_dump(mode="json"),
                        "cumulative": updated_run.usage.model_dump(mode="json"),
                    },
                )
            except Exception as error:  # noqa: BLE001 - 记账失败不得顶替 run 错误
                with suppress(Exception):
                    self.store.append_event(
                        run_id,
                        AgentEventType.ERROR,
                        message=f"Run accounting failed: {error}",
                    )

        segments = self._iterate_safe(
            stream, budget, started_at, on_finish=_flush_accounting
        )
        try:
            for segment, signals, steps in segments:
                with self._thread_lock:
                    gate = self._cancellations.get(run_id)
                    if gate is not None and gate.is_set():
                        break
                for signal in signals:
                    steps_at_end = steps
                    if signal.model_call_id:
                        now = time.monotonic()
                        call_started.setdefault(signal.model_call_id, now)
                        call_seen_last[signal.model_call_id] = now
                        usage = call_usage.setdefault(signal.model_call_id, [0, 0, 0])
                        usage[0] = max(usage[0], signal.input_tokens)
                        usage[1] = max(usage[1], signal.output_tokens)
                        usage[2] = max(usage[2], signal.cached_input_tokens)
                    else:
                        input_tokens += signal.input_tokens
                        output_tokens += signal.output_tokens
                        cached_input_tokens += signal.cached_input_tokens
                    if signal.type == AgentEventType.TOOL_STARTED:
                        # Streaming and non-streaming paths can both surface the same
                        # call id (messages chunk + assembled updates AIMessage); the
                        # durable event dedup hides it, so count and open spans once.
                        start_id = str((signal.data or {}).get("tool_call_id") or "")
                        if not start_id or start_id not in counted_tool_starts:
                            counted_tool_starts.add(start_id)
                            tool_calls_started += 1
                            self._open_tool_span(tool_open, signal)
                    if signal.type == AgentEventType.TOOL_COMPLETED:
                        tool_calls_completed += 1
                        self._close_tool_span(run_id, tool_open, signal, "completed")
                    if signal.type == AgentEventType.TOOL_FAILED:
                        self._close_tool_span(run_id, tool_open, signal, "failed")
                    if signal.model_call_id:
                        last_model_call_id = signal.model_call_id
                    if signal.type == AgentEventType.FINAL_RESPONSE and signal.message.strip() and final_answer is None:
                        final_answer = signal.message
                    if signal.type == AgentEventType.TASK_CONFIRMATION_REQUIRED:
                        self._persist_question(run_id, thread_id, signal)
                        question_key: tuple[str, AgentEventType] = (segment, signal.type)
                        if question_key not in seen:
                            self.store.append_event(
                                run_id,
                                signal.type,
                                message=signal.message,
                                progress=signal.progress,
                                data=_signal_payload(
                                    segment,
                                    signal.message,
                                    signal.data,
                                    model_call_id=signal.model_call_id,
                                ),
                            )
                            seen.add(question_key)
                        question_pending = True
                        break
                    if signal.type == AgentEventType.MESSAGE_DELTA:
                        if signal.message:
                            if signal.model_call_id:
                                call_first_token.setdefault(signal.model_call_id, time.monotonic())
                            assistant_text_parts.append(signal.message)
                            self.store.append_event(
                                run_id,
                                signal.type,
                                message=signal.message,
                                progress=signal.progress,
                                data=_signal_payload(
                                    segment,
                                    signal.message,
                                    signal.data,
                                    model_call_id=signal.model_call_id,
                                    input_tokens=signal.input_tokens,
                                    output_tokens=signal.output_tokens,
                                ),
                            )
                        continue
                    if signal.type == AgentEventType.REASONING_DELTA:
                        if signal.message:
                            if signal.model_call_id:
                                call_first_token.setdefault(signal.model_call_id, time.monotonic())
                            self.store.append_event(
                                run_id,
                                signal.type,
                                message=signal.message,
                                progress=signal.progress,
                                data=_signal_payload(
                                    segment,
                                    signal.message,
                                    {"source": "reasoning", **signal.data},
                                    model_call_id=signal.model_call_id,
                                ),
                            )
                        continue
                    key = _signal_key(segment, signal)
                    if key in seen:
                        continue
                    self.store.append_event(
                        run_id,
                        signal.type,
                        message=signal.message,
                        progress=signal.progress,
                        data=_signal_payload(
                            segment,
                            signal.message,
                            signal.data,
                            model_call_id=signal.model_call_id,
                            input_tokens=signal.input_tokens,
                            output_tokens=signal.output_tokens,
                        ),
                    )
                    seen.add(key)
                if question_pending:
                    break
        finally:
            # 挂起/取消段是从循环里 break 出去的：底层图流必须显式关闭，
            # checkpoint 才落盘，决策 4 的回写与其后的续跑才读得到它；
            # 等 GC 关闭会晚到不可用。
            segments.close()
            close_stream = getattr(stream, "close", None)
            if callable(close_stream):
                close_stream()
            # 决策 4：图流一关就回写，别等到 _execute 的 finally——那时 run 早已
            # 是 WAITING_CONFIRMATION，快速作答的用户会撞上还没落盘的 checkpoint。
            if adapter is not None and not hasattr(adapter, "execute"):
                with suppress(Exception):
                    self.store.set_run_checkpoint(
                        run_id, latest_checkpoint_id(adapter, thread_id, run_id)
                    )
        assistant_text = "".join(assistant_text_parts).strip()
        if final_answer is None and assistant_text and not question_pending:
            final_answer = assistant_text
            self.store.append_event(
                run_id,
                AgentEventType.FINAL_RESPONSE,
                message=final_answer,
                data=_signal_payload(
                    "agent",
                    final_answer,
                    {"answer": final_answer},
                    model_call_id=last_model_call_id,
                ),
            )
        _flush_accounting()
        cancelled = False
        with self._thread_lock:
            gate = self._cancellations.get(run_id)
            cancelled = gate is not None and gate.is_set()
        return _ConsumeOutcome(
            final_answer=final_answer,
            cancelled=cancelled,
            question_pending=question_pending,
        )

    def _open_tool_span(
        self, tool_open: dict[str, tuple[str, float]], signal: RuntimeSignal
    ) -> None:
        """Remember when a tool call started, keyed by tool_call_id (idempotent)."""
        data = signal.data or {}
        call_id = str(data.get("tool_call_id") or "")
        if not call_id:
            return
        tool_name = str(data.get("tool_name") or "tool")
        tool_open.setdefault(call_id, (tool_name, time.monotonic()))

    def _close_tool_span(
        self,
        run_id: str,
        tool_open: dict[str, tuple[str, float]],
        signal: RuntimeSignal,
        status: str,
    ) -> None:
        """Emit one redacted timing span for a finished tool call."""
        call_id = str((signal.data or {}).get("tool_call_id") or "")
        opened = tool_open.pop(call_id, None) if call_id else None
        if opened is None:
            return
        tool_name, started = opened
        self._write_tool_span(run_id, tool_name, started, status)

    def _flush_open_tool_spans(
        self, run_id: str, tool_open: dict[str, tuple[str, float]]
    ) -> None:
        """Record spans for tool calls that never completed (cancel/failure)."""
        for tool_name, started in tool_open.values():
            self._write_tool_span(run_id, tool_name, started, "cancelled")
        tool_open.clear()

    def _write_tool_span(
        self, run_id: str, tool_name: str, started: float, status: str
    ) -> None:
        finished_at = datetime.now(UTC)
        duration_ms = max(0.0, (time.monotonic() - started) * 1000.0)
        self.store.upsert_span(
            AgentSpan(
                span_id=f"span_{uuid.uuid4().hex}",
                run_id=run_id,
                kind="tool",
                name=tool_name,
                status=status,
                started_at=finished_at - timedelta(seconds=duration_ms / 1000.0),
                finished_at=finished_at,
                duration_ms=duration_ms,
                data={"tool": True},
            )
        )

    def _record_model_spans(
        self,
        run_id: str,
        call_usage: dict[str, list[int]],
        call_started: dict[str, float],
        call_seen_last: dict[str, float],
        call_first_token: dict[str, float],
    ) -> None:
        """Write one redacted span per model call so diagnostics has per-round rows."""
        if not call_usage:
            return
        finished_at = datetime.now(UTC)
        model_name = settings.openai_model or "model"
        for call_id, tokens in call_usage.items():
            started = call_started.get(call_id, 0.0)
            last = call_seen_last.get(call_id, started)
            duration_ms = max(0.0, (last - started) * 1000.0)
            first = call_first_token.get(call_id)
            ttft_ms = max(0.0, (first - started) * 1000.0) if first else None
            started_at = (
                finished_at - timedelta(seconds=duration_ms / 1000.0)
                if duration_ms > 0
                else finished_at
            )
            self.store.upsert_span(
                AgentSpan(
                    span_id=f"span_{uuid.uuid4().hex}",
                    run_id=run_id,
                    kind="model",
                    name=model_name,
                    status="completed",
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    ttft_ms=ttft_ms,
                    input_tokens=tokens[0],
                    output_tokens=tokens[1],
                    cached_input_tokens=tokens[2],
                    cache_creation_input_tokens=0,
                    data={"model_call_id": call_id},
                )
            )


    def _persist_question(
        self, run_id: str, thread_id: str, signal: RuntimeSignal
    ) -> None:
        """持久化挂起问题并转入 WAITING_CONFIRMATION（非终态，等待用户回复）。"""
        payload = (signal.data or {}).get("interrupt") or {}
        question = PendingQuestion(
            question_id=f"q_{uuid.uuid4().hex}",
            run_id=run_id,
            thread_id=thread_id,
            tool_call_id=payload.get("tool_call_id"),
            question=str(payload.get("question") or "")[:2_000],
            options=[str(option)[:120] for option in (payload.get("options") or [])][:5],
            required=bool(payload.get("required", True)),
        )
        self.store.save_pending_question_and_transition(
            question,
            message="Waiting for the user to answer a question.",
            data={"question_id": question.question_id},
        )


    def _open_stream_resume(
        self,
        adapter: Any,
        thread_id: str,
        context: WikiAgentContext,
        *,
        answers: list[str],
        run_id: str,
        checkpoint_id: str | None,
    ) -> Any:
        """以用户答案续跑：graph adapter 用 Command(resume)，协议 adapter 用 execute(resume=)。

        ADR-0010 决策 2/3：续跑段在该 run 自己的作用域键上、从记录的 checkpoint
        继续，不重放 transcript。决策 4 的显式拒绝在 ``answer_question`` 里、
        早于任何状态变更，因此到这里 ``checkpoint_id`` 对图 adapter 必定非空。
        """
        if hasattr(adapter, "execute"):
            return adapter.execute(
                thread_id=thread_id,
                message=None,
                context=context,
                resume=answers,
            )
        from langgraph.types import Command

        return adapter.stream(
            Command(resume={"answers": answers}),
            config={
                "configurable": {
                    "thread_id": checkpoint_state_key(thread_id, run_id),
                    "checkpoint_id": checkpoint_id,
                }
            },
            context=context,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        )


    def answer_question(
        self, run_id: str, answers: object, *, timed_out: bool = False
    ) -> dict[str, Any]:
        """回复挂起问题并续跑（5+1：string | array）；timed_out 则按超时收尾。"""
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        if run.status != AgentRunStatus.WAITING_CONFIRMATION:
            raise InvalidRunTransitionError(
                f"run {run_id} is not waiting for a question ({run.status.value})"
            )
        question = self.store.get_open_question(run_id)
        if question is None:
            raise ValueError(f"run {run_id} has no open question")
        if isinstance(answers, str):
            answers_list = [str(answers).strip()[:2_000]]
        elif answers is None:
            answers_list = []
        else:
            answers_list = [
                str(item).strip()[:2_000]
                for item in cast(Iterable[Any], answers)
            ]
        if question.get("required") and not answers_list:
            raise ValueError("required question needs at least one answer")
        if timed_out:
            self.store.answer_question(run_id, [], timed_out=True)
            self._finalize_unfinished(run_id, AgentErrorType.TIMEOUT, "question timed out")
            return self.store.get_run(run_id).model_dump(mode="json")  # type: ignore[union-attr]
        adapter = self.adapter or self._built_adapter or _instantiate_agent(self.project_root)
        self._built_adapter = adapter
        # ADR-0010 决策 4：图 adapter 的续跑依赖该 run 自己的 checkpoint。升级前
        # 产生的 run 一律 checkpoint_id=NULL，必须在登记答案与转 RUNNING 之前显式
        # 失败，否则 run 会停在 RUNNING 而没有执行者。协议型 adapter 没有图状态。
        checkpoint_id = run.checkpoint_id
        if not hasattr(adapter, "execute"):
            if not checkpoint_id:
                # run 是在流里转成 WAITING_CONFIRMATION 的，回写发生在流关闭时；
                # 作答够快就会读到还没落盘的字段，因此拒绝前先向载体复核一次。
                checkpoint_id = latest_checkpoint_id(adapter, run.thread_id, run_id)
            if not checkpoint_id:
                raise CheckpointMissingError(
                    f"run {run_id} has no checkpoint; resend the message to start a new run"
                )
        self.store.answer_question(run_id, answers_list)
        self.store.transition(
            run_id, AgentRunStatus.RUNNING, message="Answer received. Resuming the run."
        )
        thread_id = run.thread_id
        context = self._context_for_run(run)
        with self._thread_lock:
            self._running_run_id = run_id
        set_attachment_resolver(
            lambda attachment_id: self.resolve_attachment_path(thread_id, attachment_id)
        )
        try:
            stream = self._open_stream_resume(
                adapter,
                thread_id,
                context,
                answers=answers_list,
                run_id=run_id,
                checkpoint_id=checkpoint_id,
            )
            seen: set[tuple[str, AgentEventType]] = set()
            # 决策 8：墙钟预算跨段累计——续跑段继承已消耗的时间，而不是重新计时，
            # "崩溃恢复继承剩余预算"因此可测。
            outcome = self._consume_stream(
                run_id,
                thread_id,
                stream,
                run.budget,
                started_at=time.monotonic() - run.usage.elapsed_seconds,
                seen=seen,
                adapter=adapter,
            )
            if outcome.question_pending:
                return self.store.get_run(run_id).model_dump(mode="json")  # type: ignore[union-attr]
            self._finalize_stream_outcome(run_id, thread_id, outcome)
            try:
                self._maybe_publish_pending_diff(run_id)
            except (GitCommandError, OSError):
                pass
        except _RunTimeoutError as error:
            self._finalize_unfinished(run_id, AgentErrorType.TIMEOUT, str(error))
        except AgentBudgetExceeded as error:
            self._finalize_unfinished(run_id, AgentErrorType.BUDGET, str(error))
        except InvalidRunTransitionError:
            raise
        except Exception as error:
            self.store.append_event(
                run_id,
                AgentEventType.ERROR,
                message=f"Resume failed: {error}",
            )
            self._finalize_unfinished(run_id, AgentErrorType.SYSTEM, str(error))
        finally:
            self._persist_run_checkpoint(run_id, run.thread_id)
            clear_attachment_resolver()
            with self._thread_lock:
                if self._running_run_id == run_id:
                    self._running_run_id = None
                self._cancellations.pop(run_id, None)
        return self.store.get_run(run_id).model_dump(mode="json")  # type: ignore[union-attr]


    def _iterate_safe(
        self,
        stream: Iterable[Any],
        budget: RunBudget,
        started_at: float,
        on_finish: Callable[[], None] | None = None,
    ) -> Generator[tuple[str, list[RuntimeSignal], int], None, None]:
        """Bound the stream, then run ``on_finish`` as iteration unwinds.

        The ``finally`` is the caller's accounting hook for the abort paths: a
        budget/timeout raise skips everything after the consumer's loop. On a
        plain ``break`` the generator is only closed at collection time, so the
        consumer must flush explicitly too -- hence the caller's once-guard.

        返回 Generator 而不是 Iterable：调用方必须能 ``close()`` 它。挂起段是从
        循环里 break 出去的，不显式关闭就要等 GC，那时 checkpoint 还没落盘，
        决策 4 的回写与其后的续跑都读不到（ADR-0010）。
        """
        try:
            yield from self._iterate_bounded(stream, budget, started_at)
        finally:
            if on_finish is not None:
                on_finish()

    def _iterate_bounded(
        self,
        stream: Iterable[Any],
        budget: RunBudget,
        started_at: float,
    ) -> Iterable[tuple[str, list[RuntimeSignal], int]]:
        """Bound the stream by model-call budget and wall-clock timeout."""
        model_calls = 0
        seen_model_call_ids: set[str] = set()
        for item in stream:
            if time.monotonic() - started_at > max(
                budget.max_runtime_seconds, MAX_RUN_SECONDS_FLOOR
            ):
                raise _RunTimeoutError(
                    "run exceeded the wall-clock budget and was interrupted"
                )
            signals = (
                [item]
                if isinstance(item, RuntimeSignal)
                else _signals_from_stream_item(item)
            )
            if not signals:
                continue
            # Count one logical model response, not every streamed text chunk.
            model_ids = {
                signal.model_call_id
                for signal in signals
                if signal.model_call_id
                and signal.type in {
                    AgentEventType.MESSAGE_DELTA,
                    AgentEventType.REASONING_DELTA,
                    AgentEventType.TOOL_STARTED,
                    AgentEventType.FINAL_RESPONSE,
                }
            }
            new_model_ids = model_ids - seen_model_call_ids
            if model_ids:
                seen_model_call_ids.update(new_model_ids)
                model_calls += len(new_model_ids)
            elif not all(
                signal.type in {
                    AgentEventType.TOOL_COMPLETED,
                    AgentEventType.TASK_CONFIRMATION_REQUIRED,
                }
                for signal in signals
            ):
                # Protocol adapters may not expose a model id; retain a safe
                # one-signal fallback for those adapters.
                model_calls += 1
            if model_calls > budget.max_model_calls:
                raise AgentBudgetExceeded(
                    f"run exceeded the model-call budget ({budget.max_model_calls})"
                )
            yield ("agent", signals, model_calls)

    # ---- 终结 ----
    def _finalize_unfinished(
        self, run_id: str, error_type: AgentErrorType, message: str
    ) -> AgentRun:

        # transition 一次写入状态 + 错误字段 + finished_at：任何时刻读到
        # UNFINISHED 的行都带完整信息；没有后续覆盖写，resume（claim）不会被
        # 迟到的写回退。
        run = self.store.transition(
            run_id,
            AgentRunStatus.UNFINISHED,
            error_type=error_type,
            error_message=message[:2000],
            message=f"Run paused: {message}. Resume to continue.",
            data={"reason": "budget_or_timeout"},
            finished_at=datetime.now(UTC),
        )
        self._maintain_unfinished(run)
        return run

    def _finish_failed(self, run_id: str, error: Exception) -> AgentRun:
        # 僵尸 worker 防改写：运行已被恢复/终结时不再落盘 FAILED
        current = self.store.get_run(run_id)
        if current.status not in {
            AgentRunStatus.RUNNING,
            AgentRunStatus.RETRYING,
        }:
            return current
        error_type = classify_agent_error(error)
        return self.store.finalize_run(
            run_id,
            AgentRunOutcome(
                status=AgentRunStatus.FAILED,
                message=str(error)[:2000],
                error_type=error_type,
                error_message=str(error)[:2000],
            ),
        )

    # ---- pending diff 发布（审批单元 = 一行一次判定）----
    def _unit_id(self, run_id: str, index: int) -> str:
        return f"diff_{run_id}_{index}"

    def _resolve_publish_target(
        self, run: AgentRun
    ) -> tuple[str, int, str | None]:
        """Return (diff_id, unit_index, baseline_commit) for the next publish.

        审批单元边界 = 判定，不是发布：最新单元仍未判定时复用它的行（就地刷新，
        基线不变）；已判定（或尚无任何单元）时新建序号 +1 的单元，基线取上一单元
        head。旧库中无序号的 ``diff_<run_id>`` 视为单元 1，不重编号。
        """
        units = sorted(
            self.store.list_pending_diffs(run_id=run.run_id, limit=500),
            key=lambda d: d.created_at,
        )
        if units:
            latest = units[-1]
            if latest.status == PendingDiffStatus.PENDING:
                index = self._unit_index(latest.diff_id, run.run_id, len(units))
                return latest.diff_id, index, latest.snapshot_commit
            last_index = self._unit_index(latest.diff_id, run.run_id, len(units))
            return (
                self._unit_id(run.run_id, last_index + 1),
                last_index + 1,
                latest.head_commit,
            )
        return self._unit_id(run.run_id, 1), 1, run.snapshot_commit

    def _unit_index(self, diff_id: str, run_id: str, fallback: int) -> int:
        """Parse the unit index from a diff id; legacy suffix-less rows are unit 1."""
        prefix = f"diff_{run_id}_"
        if diff_id.startswith(prefix) and diff_id[len(prefix):].isdigit():
            return int(diff_id[len(prefix):])
        if diff_id == f"diff_{run_id}":
            return 1
        return fallback

    def _resolved_revert_commits(self, run_id: str) -> frozenset[str]:
        """Revert commits produced by rejecting earlier units of this run.

        拒绝单元 N 会生成一串新 commit；它们物理上位于单元 N+1 的基线之后，
        但既不是 Agent 内容也不是系统维护提交，必须从后续单元的审批范围里排除，
        否则"拒绝单元 2"会把"拒绝单元 1 的回滚"再次回滚。
        """
        shas: set[str] = set()
        for diff in self.store.list_pending_diffs(run_id=run_id, limit=500):
            if diff.status == PendingDiffStatus.PENDING:
                continue
            recorded = diff.data.get("revert_commits") if isinstance(diff.data, dict) else None
            if isinstance(recorded, list):
                shas.update(str(item) for item in recorded)
        return frozenset(shas)

    def _maybe_publish_pending_diff(self, run_id: str) -> bool:
        """Collect the run's newest commits into the current pending unit.

        Returns True when a pending diff was published or refreshed. System
        maintenance commits and earlier units' revert commits are excluded from
        both the commit list and the review patch.
        """
        run = self.store.get_run(run_id)
        if run is None:
            return False
        git = self._git_executor()
        if git is None:
            return False
        diff_id, _index, baseline = self._resolve_publish_target(run)
        try:
            # baseline 为 None = 工作区当时尚无提交：取该范围内产出的 commit(s)
            commits = git.commits_since(baseline)
        except GitCommandError:
            return False
        if not commits:
            return False
        # 系统维护 commit（chore(system): maintenance ...）不属于任何 Agent
        # run：commit 列表与审查补丁都要排除，避免接受/拒绝时误伤审计记录。
        reverted = self._resolved_revert_commits(run.run_id)
        agent_commits = [
            sha
            for sha in commits
            if sha not in reverted
            and not self._is_system_maintenance_commit(git, sha)
        ]
        if not agent_commits:
            return False
        head = agent_commits[0]
        refs = frozenset({head})
        if baseline is not None:
            refs = frozenset({baseline, head})
        diff = git.diff_between(
            baseline,
            right=head,
            enabled_refs=refs,
            exclude_paths=("overview.md", "statistics.md", "log.md", "audit_report.md"),
        )
        existing: PendingDiff | None = None
        try:
            candidate = self.store.get_pending_diff(diff_id)
            if candidate.status == PendingDiffStatus.PENDING:
                existing = candidate
        except KeyError:
            pass
        pending = PendingDiff(
            diff_id=diff_id,
            run_id=run.run_id,
            thread_id=run.thread_id,
            project_id=run.project_id,
            snapshot_commit=baseline,
            head_commit=head,
            commits=agent_commits,
            files=diff.files,
            insertions=diff.insertions,
            deletions=diff.deletions,
            # 同一 pending 单元在 question 挂起与续跑之间会被就地刷新多次；
            # data 里此前的维护标记（若有）必须活过刷新，否则重试线索丢失。
            data=existing.data if existing is not None else {},
        )
        self.store.save_pending_diff(pending)
        self.store.update_run(
            run.model_copy(update={"pending_diff_id": pending.diff_id})
        )
        return True

    # ---- 系统维护（ADR-0009：判定时维护 + 系统维护 commit）----
    def _run_maintenance(self, verdict: str, diff: PendingDiff) -> None:
        """Post-verdict maintenance for accept/reject; failures never block it."""
        if self._git_executor() is None:
            return
        with self._maintenance_lock:
            self._run_maintenance_locked(verdict, diff)

    def _run_maintenance_locked(self, verdict: str, diff: PendingDiff) -> None:
        parent_run_id = None
        try:
            run = self.store.get_run(diff.run_id)
            parent_run_id = run.parent_run_id
        except KeyError:
            pass
        try:
            if verdict == "accept":
                outcome = maintain_after_accept(
                    self.project_root,
                    run_id=diff.run_id,
                    parent_run_id=parent_run_id,
                    diff=diff,
                )
            else:
                outcome = maintain_after_reject(
                    self.project_root,
                    run_id=diff.run_id,
                    parent_run_id=parent_run_id,
                    diff=diff,
                )
        except Exception as error:  # noqa: BLE001 - 维护失败必须记录并留待重试
            self._mark_maintenance_failure(diff, verdict, error)
            return
        warning = take_maintenance_warning()
        try:
            marker: dict[str, Any] = {
                "status": "ok",
                "verdict": verdict,
                "commit": outcome.commit_sha,
            }
            if warning:
                # 方案 D：外来暂存不再中止维护，但必须可见——用户需要知道
                # 自己的 staged 文件没有被系统动过。
                marker["foreign_staged"] = warning[:20]
            self.store.update_pending_diff(
                diff.diff_id,
                status=diff.status,
                resolution=diff.resolution,
                data={"maintenance": marker},
            )
        except Exception:
            pass
        self._record_maintenance_event(
            diff.run_id,
            verdict,
            diff_id=diff.diff_id,
            commit=outcome.commit_sha,
            foreign_staged=warning,
        )

    def _mark_maintenance_failure(
        self, diff: PendingDiff, verdict: str, error: Exception
    ) -> None:
        try:
            self.store.update_pending_diff(
                diff.diff_id,
                status=diff.status,
                resolution=diff.resolution,
                data={
                    "maintenance": {
                        "status": "failed",
                        "verdict": verdict,
                        "error": str(error)[:500],
                    }
                },
            )
        except Exception:
            pass
        self._record_maintenance_event(
            diff.run_id, verdict, diff_id=diff.diff_id, error=error
        )

    def _maintain_unfinished(self, run: AgentRun) -> None:
        if self._git_executor() is None:
            return
        with self._maintenance_lock:
            self._maintain_unfinished_locked(run)

    def _maintain_unfinished_locked(self, run: AgentRun) -> None:
        try:
            outcome = maintain_after_unfinished(
                self.project_root,
                run_id=run.run_id,
                parent_run_id=run.parent_run_id,
                reason=str(run.error_message or run.error_type or "unfinished")[:200],
            )
        except Exception as error:  # noqa: BLE001
            self._record_maintenance_event(run.run_id, "unfinished", error=error)
            return
        self._record_maintenance_event(
            run.run_id, "unfinished", commit=outcome.commit_sha
        )

    def _forced_lint_audit(self, run_id: str) -> None:
        """Run-end forced lint snapshot appended to audit_report.md (record only)."""
        if self._git_executor() is None:
            return
        with self._maintenance_lock:
            self._forced_lint_audit_locked(run_id)

    def _forced_lint_audit_locked(self, run_id: str) -> None:
        try:
            run = self.store.get_run(run_id)
        except KeyError:
            return
        try:
            report = inspect_projection(self.project_root)
            outcome = maintain_after_lint(
                self.project_root,
                run_id=run_id,
                parent_run_id=run.parent_run_id,
                report=report,
            )
        except Exception as error:  # noqa: BLE001
            self._record_maintenance_event(run_id, "lint", error=error)
            return
        self._record_maintenance_event(run_id, "lint", commit=outcome.commit_sha)

    def _record_maintenance_event(
        self,
        run_id: str,
        verdict: str,
        *,
        diff_id: str | None = None,
        commit: str | None = None,
        error: Exception | None = None,
        foreign_staged: list[str] | None = None,
    ) -> None:
        """Append a maintenance outcome event even after the run is terminal."""
        try:
            if error is not None:
                self.store.append_event(
                    run_id,
                    AgentEventType.PROGRESS,
                    message="Workspace maintenance failed; will retry on next run start.",
                    data={
                        "kind": "maintenance_failed",
                        "verdict": verdict,
                        "diff_id": diff_id,
                        "error": str(error)[:500],
                    },
                    allow_terminal=True,
                )
            else:
                message = "Workspace maintenance applied."
                data: dict[str, Any] = {
                    "kind": "maintenance",
                    "verdict": verdict,
                    "diff_id": diff_id,
                    "commit": commit,
                }
                if foreign_staged:
                    # 可执行提示：外来暂存文件没有被系统提交，也不会被动过；
                    # 用户若不希望保留，需自行 unstage（系统不代替用户清 index）。
                    listing = ", ".join(sorted(foreign_staged)[:10])
                    suffix = (
                        ""
                        if len(foreign_staged) <= 10
                        else f" (+{len(foreign_staged) - 10} more)"
                    )
                    message = (
                        "Workspace maintenance applied; unrelated staged changes "
                        f"were left out of the system commit: {listing}{suffix}."
                    )
                    data["foreign_staged"] = sorted(foreign_staged)[:20]
                self.store.append_event(
                    run_id,
                    AgentEventType.PROGRESS,
                    message=message,
                    data=data,
                    allow_terminal=True,
                )
        except Exception:
            pass

    def _is_system_maintenance_commit(self, git: GitExecutor, sha: str) -> bool:
        """True when a commit subject matches the system maintenance prefix."""
        try:
            line = git.run("log", "--oneline", "-1", sha).strip()
        except GitCommandError:
            return False
        if " " not in line:
            return False
        return line.split(" ", 1)[1].startswith(MAINTENANCE_COMMIT_PREFIX)

    def _retry_failed_maintenance(self) -> None:
        """Best-effort retry of failed accept/reject maintenance at run start."""
        if self._git_executor() is None:
            return
        for diff in self.store.list_pending_diffs(limit=50):
            marker = diff.data.get("maintenance") if isinstance(diff.data, dict) else None
            if not isinstance(marker, dict) or marker.get("status") != "failed":
                continue
            verdict = marker.get("verdict")
            if verdict not in {"accept", "reject"}:
                continue
            try:
                self._run_maintenance(verdict, diff)
            except Exception:
                continue

    # ---- 内部工具 ----
    def _ensure_single_active_run(self) -> AgentRun | None:
        active_statuses = {
            AgentRunStatus.QUEUED,
            AgentRunStatus.RUNNING,
            AgentRunStatus.RETRYING,
            AgentRunStatus.UNFINISHED,
            AgentRunStatus.CANCELLING,
            AgentRunStatus.WAITING_CONFIRMATION,
        }
        for run in self.store.list_runs(limit=10_000):
            if run.status in active_statuses:
                return run
        return None

    def _claim_and_submit(
        self, run_id: str, status: AgentRunStatus, reason: str
    ) -> AgentRun:
        current = self._ensure_single_active_run()
        if current is not None and current.run_id != run_id:
            raise AgentRunInProgressError(
                f"another agent run is active: {current.run_id}"
            )
        if status == AgentRunStatus.RETRYING:
            claimed = self.store.claim_retry(run_id)
        else:
            raise InvalidRunTransitionError(f"unsupported claim status: {status}")
        with self._thread_lock:
            self._cancellations[run_id] = _CancellationGate()
        self._executor.submit(
            self._execute,
            claimed.run_id,
            claimed.thread_id,
            claimed.input_message,
            self._context_for_run(claimed),
            claimed.budget,
        )
        return claimed

    def _open_stream(
        self,
        adapter: Any,
        thread_id: str,
        messages_in: list[dict[str, Any]],
        context: WikiAgentContext,
        *,
        run_id: str,
    ) -> Any:
        """Normalize adapters: protocol objects (execute) or LangGraph graphs (stream)."""
        if hasattr(adapter, "execute"):
            # 协议型 adapter 没有图状态，继续用会话键。
            return adapter.execute(
                thread_id=thread_id, message=messages_in, context=context
            )
        # build_wiki_agent 返回的编译图：stream_mode=["messages","updates"]，
        # 输出交给 _signals_from_stream_item 归一化；输入必须是 dict 形状。
        # ADR-0010 决策 2：图状态键是 run 作用域的，add_messages 不再跨 run 叠加。
        graph_input: Any = {"messages": messages_in}
        return adapter.stream(
            graph_input,
            config={
                "configurable": {
                    "thread_id": checkpoint_state_key(thread_id, run_id)
                }
            },
            # build_wiki_agent 声明了 context_schema=WikiAgentContext：图这一侧
            # 也得拿到同一份 run 上下文，否则只有协议型 adapter 看得见它。
            context=context,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        )

    def _open_stream_continue(
        self,
        adapter: Any,
        thread_id: str,
        message: str,
        context: WikiAgentContext,
        *,
        run_id: str,
    ) -> Any:
        """ADR-0010 决策 3/6：从该 run 的 checkpoint 续跑，不重放 transcript。

        图 adapter 用 ``None`` 输入在自己的作用域键上继续；协议型 adapter 没有图
        状态，只能按原输入重新执行（调用方已保证不会重复落用户消息）。
        """
        if hasattr(adapter, "execute"):
            return adapter.execute(
                thread_id=thread_id, message=message, context=context
            )
        return adapter.stream(
            None,
            config={
                "configurable": {
                    "thread_id": checkpoint_state_key(thread_id, run_id)
                }
            },
            context=context,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        )

    def propose_workspace_edit(self, path: str, content: str) -> AgentRun:
        """APP 受控编辑：合成 workspace_edit run，写入文件、提交并生成 pending diff。

        接受后保留提交，拒绝后由现有 revert 语义回滚该次编辑。
        """
        from cellwiki.services.path_guard import PathGuardError, validate_workspace_path

        if len(content) > 400_000:
            raise ValueError("content exceeds the 400000-char edit limit")
        try:
            target = validate_workspace_path(self.project_root, path)
        except PathGuardError as error:
            raise ValueError(str(error)) from None
        if not target.is_file():
            raise ValueError(f"file does not exist: {path}")
        if target.suffix.lower() not in {".md", ".txt"}:
            raise ValueError("only .md and .txt files can be edited")
        active = self._ensure_single_active_run()
        if active is not None:
            raise AgentRunInProgressError(f"another agent run is active: {active.run_id}")
        pending = [
            diff
            for diff in self.store.list_pending_diffs(limit=50)
            if diff.status == PendingDiffStatus.PENDING
        ]
        if pending:
            raise AgentRunInProgressError(f"a pending diff requires review before an edit: {pending[0].diff_id}")
        thread_id = "thread_workspace_edits"
        self.store.create_thread(thread_id)
        run = AgentRun(
            run_id=_new_run_id(),
            thread_id=thread_id,
            project_id="cellwiki",
            status=AgentRunStatus.QUEUED,
            input_message=f"workspace edit: {path}",
            snapshot_commit=self._git_snapshot(),
            task_kind="workspace_edit",
            model_role="system",
            budget=RunBudget(),
            created_at=datetime.now(UTC),
        )
        self.store.create_run(run)
        self.store.transition(run.run_id, AgentRunStatus.RUNNING, message="Applying workspace edit.")
        try:
            target.write_text(content, encoding="utf-8")
            git = self._git_executor()
            if git is None:
                raise ValueError("workspace is not a git repository")
            git.run("add", target.relative_to(self.project_root).as_posix())
            git.run("commit", "-m", f"workspace edit: {path}")
            if self._maybe_publish_pending_diff(run.run_id):
                self._forced_lint_audit(run.run_id)
        except Exception as error:
            self.store.finalize_run(
                run.run_id,
                AgentRunOutcome(
                    status=AgentRunStatus.FAILED,
                    message=str(error)[:500],
                    error_type=AgentErrorType.SYSTEM,
                    error_message=str(error)[:2000],
                ),
            )
            raise
        self.store.finalize_run(
            run.run_id,
            AgentRunOutcome(
                status=AgentRunStatus.SUCCEEDED,
                message="Edit staged for approval.",
            ),
        )
        return self.store.get_run(run.run_id)

    def _attachment_manifest(self, run: AgentRun) -> list[dict[str, Any]]:
        """Build the run-scoped attachment manifest injected into Layer B."""
        records = {item["attachment_id"]: item for item in self.store.list_attachments(run.thread_id)}
        manifest: list[dict[str, Any]] = []
        for attachment_id in dict.fromkeys(run.attachment_ids):
            record = records.get(attachment_id)
            if not record:
                continue
            manifest.append(
                {
                    "attachment_id": attachment_id,
                    "original_name": record.get("original_name"),
                    "media_type": record.get("media_type"),
                    "size_bytes": record.get("size_bytes"),
                    "text_available": bool(record.get("text_available")),
                    "est_tokens": int(record.get("est_tokens") or 0),
                    "path": record.get("path"),
                    "extracted_path": record.get("extracted_path"),
                    "preview": record.get("preview"),
                }
            )
        return manifest

    def resolve_attachment_path(self, thread_id: str, attachment_id: str) -> Path | None:
        """Resolve one thread-scoped attachment file; None when not owned by the thread."""
        if self.store.get_attachment(thread_id, attachment_id) is None:
            return None
        return AttachmentFileStore(self.project_root).path_for(thread_id, attachment_id)

    def _git_status_text(self) -> str | None:
        """Short git status for Layer B / R1 (guarded; empty workspace tolerated)."""
        if not self.project_root.exists():
            return None
        try:
            from cellwiki.services.workspace import ensure_workspace

            ensure_workspace(self.project_root)
            status = GitExecutor(self.project_root).run("status", "--short")
            return (status or "")[:1_500] or None
        except Exception:
            return None

    def _open_page_snapshot(self, page_id: str | None) -> dict | None:
        """Layer B：打开页面仅取元数据 + 大纲（不注入整页内容）。"""
        if not page_id:
            return None
        try:
            from cellwiki.api.reader import WikiReader

            return WikiReader(self.project_root).read_page(page_id)
        except Exception:
            return None

    def _git_snapshot(self) -> str | None:
        git = self._git_executor()
        if git is None:
            return None
        try:
            return git.current_head() if git.has_commits() else None
        except GitCommandError:
            return None

    def _git_executor(self) -> GitExecutor | None:
        if self._git is None:
            if not (self.project_root / ".git").exists():
                return None
            self._git = GitExecutor(self.project_root)
        return self._git

    def close(self) -> None:
        self._executor.shutdown(wait=True)
        if self.adapter is not None and hasattr(self.adapter, "close"):
            self.adapter.close()


def _new_run_id() -> str:
    return f"run_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _instantiate_agent(project_root: Path) -> Any:
    """System-owned lazy agent instantiation (kept for tests and sidecars)."""
    return build_wiki_agent(project_root)