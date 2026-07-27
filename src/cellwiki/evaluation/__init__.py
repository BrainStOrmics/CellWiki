# =============================================================================
# 评估模块 —— 发布门控的稳定评估合约
# =============================================================================
# 导出语义评估函数作为模块的公共 API，用于评估提取结果的准确性。

"""Stable evaluation contracts for release gating."""

from cellwiki.evaluation.semantic import evaluate_semantic_predictions

__all__ = ["evaluate_semantic_predictions"]
