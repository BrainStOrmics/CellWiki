# =============================================================================
# Prompt 分层与会话上下文（阶段 5）
# =============================================================================
# Layer A 静态基线：身份/操作域、权力边界、行为约束；每次 run 固定，不进会话历史。
# Layer B run 动态上下文：git 状态、会话历史、当前消息、挂起问题、用户当前打开
#   的页面（仅元数据 + 大纲）—— run 启动时快照注入为系统消息。
# Layer C 按需注入：文件内容 / git diff / lint 报告 / run_powershell 输出由工具
#   返回（不在启动时静态注入）。
# 会话历史上限 512K，压缩阈值 80%，保留窗口 32K，压缩后注入 R1-R5；六类摘要。
# 模型声明窗口 < 上限时启动期非阻断 warning。
# =============================================================================

"""Phase 5 prompt layering: Layer A/B/C, bounded compaction, R1-R5, six summaries."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 估算量：1 token ≈ 4 字符（英文为主的知识库文本的常用粗估）
CHARS_PER_TOKEN = 4

# 六类摘要标签（确定性抽取，不依赖额外 LLM 调用）
_SUMMARY_CATEGORIES: dict[str, tuple[str, ...]] = {
    "decisions": ("决策", "决定", "decision", "approved", "accepted", "采纳"),
    "files": ("文件", "路径", "path", "file", "wiki/", "docs/"),
    "preferences": ("偏好", "prefer", "always", "总是", "不要", "never"),
    "unfinished": ("未完成", "unfinished", "待办", "还需要", "继续", "下一步"),
    "pending_questions": ("待确认", "?", "问题", "question", "请确认"),
    "corrections": ("纠正", "更正", "修正", "correction", "错误", "errata"),
}

# 已知模型声明窗口（token）。未知模型返回 None -> 不告警。
_KNOWN_MODEL_WINDOWS: tuple[tuple[str, int], ...] = (
    ("gpt-4o", 128_000),
    ("gpt-4.1", 1_000_000),
    ("gpt-4-turbo", 128_000),
    ("gpt-4", 128_000),
    ("gpt-3.5", 16_385),
    ("deepseek-chat", 65_536),
    ("deepseek-reasoner", 128_000),
    ("deepseek-v3", 65_536),
    ("deepseek-v4", 128_000),
    ("qwen2.5", 131_072),
    ("qwen3", 131_072),
)

# Layer A：静态基线（app.py 的 SYSTEM_PROMPT 来自这里）
LAYER_A_TEXT = """You are the Model-led CellWiki coordinator for one selected
knowledge-base workspace.

Every natural-language request enters this coordinator. Decide what the user is
trying to accomplish, make a short internal plan, and call only the visible
CellWiki tools needed for that plan.

- Inspect the workspace: use ls, glob and grep to find files, and read_file to
  read any UTF-8 text file inside the workspace (paths are workspace-relative).
- Edit knowledge: use write_file for new content and edit_file for precise
  replacements; delete_file and rename_file move single files. Writes apply
  inside the workspace immediately; the runtime versions every change in git
  and presents the whole run as a pending diff for the user to accept or
  reject - never push or rewrite history yourself.
- Version: use the git tool with only status/diff/log/add/commit/revert.
  Commit each logical change with a short -m message.
- Diagnose the runtime: run_powershell executes read-only Get-* commands only.
- Run lint_knowledge_base for the deterministic quality report; it is read-only.
- Ask the user with ask_user_question when a choice must be confirmed; the run
  pauses until the user answers (up to 5 fixed options plus free text).
- Read uploaded attachments with read_attachment (thread-scoped, temporary
  Agent context; never register them as governed pages).
- Finish with submit_agent_answer: a plain-text answer plus the
  workspace-relative file paths you referenced. Ground scientific claims in
  the files you actually read, identify missing evidence, and never invent
  citations.

