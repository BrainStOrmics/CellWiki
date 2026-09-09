# =============================================================================
# 智能体运行合约 —— 独立于 LangGraph 内部事件表示的持久化运行记录
# =============================================================================
# 定义 AgentRun（运行记录）、AgentEvent（追加式事件流）、RunBudget（预算）
# 等数据模型，用于桌面端 UI 展示运行状态、进度和事件流，
# 不依赖 LangGraph 框架的内部实现细节。
# =============================================================================

"""Durable Agent run contracts independent from LangGraph's internal event representation."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import Field

from cellwiki.domain.contracts import ContractModel


# ---- 智能体运行状态 ----
# 完整的运行生命周期：QUEUED → RUNNING → (WAITING_APPROVAL | APPLYING | VERIFYING) → SUCCEEDED/FAILED
# 支持取消（CANCELLING → CANCELLED）和重试（RETRYING）
class AgentRunStatus(str, Enum):
    QUEUED = "queued"                     # 已排队，等待执行
    RUNNING = "running"                   # 运行中
    WAITING_CONFIRMATION = "waiting_confirmation"  # 等待用户确认结构化任务
    WAITING_APPROVAL = "waiting_approval"  # 等待人工审批
    APPLYING = "applying"                 # 正在应用变更
    VERIFYING = "verifying"               # 正在验证结果
    SUCCEEDED = "succeeded"               # 成功完成
    REJECTED = "rejected"                 # 被拒绝
    FAILED = "failed"                     # 失败
    RETRYING = "retrying"                 # 正在重试
    UNFINISHED = "unfinished"             # 未完成：预算/超时进入，可继续/恢复
    CANCELLING = "cancelling"             # 正在取消
    CANCELLED = "cancelled"               # 已取消


# ---- 智能体错误类型 ----
# 错误分类，用于重试策略和用户反馈
class AgentErrorType(str, Enum):
    INPUT = "input"                     # 输入错误
    AUTHENTICATION = "authentication"   # 认证错误
    PERMISSION = "permission"           # 权限错误
    RATE_LIMIT = "rate_limit"           # 速率限制
    TIMEOUT = "timeout"                 # 超时
    BUDGET = "budget"                   # 预算超限
    STRUCTURED_OUTPUT = "structured_output"  # 结构化输出错误
    APPROVAL = "approval"               # 审批错误
    CONFLICT = "conflict"               # 冲突错误
    SYSTEM = "system"                   # 系统错误


# ---- 智能体事件类型 ----
# 桌面端消费的追加式事件，不泄露框架特定对象
class AgentEventType(str, Enum):
    RUN_STATUS = "run_status"               # 运行状态变更
    MESSAGE_DELTA = "message_delta"         # 消息增量（流式）
    REASONING_DELTA = "reasoning_delta"     # 模型推理增量（流式）
    FINAL_RESPONSE = "final_response"       # 最终回答
    TOOL_STARTED = "tool_started"           # 工具调用开始
    TOOL_COMPLETED = "tool_completed"       # 工具调用完成
    TOOL_FAILED = "tool_failed"             # 工具调用失败
    SUBAGENT_STARTED = "subagent_started"   # 子智能体启动
    SUBAGENT_COMPLETED = "subagent_completed"  # 子智能体完成
    PROGRESS = "progress"                   # 进度更新
    TASK_CONFIRMATION_REQUIRED = "task_confirmation_required"  # 需要确认动作型任务
    REVIEW_REQUIRED = "review_required"     # 需要人工审查
    CHANGESET_READY = "changeset_ready"     # ChangeSet 已就绪
    VERIFICATION = "verification"           # 验证结果
    USAGE_UPDATED = "usage_updated"         # 每 run 用量（本段 + 累计）；只在诊断面板展示，不进聊天气泡
    ERROR = "error"                         # 错误


# ---- 运行预算 ----
# 每次智能体运行的资源预算，防止无限执行
class RunBudget(ContractModel):
    max_model_calls: int = Field(default=100, ge=1)       # 最大模型调用次数（默认对齐 AGENT_MAX_TOOL_STEPS）
    max_runtime_seconds: int = Field(default=7200, ge=1)  # 最大运行时间（秒）（默认对齐 AGENT_RUN_MAX_SECONDS）
    max_retries: int = Field(default=3, ge=0)             # 最大重试次数


# ---- 运行用量 ----
# 智能体运行的资源消耗统计
class RunUsage(ContractModel):
    model_calls: int = Field(default=0, ge=0)               # 模型调用次数
    input_tokens: int = Field(default=0, ge=0)               # 输入 token 数
    output_tokens: int = Field(default=0, ge=0)              # 输出 token 数
    cached_input_tokens: int = Field(default=0, ge=0)         # 缓存命中输入 token 数
    cache_creation_input_tokens: int = Field(default=0, ge=0) # 缓存写入输入 token 数
    estimated_cost_usd: float = Field(default=0, ge=0)       # 估算成本（美元）
    tool_calls: int = Field(default=0, ge=0)                 # 工具调用次数
    tool_calls_started: int = Field(default=0, ge=0)
    tool_calls_completed: int = Field(default=0, ge=0)
    tool_calls_failed: int = Field(default=0, ge=0)
    tool_calls_cancelled: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0, ge=0)          # 已用时间（秒）
    read_chars: int = Field(default=0, ge=0)                 # 附件读取字符数（run 级累计）
    read_tokens: int = Field(default=0, ge=0)                # 附件读取估算 token


# ---- 智能体运行记录 ----
# 一次智能体运行的完整持久化记录，包含状态、预算、用量和错误信息
class AgentRun(ContractModel):
    run_id: str                                              # 运行唯一标识
    thread_id: str                                           # 对话线程 ID
    project_id: str = "cellwiki"                              # 项目 ID
    parent_run_id: str | None = None                          # 父运行 ID（用于子运行）
    source_id: str | None = None                              # 关联的来源 ID
    page_id: str | None = None                                # 关联的页面 ID
    selected_text: str | None = None                          # 用户选中的文本
    attachment_ids: list[str] = Field(default_factory=list)   # 当前运行可用的线程附件
    input_message: str = ""                                   # 用户输入消息
    snapshot_commit: str | None = None      # 运行开始时的 git HEAD（pending diff 快照点）
    pending_diff_id: str | None = None      # 运行产出的待确认 diff 标识
    task_kind: str = "conversation"                           # 结构化任务类型
    task_payload: dict[str, Any] = Field(default_factory=dict) # 结构化任务参数
    # ADR-0010 决策 4：每段流结束时写回的最新 checkpoint 标识。升级前产生的 run
    # 一律为 NULL，其"继续/回答问题"走显式失败，不在空图上静默重放。
    checkpoint_id: str | None = None
    # 决策 7：幂等提交键。同一 request_id 命中既有 run 时返回它并置 replayed=True。
    request_id: str | None = None
    # 决策 8：执行配置快照（Layer A + model + budget 短哈希），使历史 run 不受 .env 漂移影响。
    prompt_hash: str | None = None
    model_role: str = "coordinator"                           # 模型角色
    model_name: str = ""                                      # 模型名称
    status: AgentRunStatus = AgentRunStatus.QUEUED            # 当前状态
    budget: RunBudget = Field(default_factory=RunBudget)      # 资源预算
    usage: RunUsage = Field(default_factory=RunUsage)         # 资源用量
    retry_count: int = Field(default=0, ge=0)                 # 重试次数
    error_type: AgentErrorType | None = None                  # 错误类型
    error_message: str | None = None                          # 错误消息
    finished_at: datetime | None = None                       # 终态持久化时间
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 创建时间
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 更新时间


class AgentRunOutcome(ContractModel):
    """Self-contained terminal outcome persisted atomically with the run row."""

    status: AgentRunStatus
    message: str
    error_type: AgentErrorType | None = None
    error_message: str | None = None
    retryable: bool = False
    progress: int | None = Field(default=None, ge=0, le=100)
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---- 智能体事件 ----
# 追加式事件，桌面端消费，不泄露框架特定对象
class AgentEvent(ContractModel):
    """Append-only event consumed by the desktop without leaking framework-specific objects."""

    event_id: str                                              # 事件唯一标识
    run_id: str                                                # 关联运行 ID
    thread_id: str                                             # 对话线程 ID
    sequence: int = Field(ge=1)                                # 事件序号（递增）
    type: AgentEventType                                       # 事件类型
    message: str = ""                                          # 事件描述
    progress: int | None = Field(default=None, ge=0, le=100)   # 进度百分比
    data: dict[str, Any] = Field(default_factory=dict)          # 附加数据
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 创建时间


class AgentSpan(ContractModel):
    """Redacted timing record for one router, model, or tool operation."""

    span_id: str
    run_id: str
    kind: str
    name: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    data: dict[str, Any] = Field(default_factory=dict)
