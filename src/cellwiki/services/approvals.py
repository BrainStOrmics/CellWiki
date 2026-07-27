# =============================================================================
# 审批服务 —— 不可变 ChangeSet 的持久化人工审批决策
# =============================================================================

"""Persistent human decisions for immutable ChangeSets."""

from __future__ import annotations

from pathlib import Path

from cellwiki.domain.contracts import ApprovalDecision


# ---------------------------------------------------------------------------
# 审批冲突异常 —— 当已终审的决策被替换为不同决策时抛出
# ---------------------------------------------------------------------------
class ApprovalConflictError(ValueError):
    """Raised when a finalized decision is replaced with a different decision."""


# ---------------------------------------------------------------------------
# ApprovalRepository —— 审批决策仓库
# 每个 ChangeSet 只保留一条可审计、不可变的人工审批决策。
# 使用文件系统存储，以 change_set_id 为文件名。
# 写入采用原子操作（先写临时文件再重命名），避免部分写入。
# 幂等性：如果新决策与已有决策完全相同，则视为重试，返回已有决策。
# ---------------------------------------------------------------------------
class ApprovalRepository:
    """Keep one auditable, immutable human decision per ChangeSet."""

    def __init__(self, project_root: Path):
        # 审批决策存储在 data/runtime/approvals/ 目录下
        self.directory = Path(project_root) / "data" / "runtime" / "approvals"

    # 保存审批决策，如果已存在相同决策则幂等返回
    def save(self, change_set_id: str, decision: ApprovalDecision) -> ApprovalDecision:
        path = self._path(change_set_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            # 读取已有决策
            existing = ApprovalDecision.model_validate_json(path.read_text(encoding="utf-8"))
            # 重试会创建新时间戳，因此幂等性基于实际决策内容
            if (
                existing.approved == decision.approved
                and existing.decided_by == decision.decided_by
                and existing.reason == decision.reason
            ):
                return existing
            # 如果决策内容不同，抛出冲突异常
            raise ApprovalConflictError(f"ChangeSet {change_set_id!r} already has a final decision")
        # 原子写入：先写临时文件，再重命名替换
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(decision.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return decision

    # 获取审批决策，不存在则返回 None
    def get(self, change_set_id: str) -> ApprovalDecision | None:
        path = self._path(change_set_id)
        if not path.exists():
            return None
        return ApprovalDecision.model_validate_json(path.read_text(encoding="utf-8"))

    # 根据 change_set_id 生成文件路径，验证 ID 格式
    def _path(self, change_set_id: str) -> Path:
        if not change_set_id.startswith("cs_"):
            raise ValueError("change_set_id must start with 'cs_'")
        return self.directory / f"{change_set_id}.json"
