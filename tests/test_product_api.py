# =============================================================================
# 产品 API 测试 —— 验证 FastAPI 产品端点的正确性
# =============================================================================

import time
from pathlib import Path
from typing import Iterable

import cellwiki.api.extensions as extension_api
from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.contracts import ApprovalPolicy, ChangeOperation, ChangeOperationType, ChangeSet, RiskLevel
from cellwiki.domain.pipeline import PipelineTaskType
from cellwiki.domain.runs import AgentEventType
from cellwiki.domain.research import ResearchRefreshRun, ResearchRefreshStatus
from cellwiki.models import CellTypeExtract, ExtractionResult, PaperReference
from cellwiki.services.agent_runtime import AgentRuntimeManager, RuntimeSignal
from cellwiki.services.changesets import ChangeSetRepository
from cellwiki.services.parsing import DocumentParsingService
from cellwiki.services.projection import ProjectionService
from cellwiki.services.pipeline import KnowledgePipelineHarness
from cellwiki.services.sources import SourceRegistry

INTERNAL_COMPAT_HEADERS = {"X-CellWiki-Internal": "1"}


class _ApiAgentAdapter:
    """Keep Product API streaming tests independent from an external model provider."""

    def execute(self, *, thread_id: str, message, context) -> Iterable[RuntimeSignal]:
        yield RuntimeSignal(type=AgentEventType.MESSAGE_DELTA, message="live ")
        yield RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="answer",
            data={"answer": "answer", "citations": [], "confidence": "high"},
        )

    def close(self) -> None:
        return None


def test_product_api_exposes_pipeline_state_and_approval_policy(tmp_path: Path):
    client = TestClient(create_app(tmp_path))

    initial = client.get("/api/pipeline/status")
    changed = client.post(
        "/api/pipeline/approval-policy",
        json={"policy": "auto_all"},
    )
    current = client.get("/api/pipeline/status")

    assert initial.status_code == 200
    assert initial.json()["approval_policy"] == "auto_low_risk"
    assert changed.status_code == 200
    assert changed.json()["approval_policy"] == "auto_all"
    assert current.json()["approval_policy"] == "auto_all"
    assert current.json()["default_reviewer"] == "default-reviewer"


def test_product_api_exposes_governed_external_research_refresh(monkeypatch, tmp_path: Path):
    refresh_run = ResearchRefreshRun(
        refresh_run_id="refresh_test",
        project_id="cellwiki",
        query="Treg FOXP3",
        provider="test-provider",
        snapshot_id="snapshot_test",
        knowledge_version="sha256:test",
        requested_limit=5,
        status=ResearchRefreshStatus.COMPLETED,
        candidate_ids=["research_candidate"],
        provider_provenance={"provider": "test-provider", "query": "Treg FOXP3"},
    )

    class StubResearchService:
        def __init__(self, project_root):
            self.project_root = project_root

        def refresh(self, query: str, *, project_id: str, limit: int):
            return refresh_run

    monkeypatch.setattr(extension_api, "ResearchService", StubResearchService)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/internal/research/refresh",
        json={"project_id": "cellwiki", "query": "Treg FOXP3", "limit": 5},
        headers=INTERNAL_COMPAT_HEADERS,
    )

    assert response.status_code == 202
    assert response.json()["refresh_run_id"] == "refresh_test"
    assert response.json()["snapshot_id"] == "snapshot_test"
    assert response.json()["candidate_ids"] == ["research_candidate"]


def test_product_api_rejects_public_operation_compatibility_routes(tmp_path: Path):
    client = TestClient(create_app(tmp_path))

    for path, payload in (
        ("/api/quality/fixes", {"finding_ids": [], "run_id": "public"}),
        ("/api/research/refresh", {"query": "FOXP3"}),
        ("/api/research/search", {"query": "FOXP3"}),
        ("/api/lint/l2/review", {}),
        ("/api/internal/quality/fixes", {"finding_ids": ["missing"], "run_id": "missing-header"}),
        ("/api/internal/research/search", {"query": "FOXP3"}),
    ):
        response = client.post(path, json=payload)
        assert response.status_code == 404, path


