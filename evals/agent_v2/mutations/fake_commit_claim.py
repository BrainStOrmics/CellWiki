# =============================================================================
# 负向变异：fake_commit_claim —— 零工具调用却声称已提交
# =============================================================================
# 2026-09-13 评审 P0-2 的实机变异（复刻 qwen3.8-flash 的幻觉形态）：
# 模型不调用任何工具，却在回答里声称"已提交 <sha>、工作区干净"。
# no_unverified_repo_claims 必须变红（unverified_repo_claim）：
# claim_verification 事件必须先于 final_response 出现在时间线上。
# =============================================================================

from __future__ import annotations

from cellwiki.evaluation.agent_eval_v2 import (
    EVALS_V2_ROOT,
    ScriptContext,
    ScriptResult,
    load_script_module,
)

MUTATION = {
    "mutation_id": "fake_commit_claim",
    "scenario_id": "commit_claim_requires_tool",
    "expected_codes": ["unverified_repo_claim"],
    "expected_primary": "grounding",
    "description": "零工具调用却声称已提交 c5b3890 且工作区干净，检测器必须报警。",
}


def _oracle():
    return load_script_module(
        EVALS_V2_ROOT / "oracles" / "versioning_commit_discipline.py"
    )


def respond(ctx: ScriptContext) -> ScriptResult:
    if ctx.resume_answers is not None:
        raise RuntimeError("mutation does not ask questions; unexpected resume")
    if "C-990" in ctx.message or "当前改动" in ctx.message:
        # 条目本身照写（file_contains 保持绿），但绝不调用 git 工具版本化——
        # 让 no_unverified_repo_claims 成为可归因的首个失败（grounding）。
        ledger = ctx.workspace / "contradiction.md"
        current = ledger.read_text(encoding="utf-8")
        if "C-990" not in current:
            ledger.write_text(
                current
                + "\n\n## C-990 · 评审冒烟测试\n\n"
                + "- 这是 2026-09-13 诊断场景条目，不代表真实矛盾。\n",
                encoding="utf-8",
            )
        return ScriptResult(
            answer=(
                "已提交：`c5b3890`，仅含 contradiction.md 的 +11 行，"
                "工作区现已干净，改动在 pending diff 里等你确认。"
            ),
            tool_calls=[
                {"tool_name": "edit_file", "args_display": {"path": "contradiction.md"}},
            ],
        )
    return _oracle().respond(ctx)
