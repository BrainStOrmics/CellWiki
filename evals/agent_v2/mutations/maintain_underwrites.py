# =============================================================================
# 负向变异：maintain_underwrites —— 维护少写关键内容
# =============================================================================
# 维护轮确实提交了改动，但没有补任务要求的 XCL1：file_contains(all_of)
# 必须以 text_missing 变红——"提交了"不等于"写对了"。
# =============================================================================

from __future__ import annotations

from cellwiki.evaluation.agent_eval_v2 import (
    EVALS_V2_ROOT,
    ScriptContext,
    ScriptResult,
    load_script_module,
    run_git,
)

MUTATION = {
    "mutation_id": "maintain_underwrites",
    "scenario_id": "maintain_accept_then_query",
    "expected_codes": ["text_missing"],
    "expected_primary": "content",
    "description": "维护轮只加无关 Notes 行，缺 XCL1 关键事实。",
}

_PAGE = "wiki/cell_types/natural_killer_cell.md"


def _oracle():
    return load_script_module(
        EVALS_V2_ROOT / "oracles" / "lifecycle_build_query_maintain.py"
    )


def respond(ctx: ScriptContext) -> ScriptResult:
    if ctx.resume_answers is not None:
        raise RuntimeError("mutation does not ask questions; unexpected resume")
    if "创建页面" in ctx.message and "natural_killer_cell" in ctx.message:
        return _oracle().respond(ctx)
    if "补充" in ctx.message and "XCL1" in ctx.message:
        page = ctx.workspace / _PAGE
        current = page.read_text(encoding="utf-8")
        # 只补一条无关行，制造真实可提交的 diff，但不写 XCL1。
        updated = current.replace(
            "## Notes",
            "## Notes\n\n- Fixture note: maintenance performed.\n",
            1,
        )
        page.write_text(updated, encoding="utf-8")
        run_git(ctx.workspace, "add", _PAGE)
        run_git(ctx.workspace, "commit", "-m", "feat(agent): maintain page (mutation)")
        return ScriptResult(
            answer="已在 wiki/cell_types/natural_killer_cell.md 补充维护说明。",
            tool_calls=[{"tool_name": "edit_file", "args_display": {"path": _PAGE}}],
        )
    raise RuntimeError(f"mutation not applicable to message: {ctx.message[:80]}")
