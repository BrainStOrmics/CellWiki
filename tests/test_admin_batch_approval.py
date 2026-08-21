"""Phase C tests: audited admin batch approval service + API endpoint."""
import json

import pytest
from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.contracts import (
    ChangeOperation,
    ChangeOperationType,
    PipelineTaskType,
    RiskLevel,
)
from cellwiki.services.batch_approvals import AdminBatchApprovalService
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.sources import SourceRegistry


def _register_source(root, name: str = "batch"):
    path = root / f"{name}.md"
    path.write_text(
        f"# {name}\n\nTumor tissue contained LRRC15+ fibroblasts with high ENTPD1.\n",
        encoding="utf-8",
    )
    return SourceRegistry(root).register(path, source_type="paper")


def _extraction_dict(source_id: str) -> dict:
    return {
        "paper": {"paper_id": source_id, "title": "Batch", "doi": "", "year": 2024, "local_path": ""},
        "cell_types": [
            {
                "name": "LRRC15+ fibroblasts",
                "standard_name": "lrrc15_positive_fibroblast",
                "cl_id": None,
                "synonyms": [],
                "parent_type": None,
                "species": [], "tissues": [], "diseases": [],
                "markers": [{"gene_symbol": "LRRC15", "marker_type": "positive", "evidence": "LRRC15+ fibroblasts", "strength": ""}],
                "functions": [],
                "subpopulations": [],
                "description": "Tumor tissue contained LRRC15+ fibroblasts with high ENTPD1.",
                "paper_ref": {"paper_id": source_id, "title": "Batch", "doi": "", "year": 2024, "local_path": ""},
            }
        ],
        "raw_relationships": [],
        "claims": [],
        "source_document": {"source_id": source_id},
    }


def _propose(root, source_id: str, run_id: str) -> str:
    repository = ChangeSetRepository(root)
    change_set = repository.create_proposal(
        run_id=run_id,
        task_type=PipelineTaskType.INGEST,
        operations=[
            ChangeOperation(
                type=ChangeOperationType.UPSERT_EXTRACTION,
                target_id=source_id,
                payload=_extraction_dict(source_id),
            )
        ],
        reason="batch acceptance fixture",
        risk=RiskLevel.LOW,
    )
    return change_set.change_set_id


def test_admin_batch_approval_commits_and_writes_audit(tmp_path):
    first_source = _register_source(tmp_path, "batch_a")
    second_source = _register_source(tmp_path, "batch_b")
    first = _propose(tmp_path, first_source.source_id, "run_batch_1")
    second = _propose(tmp_path, second_source.source_id, "run_batch_2")

    service = AdminBatchApprovalService(tmp_path)
    result = service.approve_batch(
        [first, second],
        decided_by="admin-user",
        reason="acceptance batch",
        role="admin",
    )

    assert len(result["results"]) == 2
    assert all(item["status"] == "committed" for item in result["results"])
    audit_path = tmp_path / "data" / "runtime" / "approvals" / "batches" / f"{result['batch_id']}.json"
    assert audit_path.is_file()
    record = json.loads(audit_path.read_text(encoding="utf-8"))
    assert record["batch_id"] == result["batch_id"]
    assert record["decided_by"] == "admin-user"
    assert set(record["change_set_ids"]) == {first, second}
    wiki_page = tmp_path / "wiki" / "cell_types" / "lrrc15_positive_fibroblast.md"
    assert wiki_page.is_file()


def test_admin_batch_approval_rejects_model_decisions_and_empty_reason(tmp_path):
    source = _register_source(tmp_path)
    change_set_id = _propose(tmp_path, source.source_id, "run_batch_reject")
    service = AdminBatchApprovalService(tmp_path)
    with pytest.raises(ValueError, match="model-generated"):
        service.approve_batch([change_set_id], decided_by="agent-secret", reason="x")
    with pytest.raises(ValueError, match="non-empty reason"):
        service.approve_batch([change_set_id], decided_by="admin-user", reason="  ")


def test_admin_batch_approval_api_endpoint(tmp_path):
    source = _register_source(tmp_path)
    change_set_id = _propose(tmp_path, source.source_id, "run_batch_api")
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/api/admin/approvals/batch",
        json={
            "change_set_ids": [change_set_id],
            "reason": "api batch acceptance",
            "decided_by": "admin-user",
            "role": "admin",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["results"][0]["status"] == "committed"
    assert (tmp_path / "wiki" / "cell_types" / "lrrc15_positive_fibroblast.md").is_file()
    agent_response = client.post(
        "/api/admin/approvals/batch",
        json={"change_set_ids": [change_set_id], "reason": "x", "decided_by": "agent-bad"},
    )
    assert agent_response.status_code == 422
    assert "model-generated" in agent_response.json()["detail"]
