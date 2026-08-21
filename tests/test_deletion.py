# =============================================================================
# 删除功能测试 —— ChangeSet 与 Source 的硬删除、级联与 409 约束
# =============================================================================
"""Hard-delete tests for ChangeSets and Sources (tombstone, cascade, guards)."""

from __future__ import annotations

from pathlib import Path
import json
import uuid

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.contracts import (
    ApprovalDecision,
    ChangeOperation,
    ChangeOperationType,
    ChangeSet,
    IngestStage,
    RiskLevel,
    TaskStatus,
)
from cellwiki.domain.runs import AgentRun, AgentRunStatus
from cellwiki.services.approvals import ApprovalRepository
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.ingest import IngestService
from cellwiki.services.runtime_store import RuntimeStore
from cellwiki.services.sources import SourceRegistry
from cellwiki.services.tasks import TaskEventRepository

FIXTURE = Path(__file__).parent / "fixtures" / "sample_source.md"


class DeleteFixtureExtractor:
    """Deterministic extractor proposing an entity that appears in the fixture."""

    name = "delete-fixture"
    version = "1"
    cache_identity = "delete-fixture:1"

    def extract(self, chunk, source, *, control=None, review_feedback=None):
        from cellwiki.domain.extraction import ExtractionResult, PaperReference
        from cellwiki.models import CellTypeExtract

        paper = PaperReference(paper_id=source.source_id, title="Delete fixture", local_path=source.stored_path)
        return ExtractionResult(
            paper=paper,
            cell_types=[
                CellTypeExtract(
                    name="Regulatory T cell",
                    standard_name="regulatory_t_cell",
                    paper_ref=paper,
                )
            ],
        )


def _save_changeset(project_root: Path, source_id: str) -> ChangeSet:
    """Persist a raw proposal without starting an ingest run (no task events)."""
    repository = ChangeSetRepository(project_root)
    return repository.save(
        ChangeSet(
            change_set_id=f"cs_{uuid.uuid4().hex}",
            run_id=f"run_delete_{uuid.uuid4().hex[:8]}",
            project_id="cellwiki",
            operations=[
                ChangeOperation(
                    type=ChangeOperationType.UPSERT_EXTRACTION,
                    target_id=source_id,
                    payload={"fixture": True},
                )
            ],
            evidence=[],
            review_items=[],
            risk=RiskLevel.MEDIUM,
            reason="Deletion fixture proposal",
        )
    )


def _tombstones(project_root: Path) -> list[dict]:
    deleted_dir = project_root / "data" / "runtime" / "deleted"
    if not deleted_dir.exists():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in deleted_dir.glob("*.deleted.*.json")
    ]


