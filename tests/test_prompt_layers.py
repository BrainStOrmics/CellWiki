# =============================================================================
# 阶段 5 验证：prompt 分层（Layer A/B/C）、压缩（512K/80%/32K）、R1-R5、六类摘要
# =============================================================================

from __future__ import annotations

import re

from cellwiki.services.prompt_layers import (
    LAYER_A_TEXT,
    build_layer_b_snapshot,
    build_r1_r5_block,
    build_turn_context,
    classify_intent_hint,
    compact_transcript,
    estimate_tokens,
    schema_prompt_block,
)


def test_layer_a_is_the_static_baseline_imported_by_app():
    from cellwiki.agent.app import SYSTEM_PROMPT

    assert SYSTEM_PROMPT == LAYER_A_TEXT
    assert "coordinator" in LAYER_A_TEXT
    assert "ask_user_question" in LAYER_A_TEXT
    assert "read_attachment" in LAYER_A_TEXT
    assert "pending diff" in LAYER_A_TEXT
    assert "ingest_sources" not in LAYER_A_TEXT
    assert "raw/<source_id>/" in LAYER_A_TEXT


def test_prompt_tool_name_lists_come_from_the_registry():
    """提示词与边界提醒里的工具名必须来自注册表，不得手写。

    手写清单会和代码脱节：2026-09-21 修复前 Layer A 与边界提醒都写着模型
    根本看不到的 ls，同时漏说 delete_file 被框架排除的事实。
    """
    from cellwiki.agent.app import CELLWIKI_BOUNDARY_REMINDER
    from cellwiki.domain.agent_tools import (
        AGENT_TOOL_NAMES_TEXT,
        AGENT_VISIBLE_TOOL_NAMES,
    )

    # 两处清单逐字等于注册表文本（不是"包含某些名字"，而是恰好这一串）。
    assert AGENT_TOOL_NAMES_TEXT in LAYER_A_TEXT
    assert AGENT_TOOL_NAMES_TEXT in CELLWIKI_BOUNDARY_REMINDER
    assert len(AGENT_TOOL_NAMES_TEXT.split(", ")) == len(AGENT_VISIBLE_TOOL_NAMES)

    # 白名单里的每个名字都必须真的出现在提示词里（漏说不等于少给）。
    for name in AGENT_VISIBLE_TOOL_NAMES:
        assert name in LAYER_A_TEXT, name
        assert name in CELLWIKI_BOUNDARY_REMINDER, name

    # 边界提醒的"不可用"清单是独立散文常量，描述框架通用工具的风险面，
    # 不是 CellWiki 注册表的投影；文本逐字固定（它参与 stable prefix 与 cache_prefix_hash）。
    assert (
        "Generic deep-agent tools such as execute, ls, task, write_todos are "
        "unavailable." in CELLWIKI_BOUNDARY_REMINDER
    )

    # 已退役与框架残留的工具名不得出现在 Layer A 的可用工具清单里。
    for retired in ("ls", "ingest_sources", "move_file", "move_folder", "read_wiki_page"):
        assert not re.search(rf"\b{retired}\b", LAYER_A_TEXT), retired

    # 边界提醒里只允许把 ls 当作"不可用"提到（它是框架残留、仍需显式拦截）。
    assert "available (" in CELLWIKI_BOUNDARY_REMINDER
    available_clause = CELLWIKI_BOUNDARY_REMINDER.split("available (", 1)[1].split(")", 1)[0]
    assert "ls" not in available_clause.split(", ")


def test_v2_schema_block_and_turn_context_are_stable_and_tail_only():

    assert schema_prompt_block(2, "abc123") == (
        "## Workspace schema\nversion: 2\ncontract_hash: abc123"
    )
    context = build_turn_context(
        current_message="之前聊过什么？",
        git_status="M wiki/cell_types/a.md",
        open_page={
            "page_id": "a",
            "markdown": "# A\n\n## Markers\n\n## References\n",
        },
        selected_text="FOXP3",
        attachments=[
            {"attachment_id": "att_1", "original_name": "p.pdf", "preview": "x"}
        ],
    )
    assert "## Run context" in context
    assert "M wiki/cell_types/a.md" in context
    assert "user is viewing: a" in context
    assert "user selected this text on the page:" in context
    assert "current attachments" in context
    assert "intent hint: conversation meta" in context
    assert "recent transcript" not in context
    assert "current run goal" not in context
    assert "之前聊过什么？" not in context
    assert len(context) <= 8_000


def test_layer_b_snapshot_contains_git_open_page_and_goal():
    page = {
        "page_id": "regulatory_t_cell",
        "title": "Regulatory T cell",
        "markdown": "# Regulatory T cell\n\n## FOXP3\nmarker text.\n## Therapy\nnotes.",
    }
    snapshot = build_layer_b_snapshot(
        current_message="总结一下 FOXP3",
        git_status=" M wiki/cell_types/regulatory_t_cell.md",
        open_page=page,
        recent_transcript=[
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "我在查看页面。"},
        ],
    )
    assert "Run context snapshot" in snapshot
    assert "git status" in snapshot
    assert "user is viewing: regulatory_t_cell" in snapshot
    assert "page outline" in snapshot
    assert "## FOXP3" in snapshot
    assert "recent transcript" in snapshot
    assert "current run goal: 总结一下 FOXP3" in snapshot
    assert len(snapshot) <= 8_000


