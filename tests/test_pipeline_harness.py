from __future__ import annotations

from pathlib import Path

import pytest

from cellwiki.domain.contracts import (
    ApprovalDecision,
    ChangeOperation,
    ChangeOperationType,
    CommitResult,
    RiskLevel,
)
from cellwiki.domain.pipeline import ApprovalPolicy, PipelineTaskType
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.central_writer import CentralWriter, VersionConflictError
from cellwiki.services.pipeline import (
    KnowledgePipelineHarness,
    PipelineBusyError,
)


def test_pipeline_snapshot_records_formal_state_and_pending_work(tmp_path: Path) -> None:
    wiki_page = tmp_path / "wiki" / "cell_types" / "t_cell.md"
    wiki_page.parent.mkdir(parents=True)
    wiki_page.write_text("# T cell\n", encoding="utf-8")
    extraction = tmp_path / "data" / "extraction" / "src_demo.json"
    extraction.parent.mkdir(parents=True)
    extraction.write_text("{\"source_document\": {\"source_id\": \"src_demo\"}}", encoding="utf-8")

    harness = KnowledgePipelineHarness(tmp_path)
    snapshot = harness.capture_snapshot(
        task_type=PipelineTaskType.LINT,
        run_id="run_lint",
    )

    assert snapshot.project_id == "cellwiki"
    assert snapshot.task_type is PipelineTaskType.LINT
    assert snapshot.run_id == "run_lint"
    assert snapshot.knowledge_version.startswith("sha256:")
    assert snapshot.inventory["formal"]["wiki_pages"] == 1
    assert snapshot.inventory["formal"]["extractions"] == 1
    assert harness.get_snapshot(snapshot.snapshot_id) == snapshot


def test_pipeline_lease_prevents_two_mutating_tasks(tmp_path: Path) -> None:
    harness = KnowledgePipelineHarness(tmp_path)

    assert harness.lock_path == CentralWriter(tmp_path).runtime_dir / "cellwiki.lock"

    lease = harness.acquire(task_type=PipelineTaskType.INGEST, run_id="run_one")
    first = lease.__enter__()
    try:
        assert first.snapshot.run_id == "run_one"
        with pytest.raises(PipelineBusyError):
            with harness.acquire(task_type=PipelineTaskType.LINT, run_id="run_two"):
                pass
    finally:
        lease.__exit__(None, None, None)

    with harness.acquire(task_type=PipelineTaskType.LINT, run_id="run_two") as second:
        assert second.snapshot.run_id == "run_two"


def test_approval_policy_defaults_to_auto_approve_all_and_can_require_review(tmp_path: Path) -> None:
    harness = KnowledgePipelineHarness(tmp_path)

    assert harness.approval_policy() is ApprovalPolicy.AUTO_ALL
    automatic = harness.approval_for("cs_demo", reviewer="default-reviewer")
    assert automatic.approved is True
    assert automatic.decided_by == "policy:auto_all"
    assert "cs_demo" in automatic.reason

    harness.set_approval_policy(ApprovalPolicy.MANUAL)
    manual = harness.approval_for("cs_demo", reviewer="default-reviewer")
    assert manual.approved is False
    assert manual.decided_by == "pending:default-reviewer"


def test_parallel_proposals_share_a_base_but_rebase_only_non_overlapping_work(tmp_path: Path) -> None:
    repository = ChangeSetRepository(tmp_path)
    first = repository.create_proposal(
        run_id="run_first",
        task_type=PipelineTaskType.INGEST,
        operations=[_curation_operation("cell_a")],
        reason="Add cell A evidence.",
        risk=RiskLevel.MEDIUM,
    )
    second = repository.create_proposal(
        run_id="run_second",
        task_type=PipelineTaskType.LINT,
        operations=[_curation_operation("cell_b")],
        reason="Add cell B evidence.",
        risk=RiskLevel.LOW,
    )

    assert first.change_set_id != second.change_set_id
    assert first.base_knowledge_version == second.base_knowledge_version
    assert first.snapshot_id and second.snapshot_id

    overlapping = repository.create_proposal(
        run_id="run_overlap",
        task_type=PipelineTaskType.INGEST,
        operations=[_curation_operation("cell_a")],
        reason="Touch the already changed cell.",
        risk=RiskLevel.MEDIUM,
    )
    _record_commit(tmp_path, first.change_set_id, ["cell_a"], overlapping.created_at)
    (tmp_path / "wiki" / "curation" / "cell_types" / "cell_a.md").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "wiki" / "curation" / "cell_types" / "cell_a.md").write_text("A", encoding="utf-8")

    rebased = repository.rebase(second.change_set_id)
    assert rebased.status == "rebased"
    assert rebased.rebased_change_set_id
    assert repository.get(second.change_set_id).parent_change_set_id is None
    assert repository.get(rebased.rebased_change_set_id).parent_change_set_id == second.change_set_id
    assert repository.get(rebased.rebased_change_set_id).base_knowledge_version == rebased.current_knowledge_version

    conflict = repository.rebase(overlapping.change_set_id)
    assert conflict.status == "conflict"
    assert conflict.conflicting_target_ids == ["cell_a"]
    assert conflict.rebased_change_set_id is None


def test_central_writer_rejects_a_stale_base_before_writing(tmp_path: Path) -> None:
    repository = ChangeSetRepository(tmp_path)
    change_set = repository.create_proposal(
        run_id="run_stale",
        task_type=PipelineTaskType.INGEST,
        operations=[_curation_operation("cell_a")],
        reason="Write against an old base.",
        risk=RiskLevel.MEDIUM,
    )
    page = tmp_path / "wiki" / "cell_types" / "already_formal.md"
    page.parent.mkdir(parents=True)
    page.write_text("Changed outside the proposal.", encoding="utf-8")

    writer = CentralWriter(tmp_path, verifier=lambda _: None, projector=_NoopProjector())
    with pytest.raises(VersionConflictError):
        writer.commit(
            change_set.change_set_id,
            ApprovalDecision(approved=True, decided_by="test", reason="test"),
        )
    assert not (tmp_path / "wiki" / "curation" / "cell_types" / "cell_a.md").exists()


def _curation_operation(target_id: str) -> ChangeOperation:
    return ChangeOperation(
        type=ChangeOperationType.UPDATE_CURATION,
        target_id=target_id,
        payload={"content": f"Content for {target_id}"},
    )


def _record_commit(tmp_path: Path, change_set_id: str, targets: list[str], created_at) -> None:
    commit_dir = tmp_path / "data" / "runtime" / "commits"
    commit_dir.mkdir(parents=True, exist_ok=True)
    result = CommitResult(
        commit_id=f"commit_{change_set_id}",
        change_set_id=change_set_id,
        status="committed",
        changed_targets=targets,
        snapshot_id=f"snapshot_{change_set_id}",
        committed_at=created_at.replace(microsecond=created_at.microsecond + 1),
    )
    (commit_dir / f"{change_set_id}.json").write_text(result.model_dump_json(), encoding="utf-8")


class _NoopProjector:
    def render(self):
        return None
