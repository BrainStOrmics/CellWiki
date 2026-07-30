from __future__ import annotations

from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.tasks import LintTask, PageLintScope
from cellwiki.services.task_router import TaskRouter


def test_chinese_page_quality_request_routes_to_typed_lint() -> None:
    route = TaskRouter().route(
        "请只读检查当前页面质量，返回前 5 个 finding，不要修复。",
        WikiAgentContext(project_id="cellwiki", page_id="activated_cd4_t_cell"),
    )

    assert route is not None
    assert route.requires_confirmation is False
    assert route.task == LintTask(
        action="inspect",
        scope=PageLintScope(page_id="activated_cd4_t_cell"),
    )
