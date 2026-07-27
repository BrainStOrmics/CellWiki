# =============================================================================
# 外部研究合约 —— 需经审批才能进入正式知识库的外部研究结果
# =============================================================================
# 定义 ExternalResearchResult（外部来源的研究结果）和 ResearchCandidate
# （注册后的候选来源）的数据模型。外部研究必须经过导入、生成 ChangeSet、
# 人工审批后才能影响正式 Wiki 知识。
# =============================================================================

"""Contracts for external research that remains outside formal knowledge until approval."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import Field, HttpUrl

from cellwiki.domain.contracts import ContractModel


# ---- 研究发表状态 ----
# 外部研究文献的发表状态分类
class ResearchPublicationStatus(str, Enum):
    PEER_REVIEWED = "peer_reviewed"   # 同行评审
    PREPRINT = "preprint"             # 预印本
    RETRACTED = "retracted"           # 已撤回
    UNKNOWN = "unknown"               # 未知


class ResearchCandidateStatus(str, Enum):
    """Lifecycle status for a registered research result."""

    CANDIDATE = "candidate"
    DUPLICATE = "duplicate"
    INGEST_READY = "ingest_ready"
    REJECTED = "rejected"


class ResearchRefreshStatus(str, Enum):
    """Bounded lifecycle for one external research refresh run."""

    COMPLETED = "completed"
    FAILED = "failed"


# ---- 外部研究结果 ----
# 从外部来源获取的研究结果，尚未注册为正式来源。
# 包含外部 ID、标题、URL、作者、发表年份、DOI、摘要等信息。
# 必须经过注册→导入→ChangeSet→人工审批才能影响正式知识库。
class ExternalResearchResult(ContractModel):
    external_id: str                                          # 外部来源 ID
    title: str                                                # 论文标题
    url: HttpUrl                                              # 论文 URL（Pydantic 验证 URL 格式）
    authors: list[str] = Field(default_factory=list)           # 作者列表
    published_year: int | None = Field(default=None, ge=1500, le=2200)  # 发表年份
    doi: str | None = None                                     # DOI 标识符
    abstract: str = ""                                         # 摘要
    publication_status: ResearchPublicationStatus = ResearchPublicationStatus.UNKNOWN  # 发表状态
    is_paywalled: bool | None = None                           # 是否付费墙


# ---- 研究候选 ----
# 已注册为 SourceRecord 的外部研究候选，等待进一步处理。
# 记录查询信息、来源信息和访问时间，供后续导入参考。
class ResearchCandidate(ContractModel):
    candidate_id: str                              # 候选 ID
    project_id: str                                # 项目 ID
    query: str                                     # 搜索查询
    source_id: str                                 # 注册后的来源 ID
    title: str                                     # 论文标题
    url: HttpUrl                                   # 论文 URL
    status: ResearchPublicationStatus              # 发表状态
    warnings: list[str] = Field(default_factory=list)  # 警告信息
    accessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 访问时间
    candidate_status: ResearchCandidateStatus = ResearchCandidateStatus.CANDIDATE
    provider: str = "unknown"
    refresh_run_id: str | None = None
    snapshot_id: str | None = None
    dedup_key: str | None = None


class ResearchRefreshRun(ContractModel):
    """Auditable external refresh summary; it never represents formal Wiki writes."""

    refresh_run_id: str
    project_id: str
    query: str
    provider: str
    snapshot_id: str
    knowledge_version: str
    requested_limit: int
    status: ResearchRefreshStatus
    candidate_ids: list[str] = Field(default_factory=list)
    duplicate_candidate_ids: list[str] = Field(default_factory=list)
    provider_provenance: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
