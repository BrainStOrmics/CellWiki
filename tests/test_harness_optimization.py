from __future__ import annotations

import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from filelock import FileLock

from cellwiki.api.app import create_app
from cellwiki.domain.contracts import (
    AgentAnswer,
    ApprovalDecision,
    ApprovalPolicy,
    ChangeOperation,
    ChangeOperationType,
    ChangeSet,
    Citation,
    RiskLevel,
    WikiAgentContext,
)
from cellwiki.domain.runs import AgentEventType, AgentRunStatus
from cellwiki.domain.tasks import LintTask
from cellwiki.services.agent_runtime import AgentRuntimeManager, RuntimeSignal
from cellwiki.services.central_writer import CentralWriter
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.operations import bind_agent_run
from cellwiki.services.pipeline import ApprovalPolicyError, KnowledgePipelineHarness
from cellwiki.services.query import FormalQueryService, FormalQuerySession
from cellwiki.services.typed_tasks import TypedTaskExecutor, TypedTaskResult


def test_invalid_approval_policy_is_visible_and_blocks_policy_reads(tmp_path: Path):
    policy = tmp_path / "data" / "runtime" / "pipeline" / "approval_policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_text("{not-json", encoding="utf-8")

    harness = KnowledgePipelineHarness(tmp_path)
    state = harness.approval_policy_status()

    assert state["valid"] is False
    assert state["policy"] is None
    with pytest.raises(ApprovalPolicyError):
        harness.approval_policy()


def test_startup_recovers_an_uncommitted_publication_transaction(tmp_path: Path):
    writer = CentralWriter(tmp_path)
    target = tmp_path / "wiki" / "cell_types" / "t_cell.md"
    target.parent.mkdir(parents=True)
    target.write_text("before", encoding="utf-8")
    writer._write_snapshot("snapshot_recovery", {target: b"before"})
    target.write_text("partial", encoding="utf-8")
    writer._write_transaction(
        "txn_recovery",
        {
            "transaction_id": "txn_recovery",
            "change_set_id": "cs_recovery",
            "snapshot_id": "snapshot_recovery",
            "stage": "prepared",
        },
    )

    CentralWriter(tmp_path)

    assert target.read_text(encoding="utf-8") == "before"
    assert not (tmp_path / "data" / "runtime" / "transactions" / "txn_recovery.json").exists()


def test_startup_recovery_waits_for_the_project_write_lease(tmp_path: Path):
    writer = CentralWriter(tmp_path)
    target = tmp_path / "wiki" / "cell_types" / "t_cell.md"
    target.parent.mkdir(parents=True)
    target.write_text("before", encoding="utf-8")
    writer._write_snapshot("snapshot_locked_recovery", {target: b"before"})
    target.write_text("active publication", encoding="utf-8")
    writer._write_transaction(
        "txn_locked_recovery",
        {
            "transaction_id": "txn_locked_recovery",
            "change_set_id": "cs_locked_recovery",
            "snapshot_id": "snapshot_locked_recovery",
            "stage": "prepared",
        },
    )

    project_lock = FileLock(str(writer.pipeline.lock_path))
    project_lock.acquire()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            recovery = executor.submit(CentralWriter, tmp_path)
            time.sleep(0.1)
            assert not recovery.done()
            assert target.read_text(encoding="utf-8") == "active publication"
            project_lock.release()
            recovery.result(timeout=2)
    finally:
        if project_lock.is_locked:
            project_lock.release()

    assert target.read_text(encoding="utf-8") == "before"


def test_commit_marker_remains_authoritative_when_journal_cleanup_fails(
    tmp_path: Path,
    monkeypatch,
):
    change_set = ChangeSet(
        change_set_id="cs_cleanup_failure",
        run_id="run_cleanup_failure",
        project_id="cellwiki",
        risk=RiskLevel.MEDIUM,
        reason="Verify the durable commit boundary.",
        operations=[
            ChangeOperation(
                type=ChangeOperationType.UPDATE_CURATION,
                target_id="t_cell",
                payload={"content": "committed curation"},
            )
        ],
    )
    ChangeSetRepository(tmp_path).save(change_set)
    writer = CentralWriter(tmp_path)
    original_unlink = Path.unlink

    def fail_transaction_cleanup(path: Path, *args, **kwargs):
        if path.parent == writer.transactions_dir:
            raise PermissionError("transaction journal is temporarily locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_transaction_cleanup)

    result = writer.commit(
        change_set.change_set_id,
        ApprovalDecision(approved=True, decided_by="desktop-user"),
    )

    curation = tmp_path / "wiki" / "curation" / "cell_types" / "t_cell.md"
    assert result.status == "committed"
    assert curation.read_text(encoding="utf-8") == "committed curation"
    assert writer.get_commit(change_set.change_set_id) == result
    assert list(writer.transactions_dir.glob("txn_*.json"))


def test_formal_query_validator_rejects_unread_or_wrong_version_citations(tmp_path: Path):
    page = tmp_path / "wiki" / "cell_types" / "t_cell.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\ndisplay_name: T cell\nreferences:\n  - paper_id: paper-a\n---\n\nCD3D marker",
        encoding="utf-8",
    )
    service = FormalQueryService(tmp_path)

    with bind_agent_run("query-validation"):
        read = service.read_page("t_cell")
        valid = service.validate_answer(
            AgentAnswer(
                answer="CD3D is listed.",
                citations=[
                    Citation(
                        page_id="t_cell",
                        source_id="paper-a, paper-b",
                        locator="CD3D",
                    )
                ],
                knowledge_version=f"{read.knowledge_version[:12]}…{read.knowledge_version[-5:]}",
            )
        )
        invalid = service.validate_answer(
            AgentAnswer(
                answer="Unsupported.",
                citations=[Citation(page_id="other")],
                knowledge_version="sha256:wrong",
            )
        )

    assert valid.verification_level.value == "page"
    assert valid.knowledge_scope == "formal"
    assert invalid.verification_level.value == "unvalidated"
    assert invalid.knowledge_scope == "unvalidated"
    assert invalid.confidence == "low"
    assert invalid.declared_confidence == "medium"
    assert {issue.code for issue in invalid.validation_issues} == {
        "unread_page",
        "version_mismatch",
    }
    assert invalid.validation_warnings


def test_formal_answer_gate_repairs_unread_citations_once(tmp_path: Path):
    page = tmp_path / "wiki" / "cell_types" / "t_cell.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ndisplay_name: T cell\n---\n\nCD3D marker", encoding="utf-8")
    service = FormalQueryService(tmp_path)

    with bind_agent_run("query-auto-read"):
        validated = service.validate_answer(
            AgentAnswer(
                answer="CD3D is listed.",
                citations=[Citation(page_id="t_cell", locator="CD3D")],
                confidence="high",
            )
        )

    assert validated.verification_level.value == "page"
    assert validated.knowledge_scope == "formal"
    assert validated.confidence == "high"
    assert validated.declared_confidence == "high"
    assert validated.validation_issues == []