def test_intent_hint_classifier_and_goal_label():
    # 分诊事故回归（2026-09-10）：会话元问题必须拿到"别开工"的提示标签。
    assert classify_intent_hint("之前聊过什么？") == "conversation meta"
    assert classify_intent_hint("你有哪些工具？") == "conversation meta"
    assert classify_intent_hint("先 ingest 五篇，我看看效果") == "library work"
    assert classify_intent_hint("现在 git 状态是怎么样的？") == "question"
    # 状态问句里的"改动"不能误判成工作指令。
    assert classify_intent_hint("有什么未提交的改动？") == "question"
    assert classify_intent_hint("总结一下 FOXP3") is None
    assert classify_intent_hint("") is None
    snapshot = build_layer_b_snapshot(current_message="之前聊过什么？")
    assert "current run goal (conversation meta): 之前聊过什么？" in snapshot


def test_layer_b_bounds_an_overlong_selection_with_a_visible_marker():
    # 注入/未注入两种情形由 tests/test_layer_b_injection.py 走真实图锁；这里只管上界
    # 本身。片段必须唯一：周期性文本会让"上界之外"的切片也出现在保留的前缀里，
    # 断言就证明不了截断真的发生过。
    selection = "".join(f"[{index:05d}]" for index in range(700))   # 4900 字符
    assert len(selection) > 2_000
    snapshot = build_layer_b_snapshot(
        current_message="总结这段",
        selected_text=selection,
        git_status=" M wiki/cell_types/a.md",
        attachments=[
            {"attachment_id": "att_1", "original_name": "p.pdf", "preview": "x" * 400}
        ],
    )
    assert "…[selected text truncated]" in snapshot
    assert selection[:2_000] in snapshot
    assert selection[2_500:2_600] not in snapshot
    # 截掉的是选中文本，不是这次运行的目标
    assert "current run goal: 总结这段" in snapshot
    assert len(snapshot) <= 8_000


def test_compaction_keeps_small_transcripts_untouched():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    result = compact_transcript(messages, max_tokens=512_000)
    assert result.compacted is False
    assert result.retained == messages
    assert result.summary_text == ""


def test_compaction_preserves_six_categories_and_retains_window():
    long_excerpts = [
        {"role": "user", "content": f"决定：保留 A 方案（decision 记录）。{chr(97) * 400}"},
        {"role": "assistant", "content": f"文件：修改 wiki/cell_types/a.md {chr(98) * 400}"},
        {"role": "user", "content": f"偏好：总是用中文，不要英文。{chr(99) * 400}"},
        {"role": "assistant", "content": f"未完成：还需要补充证据。{chr(100) * 400}"},
        {"role": "user", "content": f"待确认：请确认是否继续？{chr(101) * 400}"},
        {"role": "assistant", "content": f"纠正：更正前面的错误。{chr(102) * 400}"},
        {"role": "user", "content": "当前消息（应保留）"},
    ]
    result = compact_transcript(
        messages=long_excerpts,
        max_tokens=100,
        auto_compact_ratio=0.8,
        retained_tokens=16,
    )
    assert result.compacted is True
    assert result.summary_text.startswith("## Compacted history summary")
    for marker in ("decisions:", "files:", "preferences:", "unfinished:", "pending_questions:", "corrections:"):
        assert marker in result.summary_text, marker
    retained_chars = sum(len(str(m.get("content") or "")) for m in result.retained)
    assert retained_chars <= 16 * 4
    # 最新内容优先留在窗口内
    assert result.retained[-1]["content"] == "当前消息（应保留）"


def test_r1_r5_reinjection_block():
    block = build_r1_r5_block(
        git_status=" M wiki/a.md",
        page_snapshot="# A",
        pending_question="请确认？",
        recent_lint="- 1 info",
        run_goal="继续修订",
    )
    for marker in ("R1 (git status)", "R2 (page snapshot)", "R3 (pending question)", "R4 (recent lint)", "R5 (current run goal)"):
        assert marker in block


def test_token_estimate():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 100) == 25


def test_turn_context_renders_previous_gate_issues():
    context = build_turn_context(
        current_message="repair the pages",
        gate_issues=["wiki/cell_types/a.md: missing Evidence: Tier N"],
    )
    assert "previous run was blocked by the schema gate" in context
    assert "wiki/cell_types/a.md: missing Evidence: Tier N" in context

    snapshot = build_layer_b_snapshot(
        current_message="repair the pages",
        git_status=" M wiki/cell_types/a.md",
        gate_issues=["wiki/cell_types/a.md: missing Evidence: Tier N"],
    )
    assert "previous run was blocked by the schema gate" in snapshot
