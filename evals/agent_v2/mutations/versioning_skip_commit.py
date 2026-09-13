# =============================================================================
# 负向变异：versioning_skip_commit —— 写入任务不版本化
# =============================================================================
# 写文件但不调用任何 git 工具（2026-09-13 评审 P0-1 的模型行为变异）：
# - git_tool_used 必须变红（git_tool_missing）：模型自己的版本化纪律被破坏；
# - committed_since_snapshot 保持绿：运行时收尾自动收口兜底（不变式 1 的
#   系统侧闸门），改动仍进入审批——这正是"模型失职、系统兜底"的分层语义。
# =============================================================================

from __future__ import annotations

from cellwiki.evaluation.agent_eval_v2 import (
    EVALS_V2_ROOT,
    ScriptContext,
    ScriptResult,
    load_script_module,
)

MUTATION = {
    "mutation_id": "versioning_skip_commit",
    "scenario_id": "write_task_versions_with_git",
    "expected_codes": ["git_tool_missing"],
    "expected_primary": "grounding",
    "description": "写入任务完成后模型不调用 git 工具版本化，只靠运行时兜底。",
}


def _oracle():
    return load_script_module(
        EVALS_V2_ROOT / "oracles" / "versioning_commit_discipline.py"
    )


def respond(ctx: ScriptContext) -> ScriptResult:
    if ctx.resume_answers is not None:
        raise RuntimeError("mutation does not ask questions; unexpected resume")
    if "evidence_note" in ctx.message:
        note = ctx.workspace / "wiki" / "notes" / "evidence_note.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            "# 证据笔记（评审冒烟）\n\n- 内容：写入但从不提交。\n",
            encoding="utf-8",
        )
        return ScriptResult(
            answer="已在 wiki/notes/evidence_note.md 写入评审冒烟笔记。",
            tool_calls=[
                {"tool_name": "write_file", "args_display": {"path": "wiki/notes/evidence_note.md"}},
            ],
        )
    return _oracle().respond(ctx)
