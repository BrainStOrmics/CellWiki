# =============================================================================
# 操作服务 —— 长时间运行本地操作的协作取消和进度控制
# =============================================================================

"""Cooperative cancellation and progress control for long-running local operations."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Callable, Iterator


# ---------------------------------------------------------------------------
# OperationCancelled —— 操作取消异常
# 当用户或桌面关闭取消正在进行的操作时抛出。
# 深层模块通过定期检查 cancellation 标志来协作式取消。
# ---------------------------------------------------------------------------
class OperationCancelled(RuntimeError):
    """Raised when a user or desktop shutdown cancels an active operation."""


# ---------------------------------------------------------------------------
# OperationProgress —— 操作进度
# 框架无关的进度信息，由模型承载服务发出。
# 包含当前状态、尝试次数、已用时间和错误信息。
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OperationProgress:
    """Framework-neutral attempt progress emitted by model-bearing services."""

    state: str                        # 当前状态描述
    attempt: int                      # 当前尝试次数
    max_attempts: int                 # 最大尝试次数
    attempt_elapsed_seconds: float = 0.0  # 本次尝试已用时间
    error: str | None = None          # 错误信息（如果有）


# 进度回调类型
ProgressCallback = Callable[[OperationProgress], None]


# ---------------------------------------------------------------------------
# OperationControl —— 操作控制
# 向深层模块暴露取消令牌和可选的进度回调。
# 支持双重取消信号（用户取消 + 批量中止），
# 通过短轮询（50ms）保持对两个取消信号的响应性。
# ---------------------------------------------------------------------------
class OperationControl:
    """Expose one cancellation token and optional progress callback to deep modules."""

    def __init__(
        self,
        run_id: str,
        cancellation: threading.Event,
        progress: ProgressCallback | None = None,
        additional_cancellation: threading.Event | None = None,
    ):
        self.run_id = run_id
        self._cancellation = cancellation           # 主取消信号
        self._additional_cancellation = additional_cancellation  # 附加取消信号
        self._progress = progress                   # 进度回调

    # 检查是否已取消（两个信号中任意一个被设置）
    @property
    def cancelled(self) -> bool:
        return self._cancellation.is_set() or bool(
            self._additional_cancellation is not None
            and self._additional_cancellation.is_set()
        )

    # 如果已取消，抛出 OperationCancelled 异常
    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise OperationCancelled(f"operation {self.run_id} was cancelled")

    # 等待指定时间，同时保持对取消信号的响应性
    # Python 事件无法同时等待两个句柄，因此使用短轮询
    # 保持用户取消和批量中止信号都能及时响应
    def wait(self, seconds: float) -> None:
        """Wait for backoff while remaining immediately responsive to cancellation."""

        if seconds <= 0:
            return
        if self._additional_cancellation is None:
            if self._cancellation.wait(seconds):
                self.raise_if_cancelled()
            return

        # 双信号场景：Python 事件无法同时等待两个句柄
        # 使用短轮询（50ms 间隔）保持两个取消信号都能响应
        deadline = time.monotonic() + seconds
        while True:
            self.raise_if_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._cancellation.wait(min(0.05, remaining))

    # 报告进度
    def report(
        self,
        state: str,
        *,
        attempt: int,
        max_attempts: int,
        attempt_elapsed_seconds: float = 0.0,
        error: str | None = None,
    ) -> None:
        if self._progress is not None:
            self._progress(
                OperationProgress(
                    state=state,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    attempt_elapsed_seconds=attempt_elapsed_seconds,
                    error=error,
                )
            )


# ---------------------------------------------------------------------------
# CancellationRegistry —— 取消注册表
# 在运行时和领域工具之间共享项目范围的取消事件。
# 使用 threading.Event 作为取消令牌，支持：
# - 按 run_id 注册/获取取消令牌
# - 发送取消信号
# - 批量取消所有运行
# - 清理已完成的运行
# 单例模式：每个项目根目录只有一个实例。
# ---------------------------------------------------------------------------
class CancellationRegistry:
    """Share project-scoped cancellation events between runtime and domain tools."""

    _instances: dict[Path, "CancellationRegistry"] = {}   # 项目根目录 -> 实例
    _instances_lock = threading.Lock()

    def __init__(self) -> None:
        self._events: dict[str, threading.Event] = {}     # run_id -> 取消事件
        self._lock = threading.Lock()

    # 获取或创建项目范围的取消注册表实例
    @classmethod
    def for_project(cls, project_root: Path) -> "CancellationRegistry":
        root = Path(project_root).resolve()
        with cls._instances_lock:
            return cls._instances.setdefault(root, cls())

    # 注册一个运行的取消令牌
    def register(self, run_id: str, *, reset: bool = True) -> threading.Event:
        with self._lock:
            event = self._events.get(run_id)
            if event is None or reset:
                event = threading.Event()
                self._events[run_id] = event
            return event

    # 获取已有取消令牌（不重置）
    def token(self, run_id: str) -> threading.Event:
        return self.register(run_id, reset=False)

    # 发送取消信号
    def cancel(self, run_id: str) -> bool:
        with self._lock:
            event = self._events.get(run_id)
            if event is None:
                event = threading.Event()
                self._events[run_id] = event
            already_cancelled = event.is_set()
            event.set()  # 设置事件，触发取消
            return not already_cancelled

    # 批量取消所有运行
    def cancel_all(self) -> None:
        with self._lock:
            for event in self._events.values():
                event.set()

    # 清理已完成的运行
    def clear(self, run_id: str) -> None:
        with self._lock:
            self._events.pop(run_id, None)


# ---------------------------------------------------------------------------
# 智能体运行 ID 的上下文变量
# 使用 ContextVar（Python 3.7+）实现线程安全的上下文传递。
# 在工具函数中不需要模型提供参数即可获取当前运行的 ID。
# 这在取消操作中尤为重要：取消权限来自持久化运行时上下文，
# 而非模型提供的任务标识符。
# ---------------------------------------------------------------------------
_CURRENT_AGENT_RUN_ID: ContextVar[str | None] = ContextVar(
    "cellwiki_current_agent_run_id", default=None
)


# 将当前运行 ID 绑定到上下文
@contextmanager
def bind_agent_run(run_id: str) -> Iterator[None]:
    """Make the durable Agent run ID available to tools without model-supplied arguments."""

    token = _CURRENT_AGENT_RUN_ID.set(run_id)
    try:
        yield
    finally:
        _CURRENT_AGENT_RUN_ID.reset(token)


# 获取当前运行的 ID
def current_agent_run_id() -> str | None:
    return _CURRENT_AGENT_RUN_ID.get()