Never call generic filesystem or shell tools beyond the whitelist; use only
the visible CellWiki tools. Answer in the user's language.
"""


def estimate_tokens(text: str) -> int:
    """Rough token estimate (en/zh mixed markdown): chars / 4."""
    return max(0, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def resolve_declared_window(model_name: str | None) -> int | None:
    """Return the known declared context window for a model name, else None."""
    lowered = (model_name or "").lower()
    for marker, window in _KNOWN_MODEL_WINDOWS:
        if marker in lowered:
            return window
    return None


def warn_if_narrow_window(
    model_name: str | None,
    configured_max_tokens: int,
    *,
    emit: Callable[[str], None] = lambda text: logger.warning(text),
) -> bool:
    """非阻断告警：模型声明窗口小于配置上限时记录 warning，不改变行为。"""
    declared = resolve_declared_window(model_name)
    if declared is not None and declared < configured_max_tokens:
        emit(
            "model window is below AGENT_CONTEXT_MAX_TOKENS: declared "
            f"{declared} < configured {configured_max_tokens}; compaction will "
            "keep the session within the model window."
        )
        return True
    return False


def _page_outline(markdown: str, max_headings: int = 24) -> list[str]:
    """Only metadata + heading outline (Layer B keeps page context small)."""
    outline: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            outline.append(f"{'#' * level} {stripped.lstrip('#').strip()}")
            if len(outline) >= max_headings:
                break
    return outline


def build_layer_b_snapshot(
    *,
    current_message: str,
    git_status: str | None = None,
    open_page: dict[str, Any] | None = None,
    pending_question: str | None = None,
    recent_transcript: list[dict[str, str]] | None = None,
    limit_transcript: int = 6,
) -> str:
    """Layer B：run 启动时快照的 run 动态上下文（纯文本、紧凑、不泄露原始内容）。"""
    parts: list[str] = ["## Run context snapshot"]
    if git_status is not None:
        parts.append(f"- git status:\n{git_status[:1_500]}")
    if open_page is not None:
        page_id = open_page.get("page_id") or open_page.get("title") or "?"
        parts.append(f"- user is viewing: {page_id}")
        outline = _page_outline(str(open_page.get("markdown") or ""))
        if outline:
            parts.append("- page outline:\n" + "\n".join(outline[:16]))
    if pending_question is not None:
        parts.append(f"- pending question: {pending_question[:500]}")
    if recent_transcript:
        transcript_lines = [
            f"  {item.get('role', '?')}: {str(item.get('content') or '')[:220].replace(chr(10), ' ')}"
            for item in recent_transcript[-limit_transcript:]
        ]
        parts.append("- recent transcript:\n" + "\n".join(transcript_lines))
    parts.append(f"- current run goal: {current_message[:800]}")
    snapshot = "\n".join(parts)
    return snapshot[:8_000]


# 归类的优先级：模糊关键词重叠时（如“继续”同时是 unfinished 标记）优先更具体的类别
_CATEGORY_PRIORITY: tuple[str, ...] = (
    "pending_questions",
    "corrections",
    "decisions",
    "unfinished",
    "preferences",
    "files",
)


def _six_category_summary(excerpts: list[str]) -> str:
    """确定性抽取：按六类关键词将过期 transcript 归类总结。"""
    buckets: dict[str, list[str]] = {category: [] for category in _SUMMARY_CATEGORIES}
    for excerpt in excerpts:
        lowered = excerpt.lower()
        for category in _CATEGORY_PRIORITY:
            markers = _SUMMARY_CATEGORIES[category]
            if any(marker in lowered for marker in markers):
                buckets[category].append(excerpt.strip()[:260])
                break

    blocks: list[str] = []
    for category, items in buckets.items():
        if not items:
            continue
        blocks.append(f"{category}:\n" + "\n".join(f"- {item}" for item in items[:8]))
    if not blocks:
        return ""
    return "## Compacted history summary\n" + "\n".join(blocks)


@dataclass
class CompactedContext:
    """Result of one compaction pass over a durable transcript."""

    summary_text: str = ""
    retained: list[dict[str, str]] = field(default_factory=list)
    compacted: bool = False


def compact_transcript(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 512_000,
    auto_compact_ratio: float = 0.8,
    retained_tokens: int = 32_768,
) -> CompactedContext:
    """Compress an over-budget transcript into six-category summary + retained window."""
    total_chars = sum(len(str(item.get("content") or "")) for item in messages)
    threshold_chars = int(max_tokens * auto_compact_ratio) * CHARS_PER_TOKEN
    if total_chars <= threshold_chars:
        return CompactedContext(retained=messages, compacted=False)
    retained_chars = retained_tokens * CHARS_PER_TOKEN
    summary_excerpts: list[str] = []
    retained: list[dict[str, str]] = []
    used_chars = 0
    for item in reversed(messages):
        content_text = str(item.get("content") or "")
        if used_chars + len(content_text) <= retained_chars:
            retained.append(item)
            used_chars += len(content_text)
        else:
            summary_excerpts.append(content_text)
    retained.reverse()
    summary = _six_category_summary(summary_excerpts)
    return CompactedContext(summary_text=summary, retained=retained, compacted=True)


def build_r1_r5_block(
    *,
    git_status: str | None = None,
    page_snapshot: str | None = None,
    pending_question: str | None = None,
    recent_lint: str | None = None,
    run_goal: str = "",
) -> str:
    """压缩后重新注入 R1-R5（git 状态、页面快照、挂起问题、最近 lint、当前目标）。"""
    blocks = [
        "## Recovery context",
        f"R1 (git status): {git_status or 'n/a'}"[:1_200],
        f"R2 (page snapshot): {page_snapshot or 'n/a'}"[:1_200],
        f"R3 (pending question): {pending_question or 'n/a'}"[:500],
        f"R4 (recent lint): {recent_lint or 'n/a'}"[:1_200],
        f"R5 (current run goal): {run_goal}"[:800],
    ]
    return "\n".join(blocks)


__all__ = [
    "CompactedContext",
    "LAYER_A_TEXT",
    "build_layer_b_snapshot",
    "build_r1_r5_block",
    "compact_transcript",
    "estimate_tokens",
    "resolve_declared_window",
    "warn_if_narrow_window",
]
