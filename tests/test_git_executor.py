# =============================================================================
# git 白名单执行器契约测试 —— 六动作、标志/ref/path 白名单、toplevel、
# diff 生成与 revert 语义
# =============================================================================

from __future__ import annotations

from pathlib import Path

import pytest

from cellwiki.services.git_executor import (
    GitCommandError,
    GitExecutor,
    GitForbiddenCommandError,
    GitPathError,
    GitToplevelMismatchError,
)
from cellwiki.services.workspace import ensure_workspace


@pytest.fixture()
def repo(tmp_path: Path):
    root = tmp_path / "kb"
    ensure_workspace(root)
    executor = GitExecutor(root)
    executor.run("add", ".")
    executor.run("commit", "-m", "baseline")
    return root, executor


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_baseline_commit_exists(repo):
    _, executor = repo
    head = executor.current_head()
    assert len(head) == 40


def test_status_short_and_plain_are_allowed(repo):
    root, executor = repo
    (root / "index.md").write_text("# nav changed\n", encoding="utf-8")
    assert "index.md" in executor.run("status", "--short")
    assert "index.md" in executor.run("status")


def test_add_and_commit_with_single_message(repo):
    root, executor = repo
    _write(root, "wiki/added.md", "# added\n")
    executor.run("add", "wiki/added.md")
    executor.run("commit", "-m", "add page")
    assert "added.md" in executor.run("diff", "--name-only", "HEAD~1", "HEAD")


def test_forbidden_commands_and_flags_are_rejected(repo):
    _, executor = repo
    forbidden_commands = [
        ("reset", "--hard", "HEAD"),
        ("clean", "-f"),
        ("rm", "-r", "wiki"),
        ("rebase", "-i", "HEAD~3"),
        ("checkout", "main"),
        ("restore", "wiki"),
        ("push", "origin", "main"),
        ("fetch", "origin"),
    ]
    for args in forbidden_commands:
        with pytest.raises(GitForbiddenCommandError):
            executor.run(*args)
    forbidden_flags = [
        ("add", "-A"),
        ("add", "--all"),
        ("add", "-u"),
        ("add", "-p"),
        ("add", "-f", "wiki"),
        ("commit", "--amend"),
        ("commit", "-a", "-m", "x"),
        ("commit", "--allow-empty", "-m", "x"),
        ("revert", "-n", "HEAD"),
    ]
    for args in forbidden_flags:
        with pytest.raises(GitForbiddenCommandError):
            executor.run(*args)
    # 非白名单动作
    with pytest.raises(GitForbiddenCommandError):
        executor.run("show", "HEAD")
    # 不合法 ref
    with pytest.raises(GitForbiddenCommandError):
        executor.run("diff", "feature-branch")


def test_commit_requires_exactly_one_message(repo):
    _, executor = repo
    with pytest.raises(GitForbiddenCommandError):
        executor.run("commit")
    with pytest.raises(GitForbiddenCommandError):
        executor.run("commit", "-m", "a", "-m", "b")


def test_commit_only_pathspec_commits_only_named_paths(repo):
    """系统维护的 `commit --only -- <paths>`（方案 D）：只收显式路径。

    前提与实现一致：`--only` 只认 git 已知的路径（未跟踪文件要先 add），
    且 pathspec 覆盖 index 与 worktree。
    """
    root, executor = repo
    _write(root, "wiki/mine.md", "# mine\n")
    _write(root, "wiki/theirs.md", "# theirs\n")
    executor.run("add", "wiki/mine.md", "wiki/theirs.md")
    executor.run("commit", "--only", "-m", "only mine", "--", "wiki/mine.md")
    committed = executor.run("diff", "--name-only", "HEAD~1", "HEAD").splitlines()
    assert committed == ["wiki/mine.md"]
    # theirs 仍留在暂存区，未被系统提交动过。
    assert any(
        line.startswith("A ") and line[3:] == "wiki/theirs.md"
        for line in executor.run("status", "--short").splitlines()
    )
    # --only 的 pathspec 仍走 P1：越界路径拒绝。
    with pytest.raises(GitPathError):
        executor.run("commit", "--only", "-m", "x", "--", "../outside.md")


