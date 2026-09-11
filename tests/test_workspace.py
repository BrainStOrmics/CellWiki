# =============================================================================
# 工作区初始化契约测试 —— 目录、六文件、git init、repo-local 身份与运行时边界
# =============================================================================

from __future__ import annotations

from pathlib import Path

import pytest

from cellwiki.services.workspace import (
    AGENT_GIT_IDENTITY_EMAIL,
    AGENT_GIT_IDENTITY_NAME,
    SYSTEM_OWNED_FILES,
    WORKSPACE_IGNORE_CONTENT,
    WORKSPACE_IGNORE_FILE_NAME,
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


def test_ensure_workspace_creates_runtime_ignore_boundary(tmp_path: Path):
    root = tmp_path / "kb"

    ensure_workspace(root)

    ignore = root / WORKSPACE_IGNORE_FILE_NAME
    assert ignore.is_file()
    assert ignore.read_text(encoding="utf-8") == WORKSPACE_IGNORE_CONTENT


def test_runtime_artifacts_stay_out_of_git_status(tmp_path: Path):
    # 回归 Layer B 噪声：_git_status_text 把 git status --short 直接注进提示词。
    root = tmp_path / "kb"
    ensure_workspace(root)
    (root / "data" / "runtime").mkdir(parents=True)
    (root / "data" / "runtime" / "cellwiki.db").write_bytes(b"runtime database")

    status = _git(root, "status", "--short")

    assert "data/" not in status
    # 已知代价：忽略文件自身仍以未跟踪形式出现一次（不提交是为了保住
    # "新工作区无初始 commit" 的首轮 pending diff 语义）。
    assert WORKSPACE_IGNORE_FILE_NAME in status


def test_runtime_database_cannot_be_staged_into_history(tmp_path: Path):
    # ADR-0007 让历史不可改写，所以"运行库进不了暂存区"必须在初始化层就成立。
    root = tmp_path / "kb"
    ensure_workspace(root)
    (root / "wiki").mkdir(exist_ok=True)
    (root / "wiki" / "page.md").write_text("# page\n", encoding="utf-8")
    (root / "data" / "runtime").mkdir(parents=True)
    (root / "data" / "runtime" / "cellwiki.db").write_bytes(b"runtime database")

    with pytest.raises(RuntimeError):
        _git(root, "add", "--", "data/runtime/cellwiki.db")


def test_existing_ignore_file_is_never_rewritten(tmp_path: Path):
    # 用户已有忽略规则时一律不碰：追加或覆盖都会吞掉他的意图。
    root = tmp_path / "kb"
    root.mkdir()
    (root / WORKSPACE_IGNORE_FILE_NAME).write_text("output/\n", encoding="utf-8")

    ensure_workspace(root)
    ensure_workspace(root)

    assert (root / WORKSPACE_IGNORE_FILE_NAME).read_text(encoding="utf-8") == "output/\n"


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