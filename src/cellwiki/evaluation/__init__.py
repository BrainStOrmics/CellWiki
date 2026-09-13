# =============================================================================
# 智能体评估模块 —— 发布门控的稳定评估合约
# =============================================================================
# agent_eval 面向当前工作区架构的运行记录（引用路径、git 改动面、lint 结论）；
# agent_eval_v2 是旁路多轮评测体系（suite/fixture/oracle/mutation）。

"""Stable evaluation contracts for release gating."""

from cellwiki.evaluation.agent_eval import (
    cited_paths,
    evaluate_agent_predictions,
    threshold_failures,
)

__all__ = [
    "cited_paths",
    "evaluate_agent_predictions",
    "threshold_failures",
]
