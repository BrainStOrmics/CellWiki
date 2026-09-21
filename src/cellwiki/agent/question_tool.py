# =============================================================================
# ask_user_question —— 5+1 契约（运行中挂起询问）
# =============================================================================
# 契约要点（设计 H5/H6 定稿）：
#   - 输入：question（最多 5 个固定选项）+ required；"+1" = 始终可用的自由文本；
#     每个选项收 {label, description, recommended} 或裸字符串：label 是答案回传值，
#     description 是卡片上的灰色说明，recommended 只影响展示；
#   - 输出：string | array（单选返回字符串，多选/自由文本按答案结构返回）；
#   - 绑定 run_id + tool_call_id（运行时在持久化时关联）；
#   - 用 langgraph interrupt 挂起：ToolNode 内调用后图暂停，运行时持久化问题并
#     转为 WAITING_CONFIRMATION；用户回复后以 Command(resume=answers) 续跑；
#   - 文本截断清洗与纯文本转义在此统一完成。
# =============================================================================

"""ask_user_question tool: 5+1 contract with a langgraph interrupt pause."""

from __future__ import annotations

import json
import re
from typing import Any, Union

from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from cellwiki.domain.questions import (
    MAX_OPTIONS,
    MAX_OPTION_DESCRIPTION_CHARS,
    MAX_OPTION_LABEL_CHARS,
    normalize_question_options,
)

MAX_QUESTION_CHARS = 2_000

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class AskUserQuestionOption(BaseModel):
    """一个固定选项：标签是回传给模型的答案，说明与推荐标记只影响卡片展示。"""

    label: str = Field(
        min_length=1,
        max_length=MAX_OPTION_LABEL_CHARS,
        description="Short label; the user's answer comes back as this exact string.",
    )
    description: str = Field(
        default="",
        max_length=MAX_OPTION_DESCRIPTION_CHARS,
        description="Optional one-line explanation shown in grey under the label.",
    )
    recommended: bool = Field(
        default=False,
        description="true marks the option you recommend; the card badges it.",
    )


class AskUserQuestionInput(BaseModel):
    """5+1 询问输入：5 个稳定选项 + 1 个自由文本（由 UI 提供）。

    选项同时收对象和裸字符串：弱模型经常原样发字符串，严格拒收会让它重试时
    干脆放弃选项（2026-09-20 实测：先报 schema 错、重试变成 options=[]）。
    字符串在归一化时补成"只有标签"的选项。
    """

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    options: list[Union[str, AskUserQuestionOption]] = Field(
        default_factory=list, max_length=MAX_OPTIONS
    )
    required: bool = Field(default=True, description="true 时自由文本也必须填写")


def _clean_text(value: str, limit: int = MAX_QUESTION_CHARS) -> str:
    value = _CONTROL_RE.sub("", str(value or "")).replace("\\", "\\\\").replace("\n", " ")
    return value.strip()[:limit]


def _clean_options(options: list[Any] | None) -> list[dict[str, Any]]:
    return [
        {
            "label": _clean_text(option.label, MAX_OPTION_LABEL_CHARS),
            "description": _clean_text(option.description, MAX_OPTION_DESCRIPTION_CHARS),
            "recommended": option.recommended,
        }
        for option in normalize_question_options(options)
    ]


def _question_payload(
    question: str, options: list[Any] | None, required: bool
) -> dict[str, Any]:
    return {
        "type": "ask_user_question",
        "question": _clean_text(question),
        "options": _clean_options(options),
        "required": bool(required),
    }


def build_question_tool() -> list[BaseTool]:
    """Register the ask_user_question tool (interrupt-based; only callable inside a graph)."""

    @tool("ask_user_question", args_schema=AskUserQuestionInput)
    def ask_user_question(
        question: str,
        options: list[Union[str, AskUserQuestionOption]] | None = None,
        required: bool = True,
    ) -> str:
        """Pause the run and ask the user a question with up to 5 fixed options plus free text.

        Each option is either a plain string or {label, description, recommended}:
        label is the short choice and comes back as the answer, description is an
        optional one-line explanation shown under it, and recommended=true marks
        the option you suggest. Prefer objects; plain strings are also accepted.
        The graph suspends until the user answers; the answer (string or list of
        strings) is returned to the agent. Use it for choices that must be confirmed.
        """
        payload = _question_payload(question, options, required)
        answer = interrupt(payload)
        return json.dumps({"answer": answer}, ensure_ascii=False)

    return [ask_user_question]


__all__ = [
    "AskUserQuestionInput",
    "AskUserQuestionOption",
    "MAX_OPTIONS",
    "MAX_QUESTION_CHARS",
    "build_question_tool",
]
