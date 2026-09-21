# =============================================================================
# 白名单工具测试 —— File/Glob/Grep/Git/PowerShell 工具 + lint
# =============================================================================
# P1/P2 边界由 test_path_guard.py 覆盖；这里验证工具级契约：读写编辑、
# glob/grep 范围、git 直达白名单执行器、run_powershell 只读白名单，
# 以及 lint 报告。
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path

from cellwiki.agent.executor import build_workspace_tools
from cellwiki.agent.tools import build_lint_tools


def _workspace(root: Path) -> Path:
    wiki = root / "wiki" / "cell_types"
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "alpha-cell.md").write_text(
        "# Alpha Cell\n\nFOXP3 marks regulatory T cells.\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Workspace README\n", encoding="utf-8")
    return root


def _tools(root: Path):
    return {tool.name: tool for tool in build_workspace_tools(root)}


def test_read_file_reads_workspace_text(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    payload = json.loads(tools["read_file"].invoke({"path": "wiki/cell_types/alpha-cell.md"}))
    assert "FOXP3" in payload["content"]


def test_read_file_rejects_paths_outside_workspace(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    for path in ("../../etc/passwd", "C:\\Windows\\win.ini", "$HOME/.bashrc"):
        payload = json.loads(tools["read_file"].invoke({"path": path}))
        assert payload.get("error"), path


def test_write_and_edit_file_roundtrip(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    written = json.loads(
        tools["write_file"].invoke({"path": "wiki/new.md", "content": "# New\n"})
    )
    assert written["ok"] is True
    payload = json.loads(tools["read_file"].invoke({"path": "wiki/new.md"}))
    assert payload["content"] == "# New\n"
    edited = json.loads(
        tools["edit_file"].invoke({"path": "wiki/new.md", "old_string": "# New", "new_string": "# Edited"})
    )
    assert edited["ok"] is True
    assert (root / "wiki" / "new.md").read_text(encoding="utf-8") == "# Edited\n"


def test_edit_file_rejects_ambiguous_or_missing_target(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    ambiguous = json.loads(
        tools["edit_file"].invoke({"path": "wiki/cell_types/alpha-cell.md", "old_string": "e", "new_string": "X"})
    )
    assert "ambiguous" in ambiguous["error"]
    missing = json.loads(
        tools["edit_file"].invoke({"path": "wiki/cell_types/alpha-cell.md", "old_string": "NOPE", "new_string": "X"})
    )
    assert "not found" in missing["error"]


def test_glob_lists_markdown_files(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    payload = json.loads(tools["glob"].invoke({"pattern": "**/*.md"}))
    assert "wiki/cell_types/alpha-cell.md" in payload["results"]


def test_grep_finds_literal_matches(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    payload = json.loads(tools["grep"].invoke({"pattern": "FOXP3"}))
    assert payload["results"][0]["file"] == "wiki/cell_types/alpha-cell.md"


def test_git_tool_forwards_to_whitelist_executor(tmp_path: Path):
    root = _workspace(tmp_path)
    from cellwiki.services.workspace import ensure_workspace

    ensure_workspace(root)
    tools = _tools(root)
    payload = json.loads(tools["git"].invoke({"args": ["status", "--short"]}))
    assert "stdout" in payload
    forbidden = json.loads(tools["git"].invoke({"args": ["reset", "--hard"]}))
    assert "error" in forbidden


def test_run_powershell_rejects_mutation_and_non_get_verbs(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    for command in ("Remove-Item wiki", "Get-ChildItem; Remove-Item wiki", "iex 'x'"):
        payload = json.loads(tools["run_powershell"].invoke({"command": command}))
        assert "error" in payload, command
    payload = json.loads(
        tools["run_powershell"].invoke({"command": "Set-Content -Path x -Value 1"})
    )
    assert "error" in payload


def test_lint_knowledge_base_returns_json_report(tmp_path: Path):
    _workspace(tmp_path)
    tools = {tool.name: tool for tool in build_lint_tools(tmp_path)}
    payload = json.loads(tools["lint_knowledge_base"].invoke({}))
    assert "issues" in payload or "status" in payload


def test_delete_and_rename_single_files(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    created = _workspace(tmp_path) / "wiki" / "tmp.md"
    created.write_text("# Tmp\n", encoding="utf-8")
    deleted = json.loads(tools["delete_file"].invoke({"path": "wiki/tmp.md"}))
    assert deleted["ok"] is True and not created.exists()
    missing = json.loads(tools["delete_file"].invoke({"path": "wiki/cell_types"}))
    assert "error" in missing  # 目录不可删除

    renamed = json.loads(
        tools["rename_file"].invoke(
            {"path": "wiki/cell_types/alpha-cell.md", "new_path": "wiki/cell_types/alpha-renamed.md"}
        )
    )
    assert renamed["ok"] is True
    assert (root / "wiki" / "cell_types" / "alpha-renamed.md").exists()
    traversal = json.loads(
        tools["rename_file"].invoke(
            {"path": "wiki/cell_types/alpha-renamed.md", "new_path": "../escape.md"}
        )
    )
    assert "error" in traversal


def test_ask_user_question_registers_5_plus_one_schema(tmp_path: Path):
    from cellwiki.agent.question_tool import AskUserQuestionInput, build_question_tool

    tool = build_question_tool()[0]
    schema = tool.args_schema
    assert schema is AskUserQuestionInput
    json_schema = AskUserQuestionInput.model_json_schema()
    props = json_schema["properties"]
    assert props["question"]["maxLength"] == 2_000
    assert props["options"]["maxItems"] == 5
    assert props["required"]["default"] is True
    # 选项收对象或裸字符串（弱模型会原样发字符串，严格拒收会把它逼成 options=[]）；
    # 对象里标签必填且是答案回传值，说明与推荐标记可选。
    assert props["options"]["items"]["anyOf"][0]["type"] == "string"
    option = json_schema["$defs"]["AskUserQuestionOption"]["properties"]
    assert option["label"]["maxLength"] == 120
    assert option["description"]["maxLength"] == 240
    assert option["recommended"]["default"] is False
    assert json_schema["$defs"]["AskUserQuestionOption"]["required"] == ["label"]


def test_question_payload_keeps_richer_option_objects():
    """工具函数收到的是 LangChain 校验后的模型实例，不是 dict。

    2026-09-20 真机实测：归一化只认 dict/str 时实例被静默丢光（卡片只剩问题、
    没有选项），因此这里固定"实例也留得住"。
    """
    from cellwiki.agent.question_tool import (
        AskUserQuestionOption,
        _question_payload,
    )

    payload = _question_payload(
        "继续吗？",
        [
            AskUserQuestionOption(label="A 先做，再做 B", description="先修缺陷"),
            AskUserQuestionOption(label="只做 A"),
        ],
        True,
    )
    assert payload["options"] == [
        {"label": "A 先做，再做 B", "description": "先修缺陷", "recommended": False},
        {"label": "只做 A", "description": "", "recommended": False},
    ]


def test_question_payload_accepts_string_and_object_options():
    from cellwiki.agent.question_tool import _question_payload

    payload = _question_payload(
        "继续吗？",
        ["是", {"label": "否", "description": "先停在这里", "recommended": True}],
        True,
    )
    assert payload["options"] == [
        {"label": "是", "description": "", "recommended": False},
        {"label": "否", "description": "先停在这里", "recommended": True},
    ]


def test_question_options_normalize_to_label_description_recommended():
    from cellwiki.domain.questions import normalize_question_options

    options = normalize_question_options(
        [
            {"label": "写入", "description": "走审批单元", "recommended": True},
            {"label": "写入"},              # 标签重复：保留先出现的那条
            "仅回答",                        # 旧载荷/脚本里的字符串选项
            {"label": "  "},                # 空标签丢掉
            {"text": "没有 label"},          # 形状不对：丢掉而不是报错
            "放弃",
            "第五个",
            "第六个",                        # 超过 5 个截断
        ]
    )
    assert [option.model_dump() for option in options] == [
        {"label": "写入", "description": "走审批单元", "recommended": True},
        {"label": "仅回答", "description": "", "recommended": False},
        {"label": "放弃", "description": "", "recommended": False},
        {"label": "第五个", "description": "", "recommended": False},
        {"label": "第六个", "description": "", "recommended": False},
    ]


def test_runtime_tool_schema_is_exactly_the_whitelist(tmp_path: Path):
    """编译后真正发给模型的工具面必须恰好等于白名单。

    2026-09-21 之前这条用例只断言中间件的常量 _allowed_tools，因此看着通过，
    真实模型请求却少了 ls 与 delete_file（HarnessProfile.excluded_tools 按名
    剥离、不区分来源）。这里改断言"真实编译图传给 bind_tools 的工具名"。
    """
    from cellwiki.domain.agent_tools import AGENT_VISIBLE_TOOL_NAMES
    from tests.tool_surface import model_visible_tool_names

    names = model_visible_tool_names(_workspace(tmp_path))

    assert names == set(AGENT_VISIBLE_TOOL_NAMES)
    assert "delete_file" in names
    assert "ls" not in names


def test_framework_exclusions_never_touch_whitelisted_tools(tmp_path: Path):
    """框架排除清单与白名单必须互斥（防止白名单工具被自己人删掉复发）。"""
    from cellwiki.domain.agent_tools import (
        AGENT_VISIBLE_TOOL_NAMES,
        FRAMEWORK_EXCLUDED_TOOL_NAMES,
    )

    overlap = FRAMEWORK_EXCLUDED_TOOL_NAMES & AGENT_VISIBLE_TOOL_NAMES
    assert overlap == frozenset(), (
        "framework excluded_tools strips tools by name without checking their "
        f"origin; these whitelisted tools would be deleted: {sorted(overlap)}"
    )


# ---------------------------------------------------------------------------
# ADR-0009：根级系统维护文件对 Agent 写操作不可达（读不受限）
# ---------------------------------------------------------------------------


def test_system_owned_files_reject_write_edit_delete_rename(tmp_path: Path):
    root = _workspace(tmp_path)
    names = ("overview.md", "statistics.md", "log.md", "audit_report.md")
    for name in names:
        (root / name).write_bytes(b"# heading\n")
    tools = _tools(root)
    for name in names:
        for tool, args in (
            ("write_file", {"path": name, "content": "hijack"}),
            ("edit_file", {"path": name, "old_string": "# heading", "new_string": "# hijack"}),
            ("delete_file", {"path": name}),
            ("rename_file", {"path": name, "new_path": "renamed.md"}),
        ):
            payload = json.loads(tools[tool].invoke(args))
            assert "system-owned file is not writable" in payload.get("error", ""), (tool, name)
        read = json.loads(tools["read_file"].invoke({"path": name}))
        assert read.get("content") == "# heading\n", name
    # 非根级同名文件与 index.md（Agent 维护）不受系统文件约束
    payload = json.loads(tools["write_file"].invoke({"path": "wiki/log.md", "content": "ok"}))
    assert payload["ok"] is True
    payload = json.loads(tools["write_file"].invoke({"path": "index.md", "content": "nav"}))
    assert payload["ok"] is True

def test_agent_cannot_write_schema_contract_directly(tmp_path: Path):
    root = _workspace(tmp_path)
    (root / "schema.md").write_text("user-owned", encoding="utf-8")
    tools = _tools(root)
    write = json.loads(
        tools["write_file"].invoke({"path": "schema.md", "content": "agent-owned"})
    )
    edit = json.loads(
        tools["edit_file"].invoke(
            {"path": "schema.md", "old_string": "user-owned", "new_string": "changed"}
        )
    )
    deleted = json.loads(tools["delete_file"].invoke({"path": "schema.md"}))
    assert write.get("error") == "system-owned file is not writable"
    assert edit.get("error") == "system-owned file is not writable"
    assert deleted.get("error") == "system-owned file is not writable"
    assert (root / "schema.md").read_text(encoding="utf-8") == "user-owned"


def test_edit_file_keeps_lf_across_repeated_edits(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    target = root / "wiki" / "lines.md"
    tools["write_file"].invoke(
        {"path": "wiki/lines.md", "content": "line1\nline2\nline3\n"}
    )
    tools["edit_file"].invoke(
        {"path": "wiki/lines.md", "old_string": "line2", "new_string": "line2x"}
    )
    tools["edit_file"].invoke(
        {"path": "wiki/lines.md", "old_string": "line3", "new_string": "line3x"}
    )
    assert target.read_bytes() == b"line1\nline2x\nline3x\n"


def test_edit_file_normalizes_crlf_and_matches_multiline(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    target = root / "wiki" / "crlf.md"
    target.write_bytes("alpha\r\nbeta\r\ngamma\r\n".encode("utf-8"))
    edited = json.loads(
        tools["edit_file"].invoke(
            {
                "path": "wiki/crlf.md",
                "old_string": "alpha\nbeta",
                "new_string": "alpha\nBETA",
            }
        )
    )
    assert edited["ok"] is True
    assert target.read_bytes() == b"alpha\nBETA\ngamma\n"
    read = json.loads(tools["read_file"].invoke({"path": "wiki/crlf.md"}))
    assert read["content"] == "alpha\nBETA\ngamma\n"


def test_lint_knowledge_base_scopes_to_run_changed_pages(tmp_path: Path):
    from cellwiki.services.git_executor import GitExecutor
    from cellwiki.services.run_scope import clear_run_scope, set_run_scope
    from cellwiki.services.workspace import ensure_workspace
    from tests.schema_helpers import invalid_cell_type_page, minimal_schema_contract

    root = _workspace(tmp_path)
    ensure_workspace(root)
    (root / "schema.md").write_text(minimal_schema_contract(), encoding="utf-8")
    git = GitExecutor(root)
    git.run("add", ".")
    git.run("commit", "-m", "baseline")
    baseline = git.current_head()

    tools = {tool.name: tool for tool in build_lint_tools(root)}
    outside = json.loads(tools["lint_knowledge_base"].invoke({}))
    assert outside["page_count"] == 0

    set_run_scope("run_lint_scope", baseline)
    try:
        target = root / "wiki" / "cell_types" / "cd8_t_cell.md"
        target.write_text(invalid_cell_type_page(), encoding="utf-8")
        report = json.loads(tools["lint_knowledge_base"].invoke({}))
    finally:
        clear_run_scope()

    assert report["status"] == "failed"
    assert report["scope"]["changed_pages_only"] is True
    assert report["error_count"] >= 1
