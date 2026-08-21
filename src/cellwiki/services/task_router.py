"""High-precision routing from explicit chat actions to deterministic tasks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.tasks import (
    AgentTask,
    LintTask,
    PageLintScope,
    ProjectLintScope,
)


@dataclass(frozen=True)
class TaskRoute:
    task: AgentTask
    requires_confirmation: bool
    reason: str


class TaskRouter:
    """Recognize only action intents precise enough to execute without guesswork."""

    _QUESTION_MARKERS = ("为什么", "为何", "怎么", "如何", "是什么", "吗", "？", "?")
    _EXPLICIT_ACTION = ("请", "帮我", "开始", "执行", "运行", "进行")

    def route(self, message: str, context: WikiAgentContext) -> TaskRoute | None:
        normalized = " ".join(message.strip().lower().split())
        if not normalized or self._looks_like_explanation(normalized):
            return None

        lint = self._lint_route(normalized, context)
        if lint is not None:
            return lint
        return self._lint_fix_route(normalized)

    def _lint_route(self, text: str, context: WikiAgentContext) -> TaskRoute | None:
        has_lint_subject = any(
            marker in text
            for marker in ("lint", "质量问题", "质量检查", "检查质量", "知识库检查")
        ) or ("检查" in text and "质量" in text)
        has_check_action = any(marker in text for marker in ("检查", "运行", "执行", "开始"))
        if not (has_lint_subject and has_check_action):
            return None
        if any(marker in text for marker in ("外部论文", "外部研究", "research", "文献检索")):
            return None

        project_scope = any(
            marker in text
            for marker in ("全库", "整个知识库", "全项目", "广义", "broad", "project")
        )
        scope = (
            ProjectLintScope()
            if project_scope or not context.page_id
            else PageLintScope(page_id=context.page_id)
        )
        return TaskRoute(
            task=LintTask(action="inspect", scope=scope),
            requires_confirmation=False,
            reason="The user explicitly requested a read-only Lint inspection.",
        )

    def _looks_like_explanation(self, text: str) -> bool:
        return (
            any(marker in text for marker in self._QUESTION_MARKERS)
            and not any(marker in text for marker in self._EXPLICIT_ACTION)
        )

    def _lint_fix_route(self, text: str) -> TaskRoute | None:
        if not any(marker in text for marker in ("修复", "fix", "propose fix", "修复提案")):
            return None
        if not any(marker in text for marker in self._EXPLICIT_ACTION):
            return None
        finding_ids = list(
            dict.fromkeys(re.findall(r"\b(?:lint|finding)_[a-z0-9_.:-]+\b", text))
        )
        snapshot = re.search(r"\b(?:snapshot|snap)_[a-z0-9_.:-]+\b", text)
        if not finding_ids or snapshot is None:
            return None
        return TaskRoute(
            task=LintTask(
                action="propose_fix",
                scope=ProjectLintScope(),
                snapshot_id=snapshot.group(0),
                finding_ids=finding_ids,
            ),
            requires_confirmation=True,
            reason="The user requested a fix proposal for explicit Lint findings.",
        )


__all__ = ["TaskRoute", "TaskRouter"]
