# =============================================================================
# 负向变异：fake_citation —— 回答引用不存在的路径
# =============================================================================
# 构建行为正确，但回答里编造一个 wiki 路径：no_unresolved_citations 必须以
# unresolved_citation_found 变红；citation_exists 对真实页面仍然通过，
# 证明两条断言各管各的口径。
# =============================================================================

from __future__ import annotations

from cellwiki.evaluation.agent_eval_v2 import (
    EVALS_V2_ROOT,
    ScriptContext,
    ScriptResult,
    load_script_module,
)


MUTATION = {
    "mutation_id": "fake_citation",
    "scenario_id": "build_from_raw",
    "expected_codes": ["unresolved_citation_found"],
    "expected_primary": "grounding",
    "description": "回答编造 wiki/cell_types/nk_activation.md 引用。",
}


def _oracle():
    return load_script_module(
        EVALS_V2_ROOT / "oracles" / "lifecycle_build_query_maintain.py"
    )


def respond(ctx: ScriptContext) -> ScriptResult:
    if ctx.resume_answers is not None:
        raise RuntimeError("mutation does not ask questions; unexpected resume")
    if "创建页面" not in ctx.message or "natural_killer_cell" not in ctx.message:
        raise RuntimeError(f"mutation not applicable to message: {ctx.message[:80]}")
    result = _oracle().respond(ctx)
    return ScriptResult(
        # 真实页面引用仍有效，另加一条不存在的路径。
        answer=result.answer
        + " 相关证据另见 wiki/cell_types/nk_activation.md。",
        tool_calls=result.tool_calls,
    )
