"""Workspace-memory API tests (ADR-0016, slice 6)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.memory import MemoryKind, MemoryTopicFamily
from cellwiki.services.agent_memory import (
    MEMORY_INDEX_FILE,
    MEMORY_SUMMARY_FILE,
    WorkspaceMemoryStore,
    render_summary,
)
from cellwiki.services.agent_memory_jobs import MemoryJobStore
from cellwiki.services.runtime_store import RuntimeStore


def _seed(
    root: Path,
    *,
    title: str = "逐行审批",
    origin_thread_id: str = "thread_api",
    origin_run_id: str = "run_api",
) -> str:
    memory = WorkspaceMemoryStore(root, RuntimeStore(root).path)
    entry = memory.upsert_entry(
        memory_id="mem_api",
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title=title,
        file_name="run-approval.md",
        derived_hash="",
        origin_thread_id=origin_thread_id,
        origin_run_id=origin_run_id,
        source_refs=[f"thread:{origin_thread_id}", f"run:{origin_run_id}"],
    )
    derived = memory.write_entry_file(entry, "评审时逐行判定 diff。")
    memory.upsert_entry(
        memory_id="mem_api",
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title=title,
        file_name="run-approval.md",
        derived_hash=derived,
        origin_thread_id=origin_thread_id,
        origin_run_id=origin_run_id,
        source_refs=[f"thread:{origin_thread_id}", f"run:{origin_run_id}"],
    )
    return "mem_api"


def _client(root: Path) -> TestClient:
    RuntimeStore(root)
    return TestClient(create_app(project_root=root))


def _seed_views(root: Path) -> None:
    memory = WorkspaceMemoryStore(root, RuntimeStore(root).path)
    memory.write_summary(
        render_summary(
            profile="工作区协作口径。",
            preferences="逐行审批。",
            tips="先读 schema。",
            index="### run 与审批\n- run-approval.md",
        )
    )
    memory.write_index("# Memory index\n")


def test_list_memory_returns_entries(tmp_path: Path):
    _seed(tmp_path)
    client = _client(tmp_path)

    response = client.get("/api/memory")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["entries"][0]["memory_id"] == "mem_api"
    assert [view["file_name"] for view in body["views"]] == [
        MEMORY_SUMMARY_FILE,
        MEMORY_INDEX_FILE,
    ]
    assert isinstance(body["status"]["enabled"], bool)
    assert body["status"]["pending_candidates"] == 0
    assert body["status"]["jobs_pending"] == 0


def test_list_memory_is_empty_without_entries(tmp_path: Path):
    client = _client(tmp_path)

    response = client.get("/api/memory")

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []
    assert body["count"] == 0
    assert [view["file_name"] for view in body["views"]] == [
        MEMORY_SUMMARY_FILE,
        MEMORY_INDEX_FILE,
    ]
    assert all(view["read_only"] is True for view in body["views"])
    assert all(view["exists"] is False for view in body["views"])
    assert isinstance(body["status"]["enabled"], bool)
    assert body["status"]["jobs_failed"] == 0


def test_list_memory_reports_scheduler_status(tmp_path: Path):
    _seed(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)
    jobs = MemoryJobStore(memory.runtime_db, tmp_path)
    jobs.upsert_thread_job(
        thread_id="thread_api",
        available_at=datetime(2026, 9, 29, 16, 0, tzinfo=UTC),
        input_watermark="run_api",
    )
    client = _client(tmp_path)

    status = client.get("/api/memory").json()["status"]

    assert status["jobs_pending"] == 1
    assert status["jobs_leased"] == 0
    assert status["next_job_at"].startswith("2026-09-29T16:00")
    assert status["last_consolidated_at"] is not None


def test_list_memory_reports_generated_derived_views(tmp_path: Path):
    _seed_views(tmp_path)
    client = _client(tmp_path)

    views = client.get("/api/memory").json()["views"]

    assert all(view["exists"] is True for view in views)
    assert all(view["updated_at"] for view in views)


def test_read_memory_summary_view_returns_content(tmp_path: Path):
    _seed_views(tmp_path)
    client = _client(tmp_path)

    response = client.get(f"/api/memory/views/{MEMORY_SUMMARY_FILE}")

    assert response.status_code == 200
    body = response.json()
    assert body["file_name"] == MEMORY_SUMMARY_FILE
    assert body["read_only"] is True
    assert body["content"].startswith("v1")
    assert "逐行审批" in body["content"]


def test_read_memory_index_view_returns_content(tmp_path: Path):
    _seed_views(tmp_path)
    client = _client(tmp_path)

    response = client.get(f"/api/memory/views/{MEMORY_INDEX_FILE}")

    assert response.status_code == 200
    assert response.json()["content"] == "# Memory index\n"


def test_read_memory_view_rejects_unknown_file(tmp_path: Path):
    client = _client(tmp_path)

    assert client.get("/api/memory/views/other.md").status_code == 404


def test_read_memory_view_missing_file_returns_404(tmp_path: Path):
    client = _client(tmp_path)

    assert (
        client.get(f"/api/memory/views/{MEMORY_SUMMARY_FILE}").status_code == 404
    )


def test_read_memory_returns_body(tmp_path: Path):
    _seed(tmp_path)
    client = _client(tmp_path)

    response = client.get("/api/memory/mem_api")

    assert response.status_code == 200
    assert "逐行判定 diff" in response.json()["body"]


def test_read_memory_missing_returns_404(tmp_path: Path):
    client = _client(tmp_path)

    assert client.get("/api/memory/missing").status_code == 404


def test_update_memory_marks_user_edited(tmp_path: Path):
    _seed(tmp_path)
    client = _client(tmp_path)

    response = client.put(
        "/api/memory/mem_api", json={"body": "用户改写后的内容。"}
    )

    assert response.status_code == 200
    assert response.json()["user_edited"] is True
    assert client.get("/api/memory/mem_api").json()["body"] == "用户改写后的内容。"


def test_update_memory_can_reenable_auto_update(tmp_path: Path):
    _seed(tmp_path)
    client = _client(tmp_path)

    response = client.put(
        "/api/memory/mem_api",
        json={"body": "重新纳入自动更新。", "reenable_auto_update": True},
    )

    assert response.status_code == 200
    assert response.json()["user_edited"] is False
    assert response.json()["auto_update"] is True


def test_delete_memory_removes_entry_and_file(tmp_path: Path):
    _seed(tmp_path)
    client = _client(tmp_path)

    response = client.delete("/api/memory/mem_api")

    assert response.status_code == 200
    assert response.json() == {"deleted": "mem_api"}
    assert client.get("/api/memory/mem_api").status_code == 404
    assert not (tmp_path / "data" / "runtime" / "memory" / "run-approval.md").exists()


def test_delete_memory_missing_returns_404(tmp_path: Path):
    client = _client(tmp_path)

    assert client.delete("/api/memory/missing").status_code == 404


def test_list_memory_returns_provenance(tmp_path: Path):
    _seed(tmp_path)
    client = _client(tmp_path)

    entry = client.get("/api/memory").json()["entries"][0]

    assert entry["origin_thread_id"] == "thread_api"
    assert entry["origin_run_id"] == "run_api"
    assert entry["source_refs"] == ["thread:thread_api", "run:run_api"]


def test_delete_memory_source_removes_matching_entries_and_candidates(
    tmp_path: Path,
):
    _seed(tmp_path)
    memory = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)
    memory.add_candidate(
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title="同一来源候选",
        body="同一来源候选。",
        origin_thread_id="thread_api",
        origin_run_id="run_api",
    )
    client = _client(tmp_path)

    response = client.delete("/api/memory/sources/thread_api")

    assert response.status_code == 200
    assert response.json() == {
        "source": "thread_api",
        "deleted_entries": 1,
        "deleted_candidates": 1,
    }
    assert client.get("/api/memory").json()["count"] == 0


def test_consolidate_memory_requires_enabled(monkeypatch, tmp_path: Path):
    import cellwiki.config as config_module

    # 显式关闭，避免测试结果依赖本机 .env 的开关状态。
    monkeypatch.setattr(config_module.settings, "agent_memory_enabled", False)
    client = _client(tmp_path)

    assert client.post("/api/memory/consolidate").status_code == 409


def test_consolidate_memory_without_model_returns_422(monkeypatch, tmp_path: Path):
    import cellwiki.config as config_module

    monkeypatch.setattr(config_module.settings, "agent_memory_enabled", True)
    memory = WorkspaceMemoryStore(tmp_path, RuntimeStore(tmp_path).path)
    memory.add_candidate(
        kind=MemoryKind.LESSON,
        topic_family=MemoryTopicFamily.EVALUATION,
        title="待合并",
        body="需要有模型才能合并。",
        origin_thread_id="thread_api",
        origin_run_id="run_api",
    )
    client = _client(tmp_path)

    assert client.post("/api/memory/consolidate").status_code == 422
