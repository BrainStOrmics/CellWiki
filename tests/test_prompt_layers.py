# =============================================================================
# 阶段 5 验证：prompt 分层（Layer A/B/C）、压缩（512K/80%/32K）、R1-R5、六类摘要
# =============================================================================

from __future__ import annotations

from cellwiki.services.prompt_layers import (
    LAYER_A_TEXT,
    build_layer_b_snapshot,
    build_r1_r5_block,
    classify_intent_hint,
    compact_transcript,
    estimate_tokens,
    resolve_declared_window,
    warn_if_narrow_window,
)


def test_layer_a_is_the_static_baseline_imported_by_app():
    from cellwiki.agent.app import SYSTEM_PROMPT

    assert SYSTEM_PROMPT == LAYER_A_TEXT
    assert "coordinator" in LAYER_A_TEXT
    assert "ask_user_question" in LAYER_A_TEXT
    assert "read_attachment" in LAYER_A_TEXT
    assert "pending diff" in LAYER_A_TEXT


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


def test_narrow_window_warning_is_non_blocking():
    warned: list[str] = []
    result = warn_if_narrow_window(
        "gpt-4o", 512_000, emit=warned.append  # type: ignore[arg-type]
    )
    assert result is True
    assert warned and "below AGENT_CONTEXT_MAX_TOKENS" in warned[0]
    # 未知模型不告警；窗口充足不告警
    assert warn_if_narrow_window("unknown-model", 512_000, emit=warned.append) is False  # type: ignore[arg-type]
    assert warn_if_narrow_window("gpt-4.1", 512_000, emit=warned.append) is False  # type: ignore[arg-type]


def test_declared_window_and_token_estimate():
    assert resolve_declared_window("gpt-4o-mini") == 128_000
    assert resolve_declared_window("deepseek-chat") == 65_536
    assert resolve_declared_window("mystery") is None
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 100) == 25
