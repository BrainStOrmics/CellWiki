# =============================================================================
# 变更差异对比 —— 具有领域感知列表索引的字段级 ChangeSet 预览
# =============================================================================

"""Field-level ChangeSet previews with domain-aware list indexing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cellwiki.domain.changes import FieldChangeType, FieldDiff
from cellwiki.domain.contracts import ChangeOperation, ChangeOperationType, ChangeSet


# ---------------------------------------------------------------------------
# ChangeSetDiffService —— 变更差异对比服务
# 为 ChangeSet 审查 UI 提供字段级差异预览。
# 隐藏了形式化存储查找和递归差异比较的底层机制。
# 支持不同类型的操作（提取、策展、lint 修复），每种操作有不同的
# "before" 值来源。差异结果限制为 500 个字段以防止 UI 过载。
# ---------------------------------------------------------------------------
class ChangeSetDiffService:
    """Hide formal storage lookup and recursive diff mechanics behind one review interface."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()

    # 生成 ChangeSet 的完整预览
    def preview(self, change_set: ChangeSet) -> dict[str, Any]:
        operations = [self._operation_preview(operation) for operation in change_set.operations]
        # 统计各类变更的数量
        counts = {change_type.value: 0 for change_type in FieldChangeType}
        for operation in operations:
            for difference in operation["field_diffs"]:
                counts[difference["change_type"]] += 1
        return {"operations": operations, "summary": counts}

    # 生成单个操作的预览
    def _operation_preview(self, operation: ChangeOperation) -> dict[str, Any]:
        before, after = self._values(operation)
        # 归并列表后计算差异（将实体列表转换为按名称索引的字典）
        field_diffs = _diff_values(_normalize_lists(before), _normalize_lists(after))
        # 提取细胞类型实体信息（最多 100 个）
        cell_types = operation.payload.get("cell_types", [])
        if not isinstance(cell_types, list):
            cell_types = []
        entities = []
        for cell_type in cell_types[:100]:
            if not isinstance(cell_type, dict):
                continue
            markers = cell_type.get("markers", [])
            entities.append(
                {
                    "name": cell_type.get("name")
                    or cell_type.get("standard_name")
                    or "Unnamed cell type",
                    "standard_name": cell_type.get("standard_name"),
                    "marker_count": len(markers) if isinstance(markers, list) else 0,
                }
            )
        return {
            "type": operation.type.value,
            "target_id": operation.target_id,
            "entity_count": len(cell_types),
            "entities": entities,
            # 最多显示 500 个字段差异，防止 UI 过载
            "field_diffs": [difference.model_dump(mode="json") for difference in field_diffs[:500]],
            "diff_truncated": len(field_diffs) > 500,
        }

    # 根据操作类型获取操作前后的值
    # UPSERT_EXTRACTION: 从 extraction 目录读取已有数据
    # UPDATE_CURATION: 从 curation 目录读取已有策展内容
    # APPLY_LINT_FIX: 从 lint_fixes 目录读取已有标记文件
    def _values(self, operation: ChangeOperation) -> tuple[Any, Any]:
        if operation.type == ChangeOperationType.UPSERT_EXTRACTION:
            path = self.project_root / "data" / "extraction" / f"{operation.target_id}.json"
            before = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            return before, operation.payload
        if operation.type == ChangeOperationType.UPDATE_CURATION:
            path = self.project_root / "wiki" / "curation" / "cell_types" / f"{operation.target_id}.md"
            before = path.read_text(encoding="utf-8") if path.exists() else ""
            return before, operation.payload.get("content", "")
        if operation.type == ChangeOperationType.APPLY_LINT_FIX:
            path = self.project_root / "data" / "runtime" / "lint_fixes" / f"{operation.target_id}.json"
            before = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            return before, operation.payload
        return {}, operation.payload


# 领域感知的列表键：当列表中的字典包含这些键时，将其转换为按值索引的字典
# 以实现更精确的差异比较（而不是按位置比较）
_LIST_KEYS = ("standard_name", "claim_id", "evidence_id", "gene_symbol", "review_item_id")


# 归并列表：将包含稳定 ID 键的列表转换为按 ID 索引的字典
# 这样差异比较可以按 ID 匹配而非按位置，结果更准确
def _normalize_lists(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_lists(item) for key, item in value.items()}
    if isinstance(value, list):
        # 检查列表中的字典是否包含稳定的 ID 键
        for key in _LIST_KEYS:
            if value and all(isinstance(item, dict) and item.get(key) for item in value):
                names = [str(item[key]) for item in value]
                if len(names) == len(set(names)):
                    # 所有 ID 唯一，转换为按 ID 索引的字典
                    return {name: _normalize_lists(item) for name, item in zip(names, value)}
        return [_normalize_lists(item) for item in value]
    return value


# 递归比较两个值，返回字段级差异列表
# 支持字典和列表的递归比较，标量值直接比较
def _diff_values(before: Any, after: Any, path: str = "") -> list[FieldDiff]:
    if before == after:
        return []
    # 字典比较：遍历所有键，检测新增、删除和修改
    if isinstance(before, dict) and isinstance(after, dict):
        differences: list[FieldDiff] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{_escape_pointer(str(key))}"
            if key not in before:
                differences.append(
                    FieldDiff(path=child, change_type=FieldChangeType.ADDED, after=after[key])
                )
            elif key not in after:
                differences.append(
                    FieldDiff(path=child, change_type=FieldChangeType.REMOVED, before=before[key])
                )
            else:
                differences.extend(_diff_values(before[key], after[key], child))
        return differences
    # 列表比较：按索引位置逐个比较
    if isinstance(before, list) and isinstance(after, list):
        differences = []
        for index in range(max(len(before), len(after))):
            child = f"{path}/{index}"
            if index >= len(before):
                differences.append(
                    FieldDiff(path=child, change_type=FieldChangeType.ADDED, after=after[index])
                )
            elif index >= len(after):
                differences.append(
                    FieldDiff(path=child, change_type=FieldChangeType.REMOVED, before=before[index])
                )
            else:
                differences.extend(_diff_values(before[index], after[index], child))
        return differences
    # 标量值：直接标记为 CHANGED
    return [
        FieldDiff(
            path=path or "/",
            change_type=FieldChangeType.CHANGED,
            before=before,
            after=after,
        )
    ]


# 转义 JSON Pointer 中的特殊字符（~ 和 /）
def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")

