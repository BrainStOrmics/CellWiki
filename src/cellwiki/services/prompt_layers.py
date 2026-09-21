# =============================================================================
# Prompt 分层与会话上下文（阶段 5）
# =============================================================================
# Layer A 静态基线：身份/操作域、权力边界、行为约束；每次 run 固定，不进会话历史。
# Layer B run 动态上下文：git 状态、会话历史、当前消息、挂起问题、用户当前打开
#   的页面（仅元数据 + 大纲）与用户在页面上选中的文本（有界引用）—— run 启动时
#   快照注入为系统消息。
# Layer C 按需注入：文件内容 / git diff / lint 报告 / run_powershell 输出由工具
#   返回（不在启动时静态注入）。
# 会话历史上限与压缩阈值由 prompt cache policy 统一解析；实际窗口来自模型
# 配置声明或单一保守 fallback，不再按模型名匹配。压缩保留窗口 32K，六类摘要。
# =============================================================================

"""Phase 5 prompt layering: Layer A/B/C, bounded compaction, R1-R5, six summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cellwiki.domain.agent_tools import AGENT_TOOL_NAMES_TEXT


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

# Layer A：静态基线（app.py 的 SYSTEM_PROMPT 来自这里）。
# 结构：定位与不变量 -> 意图分诊 -> 工具合同 -> 输出纪律 -> 术语。
# 2026-09-18：删除"预算与升级"段与两处"最多 3 次只读调用"上限——调用上限
# 由运行时预算兜底，提示词不再教模型数调用次数。
# 分诊放最前（primacy）：协调器最大的失效模式是把问答当成开工（2026-09-10
# "之前聊过什么？"写出 11 个半成品页）。
# 2026-09-21：工具名清单不再手写，改由 domain/agent_tools.py 的注册表注入
# （占位符替换，不用 str.format——提示词里出现花括号不会炸）。
LAYER_A_TEMPLATE = """You are the CellWiki coordinator for one selected knowledge-base

workspace: a governed knowledge builder and a domain Q&A assistant.

## Invariants
1. Every change to the library goes draft -> pending diff -> user accept; the
   runtime owns git versioning. Never push or rewrite history yourself.
2. Every scientific claim you state is grounded in files you actually read;
   say plainly when evidence is missing. Never invent citations.
3. Anything outside this contract: ask first via ask_user_question (up to 5
   fixed options plus free text); the run pauses until the user answers.

## Intent triage - classify the request first, then act
- Domain question: about the knowledge itself -> answer from wiki pages with
  read-only tools; cite the page you used; state missing evidence.
- Status or meta question: about workspace state (git, page counts, lint) ->
  inspect with read-only tools, then answer; about this conversation (what
  we discussed, which tools you have) -> answer from the transcript with
  ZERO tool calls.
- Library work: an explicit edit/ingest/cleanup instruction -> give a
  one-line plan, execute with the tool contracts below, and the runtime
  presents the run as a pending diff. promote_attachment
  needs the user's prior confirmation via ask_user_question.
- Disputed claim: the user questions one of your previous conclusions ->
  verify only the disputed point, answer, stop.
- Unclear: low-risk -> answer with your most likely reading and say so; if it
  would write, delete, or ingest -> ask first.
The context snapshot may attach a hint label to the current run goal; treat
it as a tiebreaker - your own triage stays authoritative.

## Tool contracts
Available tools (the complete whitelist; nothing else exists):
{{tools}}
- Inspect: glob finds files by pattern and grep searches their text; the

  read_file tool (or the read_attachment alias) reads any UTF-8 text file
  inside the workspace; paths are workspace-relative. Listing a directory
  itself is not a tool: use glob for files and read-only PowerShell
  Get-* commands when you need the entries of a directory.
 The attachment manifest in the context snapshot lists
  uploaded files (id, name, type, size, text_available, est_tokens, path,
  preview); page through large attachment text with offset/length.
  Attachments are thread-scoped temporary context until promoted.
- Edit knowledge: write_file for new content and edit_file for precise
  replacements; delete_file and rename_file move single files. Writes apply
  inside the workspace immediately but are NOT approved until versioned:
  commit each logical change yourself. Never describe a commit as done
  unless the git tool actually returned success.
- Version: the git tool with only status/diff/log/add/commit/revert; commit
  each logical change with a short -m message. The runtime collects your
  commits into a pending diff for the user to accept or reject, and
  auto-commits anything you leave uncommitted when the run ends.