def test_product_api_exposes_changeset_rebase_result(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    change_set = repository.create_proposal(
        run_id="run_rebase_api",
        task_type=PipelineTaskType.INGEST,
        operations=[
            ChangeOperation(
                type=ChangeOperationType.UPDATE_CURATION,
                target_id="regulatory_t_cell",
                payload={"content": "FOXP3 evidence."},
            )
        ],
        reason="Test rebase endpoint.",
        risk=RiskLevel.MEDIUM,
    )
    client = TestClient(create_app(tmp_path))

    response = client.post(f"/api/changesets/{change_set.change_set_id}/rebase")

    assert response.status_code == 200
    assert response.json()["original_change_set_id"] == change_set.change_set_id
    assert response.json()["status"] == "current"


def test_product_api_exposes_durable_agent_runs_and_sse(tmp_path: Path):
    runtime = AgentRuntimeManager(tmp_path, adapter=_ApiAgentAdapter())
    client = TestClient(create_app(tmp_path, agent_runtime=runtime))
    try:
        thread = client.post("/api/agent/threads").json()
        started = client.post(
            "/api/agent/runs",
            json={"thread_id": thread["thread_id"], "message": "question"},
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            run = client.get(f"/api/agent/runs/{run_id}").json()
            if run["status"] == "succeeded":
                break
            time.sleep(0.01)
        assert run["status"] == "succeeded"
        assert client.get(
            "/api/agent/runs", params={"thread_id": thread["thread_id"]}
        ).json()[0]["run_id"] == run_id

        events = client.get(f"/api/agent/runs/{run_id}/events").json()
        assert any(event["type"] == "final_response" for event in events)
        stream = client.get(f"/api/agent/runs/{run_id}/stream")
        assert stream.status_code == 200
        assert "event: final_response" in stream.text
        assert "event: run_status" in stream.text
    finally:
        runtime.close()


def test_product_api_restores_and_deletes_complete_thread_history(tmp_path: Path):
    runtime = AgentRuntimeManager(tmp_path, adapter=_ApiAgentAdapter())
    client = TestClient(create_app(tmp_path, agent_runtime=runtime))
    try:
        thread = client.post("/api/agent/threads").json()["thread_id"]
        started = client.post(
            "/api/agent/runs",
            json={"thread_id": thread, "message": "question"},
        )
        run_id = started.json()["run_id"]

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if client.get(f"/api/agent/runs/{run_id}").json()["status"] == "succeeded":
                break
            time.sleep(0.01)

        messages = client.get(f"/api/agent/threads/{thread}/messages")
        assert messages.status_code == 200
        assert [(item["role"], item["content"]) for item in messages.json()] == [
            ("user", "question"),
            ("assistant", "answer"),
        ]

        deleted = client.delete(f"/api/agent/threads/{thread}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted_runs"] == 1
        assert client.get(f"/api/agent/threads/{thread}/messages").json() == []
        assert client.get("/api/agent/runs", params={"thread_id": thread}).json() == []
    finally:
        runtime.close()


def test_product_api_returns_not_found_for_invalid_thread_delete(tmp_path: Path):
    client = TestClient(create_app(tmp_path))

    response = client.delete("/api/agent/threads/thread_not-a-valid-id")

    assert response.status_code == 404
    assert response.json()["detail"] == "agent thread not found"


def test_product_api_persists_sent_attachment_metadata_in_user_message(tmp_path: Path):
    runtime = AgentRuntimeManager(tmp_path, adapter=_ApiAgentAdapter())
    client = TestClient(create_app(tmp_path, agent_runtime=runtime))
    try:
        thread = client.post("/api/agent/threads").json()["thread_id"]
        uploaded = client.post(
            f"/api/agent/threads/{thread}/attachments",
            files={"files": ("notes.txt", b"FOXP3 attachment evidence.", "text/plain")},
        )
        attachment = uploaded.json()[0]

        started = client.post(
            "/api/agent/runs",
            json={
                "thread_id": thread,
                "message": "Read the attached notes.",
                "attachment_ids": [attachment["attachment_id"]],
            },
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            run = client.get(f"/api/agent/runs/{run_id}").json()
            if run["status"] == "succeeded":
                break
            time.sleep(0.01)

        assert run["status"] == "succeeded"
        messages = client.get(f"/api/agent/threads/{thread}/messages").json()
        assert messages[0]["role"] == "user"
        assert messages[0]["data"]["attachments"] == [
            {
                "attachment_id": attachment["attachment_id"],
                "original_name": "notes.txt",
                "media_type": "text/plain",
                "content_hash": attachment["content_hash"],
                "size_bytes": len(b"FOXP3 attachment evidence."),
            }
        ]
        assert "text" not in messages[0]["data"]["attachments"][0]

        cannot_delete = client.delete(
            f"/api/agent/threads/{thread}/attachments/{attachment['attachment_id']}"
        )
        assert cannot_delete.status_code == 409
        assert client.get(f"/api/agent/threads/{thread}/attachments").json() == [attachment]
    finally:
        runtime.close()


def test_product_api_manages_thread_scoped_agent_attachments(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    thread = client.post("/api/agent/threads").json()["thread_id"]

    uploaded = client.post(
        f"/api/agent/threads/{thread}/attachments",
        files={"files": ("notes.txt", b"FOXP3 attachment evidence.", "text/plain")},
    )

    assert uploaded.status_code == 201
    attachment = uploaded.json()[0]
    assert attachment["thread_id"] == thread
    assert attachment["attachment_id"].startswith("att_")
    assert attachment["original_name"] == "notes.txt"
    assert attachment["media_type"] == "text/plain"
    assert attachment["promoted_source_id"] is None
    assert client.get(f"/api/agent/threads/{thread}/attachments").json() == [attachment]

    deleted_pending = client.delete(
        f"/api/agent/threads/{thread}/attachments/{attachment['attachment_id']}"
    )

    assert deleted_pending.status_code == 200
    assert deleted_pending.json() == {
        "thread_id": thread,
        "attachment_id": attachment["attachment_id"],
        "deleted": True,
    }
    assert client.get(f"/api/agent/threads/{thread}/attachments").json() == []

    remaining = client.post(
        f"/api/agent/threads/{thread}/attachments",
        files={"files": ("remaining.txt", b"still pending", "text/plain")},
    )
    assert remaining.status_code == 201

    deleted = client.delete(f"/api/agent/threads/{thread}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_attachments"] == 1
    assert client.get(f"/api/agent/threads/{thread}/attachments").json() == []


def test_product_api_rejects_attachment_ids_from_another_thread(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    owner_thread = client.post("/api/agent/threads").json()["thread_id"]
    other_thread = client.post("/api/agent/threads").json()["thread_id"]
    uploaded = client.post(
        f"/api/agent/threads/{owner_thread}/attachments",
        files={"files": ("notes.txt", b"FOXP3 evidence", "text/plain")},
    )
    attachment_id = uploaded.json()[0]["attachment_id"]

    started = client.post(
        "/api/agent/runs",
        json={
            "thread_id": other_thread,
            "message": "Read the attached notes.",
            "attachment_ids": [attachment_id],
        },
    )

    assert started.status_code == 422
    assert "attachment" in started.json()["detail"]


def test_product_api_rejects_unknown_attachment_ids(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    thread = client.post("/api/agent/threads").json()["thread_id"]

    started = client.post(
        "/api/agent/runs",
        json={
            "thread_id": thread,
            "message": "Read the attached notes.",
            "attachment_ids": ["att_" + "f" * 32],
        },
    )

    assert started.status_code == 422
    assert "attachment" in started.json()["detail"]


def test_product_api_reads_wiki_and_registers_sources(tmp_path: Path):
    pages = tmp_path / "wiki" / "cell_types"
    pages.mkdir(parents=True)
    (pages / "regulatory_t_cell.md").write_text(
        "---\nstandard_name: regulatory_t_cell\n---\n\n# Regulatory T Cell\n\nFOXP3 evidence.",
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))

    health = client.get("/health")
    tree = client.get("/api/projects/cellwiki/tree")
    page = client.get("/api/pages/regulatory_t_cell")
    search = client.get("/api/search", params={"q": "FOXP3"})
    upload = client.post(
        "/api/sources",
        files={"file": ("paper.pdf", b"paper bytes", "application/pdf")},
    )

    assert health.json() == {"status": "ok"}
    assert tree.json()[0]["page_id"] == "regulatory_t_cell"
    assert page.json()["frontmatter"]["standard_name"] == "regulatory_t_cell"
    assert search.json()[0]["page_id"] == "regulatory_t_cell"
    assert upload.status_code == 201
    assert upload.json()["source_id"].startswith("src_")
    assert client.get("/api/sources").json() == [upload.json()]


def test_product_api_query_exposes_formal_knowledge_contract(tmp_path: Path):
    pages = tmp_path / "wiki" / "cell_types"
    pages.mkdir(parents=True)
    (pages / "regulatory_t_cell.md").write_text(
        "---\ndisplay_name: Regulatory T Cell\nreferences:\n"
        "  - paper_id: src_formal\n    title: Formal paper\n---\n\nFOXP3 marker.",
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/query", params={"q": "FOXP3"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "formal"
    assert payload["results"][0]["source_ids"] == ["src_formal"]
    assert payload["knowledge_version"].startswith("sha256:")


def test_semantic_lint_api_captures_a_pipeline_snapshot(tmp_path: Path):
    extraction_dir = tmp_path / "data" / "extraction"
    extraction_dir.mkdir(parents=True)
    (extraction_dir / "src_empty.json").write_text('{"claims": []}', encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/lint/l2")
    snapshots = list((tmp_path / "data" / "runtime" / "pipeline" / "snapshots").glob("*.json"))

    assert response.status_code == 200
    assert snapshots
    assert any('"task_type": "lint"' in path.read_text(encoding="utf-8") for path in snapshots)


def test_product_api_rejects_path_traversal(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    response = client.get("/api/pages/..%2F..%2F.env")
    assert response.status_code in {404, 422}


def test_product_api_resolves_evidence_to_registered_source_file_and_block(tmp_path: Path):
    source_path = tmp_path / "paper.md"
    source_path.write_text("# Results\n\nRegulatory T cell expressed FOXP3.", encoding="utf-8")
    source = SourceRegistry(tmp_path).register(source_path, source_type="paper")
    document = DocumentParsingService(tmp_path).parse(source)
    block = next(item for item in document.all_blocks() if "FOXP3" in item.text)
    client = TestClient(create_app(tmp_path))

    raw = client.get(f"/api/sources/{source.source_id}/file")
    resolved = client.get(f"/api/sources/{source.source_id}/evidence/{block.block_id}")

    assert raw.status_code == 200
    assert "inline" in raw.headers["content-disposition"]
    assert "FOXP3" in raw.text
    assert resolved.json()["page_number"] == 1
    assert resolved.json()["block_id"] == block.block_id


def test_product_api_settings_never_return_the_api_key_and_preserve_unknown_env_values(
    tmp_path: Path,
):
    (tmp_path / ".env").write_text(
        "# local config\nOPENAI_API_KEY=secret-value\nOPENAI_MODEL=old-model\nCUSTOM_FLAG=keep-me\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))

    current = client.get("/api/settings")
    saved = client.post(
        "/api/settings",
        json={
            "openai_base_url": "https://provider.example/v1",
            "openai_model": "new-model",
            "openai_api_protocol": "responses",
            "openai_api_key": "",
            "log_level": "warning",
            "app_language": "en",
            "enable_agent_memory": True,
            "enable_external_research": True,
            "memory_recall_token_budget": 1200,
        },
    )

    assert current.json()["openai_api_key_configured"] is True
    assert current.json()["app_language"] == "zh-CN"
    assert "secret-value" not in current.text
    assert saved.status_code == 200
    assert saved.json()["restart_required"] is True
    assert saved.json()["enable_agent_memory"] is True
    assert saved.json()["enable_external_research"] is True
    assert saved.json()["memory_recall_token_budget"] == 1200
    assert saved.json()["openai_api_protocol"] == "responses"
    assert "secret-value" not in saved.text
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=secret-value" in env_text
    assert "OPENAI_MODEL=new-model" in env_text
    assert "OPENAI_API_PROTOCOL=responses" in env_text
    assert "LOG_LEVEL=WARNING" in env_text
    assert "APP_LANGUAGE=en" in env_text
    assert "ENABLE_AGENT_MEMORY=true" in env_text
    assert "ENABLE_EXTERNAL_RESEARCH=true" in env_text
    assert "MEMORY_RECALL_TOKEN_BUDGET=1200" in env_text
    assert "CUSTOM_FLAG=keep-me" in env_text


def test_product_api_settings_can_clear_the_stored_api_key(tmp_path: Path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=secret-value\n", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/settings",
        json={
            "openai_base_url": "",
            "openai_model": "qwen3.6-plus",
            "clear_openai_api_key": True,
            "log_level": "INFO",
            "app_language": "zh-CN",
        },
    )

    assert response.status_code == 200
    assert response.json()["openai_api_key_configured"] is False
    assert "OPENAI_API_KEY=\n" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_language_only_settings_change_does_not_require_agent_restart(tmp_path: Path):
    (tmp_path / ".env").write_text(
        "OPENAI_API_PROTOCOL=responses\nAPP_LANGUAGE=zh-CN\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/settings",
        json={
            "openai_base_url": "",
            "openai_model": "qwen3.6-plus",
            "log_level": "INFO",
            "app_language": "en",
        },
    )

    assert response.status_code == 200
    assert response.json()["app_language"] == "en"
    assert response.json()["openai_api_protocol"] == "responses"
    assert response.json()["restart_required"] is False


def test_product_api_lists_reviews_and_records_rejection(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    repository.save(_curation_change("cs_reject"))
    KnowledgePipelineHarness(tmp_path).set_approval_policy(ApprovalPolicy.MANUAL)
    client = TestClient(create_app(tmp_path))

    reviews = client.get("/api/changesets")
    rejected = client.post(
        "/api/changesets/cs_reject/decision",
        json={"approved": False, "reason": "Evidence is incomplete."},
    )

    assert reviews.status_code == 200
    assert reviews.json()[0]["status"] == "awaiting_review"
    assert reviews.json()[0]["preview"]["operations"][0]["target_id"] == "regulatory_t_cell"
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert not (tmp_path / "wiki" / "curation" / "cell_types" / "regulatory_t_cell.md").exists()
    timeline = client.get("/api/tasks/run_cs_reject")
    assert [event["status"] for event in timeline.json()["events"]] == ["rejected"]


def test_product_api_approved_review_uses_central_writer(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    repository.save(_curation_change("cs_approve"))
    client = TestClient(create_app(tmp_path))

    approved = client.post(
        "/api/changesets/cs_approve/decision",
        json={"approved": True, "reason": "Reviewed in the desktop workspace."},
    )
    review = client.get("/api/changesets/cs_approve/review")
    quality = client.get("/api/quality")

    assert approved.status_code == 200
    assert approved.json()["status"] == "committed"
    assert approved.json()["commit"]["changed_targets"] == ["regulatory_t_cell"]
    assert review.json()["status"] == "committed"
    assert quality.json()["status"] == "passed"
    timeline = client.get("/api/tasks/run_cs_approve")
    assert [event["status"] for event in timeline.json()["events"]] == ["committing", "committing", "committed"]
    curation = tmp_path / "wiki" / "curation" / "cell_types" / "regulatory_t_cell.md"
    assert curation.read_text(encoding="utf-8") == "FOXP3 is a commonly reported marker."


def test_explicit_rejection_overrides_the_default_auto_approval_policy(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    repository.save(_curation_change("cs_explicit_reject"))
    client = TestClient(create_app(tmp_path))

    rejected = client.post(
        "/api/changesets/cs_explicit_reject/decision",
        json={"approved": False, "reason": "The evidence needs curator correction."},
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["decision"]["decided_by"] == "desktop-user"
    assert not (
        tmp_path / "wiki" / "curation" / "cell_types" / "regulatory_t_cell.md"
    ).exists()


def test_review_exposes_field_diff_and_committed_change_can_be_rolled_back(tmp_path: Path):
    repository = ChangeSetRepository(tmp_path)
    repository.save(_curation_change("cs_rollback"))
    client = TestClient(create_app(tmp_path))

    review = client.get("/api/changesets/cs_rollback/review")
    committed = client.post(
        "/api/changesets/cs_rollback/decision",
        json={"approved": True, "reason": "Reviewed."},
    )
    rolled_back = client.post(
        "/api/changesets/cs_rollback/rollback",
        json={"reason": "The curator withdrew this note."},
    )

    differences = review.json()["preview"]["operations"][0]["field_diffs"]
    assert differences == [
        {
            "path": "/",
            "change_type": "changed",
            "before": "",
            "after": "FOXP3 is a commonly reported marker.",
        }
    ]
    assert committed.json()["status"] == "committed"
    assert rolled_back.status_code == 200
    assert rolled_back.json()["status"] == "rolled_back"
    assert not (tmp_path / "wiki" / "curation" / "cell_types" / "regulatory_t_cell.md").exists()


def test_quality_fix_is_proposed_then_rebuilds_projection_after_approval(tmp_path: Path):
    extraction_dir = tmp_path / "data" / "extraction"
    extraction_dir.mkdir(parents=True)
    paper = PaperReference(paper_id="src_fixture", title="Fixture")
    extraction = ExtractionResult(
        paper=paper,
        cell_types=[
            CellTypeExtract(
                name="Regulatory T cell",
                standard_name="regulatory_t_cell",
                paper_ref=paper,
            )
        ],
    )
    (extraction_dir / "src_fixture.json").write_text(
        extraction.model_dump_json(indent=2), encoding="utf-8"
    )
    ProjectionService(tmp_path).render()
    page = tmp_path / "wiki" / "cell_types" / "regulatory_t_cell.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace("# Regulatory T Cell", ""),
        encoding="utf-8",
    )
    KnowledgePipelineHarness(tmp_path).set_approval_policy(ApprovalPolicy.MANUAL)
    client = TestClient(create_app(tmp_path))

    finding = next(
        item
        for item in client.get("/api/quality").json()["issues"]
        if item["type"] == "missing_title"
    )
    proposed = client.post(
        "/api/internal/quality/fixes",
        json={"finding_ids": [finding["finding_id"]], "run_id": "run_lint_fix"},
        headers=INTERNAL_COMPAT_HEADERS,
    )

    assert proposed.status_code == 201
    assert proposed.json()["status"] == "awaiting_review"
    assert "# Regulatory T Cell" not in page.read_text(encoding="utf-8")

    applied = client.post(
        f"/api/changesets/{proposed.json()['change_set']['change_set_id']}/decision",
        json={"approved": True, "reason": "Deterministic projection repair."},
    )
    assert applied.status_code == 200
    assert applied.json()["status"] == "committed"
    assert "# Regulatory T Cell" in page.read_text(encoding="utf-8")
    assert client.get("/api/quality").json()["status"] != "failed"


def test_quality_fix_is_auto_committed_when_project_policy_is_auto_all(tmp_path: Path):
    extraction_dir = tmp_path / "data" / "extraction"
    extraction_dir.mkdir(parents=True)
    paper = PaperReference(paper_id="src_fixture", title="Fixture")
    extraction = ExtractionResult(
        paper=paper,
        cell_types=[
            CellTypeExtract(
                name="Regulatory T cell",
                standard_name="regulatory_t_cell",
                paper_ref=paper,
            )
        ],
    )
    (extraction_dir / "src_fixture.json").write_text(
        extraction.model_dump_json(indent=2), encoding="utf-8"
    )
    ProjectionService(tmp_path).render()
    page = tmp_path / "wiki" / "cell_types" / "regulatory_t_cell.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace("# Regulatory T Cell", ""),
        encoding="utf-8",
    )
    client = TestClient(create_app(tmp_path))
    assert client.post(
        "/api/pipeline/approval-policy",
        json={"policy": "auto_all"},
    ).status_code == 200

    finding = next(
        item
        for item in client.get("/api/quality").json()["issues"]
        if item["type"] == "missing_title"
    )
    proposed = client.post(
        "/api/internal/quality/fixes",
        json={"finding_ids": [finding["finding_id"]], "run_id": "run_auto_lint"},
        headers=INTERNAL_COMPAT_HEADERS,
    )

    assert proposed.status_code == 201
    assert proposed.json()["status"] == "committed"
    assert proposed.json()["decision"]["decided_by"] == "policy:auto_all"
    assert "# Regulatory T Cell" in page.read_text(encoding="utf-8")


def _curation_change(change_set_id: str) -> ChangeSet:
    return ChangeSet(
        change_set_id=change_set_id,
        run_id=f"run_{change_set_id}",
        project_id="cellwiki",
        risk=RiskLevel.MEDIUM,
        reason="Add a reviewed curation note.",
        operations=[
            ChangeOperation(
                type=ChangeOperationType.UPDATE_CURATION,
                target_id="regulatory_t_cell",
                payload={"content": "FOXP3 is a commonly reported marker."},
            )
        ],
    )