def test_formal_answer_gate_rejects_a_citation_without_locator(tmp_path: Path):
    page = tmp_path / "wiki" / "cell_types" / "t_cell.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ndisplay_name: T cell\n---\n\nCD3D marker", encoding="utf-8")
    service = FormalQueryService(tmp_path)

    with bind_agent_run("query-missing-locator"):
        validated = service.validate_answer(
            AgentAnswer(
                answer="CD3D is listed.",
                citations=[Citation(page_id="t_cell")],
                confidence="high",
            )
        )

    assert validated.verification_level.value == "unvalidated"
    assert validated.confidence == "low"
    assert {issue.code for issue in validated.validation_issues} == {"locator_missing"}


def test_general_answer_does_not_require_formal_citations(tmp_path: Path):
    service = FormalQueryService(tmp_path)

    with bind_agent_run("query-general"):
        validated = service.validate_answer(
            AgentAnswer(
                answer="请说明要检查当前页面还是整个知识库。",
                citations=[],
                confidence="medium",
                knowledge_scope="general",
            )
        )

    assert validated.knowledge_scope == "general"
    assert validated.confidence == "medium"
    assert validated.validation_issues == []


def test_attachment_answer_does_not_enter_formal_page_validation(tmp_path: Path):
    service = FormalQueryService(tmp_path)

    with bind_agent_run("query-attachment"):
        validated = service.validate_answer(
            AgentAnswer(
                answer="The attachment mentions regulatory T cells.",
                citations=[
                    Citation(
                        attachment_id="att_" + "a" * 32,
                        original_name="paper.pdf",
                        section_locator="Page 1",
                        type="thread_attachment",
                    )
                ],
                confidence="high",
                knowledge_scope="attachment",
            )
        )

    assert validated.knowledge_scope == "attachment"
    assert validated.verification_level.value == "unvalidated"
    assert validated.confidence == "low"
    assert validated.validation_issues == []


