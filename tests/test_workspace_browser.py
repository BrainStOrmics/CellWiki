# =============================================================================
# 工作区文件浏览器测试：tree / file / 受控 edit（合成 run + pending diff）
# =============================================================================

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app


def _git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@cellwiki.local"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test Agent"], check=True)


def _workspace(root: Path) -> None:
    (root / "wiki" / "cell_types").mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "cell_types" / "alpha.md").write_text("# Alpha Cell\n\nFOXP3.\n", encoding="utf-8")
    (root / "raw" / "src_aaaaaaaaaaaaaaaaaaaa").mkdir(parents=True, exist_ok=True)
    (root / "raw" / "src_aaaaaaaaaaaaaaaaaaaa" / "paper.md").write_text("# Paper\n", encoding="utf-8")
    (root / "raw" / "src_aaaaaaaaaaaaaaaaaaaa" / "meta.json").write_text("{}", encoding="utf-8")
    (root / "schema.md").write_text("# Custom schema\n", encoding="utf-8")
    (root / "index.md").write_text("# Index\n", encoding="utf-8")
    _git_init(root)


def test_workspace_tree_lists_wiki_raw_root_and_schema(tmp_path: Path):
    _workspace(tmp_path)
    client = TestClient(create_app(tmp_path))
    tree = client.get("/api/workspace/tree").json()
    paths = {entry["path"] for entry in tree}
    assert "wiki/cell_types/alpha.md" in paths
    assert "raw/src_aaaaaaaaaaaaaaaaaaaa/paper.md" in paths
    assert "raw/src_aaaaaaaaaaaaaaaaaaaa/meta.json" in paths
    assert "schema.md" in paths
    assert "index.md" in paths
    assert not any(entry["path"].startswith("data/") for entry in tree)
    assert not any(entry["path"] == "data" for entry in tree)


def test_workspace_file_reads_md_and_denies_runtime(tmp_path: Path):
    _workspace(tmp_path)
    client = TestClient(create_app(tmp_path))
    md = client.get("/api/workspace/file", params={"path": "wiki/cell_types/alpha.md"})
    assert md.status_code == 200
    assert "FOXP3" in md.text
    (tmp_path / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "runtime" / "cellwiki.db").write_bytes(b"sqlite")
    denied = client.get("/api/workspace/file", params={"path": "data/runtime/cellwiki.db"})
    assert denied.status_code == 403
    missing = client.get("/api/workspace/file", params={"path": "wiki/nope.md"})
    assert missing.status_code in (404, 422)


def test_workspace_edit_stages_pending_diff_then_gates(tmp_path: Path):
    root = tmp_path
    _workspace(root)
    client = TestClient(create_app(root))
    first = client.post(
        "/api/workspace/edit",
        json={"path": "wiki/cell_types/alpha.md", "content": "# Alpha Cell\n\nCD8+ T cells.\n"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "succeeded"
    assert body["pending_diff_id"].startswith("diff_")
    assert "CD8+ T cells" in (root / "wiki" / "cell_types" / "alpha.md").read_text(encoding="utf-8")
    # 已有未处理 pending diff 时，下一次编辑被串行门禁拒绝
    second = client.post(
        "/api/workspace/edit",
        json={"path": "index.md", "content": "# Index 2\n"},
    )
    assert second.status_code == 409


def test_workspace_edit_rejects_unsupported_type(tmp_path: Path):
    root = tmp_path
    _workspace(root)
    client = TestClient(create_app(root))
    response = client.post("/api/workspace/edit", json={"path": "raw/src_aaaaaaaaaaaaaaaaaaaa/meta.json", "content": "{}"})
    assert response.status_code == 422
