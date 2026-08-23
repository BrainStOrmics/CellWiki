# =============================================================================
# 工作区初始化契约测试 —— 目录、六文件、git init 与 repo-local 身份
# =============================================================================

from __future__ import annotations

from pathlib import Path


from cellwiki.services.workspace import (
    AGENT_GIT_IDENTITY_EMAIL,
    AGENT_GIT_IDENTITY_NAME,
    SYSTEM_OWNED_FILES,
    ensure_workspace,
    workspace_toplevel,
)


def test_ensure_workspace_creates_directories_and_six_files(tmp_path: Path):
    root = tmp_path / "kb"
    layout = ensure_workspace(root)
    assert layout.wiki_dir.is_dir()
    assert layout.raw_dir.is_dir()
    for name in ("index.md", "contradiction.md", "overview.md", "statistics.md", "log.md", "audit_report.md"):
        assert (root / name).is_file(), name
        assert layout.file_for(name) == (root / name).resolve()


def test_ensure_workspace_is_idempotent_and_preserves_content(tmp_path: Path):
    root = tmp_path / "kb"
    ensure_workspace(root)
    (root / "wiki" / "x.md").write_text("custom", encoding="utf-8")
    (root / "index.md").write_text("custom nav", encoding="utf-8")
    ensure_workspace(root)
    assert (root / "wiki" / "x.md").read_text(encoding="utf-8") == "custom"
    assert (root / "index.md").read_text(encoding="utf-8") == "custom nav"


def test_git_init_and_repo_local_identity(tmp_path: Path):
    root = tmp_path / "kb"
    ensure_workspace(root)
    assert (root / ".git").exists()
    name = _git_config(root, "user.name")
    email = _git_config(root, "user.email")
    assert name == AGENT_GIT_IDENTITY_NAME
    assert email == AGENT_GIT_IDENTITY_EMAIL


def test_toplevel_equals_workspace_root(tmp_path: Path):
    root = tmp_path / "kb"
    ensure_workspace(root)
    assert workspace_toplevel(root) == root.resolve()


def test_directory_under_another_repo_becomes_its_own_workspace_repo(tmp_path: Path):
    outer = tmp_path / "outer"
    outer.mkdir()
    _git(outer, "init")
    nested = outer / "kb"
    nested.mkdir()
    ensure_workspace(nested)
    assert workspace_toplevel(nested) == nested.resolve()


def test_system_owned_files_are_system_scope(tmp_path: Path):
    assert SYSTEM_OWNED_FILES == {"overview.md", "statistics.md", "log.md", "audit_report.md"}


def _git(root: Path, *args: str) -> str:
    import subprocess

    completed = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return completed.stdout


def _git_config(root: Path, key: str) -> str:
    return _git(root, "config", "--get", key).strip()