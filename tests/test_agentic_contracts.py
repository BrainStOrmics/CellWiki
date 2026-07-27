# =============================================================================
# 智能体合约测试 —— 验证智能体架构的合约和数据模型
# =============================================================================

from pathlib import Path

import pytest
from pydantic import ValidationError

from cellwiki.domain.contracts import (
    ApprovalDecision,
    ChangeOperation,
    ChangeOperationType,
    ChangeSet,
    RiskLevel,
    SourceStatus,
    EvidenceReference,
    ApprovalPolicy,
    PipelineTaskType,
)
from cellwiki.domain.linting import LintFinding, LintLevel, LintSeverity
from cellwiki.domain.runs import AgentEvent, AgentEventType, AgentRun
from cellwiki.services.central_writer import ApprovalRequiredError, CentralWriter, VersionConflictError
from cellwiki.services.approvals import ApprovalRepository
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.sources import SourceRegistry
from cellwiki.services.pipeline import KnowledgePipelineHarness


def make_curation_change(
    change_set_id: str = "cs_test",
    content: str = "FOXP3 is a commonly reported marker.",
) -> ChangeSet:
    return ChangeSet(
        change_set_id=change_set_id,
        run_id="run_test",
        project_id="cellwiki",
        risk=RiskLevel.MEDIUM,
        reason="Add an expert-curated note.",
        operations=[
            ChangeOperation(
                type=ChangeOperationType.UPDATE_CURATION,
                target_id="regulatory_t_cell",
                payload={"content": content},
            )
        ],
    )


def test_change_operation_rejects_file_paths():
    with pytest.raises(ValidationError):
        ChangeOperation(
            type=ChangeOperationType.UPDATE_CURATION,
            target_id="../../wiki/cell_types/t_cell.md",
            payload={"content": "unsafe"},
        )


def test_v1_contracts_keep_backward_compatible_defaults_and_json_schemas():
    evidence = EvidenceReference.model_validate(
        {"source_id": "src_legacy", "locator": "page 1", "excerpt": "legacy excerpt"}
    )
    run = AgentRun(run_id="run_contract", thread_id="thread_contract")
    event = AgentEvent(
        event_id="event_contract",
        run_id=run.run_id,
        thread_id=run.thread_id,
        sequence=1,
        type=AgentEventType.RUN_STATUS,
        progress=0,
    )
    finding = LintFinding(
        finding_id=LintFinding.stable_id(
            level=LintLevel.L0,
            category="structure:missing_title",
            target_id="t_cell",
            locator="wiki/cell_types/t_cell.md",
        ),
        level=LintLevel.L0,
        severity=LintSeverity.ERROR,
        category="structure",
        target_id="t_cell",
        locator="wiki/cell_types/t_cell.md",
        message="Missing title",
    )

    assert evidence.page_start is None
    assert AgentRun.model_validate_json(run.model_dump_json()) == run
    assert event.progress == 0
    assert finding.finding_id.startswith("lint_")
    assert "properties" in AgentRun.model_json_schema()
    assert "properties" in LintFinding.model_json_schema()


def test_source_registry_is_content_hash_idempotent(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"same paper bytes")
    registry = SourceRegistry(tmp_path / "project")

    first = registry.register(source, source_type="paper")
    second = registry.register(source, source_type="paper")

    assert first == second
    assert first.source_id.startswith("src_")
    assert Path(first.stored_path).read_bytes() == source.read_bytes()
    assert len(registry.list_sources()) == 1

    updated = registry.update_status(first.source_id, SourceStatus.ANALYZED)
    assert updated.status == SourceStatus.ANALYZED
    assert registry.get(first.source_id).status == SourceStatus.ANALYZED


def test_central_writer_requires_explicit_approval(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    repository.save(make_curation_change())
    KnowledgePipelineHarness(tmp_path).set_approval_policy(ApprovalPolicy.MANUAL)
    writer = CentralWriter(tmp_path, repository=repository)

    with pytest.raises(ApprovalRequiredError):
        writer.commit("cs_test", approval=None)

    assert not (tmp_path / "wiki" / "curation" / "cell_types" / "regulatory_t_cell.md").exists()


def test_central_writer_rejects_a_changeset_from_an_old_pipeline_snapshot(tmp_path: Path):
    harness = KnowledgePipelineHarness(tmp_path)
    snapshot = harness.capture_snapshot(task_type=PipelineTaskType.INGEST, run_id="run_snapshot")
    repository = ChangeSetRepository(tmp_path)
    repository.save(
        make_curation_change().model_copy(
            update={
                "snapshot_id": snapshot.snapshot_id,
                "base_knowledge_version": snapshot.knowledge_version,
            }
        )
    )
    page = tmp_path / "wiki" / "cell_types" / "existing.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\npage_id: existing\ntitle: Existing\n---\n\nchanged after the pipeline snapshot\n",
        encoding="utf-8",
    )

    with pytest.raises(VersionConflictError, match="knowledge version changed"):
        CentralWriter(tmp_path, repository=repository).commit(
            "cs_test",
            approval=ApprovalDecision(approved=True, decided_by="local-user"),
        )


