# =============================================================================
# 负向变异：missing_key_fact —— 构建页缺关键事实
# =============================================================================
# 模拟 Agent 漏写 KLRD1：file_contains(all_of) 必须以 text_missing 变红，
# 而不是靠"页面已创建"放行。
# =============================================================================

from __future__ import annotations

from cellwiki.evaluation.agent_eval_v2 import (
    ScriptContext,
    ScriptResult,
    run_git,
)

MUTATION = {
    "mutation_id": "missing_key_fact",
    "scenario_id": "build_from_raw",
    "expected_codes": ["text_missing"],
    "expected_primary": "content",
    "description": "构建页缺关键事实 KLRD1，file_contains(all_of) 必须失败。",
}

_PAGE = "wiki/cell_types/natural_killer_cell.md"

# 与 oracle 相同的骨架，但 Markers 只留 NCR1：页面存在、结构正确，唯独
# 缺任务要求的关键事实。
_DEFICIENT_PAGE = """---
standard_name: natural_killer_cell
display_name: Natural killer cell
cl_id: CL:0000623
species: [Homo sapiens]
references:
  - paper_id: fixture_nk_2023
    title: Fixture paraphrase of human NK cell identity evidence
    year: 2023
---
# Natural killer cell

## Definition

Cytotoxic innate lymphoid cell of peripheral blood that kills stressed or
infected cells without prior sensitization.

## Markers

- The lineage-defining combination is NCR1 (also called NKp46).

## Notes

Paraphrased from a public-access fixture source; see raw/fixture_nk_cell_source.md.
"""


def respond(ctx: ScriptContext) -> ScriptResult:
    if ctx.resume_answers is not None:
        raise RuntimeError("mutation does not ask questions; unexpected resume")
    if "创建页面" not in ctx.message or "natural_killer_cell" not in ctx.message:
        raise RuntimeError(f"mutation not applicable to message: {ctx.message[:80]}")
    page = ctx.workspace / _PAGE
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(_DEFICIENT_PAGE, encoding="utf-8")
    run_git(ctx.workspace, "add", _PAGE)
    run_git(ctx.workspace, "commit", "-m", "feat(agent): create page (mutation)")
    return ScriptResult(
        answer="已创建 wiki/cell_types/natural_killer_cell.md，Markers 记录 NCR1。",
        tool_calls=[
            {"tool_name": "write_file", "args_display": {"path": _PAGE}},
        ],
    )
