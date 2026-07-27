# =============================================================================
# 领域合约 —— CellWiki 工作流、智能体和 API 共享的稳定契约
# =============================================================================
# 所有核心数据结构（SourceRecord、ChangeSet、Claim 等）均定义在此处，
# 确保不同模块之间使用一致的不可变类型进行通信和持久化。
# =============================================================================

"""Stable contracts shared by CellWiki workflows, agents, and product APIs."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# ContractModel —— 所有持久化智能体合约的严格不可变基类
# extra="forbid" 禁止额外字段，frozen=True 确保不可变性
# ---------------------------------------------------------------------------
class ContractModel(BaseModel):
    """Strict immutable base for persisted Agentic CellWiki contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- 来源状态 ----
class SourceStatus(str, Enum):
    REGISTERED = "registered"   # 已注册
    ANALYZED = "analyzed"       # 已分析
    FAILED = "failed"           # 失败
    RETRACTED = "retracted"     # 已撤回


# ---- 任务状态 ----
# 桌面端导入时间线展示的生命周期状态
class TaskStatus(str, Enum):
    """Lifecycle states surfaced by the desktop ingest timeline."""

    RUNNING = "running"               # 运行中
    AWAITING_REVIEW = "awaiting_review"  # 等待审查
    COMMITTING = "committing"         # 正在提交
    COMMITTED = "committed"           # 已提交
    REJECTED = "rejected"             # 已拒绝
    CANCELLED = "cancelled"           # 已取消
    FAILED = "failed"                 # 失败


# ---- Pipeline 任务类型 ----
class PipelineTaskType(str, Enum):
    """Mutating knowledge-pipeline operations that share the project lease."""

    INGEST = "ingest"
    LINT = "lint"
    COMMIT = "commit"


# ---- 审批策略 ----
class ApprovalPolicy(str, Enum):
    """Project-level policy controlling whether a ChangeSet waits for a user."""

    MANUAL = "manual"
    AUTO_ALL = "auto_all"


# ---- 知识库快照 ----
class KnowledgeSnapshot(ContractModel):
    """Immutable view of the formal knowledge state seen by one pipeline task."""

    snapshot_id: str
    project_id: str = "cellwiki"
    task_type: PipelineTaskType
    run_id: str
    knowledge_version: str
    inventory: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---- 导入阶段 ----
# 稳定的事件阶段，事件消息可以演进而不破坏客户端
class IngestStage(str, Enum):
    """Stable ingest stages; event messages may evolve without breaking clients."""

    SOURCE_READ = "source_read"               # 读取来源
    PARSING = "parsing"                       # 解析
    CHUNKING = "chunking"                     # 分块
    TEXT_EXTRACTION = "text_extraction"        # 文本提取
    ENTITY_EXTRACTION = "entity_extraction"    # 实体提取
    VALIDATION = "validation"                  # 验证
    CONFLICT_ANALYSIS = "conflict_analysis"    # 冲突分析
    CHANGESET = "changeset"                    # 变更集生成
    HUMAN_REVIEW = "human_review"              # 人工审查
    PUBLISH = "publish"                        # 发布
    LINT = "lint"                              # 质量检查


# ---- 来源记录 ----
# 注册的文档来源，包含内容哈希、解析状态和元数据
class SourceRecord(ContractModel):
    source_id: str                          # 来源唯一标识
    source_type: str                        # 来源类型（paper, markdown, txt 等）
    original_name: str                      # 原始文件名
    stored_path: str                        # 存储路径
    content_hash: str                       # 内容哈希（用于去重）
    status: SourceStatus = SourceStatus.REGISTERED  # 当前状态
    parser_name: str | None = None          # 使用的解析器名称
    parser_version: str | None = None       # 解析器版本
    parse_hash: str | None = None           # 解析结果哈希
    text_hash: str | None = None            # 提取文本的哈希
    error_reason: str | None = None         # 错误原因
    metadata: dict[str, Any] = Field(default_factory=dict)  # 附加元数据
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 创建时间


