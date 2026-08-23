# =============================================================================
# 运行中挂起询问（ask_user_question 5+1 契约）
# =============================================================================
# 阶段 4：工具 interrupt 挂起后，问题记录在此持久化（绑定 run_id + tool_call_id）；
# 用户回复（string | array<string>）写入 answers 后恢复 run。
# =============================================================================

"""Pending question contract for ask_user_question interrupts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from cellwiki.domain.contracts import ContractModel
from pydantic import Field


class PendingQuestion(ContractModel):
    """One paused run question waiting for a user answer."""

    question_id: str
    run_id: str
    thread_id: str
    tool_call_id: str | None = None
    question: str = ""
    options: list[str] = Field(default_factory=list)
    required: bool = True
    status: Literal["pending", "answered", "timed_out"] = "pending"
    answers: list[Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    answered_at: datetime | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "tool_call_id": self.tool_call_id,
            "question": self.question,
            "options": self.options,
            "required": self.required,
            "status": self.status,
            "answers": self.answers,
            "created_at": self.created_at.isoformat(),
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
        }


__all__ = ["PendingQuestion"]