def test_path_arguments_after_separator_are_p1_checked(repo):
    _, executor = repo
    with pytest.raises(GitPathError):
        executor.run("diff", "--", "../../etc/passwd")
    with pytest.raises(GitPathError):
        executor.run("add", "../outside.md")
    with pytest.raises(GitPathError):
        executor.run("diff", "HEAD", "--", "wiki/.git/config")


def test_diff_between_reports_stats_and_files(repo):
    root, executor = repo
    snapshot = executor.current_head()
    _write(root, "wiki/one.md", "# one\n\nA line.\n")
    _write(root, "wiki/two.md", "# two\n\nB line.\n")
    executor.run("add", ".")
    executor.run("commit", "-m", "two pages")
    diff = executor.diff_between(snapshot)
    assert set(diff.files) == {"wiki/one.md", "wiki/two.md"}
    assert diff.insertions >= 4
    assert diff.deletions == 0


def test_diff_between_honors_exclude_paths(repo):
    root, executor = repo
    snapshot = executor.current_head()
    _write(root, "wiki/keep.md", "# keep\n")
    _write(root, "wiki/skip.md", "# skip\n")
    executor.run("add", ".")
    executor.run("commit", "-m", "mixed")
    diff = executor.diff_between(snapshot, exclude_paths=("wiki/skip.md",))
    assert diff.files == ["wiki/keep.md"]


def test_commits_since_returns_run_commits_newest_first(repo):
    root, executor = repo
    snapshot = executor.current_head()
    _write(root, "wiki/a.md", "# a\n")
    executor.run("add", ".")
    executor.run("commit", "-m", "commit a")
    _write(root, "wiki/b.md", "# b\n")
    executor.run("add", ".")
    executor.run("commit", "-m", "commit b")
    shas = executor.commits_since(snapshot)
    assert len(shas) == 2
    # 新→旧
    assert shas[0] == executor.current_head()


def test_revert_commits_restores_snapshot_state(repo):
    root, executor = repo
    snapshot = executor.current_head()
    path = _write(root, "wiki/rev.md", "# rev\n")
    executor.run("add", ".")
    executor.run("commit", "-m", "run change")
    assert path.exists()
    run_shas = executor.commits_since(snapshot)
    created = executor.revert_commits(run_shas)
    assert len(created) == 1
    assert not path.exists()
    assert executor.diff_between(snapshot).files == []


def test_toplevel_mismatch_raises(repo, tmp_path):
    root, _ = repo
    nested = root / "sub"
    nested.mkdir()
    executor = GitExecutor(nested)
    with pytest.raises((GitToplevelMismatchError, GitCommandError)):
        executor.run("status", "--short")


def test_enabled_refs_limit_diff_inputs(repo):
    root, executor = repo
    snapshot = executor.current_head()
    _write(root, "wiki/a.md", "# a\n")
    executor.run("add", ".")
    executor.run("commit", "-m", "a")
    # 不在 enabled_refs 中的 ref 即使格式合法也被拒绝
    with pytest.raises(GitForbiddenCommandError):
        executor.diff_between(snapshot, enabled_refs=frozenset({snapshot}))
    # enabled_refs 中的 ref 放行
    diff = executor.diff_between(snapshot, enabled_refs=frozenset({snapshot, "HEAD"}))
    assert diff.files == ["wiki/a.md"]

def test_commits_since_none_and_diff_from_empty_workspace(tmp_path: Path):
    """空快照（工作区尚无提交）时：commits_since(None) 返回全部提交，
    diff_between(None) 从 git 空树起算，首轮 Agent 提交可进待确认 diff。"""
    root = tmp_path / "kb"
    ensure_workspace(root)
    executor = GitExecutor(root)
    assert executor.has_commits() is False
    executor.run("add", ".")
    executor.run("commit", "-m", "first")
    _write(root, "wiki/cell_types/a.md", "# A\n")
    executor.run("add", "wiki/cell_types/a.md")
    executor.run("commit", "-m", "second")
    shas = executor.commits_since(None)
    assert len(shas) == 2, shas
    diff = executor.diff_between(None)
    assert "wiki/cell_types/a.md" in diff.files
    assert diff.insertions > 0
    # 非空快照行为保持
    snapshot = executor.current_head()
    assert executor.commits_since(snapshot) == []
