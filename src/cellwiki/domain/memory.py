# =============================================================================
# 工作区记忆领域模型
# =============================================================================
# 记忆是工作区级的协作记忆：记住用户在这个知识库里的偏好、约定和跑通的做法，
# 跨线程可召回，但不是知识权威（ADR-0016）。默认关闭；Agent 只产候选，
# 由单写方合并写成型文件。这里只承载数据结构与固定枚举，不承载 IO。
# =============================================================================

"""Workspace-scoped memory contracts (candidates, active entries, summary)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from cellwiki.domain.contracts import ContractModel
from pydantic import Field


class MemoryKind(str, Enum):
    """What a memory entry records; never a scientific conclusion."""

    PREFERENCE = "preference"            # 开发协作方式上的偏好
    CONVENTION = "convention"            # 工作区约定
    LESSON = "lesson"                    # 跑通或踩坑得到的操作经验
    DECISION_POINTER = "decision_pointer"  # 决策理由及其来源指针


class MemoryCandidateStatus(str, Enum):
    """Two-stage write pipeline state for one extracted candidate."""

    PENDING = "pending"        # 已提取，等待合并
    MERGED = "merged"          # 已被 Phase 2 消费
    REJECTED = "rejected"      # 确定性校验拒绝（脱敏、体积、重复）
    SKIPPED = "skipped"        # 低价值，未进入合并


class MemoryTopicFamily(str, Enum):
    """Fixed topic families; Phase 2 rejects anything outside this enum."""

    WIKI_CONTENT = "wiki 内容维护"
    RAW_SOURCES = "raw 与来源"
    PROMPT_CONTEXT = "prompt 与上下文"
    RUN_APPROVAL = "run 与审批"
    EVALUATION = "评估与测试"
    WORKSPACE_ENV = "工作区与环境"


class MemoryCandidate(ContractModel):
    """One candidate extracted from a finished run; not yet part of the memory."""

    memory_id: str
    workspace: str
    kind: MemoryKind
    topic_family: MemoryTopicFamily
    title: str
    body: str
    source_refs: list[str] = Field(default_factory=list)
    origin_run_id: str = ""
    origin_thread_id: str = ""
    status: MemoryCandidateStatus = MemoryCandidateStatus.PENDING
    derived_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_payload(self) -> dict[str, object]:
        return {
            "memory_id": self.memory_id,
            "workspace": self.workspace,
            "kind": self.kind.value,
            "topic_family": self.topic_family.value,
            "title": self.title,
            "body": self.body,
            "source_refs": list(self.source_refs),
            "origin_run_id": self.origin_run_id,
            "origin_thread_id": self.origin_thread_id,
            "status": self.status.value,
            "derived_hash": self.derived_hash,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class MemoryEntry(ContractModel):
    """One active memory entry; Markdown file keeps the authoritative body."""

    memory_id: str
    workspace: str
    kind: MemoryKind
    topic_family: MemoryTopicFamily
    title: str
    file_name: str
    origin_thread_id: str = ""
    origin_run_id: str = ""
    source_refs: list[str] = Field(default_factory=list)
    derived_hash: str = ""
    user_edited: bool = False       # 用户改过：跳过自动合并，直到显式放行
    auto_update: bool = True        # 面板"重新纳入自动更新"置回 True
    usage_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_used_at: datetime | None = None


class MemorySummary(ContractModel):
    """The injected summary; body is truncated separately at injection time."""

    workspace: str
    body: str
    generation: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = [
    "MemoryCandidate",
    "MemoryCandidateStatus",
    "MemoryEntry",
    "MemoryKind",
    "MemorySummary",
    "MemoryTopicFamily",
]