def test_central_writer_commit_is_idempotent(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    repository.save(make_curation_change())
    writer = CentralWriter(tmp_path, repository=repository)
    approval = ApprovalDecision(approved=True, decided_by="local-user")

    first = writer.commit("cs_test", approval=approval)
    second = writer.commit("cs_test", approval=approval)

    assert first == second
    assert first.status == "committed"
    curation = tmp_path / "wiki" / "curation" / "cell_types" / "regulatory_t_cell.md"
    assert curation.read_text(encoding="utf-8") == "FOXP3 is a commonly reported marker."


def test_central_writer_uses_project_auto_approval_policy(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    repository.save(make_curation_change())
    KnowledgePipelineHarness(tmp_path).set_approval_policy(ApprovalPolicy.AUTO_ALL)

    result = CentralWriter(tmp_path, repository=repository).commit("cs_test", approval=None)

    assert result.status == "committed"
    approval_path = tmp_path / "data" / "runtime" / "approvals" / "cs_test.json"
    assert '"decided_by": "policy:auto_all"' in approval_path.read_text(encoding="utf-8")


def test_explicit_rejection_wins_over_a_later_auto_approval_attempt(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    repository.save(make_curation_change())
    KnowledgePipelineHarness(tmp_path).set_approval_policy(ApprovalPolicy.AUTO_ALL)
    ApprovalRepository(tmp_path).save(
        "cs_test",
        ApprovalDecision(
            approved=False,
            decided_by="desktop-user",
            reason="Reject this proposal.",
        ),
    )

    with pytest.raises(ApprovalRequiredError):
        CentralWriter(tmp_path, repository=repository).commit("cs_test", approval=None)

    assert not (tmp_path / "data" / "runtime" / "commits" / "cs_test.json").exists()


def test_central_writer_commit_is_visible_as_a_pipeline_task(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    repository.save(make_curation_change())
    observed: dict[str, object] = {}

    def verify_with_pipeline_state(project_root: Path) -> None:
        observed.update(KnowledgePipelineHarness(project_root).active_task() or {})

    writer = CentralWriter(
        tmp_path,
        repository=repository,
        verifier=verify_with_pipeline_state,
    )

    writer.commit(
        "cs_test",
        approval=ApprovalDecision(approved=True, decided_by="local-user"),
    )

    assert observed["run_id"] == "run_test"
    assert observed["task_type"] == "commit"


def test_central_writer_rolls_back_when_verification_fails(tmp_path: Path):
    curation = tmp_path / "wiki" / "curation" / "cell_types" / "regulatory_t_cell.md"
    curation.parent.mkdir(parents=True)
    curation.write_text("original", encoding="utf-8")

    repository = ChangeSetRepository(tmp_path)
    repository.save(make_curation_change())

    def fail_verification(_project_root: Path) -> None:
        raise RuntimeError("lint failed")

    writer = CentralWriter(tmp_path, repository=repository, verifier=fail_verification)

    with pytest.raises(RuntimeError, match="lint failed"):
        writer.commit(
            "cs_test",
            approval=ApprovalDecision(approved=True, decided_by="local-user"),
        )

    assert curation.read_text(encoding="utf-8") == "original"


def test_manual_rollback_only_restores_the_latest_active_commit(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    repository.save(make_curation_change("cs_first", "first"))
    repository.save(make_curation_change("cs_second", "second"))
    writer = CentralWriter(tmp_path, repository=repository)
    approval = ApprovalDecision(approved=True, decided_by="local-user")

    writer.commit("cs_first", approval=approval)
    writer.commit("cs_second", approval=approval)

    with pytest.raises(VersionConflictError, match="after later commit"):
        writer.rollback("cs_first", decided_by="local-user", reason="unsafe older rollback")

    writer.rollback("cs_second", decided_by="local-user", reason="restore first commit")
    curation = tmp_path / "wiki" / "curation" / "cell_types" / "regulatory_t_cell.md"
    assert curation.read_text(encoding="utf-8") == "first"