def test_formal_query_validator_reloads_specialist_read_ledger(tmp_path: Path):
    page = tmp_path / "wiki" / "cell_types" / "t_cell.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ndisplay_name: T cell\n---\n\nCD3D marker", encoding="utf-8")

    with bind_agent_run("query-ledger"):
        read = FormalQueryService(tmp_path).read_page("t_cell")

    def validate_in_new_context() -> AgentAnswer:
        with bind_agent_run("query-ledger"):
            return FormalQueryService(tmp_path).validate_answer(
                AgentAnswer(
                    answer="CD3D is listed.",
                    citations=[Citation(page_id="t_cell", locator="CD3D")],
                    knowledge_version=read.knowledge_version,
                )
            )

    validated = contextvars.Context().run(validate_in_new_context)
    assert validated.verification_level.value == "page"
    assert validated.knowledge_scope == "formal"


def test_formal_query_ledger_merges_concurrent_specialist_reads(
    tmp_path: Path,
    monkeypatch,
):
    pages_dir = tmp_path / "wiki" / "cell_types"
    pages_dir.mkdir(parents=True)
    (pages_dir / "t_cell.md").write_text(
        "---\ndisplay_name: T cell\n---\n\nCD3D marker",
        encoding="utf-8",
    )
    (pages_dir / "b_cell.md").write_text(
        "---\ndisplay_name: B cell\n---\n\nCD79A marker",
        encoding="utf-8",
    )
    synchronize_writes = threading.Barrier(2)
    original_persist = FormalQuerySession._persist

    def persist_together(session: FormalQuerySession) -> None:
        synchronize_writes.wait(timeout=2)
        original_persist(session)

    monkeypatch.setattr(FormalQuerySession, "_persist", persist_together)

    def read(page_id: str) -> None:
        with bind_agent_run("query-concurrent-ledger"):
            FormalQueryService(tmp_path).read_page(page_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(read, page_id) for page_id in ("t_cell", "b_cell")]
        for future in futures:
            future.result(timeout=3)

    monkeypatch.setattr(FormalQuerySession, "_persist", original_persist)
    def validate_in_new_context() -> AgentAnswer:
        with bind_agent_run("query-concurrent-ledger"):
            return FormalQueryService(tmp_path).validate_answer(
                AgentAnswer(
                    answer="Both pages were read.",
                    citations=[
                        Citation(page_id="t_cell", locator="CD3D"),
                        Citation(page_id="b_cell", locator="CD79A"),
                    ],
                )
            )

    validated = contextvars.Context().run(validate_in_new_context)

    assert validated.verification_level.value == "page"
    assert validated.knowledge_scope == "formal"


def test_public_agent_api_rejects_explicit_typed_tasks(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/agent/runs",
        json={
            "message": "请检查当前知识库",
            "task": {"kind": "lint", "action": "inspect"},
        },
    )
    assert response.status_code == 422


class _ConversationAnswerAdapter:
    def __init__(self):
        self.messages: list[object] = []

    def execute(self, *, thread_id, message, context):
        self.messages.append(message)
        yield RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="The coordinator completed the request.",
            data={"answer": "The coordinator completed the request."},
        )

    def close(self) -> None:
        return None

    def delete_thread(self, thread_id: str) -> None:
        return None


