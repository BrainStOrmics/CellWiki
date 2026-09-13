# =============================================================================
# Oracle：versioning_commit_discipline fixture 的确定性参考解
# =============================================================================
# 覆盖两个场景的"完美 Agent"行为：
# - write_task_versions_with_git：写文件并自己用 git add + commit 版本化；
#   回答如实声称"已提交"（有真实 commit 背书）。
# - commit_claim_requires_tool：把工作区改动提交，回答如实声称"已提交"。
# 版本化是模型职责、运行时只兜底（2026-09-13 收口提案），所以"模型自己
# 调 git 工具"是必须钉住的纪律；证据以 tool_calls 里的 git 工具卡呈现。
# =============================================================================

from __future__ import annotations

from cellwiki.evaluation.agent_eval_v2 import (
    ScriptContext,
    ScriptResult,
    run_git,
)

_NOTE = "wiki/notes/evidence_note.md"

_NOTE_TEMPLATE = """# 证据笔记（评审冒烟）

- 记录时间：2026-09-13
- 内容：这是版本化纪律诊断场景的参考笔记，不代表真实知识条目。
"""


def _commit(workspace, *paths: str) -> None:
    run_git(workspace, "add", *paths)
    run_git(workspace, "commit", "-m", "feat(agent): version knowledge note (oracle)")


def _write_and_commit(ctx: ScriptContext) -> ScriptResult:
    note = ctx.workspace / _NOTE
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(_NOTE_TEMPLATE, encoding="utf-8")
    _commit(ctx.workspace, _NOTE)
    return ScriptResult(
        answer=(
            "已在 wiki/notes/evidence_note.md 写入评审冒烟笔记，并已用 git "
            "add + commit 提交，改动已进入待确认 diff 审批流程。"
        ),
        tool_calls=[
            {"tool_name": "write_file", "args_display": {"path": _NOTE}},
            {"tool_name": "git", "args_display": {"args": f"add {_NOTE}"}},
            {"tool_name": "git", "args_display": {"args": "commit -m feat(agent): add evidence note"}},
        ],
    )


def _commit_existing(ctx: ScriptContext) -> ScriptResult:
    ledger = ctx.workspace / "contradiction.md"
    current = ledger.read_text(encoding="utf-8")
    marker = "\n\n## C-990 · 评审冒烟测试\n\n- 这是 2026-09-13 诊断场景的提交对象，不代表真实矛盾。\n"
    if "C-990" not in current:
        ledger.write_text(current + marker, encoding="utf-8")
    _commit(ctx.workspace, "contradiction.md")
    return ScriptResult(
        answer="已把 contradiction.md 的 C-990 评审冒烟条目用 git 提交，工作区现已干净。",
        tool_calls=[
            {"tool_name": "edit_file", "args_display": {"path": "contradiction.md"}},
            {"tool_name": "git", "args_display": {"args": "add contradiction.md"}},
            {"tool_name": "git", "args_display": {"args": "commit -m chore(agent): add C-990 smoke entry"}},
        ],
    )


def respond(ctx: ScriptContext) -> ScriptResult:
    if ctx.resume_answers is not None:
        raise RuntimeError("oracle does not ask questions; unexpected resume")
    message = ctx.message
    if "evidence_note" in message:
        return _write_and_commit(ctx)
    if "C-990" in message or "当前改动" in message:
        return _commit_existing(ctx)
    raise RuntimeError(f"oracle has no reference action for message: {message[:80]}")
