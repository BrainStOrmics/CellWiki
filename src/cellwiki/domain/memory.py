# =============================================================================
# 长期记忆合约 —— 受控的智能体记忆，不含模型私有推理内容
# =============================================================================
# 定义 MemoryKind（情景记忆/稳定记忆）、MemoryCandidate（候选）、
# MemoryRecord（持久化记录）和 MemoryRecall（召回查询）的完整数据模型。
# 明确禁止存储链式推理等内部思维过程，仅保存任务结果。
# =============================================================================

"""Governed long-term memory contracts; model-private reasoning is intentionally absent."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import Field, field_validator

from cellwiki.domain.contracts import ContractModel


# ---- 记忆类型 ----
# EPISODE = 情景记忆（请求/结果对，自动记录）
# STABLE = 稳定记忆（长期保留的关键知识，需确定性键）
class MemoryKind(str, Enum):
    EPISODE = "episode"   # 情景记忆：自动记录的请求/结果对
    STABLE = "stable"     # 稳定记忆：长期保留的关键知识


# ---- 记忆状态 ----
class MemoryStatus(str, Enum):
    ACTIVE = "active"       # 活跃
    CONFLICT = "conflict"   # 冲突（与另一条记忆矛盾）
    EXPIRED = "expired"     # 已过期
    DELETED = "deleted"     # 已删除


# ---- 记忆候选 ----
# 提交给记忆存储的候选记忆，经过验证和去重后成为正式记录。
# content 字段明确禁止存储链式推理等内部思维过程。
# 稳定记忆（STABLE）需要确定性 key 用于去重。
class MemoryCandidate(ContractModel):
    candidate_id: str                                # 候选 ID
    project_id: str                                  # 项目 ID
    kind: MemoryKind                                 # 记忆类型
    content: str = Field(min_length=1, max_length=4000)  # 记忆内容
    key: str | None = Field(default=None, max_length=200)  # 确定性键（稳定记忆必需）
    run_id: str | None = Field(default=None, max_length=128)  # 关联运行 ID
    confidence: float = Field(default=0.7, ge=0, le=1)  # 置信度（0-1）
    tags: list[str] = Field(default_factory=list, max_length=20)  # 标签
    expires_at: datetime | None = None               # 过期时间

    # 验证：拒绝包含链式推理等内部思维过程的记忆内容
    @field_validator("content")
    @classmethod
    def reject_hidden_reasoning_labels(cls, value: str) -> str:
        """Reject explicit chain-of-thought payloads instead of trying to sanitize secrets."""
        lowered = value.lower()
        # 禁止包含的中英文链式推理标记
        forbidden = ("chain of thought", "hidden reasoning", "思维链", "内部推理")
        if any(marker in lowered for marker in forbidden):
            raise ValueError("memory candidates must contain outcomes, not hidden reasoning")
        # 规范化空白字符
        return " ".join(value.split())


# ---- 记忆记录 ----
# 持久化后的记忆记录，包含状态、冲突信息和时间戳
class MemoryRecord(ContractModel):
    memory_id: str                               # 记忆唯一标识
    project_id: str                              # 项目 ID
    kind: MemoryKind                             # 记忆类型
    content: str                                 # 记忆内容
    key: str | None = None                       # 确定性键
    run_id: str | None = None                    # 关联运行 ID
    confidence: float = Field(ge=0, le=1)        # 置信度
    tags: list[str] = Field(default_factory=list)  # 标签
    status: MemoryStatus = MemoryStatus.ACTIVE   # 当前状态
    conflicts_with: list[str] = Field(default_factory=list)  # 冲突的记忆 ID 列表
    expires_at: datetime | None = None           # 过期时间
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 创建时间
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 更新时间


# ---- 记忆召回 ----
# 记忆召回查询的记录，包含查询文本、召回的记录 ID 和估算 token 数
class MemoryRecall(ContractModel):
    recall_id: str                               # 召回记录 ID
    project_id: str                              # 项目 ID
    query: str                                   # 查询文本
    memory_ids: list[str]                        # 召回的记录 ID 列表
    estimated_tokens: int = Field(ge=0)           # 估算的 token 消耗
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 创建时间