# ---------------------------------------------------------------------------
# ChangeSet 删除
# ---------------------------------------------------------------------------
def test_rejected_changeset_delete_removes_proposal_and_audit_artifacts(tmp_path: Path) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    change_set = IngestService(tmp_path, extractor=DeleteFixtureExtractor()).prepare_change_set(
        source.source_id,
        "run_reject_delete",
    )
    change_set_id = change_set.change_set_id
    client = TestClient(create_app(tmp_path))

    rejected = client.post(
        f"/api/changesets/{change_set_id}/decision",
        json={"approved": False, "reason": "Reject before deleting."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    deleted = client.delete(f"/api/changesets/{change_set_id}")
    assert deleted.status_code == 204

    # ChangeSet、审批审计文件已被物理删除，审查视图返回 404
    assert client.get(f"/api/changesets/{change_set_id}/review").status_code == 404
    assert not (tmp_path / "data" / "runtime" / "changesets" / f"{change_set_id}.json").exists()
    assert not (tmp_path / "data" / "runtime" / "approvals" / f"{change_set_id}.json").exists()
    # 追加式运行日志保留
    run_dir = tmp_path / "data" / "runtime" / "tasks" / "run_reject_delete"
    assert run_dir.exists() and any(run_dir.glob("evt_*.json"))
    # 先落 tombstone：仅 id 与删除时间
    tombstones = _tombstones(tmp_path)
    assert len(tombstones) == 1
    assert tombstones[0]["change_set_id"] == change_set_id
    assert tombstones[0]["deleted_at"]
    # 再次删除返回 404
    assert client.delete(f"/api/changesets/{change_set_id}").status_code == 404


def test_committed_changeset_delete_is_blocked_until_rolled_back(tmp_path: Path) -> None:
    change_set = _save_changeset(tmp_path, "src_9b5a9e828bfb06c465f9")
    commits_dir = tmp_path / "data" / "runtime" / "commits"
    commits_dir.mkdir(parents=True, exist_ok=True)
    (commits_dir / f"{change_set.change_set_id}.json").write_text(
        '{"commit_id": "cm_fixture"}',
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))

    response = client.delete(f"/api/changesets/{change_set.change_set_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["blocking"] == "committed"
    assert (tmp_path / "data" / "runtime" / "changesets" / f"{change_set.change_set_id}.json").exists()


def test_changeset_delete_is_blocked_while_revision_children_exist(tmp_path: Path) -> None:
    parent = _save_changeset(tmp_path, "src_9b5a9e828bfb06c465f9")
    child = _save_changeset(tmp_path, "src_9b5a9e828bfb06c465f9")
    child_path = tmp_path / "data" / "runtime" / "changesets" / f"{child.change_set_id}.json"
    child_doc = json.loads(child_path.read_text(encoding="utf-8"))
    child_doc["parent_change_set_id"] = parent.change_set_id
    child_path.write_text(json.dumps(child_doc), encoding="utf-8")

    client = TestClient(create_app(tmp_path))
    response = client.delete(f"/api/changesets/{parent.change_set_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["blocking"] == "has_revisions"
    assert child.change_set_id in response.json()["detail"]["detail"]


def test_changeset_delete_blocked_while_ledger_run_is_committing(tmp_path: Path) -> None:
    change_set = _save_changeset(tmp_path, "src_9b5a9e828bfb06c465f9")
    TaskEventRepository(tmp_path).record(
        run_id="run_live_commit",
        source_id="src_9b5a9e828bfb06c465f9",
        stage=IngestStage.PUBLISH,
        status=TaskStatus.COMMITTING,
        message="Publishing the approved ChangeSet.",
        progress=70,
        change_set_id=change_set.change_set_id,
    )
    client = TestClient(create_app(tmp_path))

    response = client.delete(f"/api/changesets/{change_set.change_set_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["blocking"] == "run_waiting"
    assert "run_live_commit" in response.json()["detail"]["run_ids"]


def test_awaiting_review_changeset_deletable_after_decision_without_terminal_event(tmp_path: Path) -> None:
    """Regression: decisions written through Agent-side flows leave the ledger at AWAITING_REVIEW.

    这类提案（已拒绝/已回滚）不应被永远当作 run_waiting 挡住删除。
    """
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    change_set = IngestService(tmp_path, extractor=DeleteFixtureExtractor()).prepare_change_set(
        source.source_id,
        "run_agent_decided",
    )
    ApprovalRepository(tmp_path).save(
        change_set.change_set_id,
        ApprovalDecision(approved=False, decided_by="agent-hitl", reason="Rejected via agent."),
    )
    client = TestClient(create_app(tmp_path))

    # 账本最新事件仍是 awaiting_review，但决策已存在 -> 应可删除
    response = client.delete(f"/api/changesets/{change_set.change_set_id}")

    assert response.status_code == 204
    assert client.get(f"/api/changesets/{change_set.change_set_id}/review").status_code == 404


def test_changeset_delete_blocked_while_agent_run_waits_for_approval(tmp_path: Path) -> None:
    change_set = _save_changeset(tmp_path, "src_9b5a9e828bfb06c465f9")
    store = RuntimeStore(tmp_path)
    store.create_run(
        AgentRun(
            run_id="run_paused_approval",
            thread_id="thread_1",
            task_kind="review",
            input_message="Please review this proposal.",
            status=AgentRunStatus.WAITING_APPROVAL,
        )
    )
    store.append_message(
        thread_id="thread_1",
        run_id="run_paused_approval",
        role="assistant",
        content="ChangeSet is ready for review.",
        data={"change_set_id": change_set.change_set_id},
    )
    client = TestClient(create_app(tmp_path))

    response = client.delete(f"/api/changesets/{change_set.change_set_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["blocking"] == "run_waiting"
    assert "run_paused_approval" in response.json()["detail"]["run_ids"]


# ---------------------------------------------------------------------------
# Source 删除
# ---------------------------------------------------------------------------
def test_source_delete_removes_registered_files_and_caches(tmp_path: Path) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    source_id = source.source_id
    # 制造解析/提取缓存，验证级联清理
    for cache_name in ("parsing", "extraction_cache"):
        cache_dir = tmp_path / "data" / "runtime" / cache_name / source_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "block.json").write_text("{}", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    response = client.delete(f"/api/sources/{source_id}")

    assert response.status_code == 204
    assert not (tmp_path / "data" / "runtime" / "sources" / f"{source_id}.json").exists()
    assert not (tmp_path / "data" / "sources" / source_id).exists()
    assert not (tmp_path / "data" / "runtime" / "parsing" / source_id).exists()
    assert not (tmp_path / "data" / "runtime" / "extraction_cache" / source_id).exists()
    tombstones = _tombstones(tmp_path)
    assert tombstones[0]["source_id"] == source_id
    assert tombstones[0]["deleted_at"]
    assert client.get(f"/api/sources/{source_id}/file").status_code == 404


def test_source_delete_is_blocked_while_changesets_reference_it(tmp_path: Path) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    change_set = _save_changeset(tmp_path, source.source_id)
    client = TestClient(create_app(tmp_path))

    blocked = client.delete(f"/api/sources/{source.source_id}")
    assert blocked.status_code == 409
    assert change_set.change_set_id in blocked.json()["detail"]["blocking_change_set_ids"]
    assert (tmp_path / "data" / "sources" / source.source_id).exists()

    # 先删 ChangeSet（无活跃 run，直接可删），再删 Source 成功
    assert client.delete(f"/api/changesets/{change_set.change_set_id}").status_code == 204
    assert client.delete(f"/api/sources/{source.source_id}").status_code == 204
    assert not (tmp_path / "data" / "runtime" / "sources" / f"{source.source_id}.json").exists()


def test_source_deletable_after_ingest_run_left_awaiting_review(tmp_path: Path) -> None:
    """Regression: 已结束的历史运行（账本停在 awaiting_review）不应阻止来源删除。"""
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    change_set = IngestService(tmp_path, extractor=DeleteFixtureExtractor()).prepare_change_set(
        source.source_id,
        "run_src_finished",
    )
    client = TestClient(create_app(tmp_path))

    # 先删掉引用该来源的变更集（无活跃运行、无决策，可直接删）
    assert client.delete(f"/api/changesets/{change_set.change_set_id}").status_code == 204
    # 来源现在可删：账本最新事件虽仍是 awaiting_review，但运行已结束
    response = client.delete(f"/api/sources/{source.source_id}")
    assert response.status_code == 204
    assert not (tmp_path / "data" / "runtime" / "sources" / f"{source.source_id}.json").exists()


def test_source_delete_blocked_while_run_committing(tmp_path: Path) -> None:
    source = SourceRegistry(tmp_path).register(FIXTURE, source_type="paper")
    TaskEventRepository(tmp_path).record(
        run_id="run_src_live_commit",
        source_id=source.source_id,
        stage=IngestStage.PUBLISH,
        status=TaskStatus.COMMITTING,
        message="Publishing the approved ChangeSet.",
        progress=70,
    )
    client = TestClient(create_app(tmp_path))

    response = client.delete(f"/api/sources/{source.source_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["active_run_ids"] == ["run_src_live_commit"]


def test_delete_missing_resources_returns_404(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    assert client.delete("/api/changesets/cs_00000000000000000000").status_code == 404
    assert client.delete("/api/sources/src_00000000000000000000").status_code == 404