@pytest.mark.parametrize(
    "message",
    [
        "请检查当前页面的质量问题",
        "请分析当前来源并更新 Wiki",
        "请修复 finding_missing_title",
    ],
)
def test_natural_language_operations_remain_model_led_conversations(
    tmp_path: Path,
    message: str,
):
    adapter = _ConversationAnswerAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        run = manager.start(
            thread_id="thread_model_led_operation",
            message=message,
            context=WikiAgentContext(
                project_id="cellwiki",
                source_id="source_demo",
                page_id="t_cell",
                thread_id="thread_model_led_operation",
            ),
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status in {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED}:
                break
            time.sleep(0.01)

        assert current.status is AgentRunStatus.SUCCEEDED
        assert current.task_kind == "conversation"
        assert current.model_role == "coordinator"
        assert adapter.messages
    finally:
        manager.close()


def test_typed_task_approval_resumes_the_existing_changeset_without_langgraph(
    tmp_path: Path,
    monkeypatch,
):
    class NoConversationAdapter:
        def execute(self, *, thread_id, message, context):
            raise AssertionError("typed task approval must not enter LangGraph")

        def close(self) -> None:
            return None

        def delete_thread(self, thread_id: str) -> None:
            return None

    def prepare_waiting_change_set(self, task, *, run_id: str) -> TypedTaskResult:
        change_set = ChangeSet(
            change_set_id="cs_typed_resume",
            run_id=run_id,
            project_id="cellwiki",
            risk=RiskLevel.MEDIUM,
            reason="Exercise typed approval continuation.",
            operations=[
                ChangeOperation(
                    type=ChangeOperationType.APPLY_LINT_FIX,
                    target_id="typed_resume",
                    payload={"action": "rebuild_projection"},
                )
            ],
        )
        ChangeSetRepository(self.project_root).save(change_set)
        return TypedTaskResult(
            status="waiting_approval",
            message="ChangeSet is ready for human approval.",
            change_set_id=change_set.change_set_id,
        )

    monkeypatch.setattr(TypedTaskExecutor, "execute", prepare_waiting_change_set)
    KnowledgePipelineHarness(tmp_path).set_approval_policy(ApprovalPolicy.MANUAL)
    manager = AgentRuntimeManager(tmp_path, adapter=NoConversationAdapter())
    try:
        run = manager.start_task(
            thread_id="thread_typed_resume",
            task=LintTask(
                action="propose_fix",
                snapshot_id="snapshot_demo",
                finding_ids=["lint_demo"],
            ),
            context=WikiAgentContext(
                project_id="cellwiki",
                thread_id="thread_typed_resume",
            ),
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status is AgentRunStatus.WAITING_APPROVAL:
                break
            time.sleep(0.01)
        assert current.status is AgentRunStatus.WAITING_APPROVAL

        manager.resume(run.run_id, decision="approve")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status in {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED}:
                break
            time.sleep(0.01)

        assert current.status is AgentRunStatus.SUCCEEDED
        assert CentralWriter(tmp_path).get_commit("cs_typed_resume") is not None
    finally:
        manager.close()


def test_typed_task_retry_reexecutes_the_typed_adapter_without_langgraph(
    tmp_path: Path,
    monkeypatch,
):
    class NoConversationAdapter:
        def execute(self, *, thread_id, message, context):
            raise AssertionError("typed task retry must not enter LangGraph")

        def close(self) -> None:
            return None

        def delete_thread(self, thread_id: str) -> None:
            return None

    attempts = 0

    def flaky_typed_task(self, task, *, run_id: str) -> TypedTaskResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary typed task failure")
        return TypedTaskResult(status="succeeded", message="Typed retry succeeded.")

    monkeypatch.setattr(TypedTaskExecutor, "execute", flaky_typed_task)
    manager = AgentRuntimeManager(tmp_path, adapter=NoConversationAdapter())
    try:
        run = manager.start_task(
            thread_id="thread_typed_retry",
            task=LintTask(action="inspect"),
            context=WikiAgentContext(
                project_id="cellwiki",
                thread_id="thread_typed_retry",
            ),
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status is AgentRunStatus.FAILED:
                break
            time.sleep(0.01)
        assert current.status is AgentRunStatus.FAILED

        manager.retry(run.run_id)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            current = manager.store.get_run(run.run_id)
            if current.status in {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED}:
                if attempts > 1:
                    break
            time.sleep(0.01)

        assert attempts == 2
        assert current.status is AgentRunStatus.SUCCEEDED
    finally:
        manager.close()


def test_only_one_agent_runtime_owns_a_project_at_a_time(tmp_path: Path):
    class IdleAdapter:
        def execute(self, *, thread_id, message, context):
            return iter(())

        def close(self) -> None:
            return None

        def delete_thread(self, thread_id: str) -> None:
            return None

    first = AgentRuntimeManager(tmp_path, adapter=IdleAdapter())
    second = None
    try:
        with pytest.raises(RuntimeError, match="already owns this project"):
            second = AgentRuntimeManager(tmp_path, adapter=IdleAdapter())
    finally:
        if second is not None:
            second.close()
        first.close()

    replacement = AgentRuntimeManager(tmp_path, adapter=IdleAdapter())
    replacement.close()


def test_product_api_reports_runtime_ownership_conflict_as_service_unavailable(
    tmp_path: Path,
):
    class IdleAdapter:
        def execute(self, *, thread_id, message, context):
            return iter(())

        def close(self) -> None:
            return None

        def delete_thread(self, thread_id: str) -> None:
            return None

    owner = AgentRuntimeManager(tmp_path, adapter=IdleAdapter())
    try:
        response = TestClient(create_app(tmp_path)).post(
            "/api/agent/runs",
            json={"message": "检查当前页面"},
        )
    finally:
        owner.close()

    assert response.status_code == 503
    assert "already owns this project" in response.json()["detail"]
