# =============================================================================
# 负向变异：infra_error —— 基础设施错误伪装成 Agent 失败
# =============================================================================
# 脚本在第一轮就抛异常：run 以 error_type=system 终结。scorer 必须把它归为
# infrastructure 并标记 invalid_run——不算 Agent 能力失败，也绝不算通过。
# =============================================================================

from __future__ import annotations

from cellwiki.evaluation.agent_eval_v2 import ScriptContext, ScriptResult

MUTATION = {
    "mutation_id": "infra_error",
    "scenario_id": "build_from_raw",
    "expected_codes": [],
    "expected_primary": "infrastructure",
    "expected_invalid_run": True,
    "description": "provider 异常导致 run failed：必须标 infrastructure + invalid_run。",
}


def respond(ctx: ScriptContext) -> ScriptResult:
    raise RuntimeError("simulated provider outage (mutation)")
