# =============================================================================
# 待确认 diff 领域模型
# =============================================================================
# pending diff 是"用户批准写入知识库"的唯一入口：run 结束后系统把该 run 的
# 全部 commit（含 spec / 子 Agent 专用 commit）汇成一份 diff，进入
# pending 状态；用户接受 -> accepted（审计生效），拒绝 -> rejected（系统 revert
# 该 run 全部 commit，保留 run 后的其他 commit）。v1 没有部分接受/部分拒绝。
# =============================================================================

"""Domain model for the single pending-diff approval boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from cellwiki.domain.contracts import ContractModel
from pydantic import Field


class PendingDiffStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class PendingDiff(ContractModel):
    """One system-generated, user-resolved diff over a run's commits."""

    diff_id: str
    run_id: str
    thread_id: str
    project_id: str = "cellwiki"
    snapshot_commit: str | None = None      # run 快照点（run 开始前的 HEAD）
    head_commit: str | None = None          # diff 生成时的 HEAD
    commits: list[str] = Field(default_factory=list)   # run 内全部 commit（新→旧）
    files: list[str] = Field(default_factory=list)
    insertions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)
    status: PendingDiffStatus = PendingDiffStatus.PENDING
    resolution: str | None = None           # accepted / rejected 的说明
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    data: dict[str, Any] = Field(default_factory=dict)