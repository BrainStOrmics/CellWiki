"""Workspace-memory API tests (ADR-0016, slice 6)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.memory import MemoryKind, MemoryTopicFamily
from cellwiki.services.agent_memory import WorkspaceMemoryStore
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


def test_list_memory_returns_entries(tmp_path: Path):
    _seed(tmp_path)
    client = _client(tmp_path)

    response = client.get("/api/memory")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["entries"][0]["memory_id"] == "mem_api"


def test_list_memory_is_empty_without_entries(tmp_path: Path):
    client = _client(tmp_path)

    response = client.get("/api/memory")

    assert response.status_code == 200
    assert response.json() == {"entries": [], "count": 0}


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