- Diagnose: run_powershell executes read-only Get-* commands only.
  lint_knowledge_base returns the deterministic quality report for the pages
  changed in this run; keep L0 at zero before finishing - read-only.
- Ingest registered sources directly: read schema.md from the workspace root,
  select the matching `markdown cellwiki-template <page_type>` block, then read
  raw/<source_id>/ with read_file. Never copy the block's
  `<!-- cellwiki ... -->` directive comments into a page - they are tool
  metadata and the lint gates leftover directives as L0. Prefer the *.extracted.txt sidecar for binary
  sources. If no readable extracted text exists, ask the user for it.
  Every factual claim must carry `Evidence: Tier 1` through `Tier 5`; Tier 1-4
  require a resolvable raw/<paper_id>/ source, while Tier 5 starts with
  `inference` or `hypothesis`. Entity references in structured sections must use
  `[[page_id]]`; do not use Markdown links for wiki entities. Record contradictions
  in workspace-root contradictions.md, not in page sections. Generate or update
  pages with write_file/edit_file and run lint before finishing. Promote a paper
  into raw/<id>/ with promote_attachment only after the user confirms via
  ask_user_question; the runtime registers the source and commits it.

## Output discipline
Answer exactly what was asked - no side audits, no unrequested follow-up
work. Answer first, then evidence. Give one short progress line before each
tool call.

