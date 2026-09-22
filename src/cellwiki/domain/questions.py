# =============================================================================
# 运行中挂起询问（ask_user_question 5+1 契约）
# =============================================================================
# 工具 interrupt 挂起后，问题记录在此持久化（绑定 run_id + tool_call_id）；
# 用户回复（string | array<string>）写入 answers 后恢复 run。
# =============================================================================

"""Pending question contract for ask_user_question interrupts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from cellwiki.domain.contracts import ContractModel
from pydantic import Field

MAX_OPTIONS = 5
MAX_OPTION_LABEL_CHARS = 120
MAX_OPTION_DESCRIPTION_CHARS = 240


class QuestionOption(ContractModel):
    """一个固定选项：标签是回传给模型的答案，说明与推荐标记只影响卡片展示。"""

    label: str
    description: str = ""
    recommended: bool = False


def normalize_question_options(raw: Any) -> list[QuestionOption]:
    """把工具入参 / interrupt 载荷 / 旧版字符串统一成选项对象。

    interrupt 载荷会随 checkpoint 持久化：升级前暂停的 run 里存的是字符串列表，
    读回时仍走这条归一化，因此不能假定进来的一定是对象。
    """

    options: list[QuestionOption] = []
    seen: set[str] = set()
    for item in list(raw or []):
        if isinstance(item, str):
            label, description, recommended = item, "", False
        elif isinstance(item, dict):
            label = item.get("label") or ""
            description = item.get("description") or ""
            recommended = bool(item.get("recommended", False))
        elif hasattr(item, "label"):
            # 任何带 label 的选项对象都收（领域模型、工具入参模型，或中间件包装过的实例）：
            # 工具入参经 LangChain 校验后按**模型实例**而不是 dict 传进工具函数，
            # 只认 dict/str 会让它们被静默丢光，卡片只剩问题、没有选项（2026-09-20 实测）。
            label = getattr(item, "label") or ""
            description = getattr(item, "description", "") or ""
            recommended = bool(getattr(item, "recommended", False))
        else:
            continue
        label = str(label).strip()[:MAX_OPTION_LABEL_CHARS]
        # 重复与空标签不占名额：截断发生在清洗之后（旧实现的既有语义）。
        if not label or label in seen:
            continue
        seen.add(label)
        options.append(
            QuestionOption(
                label=label,
                description=str(description).strip()[:MAX_OPTION_DESCRIPTION_CHARS],
                recommended=recommended,
            )
        )
        if len(options) >= MAX_OPTIONS:
            break
    return options


class PendingQuestion(ContractModel):
    """One paused run question waiting for a user answer."""

    question_id: str
    run_id: str
    thread_id: str
    tool_call_id: str | None = None
    question: str = ""
    options: list[QuestionOption] = Field(default_factory=list)
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
            "options": [option.model_dump() for option in self.options],
            "required": self.required,
            "status": self.status,
            "answers": self.answers,
            "created_at": self.created_at.isoformat(),
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
        }


__all__ = [
    "MAX_OPTIONS",
    "MAX_OPTION_DESCRIPTION_CHARS",
    "MAX_OPTION_LABEL_CHARS",
    "PendingQuestion",
    "QuestionOption",
    "normalize_question_options",
]
