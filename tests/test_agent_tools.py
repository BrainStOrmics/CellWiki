# =============================================================================
# 白名单工具测试 —— File/Glob/Grep/Git/PowerShell 工具 + lint + 最终回答
# =============================================================================
# P1/P2 边界由 test_path_guard.py 覆盖；这里验证工具级契约：读写编辑、
# glob/grep 范围、git 直达白名单执行器、run_powershell 只读白名单，
# 以及 lint 报告与最终回答 JSON 信封。
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path

from cellwiki.agent.executor import build_workspace_tools
from cellwiki.agent.tools import build_final_answer_tool, build_lint_tools


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


def test_final_answer_tool_returns_json_envelope(tmp_path: Path):
    _workspace(tmp_path)
    tool = build_final_answer_tool(tmp_path)
    payload = json.loads(
        tool.invoke(
            {
                "answer": "结论是 X。",
                "file_paths": ["wiki/cell_types/alpha-cell.md", "../escape.md"],
            }
        )
    )
    assert payload["answer"] == "结论是 X。"
    assert payload["file_paths"] == ["wiki/cell_types/alpha-cell.md"]

def test_ls_delete_and_rename_single_files(tmp_path: Path):
    root = _workspace(tmp_path)
    tools = _tools(root)
    listed = json.loads(tools["ls"].invoke({"folder": "wiki/cell_types"}))
    assert any(item["path"] == "wiki/cell_types/alpha-cell.md" for item in listed["results"])
    outside = json.loads(tools["ls"].invoke({"folder": ".."}))
    assert "error" in outside

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
    props = AskUserQuestionInput.model_json_schema()["properties"]
    assert props["question"]["maxLength"] == 2_000
    assert props["options"]["maxItems"] == 5
    assert props["required"]["default"] is True


def test_runtime_tool_schema_is_exactly_the_whitelist(tmp_path: Path):
    # 编译后的运行时工具面必须恰好等于白名单（AGENTS.md：验证运行时 schema）
    from cellwiki.agent.app import _CellWikiToolBoundaryMiddleware

    middleware = _CellWikiToolBoundaryMiddleware()
    assert middleware._allowed_tools == {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "git",
        "run_powershell",
        "delete_file",
        "rename_file",
        "lint_knowledge_base",
        "ask_user_question",
        "read_attachment",
        "submit_agent_answer",
    }

def test_ls_with_empty_folder_defaults_to_root(tmp_path: Path):
    """模型把 folder 传成空串时，ls 应归一化为工作区根而不是报错。"""
    root = _workspace(tmp_path)
    tools = _tools(root)
    payload = json.loads(tools["ls"].invoke({"folder": ""}))
    assert "error" not in payload, payload
    assert payload["results"], "根目录应能列出条目"
