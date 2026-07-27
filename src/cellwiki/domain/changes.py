# =============================================================================
# 变更预览 —— 面向人工审查的字段级 ChangeSet 差异对比
# =============================================================================
# 定义 FieldDiff 模型，用于展示 ChangeSet 中各字段的增、删、改情况，
# 使审查者能够快速理解变更内容，无需逐行比对原始数据。
# =============================================================================

"""Human-review contracts for field-level ChangeSet previews."""

from __future__ import annotations

from enum import Enum
from typing import Any

from cellwiki.domain.contracts import ContractModel


# ---- 字段变更类型 ----
# 定义 ChangeSet 中单个字段的三种变更类型
class FieldChangeType(str, Enum):
    ADDED = "added"       # 新增字段
    REMOVED = "removed"   # 删除字段
    CHANGED = "changed"   # 修改字段


# ---- 字段差异 ----
# 表示单个字段在变更前后的差异，用于 ChangeSet 审查 UI 展示。
# path 使用 JSON Pointer 格式（如 /cell_types/0/name），
# before 和 after 分别表示变更前后的值。
class FieldDiff(ContractModel):
    path: str               # 字段路径（JSON Pointer 格式）
    change_type: FieldChangeType  # 变更类型
    before: Any = None      # 变更前的值（新增时为空）
    after: Any = None       # 变更后的值（删除时为空）

