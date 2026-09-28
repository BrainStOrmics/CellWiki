"""Workspace-memory API tests (ADR-0016, slice 6)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.memory import MemoryKind, MemoryTopicFamily
from cellwiki.services.agent_memory import WorkspaceMemoryStore
from cellwiki.services.runtime_store import RuntimeStore


def _seed(root: Path, *, title: str = "逐行审批") -> str:
    memory = WorkspaceMemoryStore(root, RuntimeStore(root).path)
    entry = memory.upsert_entry(
        memory_id="mem_api",
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title=title,
        file_name="run-approval.md",
        derived_hash="",
    )
    derived = memory.write_entry_file(entry, "评审时逐行判定 diff。")
    memory.upsert_entry(
        memory_id="mem_api",
        kind=MemoryKind.PREFERENCE,
        topic_family=MemoryTopicFamily.RUN_APPROVAL,
        title=title,
        file_name="run-approval.md",
        derived_hash=derived,
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