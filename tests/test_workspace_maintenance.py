# =============================================================================
# 系统维护（ADR-0009）单元测试 —— 判定时维护 + 系统维护 commit
# =============================================================================
# 覆盖四个判定路径（lint / accept / reject / unfinished）的写入与 git 行为：
# 派生文件重建、index 统计注入、log/audit 追加、固定 message 的系统 commit、
# 幂等去重、以及外部暂存变更导致维护中止的失败语义。
# =============================================================================

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cellwiki.domain.pending_diff import PendingDiff
from cellwiki.services.git_executor import GitExecutor
from cellwiki.services.workspace_maintenance import (
    MAINTENANCE_COMMIT_PREFIX,
    WorkspaceMaintenanceError,
    maintain_after_accept,
    maintain_after_lint,
    maintain_after_reject,
    maintain_after_unfinished,
)


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "tests@cellwiki.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "CellWiki Tests"],
        check=True,
        capture_output=True,
    )
    (root / "readme.md").write_text("base", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "--all"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "initial"], check=True, capture_output=True)
    return root


def _accepted_diff(root: Path, run_id: str = "run_x") -> tuple[PendingDiff, GitExecutor]:
    git = GitExecutor(root)
    snapshot = git.current_head()
    wiki = root / "wiki" / "cell_types"
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "alpha-cell.md").write_text("# Alpha Cell\n\nbody\n", encoding="utf-8")
    git.run("add", "wiki/cell_types/alpha-cell.md")
    git.run("commit", "-m", "agent change")
    head = git.current_head()
    diff = PendingDiff(
        diff_id=f"diff_{run_id}",
        run_id=run_id,
        thread_id="thread_x",
        snapshot_commit=snapshot,
        head_commit=head,
        commits=[head],
        files=["wiki/cell_types/alpha-cell.md"],
        insertions=1,
        deletions=0,
    )
    return diff, git


def _oneline_subjects(root: Path) -> list[str]:
    return GitExecutor(root).run("log", "--oneline").splitlines()


def test_maintain_after_accept_rebuilds_derived_and_commits(tmp_path: Path):
    root = _init_repo(tmp_path / "repo")
    diff, git = _accepted_diff(root)
    outcome = maintain_after_accept(root, run_id="run_x", diff=diff)

    assert outcome.commit_sha is not None
    assert "知识条目总数：1" in (root / "overview.md").read_text(encoding="utf-8")
    stats = (root / "statistics.md").read_text(encoding="utf-8")
    assert "| cell_types | 1 |" in stats and "| **总计** | 1 |" in stats
    log = (root / "log.md").read_text(encoding="utf-8")
    assert "accepted | run run_x" in log
    assert "commits:" in log and "+1/-0" in log and "alpha-cell.md" in log
    index = (root / "index.md").read_text(encoding="utf-8")
    assert "cellwiki:stats:start" in index and "知识条目总数：1" in index

    maintenance = [line for line in _oneline_subjects(root) if MAINTENANCE_COMMIT_PREFIX in line]
    assert len(maintenance) == 1
    assert "after run run_x (accepted)" in maintenance[0]


def test_maintain_after_reject_appends_log_without_touching_derived(tmp_path: Path):
    root = _init_repo(tmp_path / "repo")
    diff, _ = _accepted_diff(root)
    outcome = maintain_after_reject(root, run_id="run_x", diff=diff)

    assert outcome.commit_sha is not None
    log = (root / "log.md").read_text(encoding="utf-8")
    assert "rejected | run run_x" in log
    assert "commits:" in log and "alpha-cell.md" in log
    assert not (root / "statistics.md").exists()
    assert not (root / "overview.md").exists()


def test_maintain_after_unfinished_appends_pause_record(tmp_path: Path):
    root = _init_repo(tmp_path / "repo")
    outcome = maintain_after_unfinished(
        root, run_id="run_x", parent_run_id=None, reason="budget_or_timeout"
    )
    assert outcome.commit_sha is not None
    log = (root / "log.md").read_text(encoding="utf-8")
    assert "unfinished | run run_x" in log
    assert "budget_or_timeout" in log


def test_maintain_after_lint_appends_audit_section_and_is_idempotent(tmp_path: Path):
    root = _init_repo(tmp_path / "repo")
    _, git = _accepted_diff(root)
    report = {
        "status": "passed",
        "page_count": 1,
        "issue_count": 0,
        "error_count": 0,
        "warning_count": 0,
        "levels": {"L0": {"status": "passed"}, "L1": {"status": "passed"}},
    }
    outcome = maintain_after_lint(root, run_id="run_x", report=report)
    assert outcome.commit_sha is not None
    audit = (root / "audit_report.md").read_text(encoding="utf-8")
    assert "Audit snapshot" in audit and "- run: run_x" in audit
    assert "- gating (L0): passed" in audit and "- pages: 1" in audit

    before = git.current_head()
    again = maintain_after_lint(root, run_id="run_x", report=report)
    assert again.skipped is True
    assert git.current_head() == before
    assert (root / "audit_report.md").read_text(encoding="utf-8").count("Audit snapshot") == 1


def test_maintenance_aborts_on_foreign_staged_changes(tmp_path: Path):
    root = _init_repo(tmp_path / "repo")
    diff, git = _accepted_diff(root)
    (root / "stray.md").write_text("stray", encoding="utf-8")
    git.run("add", "stray.md")

    with pytest.raises(WorkspaceMaintenanceError):
        maintain_after_accept(root, run_id="run_x", diff=diff)
    # 中止后不产生系统维护 commit，stray 仍留在暂存区
    maintenance = [line for line in _oneline_subjects(root) if MAINTENANCE_COMMIT_PREFIX in line]
    assert maintenance == []