## Vocabulary
workspace = the selected knowledge base; run = one execution; diff = the
change awaiting user acceptance. Never call generic filesystem or shell
tools beyond this whitelist. Answer in the user's language.
"""

# 注册表注入的工具名清单；Layer A 由静态常量变为"模板 + 注册表"的拼接产物，
# 因此 stable_system_prompt_text 与 prompt_configuration_hash 都随之变化
# （ADR-0014 预期内的稳定前缀变更）。
LAYER_A_TEXT = LAYER_A_TEMPLATE.replace("{{tools}}", AGENT_TOOL_NAMES_TEXT)


# 校准系数钳制范围：provider 实测/固定估算的比值一旦超出这个区间就按边界取值。
CALIBRATION_MIN = 0.5
CALIBRATION_MAX = 4.0


def calibration_ratio(measured_tokens: int | None, estimated_tokens: int) -> float:
    """把 provider 实测 prompt 与固定估算的比值换算成切分用的校准系数。

    实测值对固定估算可低可高（中文密度、tool_calls JSON、system/工具 schema
    固定开销都会影响），因此钳制到 [0.5, 4.0]；无实测或估算非正时返回 1.0，
    保持"纯估算"语义。压缩的触发判定仍直接用实测值，不乘本系数。
    """

    if not measured_tokens or not estimated_tokens:
        return 1.0
    if measured_tokens <= 0 or estimated_tokens <= 0:
        return 1.0
    ratio = measured_tokens / estimated_tokens
    return max(CALIBRATION_MIN, min(CALIBRATION_MAX, ratio))


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


# 附件清单段预算：多附件按份收敛 preview，避免挤占快照（快照整体另有 8000 上限）
_ATTACHMENT_BLOCK_BUDGET = 3000


def _render_attachment_block(attachments: list[dict[str, Any]]) -> str:
    """将附件清单渲染为紧凑快照段（元数据 + 收敛 preview，不泄露全文）。"""
    lines = ["## current attachments"]
    per_item = max(120, _ATTACHMENT_BLOCK_BUDGET // max(1, len(attachments)))
    for att in attachments:
        att_id = str(att.get("attachment_id") or att.get("id") or "?")
        name = str(att.get("original_name") or att.get("name") or "?")
        media_type = str(att.get("media_type") or "?")
        size = att.get("size_bytes")
        size_s = f"{size} bytes" if isinstance(size, int) else "?"
        available = bool(att.get("text_available"))
        available_s = "yes" if available else "no (needs OCR or a clearer PDF)"
        tokens = att.get("est_tokens", "?")
        path = str(att.get("path") or "?")
        header = (
            f"- id={att_id} name={name} type={media_type} size={size_s} "
            f"text_available={available_s} est_tokens={tokens} path={path}"
        )
        lines.append(header)
        preview = str(att.get("preview") or "")
        budget = max(0, per_item - len(header) - 12)
        if preview and budget > 0:
            lines.append(f"  preview: {preview[:budget]}")
    block = "\n".join(lines)
    return block[: _ATTACHMENT_BLOCK_BUDGET]


# Layer B 快照整体上界（字符）。选中文本另有一份自己的上界，见 _bounded_selection。
_LAYER_B_SNAPSHOT_MAX = 8_000
_SELECTED_TEXT_MAX = 2_000
_SELECTION_TRUNCATED = "…[selected text truncated]"


def _bounded_selection(text: str) -> str:
    """选中文本的有界引用：≤2000 字符，超出部分以显式截断标记收尾。

    ADR-0007 决策 11 修订：选中文本真注入 Layer B。注入量必须有上界，否则一次
    全选就能把整份快照挤掉；截断要让模型看得见，不能静默少给。
    """
    stripped = text.strip()
    if len(stripped) <= _SELECTED_TEXT_MAX:
        return stripped
    return stripped[:_SELECTED_TEXT_MAX].rstrip() + "\n" + _SELECTION_TRUNCATED


# 意图提示的标记词表：宁缺勿滥，误标只影响 Layer B goal 行的括号提示，
# Layer A 已声明"提示只是 tiebreaker"。单字动词（写/改/删）会撞上
# "有什么改动"这类状态问句，所以只收多字短语。
_INTENT_HINT_META: tuple[str, ...] = (
    "之前",
    "聊过",
    "聊天记录",
    "对话历史",
    "上次",
    "上一次",
    "上轮",
    "上一轮",
    "你有哪些工具",
    "你有什么工具",
    "你的工具",
    "你能做什么",
    "你会什么",
    "what did we",
    "what tools",
    "your tools",
)
_INTENT_HINT_WORK: tuple[str, ...] = (
    "ingest",
    "promote",
    "commit ",
    "登记",
    "清理",
    "删除",
    "删掉",
    "删了",
    "重命名",
    "写入",
    "写一",
    "写个",
    "写进",
    "新建",
    "建页",
    "整理成",
    "改成",
    "改为",
    "改一下",
    "改掉",
    "修改",
    "write a",
    "write new",
    "add a",
    "clean up",
    "rename",
)
_INTENT_HINT_QUESTION: tuple[str, ...] = (
    "？",
    "?",
    "什么",
    "怎么",
    "哪些",
    "为什么",
    "多少",
    "如何",
    "吗",
    "what ",
    "how ",
    "which ",
    "why ",
)


def classify_intent_hint(message: str | None) -> str | None:
    """Best-effort hint for the Layer B goal line, not a routing decision.

    Order matters: meta beats work ("之前 ingest 的五篇" is a history question),
    work beats the generic question markers. Returns None when nothing matches,
    which renders the goal line without a label.
    """

    text = str(message or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _INTENT_HINT_META):
        return "conversation meta"
    if any(marker in lowered for marker in _INTENT_HINT_WORK):
        return "library work"
    if any(marker in lowered for marker in _INTENT_HINT_QUESTION):
        return "question"
    return None


def build_layer_b_snapshot(
    *,
    current_message: str,
    git_status: str | None = None,
    open_page: dict[str, Any] | None = None,
    pending_question: str | None = None,
    recent_transcript: list[dict[str, str]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    selected_text: str | None = None,
    gate_issues: list[str] | None = None,
    limit_transcript: int = 6,
) -> str:
    """Layer B：run 启动时快照的 run 动态上下文（纯文本、紧凑、不泄露原始内容）。"""
    parts: list[str] = ["## Run context snapshot"]
    if git_status is not None:
        parts.append(f"- git status:\n{git_status[:1_500]}")
    if gate_issues:
        lines = "\n".join(f"  - {line}" for line in gate_issues[:30])
        parts.append(
            "- previous run was blocked by the schema gate; the changed pages"
            f" must fix these before finishing:\n{lines}"
        )
    if open_page is not None:
        page_id = open_page.get("page_id") or open_page.get("title") or "?"
        parts.append(f"- user is viewing: {page_id}")
        outline = _page_outline(str(open_page.get("markdown") or ""))
        if outline:
            parts.append("- page outline:\n" + "\n".join(outline[:16]))
    if selected_text is not None and selected_text.strip():
        parts.append(
            "- user selected this text on the page:\n" + _bounded_selection(selected_text)
        )
    if pending_question is not None:
        parts.append(f"- pending question: {pending_question[:500]}")
    if recent_transcript:
        transcript_lines = [
            f"  {item.get('role', '?')}: {str(item.get('content') or '')[:220].replace(chr(10), ' ')}"
            for item in recent_transcript[-limit_transcript:]
        ]
        parts.append("- recent transcript:\n" + "\n".join(transcript_lines))
    if attachments:
        block = _render_attachment_block(attachments)
        if block:
            parts.append(block)
    hint = classify_intent_hint(current_message)
    label = f" ({hint})" if hint else ""
    goal = f"- current run goal{label}: {current_message[:800]}"
    body = "\n".join(parts)
    # 快照整体上界不变，但 run 目标是这次运行最不能丢的一行：先给它留位，
    # 被截掉的只能是上面的上下文段。
    return f"{body[: max(0, _LAYER_B_SNAPSHOT_MAX - len(goal) - 1)]}\n{goal}"


def schema_prompt_block(schema_version: int, schema_contract_hash: str) -> str:
    """Stable workspace contract marker placed before the cache breakpoint."""

    return (
        "## Workspace schema\n"
        f"version: {int(schema_version)}\n"
        f"contract_hash: {schema_contract_hash}"
    )


def build_turn_context(
    *,
    current_message: str,
    intent_hint: str | None = None,
    git_status: str | None = None,
    open_page: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    selected_text: str | None = None,
    gate_issues: list[str] | None = None,
) -> str:
    """Build the v2 dynamic tail merged into the current user turn.

    This intentionally excludes recent transcript, the duplicated current
    message, pending questions, and snapshot commit. Those either belong to
    append-only history or are runtime metadata that the model does not need.
    """

    parts: list[str] = ["## Run context"]
    if git_status:
        parts.append(f"- git status:\n{git_status[:1_500]}")
    if gate_issues:
        lines = "\n".join(f"  - {line}" for line in gate_issues[:30])
        parts.append(
            "- previous run was blocked by the schema gate; the changed pages"
            f" must fix these before finishing:\n{lines}"
        )
    if open_page is not None:
        page_id = open_page.get("page_id") or open_page.get("title") or "?"
        parts.append(f"- user is viewing: {page_id}")
        outline = _page_outline(str(open_page.get("markdown") or ""))
        if outline:
            parts.append("- page outline:\n" + "\n".join(outline[:16]))
    if selected_text is not None and selected_text.strip():
        parts.append(
            "- user selected this text on the page:\n" + _bounded_selection(selected_text)
        )
    if attachments:
        block = _render_attachment_block(attachments)
        if block:
            parts.append(block)
    hint = intent_hint if intent_hint is not None else classify_intent_hint(current_message)
    if hint:
        parts.append(f"- intent hint: {hint}")
    return "\n".join(parts)[:_LAYER_B_SNAPSHOT_MAX]


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


def summarize_excerpts(excerpts: list[str]) -> str:
    """Public deterministic compaction summary used by the v2 transcript."""

    return _six_category_summary(excerpts)


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
    measured_tokens: int | None = None,
) -> CompactedContext:
    """Compress an over-budget transcript into six-category summary + retained window.

    触发判定与保留窗口都走实测优先口径：`measured_tokens`（provider 回报的真实
    prompt）存在时优先用它判定超限，并按实测/估算比值校准保留窗口，使"32K"
    更接近真实 token 预算；无实测时退回 chars/4 估算（校准系数 1.0）。
    """
    total_chars = sum(len(str(item.get("content") or "")) for item in messages)
    estimated_tokens = max(
        1, (total_chars + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN
    )
    threshold = int(max_tokens * auto_compact_ratio)
    over_budget = (
        measured_tokens > threshold
        if measured_tokens is not None
        else estimated_tokens > threshold
    )
    if not over_budget:
        return CompactedContext(retained=messages, compacted=False)
    ratio = calibration_ratio(measured_tokens, estimated_tokens)
    summary_excerpts: list[str] = []
    retained: list[dict[str, str]] = []
    used = 0.0
    for item in reversed(messages):
        content_text = str(item.get("content") or "")
        # 单条代价按校准系数折算成"真实 token"，预算仍是标称的 retained_tokens；
        # 若预算也乘系数，比值会在不等式两边约掉、校准形同虚设。
        cost = (len(content_text) / CHARS_PER_TOKEN) * ratio
        if not retained or used + cost <= retained_tokens:
            retained.append(item)
            used += cost
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
    "CALIBRATION_MAX",
    "CALIBRATION_MIN",
    "CompactedContext",
    "LAYER_A_TEXT",
    "build_layer_b_snapshot",
    "build_r1_r5_block",
    "build_turn_context",
    "calibration_ratio",
    "classify_intent_hint",
    "compact_transcript",
    "schema_prompt_block",
    "summarize_excerpts",
]
