from __future__ import annotations

import time
from pathlib import Path

from cellwiki.agent.app import SYSTEM_PROMPT, build_wiki_agent
from cellwiki.domain.contracts import (
    ChangeOperation,
    ChangeOperationType,
    ChangeSet,
    ApprovalPolicy,
    RiskLevel,
    WikiAgentContext,
)
from cellwiki.domain.runs import AgentRunStatus
from cellwiki.services.agent_runtime import AgentRuntimeManager, RuntimeSignal
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.operations import current_agent_run_id
from cellwiki.services.pipeline import KnowledgePipelineHarness
from cellwiki.domain.runs import AgentEventType


class _ExplodingRouter:
    def route(self, message, context):
        raise AssertionError("natural-language runs must be owned by the Model-led coordinator")


class _ExplodingPageQueryRouter:
    def should_handle(self, message, context):
        raise AssertionError("page-query shortcuts must not bypass the coordinator")


class _IdleAdapter:
    def execute(self, *, thread_id: str, message, context):
        yield RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="Coordinator handled the request.",
            data={"answer": "Coordinator handled the request."},
        )

    def close(self) -> None:
        return None

    def delete_thread(self, thread_id: str) -> None:
        return None


class _ProposalAdapter:
    def __init__(self, project_root: Path):
        self.project_root = project_root

    def execute(self, *, thread_id: str, message, context):
        run_id = current_agent_run_id()
        assert run_id
        change_set = ChangeSet(
            change_set_id="cs_model_led",
            run_id=run_id,
            project_id="cellwiki",
            risk=RiskLevel.MEDIUM,
            reason="Model-led proposal fixture.",
            operations=[
                ChangeOperation(
                    type=ChangeOperationType.UPDATE_CURATION,
                    target_id="model_led",
                    payload={"content": "approved content"},
                )
            ],
        )
        ChangeSetRepository(self.project_root).save(change_set)
        yield RuntimeSignal(
            type=AgentEventType.TOOL_COMPLETED,
            data={
                "tool_name": "prepare_ingest_change_set",
                "change_set_id": change_set.change_set_id,
            },
        )
        yield RuntimeSignal(
            type=AgentEventType.CHANGESET_READY,
            data={"change_set_id": change_set.change_set_id},
        )
        yield RuntimeSignal(
            type=AgentEventType.REVIEW_REQUIRED,
            data={
                "change_set_id": change_set.change_set_id,
                "requires_human_review": True,
            },
        )
        yield RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="A ChangeSet is ready for your review.",
            data={"answer": "A ChangeSet is ready for your review."},
        )

    def close(self) -> None:
        return None

    def delete_thread(self, thread_id: str) -> None:
        return None


def test_natural_language_runs_always_enter_model_led_coordinator(tmp_path: Path):
    manager = AgentRuntimeManager(
        tmp_path,
        adapter=_IdleAdapter(),
        task_router=_ExplodingRouter(),
        page_query_router=_ExplodingPageQueryRouter(),
    )
    try:
        run = manager.start(
            thread_id="thread-model-led",
            message="请检查当前页面并在有问题时提出修复建议",
            context=WikiAgentContext(
                project_id="cellwiki",
                page_id="t_cell",
                thread_id="thread-model-led",
            ),
        )
        assert run.task_kind == "conversation"
    finally:
        manager.close()


def test_model_led_coordinator_exposes_governed_operation_tools(tmp_path: Path, monkeypatch):
    captured: dict[str, object] = {}

    def capture_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr("cellwiki.agent.app.create_deep_agent", capture_agent)
    build_wiki_agent(project_root=tmp_path, model="openai:model-led-test", checkpointer=False)

    tool_names = {tool.name for tool in captured["tools"]}
    assert {
        "get_project_status",
        "search_wiki",
        "read_wiki_page",
        "prepare_ingest_change_set",
        "request_ingest_revision",
        "run_broad_lint",
        "inspect_knowledge_quality",
        "propose_lint_fix",
        "submit_agent_answer",
    } <= tool_names
    assert "commit_change_set" not in tool_names
    assert "task" not in tool_names
    assert "deterministic typed tasks" not in SYSTEM_PROMPT
    assert "Model-led" in SYSTEM_PROMPT


def test_model_led_proposal_waits_then_publishes_only_after_approval(tmp_path: Path):
    KnowledgePipelineHarness(tmp_path).set_approval_policy(ApprovalPolicy.MANUAL)
    manager = AgentRuntimeManager(tmp_path, adapter=_ProposalAdapter(tmp_path))
    try:
        run = manager.start(
            thread_id="thread-model-led-approval",
            message="Analyze the registered source and update the Wiki.",
            context=WikiAgentContext(
                project_id="cellwiki",
                source_id="source_demo",
                thread_id="thread-model-led-approval",
            ),
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status is AgentRunStatus.WAITING_APPROVAL:
                break
            time.sleep(0.01)

        assert current.status is AgentRunStatus.WAITING_APPROVAL
        target = tmp_path / "wiki" / "curation" / "cell_types" / "model_led.md"
        assert not target.exists()

        manager.resume(run.run_id, decision="approve")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status in {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED}:
                break
            time.sleep(0.01)

        assert current.status is AgentRunStatus.SUCCEEDED
        assert target.read_text(encoding="utf-8") == "approved content"
        assert any(
            event.type is AgentEventType.VERIFICATION
            for event in manager.store.list_events(run.run_id)
        )
    finally:
        manager.close()
