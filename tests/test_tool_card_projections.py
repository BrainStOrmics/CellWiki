# =============================================================================
# 工具卡片有界投影 —— edit_file 真行级 diff（裁决 #11）与 lint / 附件投影
# =============================================================================
# 这些是纯函数：投影必须在运行时边界内完成，卡片只拿到有界结果。
# 关键约束：新增 edit_diff_display **不放宽** args_display 既有的 200 字符上界。
# =============================================================================

from __future__ import annotations

import json

from cellwiki.services.agent_runtime import (
    _EDIT_DIFF_CHARS,
    _EDIT_DIFF_LINE_CHARS,
    _EDIT_DIFF_LINE_MAX,
    _tool_args_display,
    _tool_edit_diff_display,
    _tool_result_preview,
)


def test_edit_diff_marks_removed_and_added_lines_with_their_numbers():
    old = "alpha\nbeta\ngamma\ndelta"
    new = "alpha\nBETA\ngamma\ndelta"

    diff = _tool_edit_diff_display(
        "edit_file", {"path": "wiki/a.md", "old_string": old, "new_string": new}
    )

    assert diff is not None
    assert (diff["removed"], diff["added"], diff["truncated"]) == (1, 1, False)
    kinds = [row["kind"] for row in diff["lines"]]
    assert kinds == ["context", "removed", "added", "context", "context"]
    removed = diff["lines"][1]
    added = diff["lines"][2]
    assert (removed["text"], removed["old_no"], removed["new_no"]) == ("beta", 2, None)
    assert (added["text"], added["old_no"], added["new_no"]) == ("BETA", None, 2)


def test_edit_diff_collapses_long_unchanged_runs_into_a_gap_row():
    old = "\n".join(f"line {index}" for index in range(40))
    new = old.replace("line 20", "LINE 20")

    diff = _tool_edit_diff_display("edit_file", {"old_string": old, "new_string": new})

    assert diff is not None
    gaps = [row for row in diff["lines"] if row["kind"] == "gap"]
    assert gaps, "长段未变内容应折叠成 gap 行，而不是全量下发"
    assert gaps[0]["count"] > 0
    # 折叠之后总行数必须远小于原文行数。
    assert len(diff["lines"]) < 20


def test_edit_diff_stays_inside_its_own_bounds_and_says_when_it_truncates():
    old = "\n".join(f"removed {index} " + "x" * 400 for index in range(400))
    new = "\n".join(f"added {index} " + "y" * 400 for index in range(400))

    diff = _tool_edit_diff_display("edit_file", {"old_string": old, "new_string": new})

    assert diff is not None
    assert diff["truncated"] is True
    assert len(diff["lines"]) <= _EDIT_DIFF_LINE_MAX
    assert all(len(row["text"]) <= _EDIT_DIFF_LINE_CHARS for row in diff["lines"])
    total = sum(len(row["text"]) + 1 for row in diff["lines"])
    assert total <= _EDIT_DIFF_CHARS


def test_edit_diff_is_only_projected_for_edit_file():
    payload = {"old_string": "a", "new_string": "b"}

    assert _tool_edit_diff_display("write_file", payload) is None
    assert _tool_edit_diff_display("edit_file", {"path": "wiki/a.md"}) is None
    assert _tool_edit_diff_display("edit_file", "not json") is None


def test_argument_cap_is_unchanged_by_the_new_projection():
    """裁决 #11 只批准**新增字段**；既有 200 字符上界一个字都不能动。"""
    display = _tool_args_display(
        "edit_file", {"path": "p" * 500, "old_string": "o" * 500, "new_string": "n" * 500}
    )

    assert display is not None
    assert len(display["path"]) == 200
    # old_string / new_string 从来不在白名单里，新投影也没有把它们塞进 args_display。
    assert "old_string" not in display
    assert "new_string" not in display


def test_command_cap_is_still_two_thousand_characters():
    display = _tool_args_display("run_powershell", {"command": "c" * 5_000})

    assert display is not None
    assert len(display["command"]) == 2_000


def test_attachment_identifiers_are_projected_for_the_attachment_cards():
    display = _tool_args_display(
        "promote_attachment", {"attachment_id": "att_123", "source_type": "paper"}
    )

    assert display is not None
    assert display["attachment_id"] == "att_123"
    assert display["source_type"] == "paper"
    assert display["title"] == "att_123"


def test_lint_report_keeps_its_verdict_even_though_the_body_is_truncated():
    report = {
        "status": "passed_with_warnings",
        "page_count": 12,
        "issue_count": 40,
        "error_count": 0,
        "warning_count": 40,
        "issues": [{"detail": "x" * 900} for _ in range(40)],
    }

    preview = _tool_result_preview("lint_knowledge_base", json.dumps(report))

    assert preview is not None
    assert preview["truncated"] is True
    assert preview["summary"] == {
        "status": "passed_with_warnings",
        "page_count": 12,
        "error_count": 0,
        "warning_count": 40,
    }


def test_non_lint_results_carry_no_summary():
    preview = _tool_result_preview("git", json.dumps({"stdout": "on branch main"}))

    assert preview is not None
    assert "summary" not in preview