# ---- 任务事件 ----
# 来自导入运行的一条不可变、追加式观察记录
class TaskEvent(ContractModel):
    """One immutable, append-only observation from an ingest run."""

    event_id: str                        # 事件唯一标识
    run_id: str                          # 运行 ID
    source_id: str                       # 来源 ID
    stage: IngestStage                   # 事件阶段
    status: TaskStatus                   # 事件状态
    message: str                         # 人类可读描述
    progress: int = Field(ge=0, le=100)  # 进度百分比 0-100
    change_set_id: str | None = None     # 关联的 ChangeSet ID
    detail: dict[str, Any] = Field(default_factory=dict)  # 附加详情
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---- 风险等级 ----
class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---- 变更操作类型 ----
class ChangeOperationType(str, Enum):
    UPSERT_EXTRACTION = "upsert_extraction"   # 更新/插入提取
    UPDATE_CURATION = "update_curation"       # 更新策展
    RETRACT_SOURCE = "retract_source"         # 撤回来源
    APPLY_LINT_FIX = "apply_lint_fix"         # 应用 lint 修复


# 领域 ID 正则：字母数字开头，最长 128 字符，允许 . _ : -
_DOMAIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


# ---- 变更操作 ----
# ChangeSet 中的单个操作，定义了要执行的具体变更
class ChangeOperation(ContractModel):
    type: ChangeOperationType                 # 操作类型
    target_id: str                            # 目标 ID（如细胞类型名称）
    payload: dict[str, Any] = Field(default_factory=dict)  # 操作负载
    expected_version: str | None = None       # 期望的版本（用于乐观锁）

    # 验证 target_id 必须是领域标识符，不能是文件路径
    @field_validator("target_id")
    @classmethod
    def validate_domain_id(cls, value: str) -> str:
        if not _DOMAIN_ID.fullmatch(value):
            raise ValueError("target_id must be a domain identifier, not a file path")
        return value


# ---- 证据类型 ----
class EvidenceType(str, Enum):
    DIRECT = "direct"              # 直接证据
    SUPPORTING = "supporting"      # 支持性证据
    CONTRADICTING = "contradicting"  # 矛盾证据
    BACKGROUND = "background"      # 背景信息


# ---- 证据引用 ----
# 包含来源、定位器和摘录的完整证据引用
class EvidenceReference(ContractModel):
    evidence_id: str = ""                       # 证据 ID
    source_id: str                              # 来源 ID
    locator: str = ""                           # 定位器
    excerpt: str = ""                           # 摘录文本
    page_start: int | None = Field(default=None, ge=1)  # 起始页码
    page_end: int | None = Field(default=None, ge=1)    # 结束页码
    section: str = ""                           # 章节
    block_id: str | None = None                 # 块 ID
    char_start: int | None = Field(default=None, ge=0)  # 起始字符位置
    char_end: int | None = Field(default=None, ge=0)    # 结束字符位置
    evidence_type: EvidenceType = EvidenceType.SUPPORTING  # 证据类型
    confidence: str = "medium"                  # 置信度

    # 验证页码范围：结束不能小于开始
    @field_validator("page_end")
    @classmethod
    def require_valid_page_range(cls, value: int | None, info) -> int | None:
        start = info.data.get("page_start")
        if value is not None and start is not None and value < start:
            raise ValueError("page_end cannot precede page_start")
        return value

    # 验证字符范围：结束不能小于开始
    @field_validator("char_end")
    @classmethod
    def require_valid_character_range(cls, value: int | None, info) -> int | None:
        start = info.data.get("char_start")
        if value is not None and start is not None and value < start:
            raise ValueError("char_end cannot precede char_start")
        return value


# ---- 科学声明 ----
# 一条归一化的科学断言，包含声明级别的来源证据
class Claim(ContractModel):
    """One normalized scientific assertion with claim-level source evidence."""

    claim_id: str                              # 声明 ID
    subject: str                               # 主体
    predicate: str                             # 谓词（如 "expresses", "regulates"）
    object: str                                # 客体
    qualifiers: dict[str, Any] = Field(default_factory=dict)  # 限定符
    evidence: list[EvidenceReference]           # 证据引用列表
    confidence: str = "medium"                 # 置信度

    # 验证：已发布的声明至少需要一个证据引用
    @field_validator("evidence")
    @classmethod
    def require_evidence(cls, value: list[EvidenceReference]) -> list[EvidenceReference]:
        if not value:
            raise ValueError("published claims require at least one evidence reference")
        return value


