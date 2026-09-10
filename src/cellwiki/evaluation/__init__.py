# =============================================================================
# 智能体评估模块 —— 发布门控的稳定评估合约
# =============================================================================
# 导出两套确定性合约：semantic 面向旧治理链的答案清单，agent_eval 面向当前
# 工作区架构的运行记录（引用路径、git 改动面、lint 结论）。

"""Stable evaluation contracts for release gating."""

from cellwiki.evaluation.agent_eval import cited_paths, evaluate_agent_predictions
from cellwiki.evaluation.semantic import evaluate_semantic_predictions

__all__ = [
    "cited_paths",
    "evaluate_agent_predictions",
    "evaluate_semantic_predictions",
]
