# =============================================================================
# Oracle：lifecycle_build_query_maintain fixture 的确定性参考解
# =============================================================================
# 无模型重放合同见 evals/agent_v2/README.md。oracle 只作用于 harness 复制的
# 工作区副本，用普通文件写入 + subprocess git 达到"完美 Agent"的终态；
# 它不是产品运行，也不得调用任何模型或网络。
# =============================================================================

from __future__ import annotations

from cellwiki.evaluation.agent_eval_v2 import (
    ScriptContext,
    ScriptResult,
    run_git,
)

_PAGE = "wiki/cell_types/natural_killer_cell.md"

_PAGE_TEMPLATE = """---
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

- The lineage-defining combination is NCR1 (also called NKp46) together with
  KLRD1.
{extra_markers}
## Notes

Paraphrased from a public-access fixture source; see raw/fixture_nk_cell_source.md.
"""

_MAINTAIN_EXTRA_MARKERS = """- Activated subsets additionally express XCL1.
- NCR1 alone was reported insufficient to separate NK cells from ILC1 in the
  same preparation.
"""


def _commit(workspace, *paths: str) -> None:
    run_git(workspace, "add", *paths)
    run_git(workspace, "commit", "-m", "feat(agent): maintain knowledge base (oracle)")


def _build(ctx: ScriptContext) -> ScriptResult:
    page = ctx.workspace / _PAGE
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        _PAGE_TEMPLATE.format(extra_markers=""), encoding="utf-8"
    )
    _commit(ctx.workspace, _PAGE)
    return ScriptResult(
        answer=(
            "已创建 wiki/cell_types/natural_killer_cell.md：Definition 概括其"
            "细胞毒性 innate 淋巴细胞身份；Markers 记录谱系定义组合 NCR1"
            "（NKp46）与 KLRD1；Notes 注明来源 raw/fixture_nk_cell_source.md。"
        ),
        tool_calls=[
            {"tool_name": "read_file", "args_display": {"path": "raw/fixture_nk_cell_source.md"}},
            {"tool_name": "write_file", "args_display": {"path": _PAGE}},
        ],
    )


def _maintain(ctx: ScriptContext) -> ScriptResult:
    page = ctx.workspace / _PAGE
    current = page.read_text(encoding="utf-8")
    if "XCL1" not in current:
        page.write_text(
            _PAGE_TEMPLATE.format(extra_markers=_MAINTAIN_EXTRA_MARKERS),
            encoding="utf-8",
        )
    _commit(ctx.workspace, _PAGE)
    return ScriptResult(
        answer=(
            "已在 wiki/cell_types/natural_killer_cell.md 的 Markers 小节补充："
            "活化亚群额外表达 XCL1，并注明 NCR1 单独不足以区分 NK 与 ILC1。"
        ),
        tool_calls=[
            {"tool_name": "edit_file", "args_display": {"path": _PAGE}},
        ],
    )


def _query(ctx: ScriptContext) -> ScriptResult:
    if "活化" in ctx.message:
        answer = (
            "自然杀伤细胞活化后额外表达 XCL1；谱系定义组合仍是 NCR1（NKp46）"
            "与 KLRD1。见 wiki/cell_types/natural_killer_cell.md。"
        )
    else:
        answer = (
            "自然杀伤细胞的谱系定义标记组合是 NCR1（NKp46）与 KLRD1。见 "
            "wiki/cell_types/natural_killer_cell.md。"
        )
    return ScriptResult(
        answer=answer,
        tool_calls=[
            {"tool_name": "read_file", "args_display": {"path": _PAGE}},
        ],
    )


def respond(ctx: ScriptContext) -> ScriptResult:
    if ctx.resume_answers is not None:
        raise RuntimeError("oracle does not ask questions; unexpected resume")
    message = ctx.message
    if "创建页面" in message and "natural_killer_cell" in message:
        return _build(ctx)
    if "补充" in message and "XCL1" in message:
        return _maintain(ctx)
    if "只读查询" in message and "自然杀伤细胞" in message:
        return _query(ctx)
    raise RuntimeError(f"oracle has no reference action for message: {message[:80]}")