# ---- 审查项 ----
# ChangeSet 审查期间必须可见的冲突或证据缺口
class ReviewItem(ContractModel):
    """A conflict or evidence gap that must remain visible during ChangeSet review."""

    review_item_id: str                  # 审查项 ID
    type: str                            # 类型
    target_id: str                       # 目标 ID
    description: str                     # 描述
    severity: RiskLevel = RiskLevel.MEDIUM  # 严重程度
    claim_ids: list[str] = Field(default_factory=list)  # 关联的声明 ID


# ---- 变更集（ChangeSet）----
# 知识库变更的不可变提议，包含操作列表、证据、审查项和风险评级。
# 必须至少包含一个操作。
class ChangeSet(ContractModel):
    change_set_id: str                           # ChangeSet 唯一标识
    run_id: str                                  # 运行 ID
    project_id: str                              # 项目 ID
    operations: list[ChangeOperation]             # 变更操作列表
    evidence: list[EvidenceReference] = Field(default_factory=list)  # 证据
    review_items: list[ReviewItem] = Field(default_factory=list)     # 审查项
    risk: RiskLevel                               # 风险评级
    reason: str                                   # 变更原因
    schema_version: str = "3"                     # 模式版本
    snapshot_id: str | None = None                # 生成该提议时观察到的知识快照
    base_knowledge_version: str | None = None     # 提交前用于乐观并发检查的正式版本
    revision_id: str | None = None                # 触发该提议的 IngestRevision
    parent_change_set_id: str | None = None       # 上一条不可变 ChangeSet
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # 验证：ChangeSet 必须至少包含一个操作
    @field_validator("operations")
    @classmethod
    def require_operations(cls, value: list[ChangeOperation]) -> list[ChangeOperation]:
        if not value:
            raise ValueError("a ChangeSet must contain at least one operation")
        return value


class ChangeSetRebaseStatus(str, Enum):
    """Outcome of checking an immutable proposal against a newer knowledge base."""

    CURRENT = "current"
    REBASED = "rebased"
    CONFLICT = "conflict"


class ChangeSetRebaseResult(ContractModel):
    """Explicit rebase result; conflicts are data returned to the Assistant/UI."""

    original_change_set_id: str
    status: ChangeSetRebaseStatus
    rebased_change_set_id: str | None = None
    previous_base_knowledge_version: str | None = None
    current_knowledge_version: str
    conflicting_target_ids: list[str] = Field(default_factory=list)
    message: str


# ---- 审批决策 ----
# 用户或智能体对 ChangeSet 的审批决定
class ApprovalDecision(ContractModel):
    approved: bool                               # 是否批准
    decided_by: str                              # 决策者（"desktop-user", "agent-hitl" 等）
    reason: str = ""                             # 决策理由
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 决策时间


# ---- 提交结果 ----
# CentralWriter 提交 ChangeSet 后的结果
class CommitResult(ContractModel):
    commit_id: str                               # 提交 ID
    change_set_id: str                           # 关联的 ChangeSet ID
    status: str                                  # 提交状态
    changed_targets: list[str]                   # 被变更的目标列表
    snapshot_id: str                             # 快照 ID（用于回滚）
    committed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 提交时间


# ---- 智能体上下文 ----
# 从桌面端传递到智能体运行时的上下文信息
class WikiAgentContext(ContractModel):
    project_id: str = "cellwiki"                 # 项目 ID
    page_id: str | None = None                    # 当前页面 ID
    source_id: str | None = None                  # 当前来源 ID
    selected_text: str | None = None              # 用户选中的文本
    thread_id: str | None = None                  # 对话线程 ID


# ---- 引用 ----
# 智能体回答中的引用信息
class Citation(ContractModel):
    page_id: str                                 # 页面 ID
    source_id: str | None = None                  # 来源 ID
    locator: str | None = None                    # 定位器


# ---- 智能体回答 ----
# 智能体对用户问题的结构化回答，包含引用、置信度和缺失证据信息
class AgentAnswer(ContractModel):
    answer: str                                  # 回答文本
    citations: list[Citation] = Field(default_factory=list)  # 引用列表
    confidence: str = "medium"                   # 回答置信度
    missing_evidence: list[str] = Field(default_factory=list)  # 缺失的证据
    knowledge_scope: str = "formal"
    knowledge_version: str | None = None
