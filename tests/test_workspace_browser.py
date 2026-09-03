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


def test_raw_scan_endpoint_registers_preplaced_and_is_idempotent(tmp_path: Path):
    """POST /api/workspace/raw/scan：用户发起的预置源登记，幂等、不产生 git 变更。"""
    root = tmp_path
    _workspace(root)
    preplaced = root / "raw" / "Fu_2025_NatMethods"
    preplaced.mkdir(parents=True)
    (preplaced / "paper.md").write_text("# Fu 2025", encoding="utf-8")
    (root / "raw" / "pdf_only").mkdir(parents=True)
    (root / "raw" / "pdf_only" / "doc.pdf").write_bytes(b"%PDF-1.7")

    def staged() -> str:
        # 登记不得 stage 任何东西（pending diff 只来自 commit）。diff --cached
        # 只看 index：仓库尚未 commit 时 status --porcelain 全是 ?? 未跟踪，无法
        # 区分，所以用这条更精确。
        return subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-only"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    client = TestClient(create_app(root))
    first = client_post_scan(client)
    # src_aaa...（fixture 里的旧 raw 目录没有登记记录）也按预置源登记
    assert first["added"] == 3
    assert first["needs_extraction"] == 1
    assert sorted(first["sources"]) == [
        "Fu_2025_NatMethods",
        "pdf_only",
        "src_aaaaaaaaaaaaaaaaaaaa",
    ]
    registry = root / "data" / "runtime" / "sources"
    assert (registry / "Fu_2025_NatMethods.json").is_file()

    second = client_post_scan(client)
    assert second["added"] == 0
    assert second["updated"] == 3
    assert len(list(registry.glob("*.json"))) == 3  # 不随扫描次数膨胀
    # 登记不 stage 任何东西（不进入 pending diff），且第二次不改 raw/ 文件。
    assert staged() == "", staged()
    assert (preplaced / "paper.md").read_text(encoding="utf-8") == "# Fu 2025"
    assert sorted(p.name for p in preplaced.iterdir()) == ["paper.md"]


def client_post_scan(client):
    response = client.post("/api/workspace/raw/scan")
    assert response.status_code == 200
    return response.json()
