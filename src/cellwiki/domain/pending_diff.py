# =============================================================================
# 待确认 diff 领域模型
# =============================================================================
# pending diff 是"用户批准写入知识库"的唯一入口，一个 run 可产生一串**审批单元**
# （diff_<run_id>_<n>，n 从 1 递增；旧库中无后缀的 diff_<run_id> 视为单元 1）：
# 首单元基线 = run.snapshot_commit，其后单元基线 = 上一单元的 head_commit。
# 用户接受 -> accepted（审计生效），拒绝 -> rejected（系统 revert 本单元的 commit，
# 撤销范围永不及格此前已判定的内容）。**审批单元的边界是判定，不是发布**：上一单元
# 仍未判定时，run 再次发布（问题挂起/回答续跑等）就地更新该 pending 行，保持
# "最多一个未处理待确认 diff"不变量；已判定记录只写一次、不可回退为 pending。
# v1 没有部分接受/部分拒绝。
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