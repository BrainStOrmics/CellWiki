# =============================================================================
# 系统维护 —— 判定时维护 + 系统维护 commit（ADR-0009）
# =============================================================================
# 工作区根级系统文件只在 run 状态机判定事件维护：
#   强制 lint 完成 -> audit_report.md 追加一段（系统 commit，verdict=lint）
#   diff 接受       -> 重建 overview/statistics、注入 index 统计、log.md 追加
#                     判定记录（合并为一个系统 commit，verdict=accepted）
#   diff 拒绝       -> log.md 追加拒绝记录（系统 commit，verdict=rejected）
#   run 未完成      -> log.md 追加未完成记录（系统 commit，verdict=unfinished）
#   查询/只读 run   -> 不写任何文件（无 commit 的 run 不触发本模块）
# 语义：SQLite run 判定状态是权威，本模块只维护人读镜像；任何失败都抛
# WorkspaceMaintenanceError 由调用方记录 maintenance_failed 事件并重试，
# 绝不阻塞 run 判定。写入确定性、可重复执行（追加带 run 标记去重）。
# =============================================================================

"""System-owned maintenance of the workspace md files (ADR-0009)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cellwiki.domain.pending_diff import PendingDiff
from cellwiki.services.git_executor import GitExecutor

MAINTENANCE_COMMIT_PREFIX = "chore(system): maintenance"

# 系统维护 commit 覆盖的文件：overview/statistics 系统重建 + log/audit
# 系统追加 + index 统计注入（index 正文仍归 Agent，统计由系统维护）。
_MAINTENANCE_FILES = (
    "overview.md",
    "statistics.md",
    "index.md",
    "log.md",
    "audit_report.md",
)
# index.md 统计块的定界注释：系统注入只替换块内内容，不碰 Agent 导航正文。
_STATS_START = "<!-- cellwiki:stats:start -->"
_STATS_END = "<!-- cellwiki:stats:end -->"


class WorkspaceMaintenanceError(RuntimeError):
    """Maintenance failed. Verdicts are never blocked; callers record and retry."""


@dataclass(frozen=True)
class MaintenanceOutcome:
    """What one maintenance step wrote and committed."""

    files_written: tuple[str, ...] = ()
    commit_sha: str | None = None
    skipped: bool = False


# ---------------------------------------------------------------------------
# 纯文本辅助
# ---------------------------------------------------------------------------
def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _append_section(path: Path, section: str, *, marker: str) -> bool:
    """Append ``section`` once; skip when ``marker`` already exists (idempotent)."""
    text = _read_text(path)
    if marker in text:
        return False
    body = section.rstrip("\n") + "\n"
    prefix = text.rstrip("\n") + "\n\n" if text.strip() else ""
    _write_text(path, prefix + body)
    return True


# ---------------------------------------------------------------------------
# 派生文件重建（overview / statistics / index 统计注入）
# ---------------------------------------------------------------------------
def _collect_stats(root: Path) -> dict[str, Any]:
    """Count Markdown pages under wiki/ by top-level category."""
    wiki = root / "wiki"
    total = 0
    by_category: dict[str, int] = {}
    if wiki.exists():
        for path in sorted(wiki.rglob("*.md")):
            if not path.is_file():
                continue
            total += 1
            rel = path.relative_to(wiki)
            category = rel.parts[0] if len(rel.parts) > 1 else "."
            by_category[category] = by_category.get(category, 0) + 1
    return {"total": total, "by_category": dict(sorted(by_category.items()))}


def _stats_block(stats: dict[str, Any]) -> str:
    lines = [f"- 知识条目总数：{stats['total']}"]
    lines += [f"- wiki/{category}/：{count}" for category, count in stats["by_category"].items()]
    return "\n".join(lines)


def _overview_content(stats: dict[str, Any], snapshot: str | None) -> str:
    lines = [
        "# 知识库概览",
        "",
        "> (系统重建，反映最近一次被接受的内容快照；Agent 不可手写)",
        "",
        f"- 知识条目总数：{stats['total']}",
    ]
    lines += [f"- wiki/{category}/：{count}" for category, count in stats["by_category"].items()]
    lines += ["", f"- 最近重建：{_timestamp()}", f"- 内容快照：`{snapshot or 'n/a'}`"]
    return "\n".join(lines) + "\n"


def _statistics_content(stats: dict[str, Any], snapshot: str | None) -> str:
    lines = [
        "# 统计",
        "",
        "> (系统重建，Agent 不可手写)",
        "",
        "| 类别 | 页面数 |",
        "| --- | --- |",
    ]
    lines += [f"| {category} | {count} |" for category, count in stats["by_category"].items()]
    lines += [
        f"| **总计** | {stats['total']} |",
        "",
        f"- 最近更新：{_timestamp()}",
        f"- 内容快照：`{snapshot or 'n/a'}`",
    ]
    return "\n".join(lines) + "\n"


def _inject_index_stats(index_path: Path, stats_block: str) -> bool:
    """Replace or append the system stats block in index.md; return True when changed."""
    text = _read_text(index_path)
    block = f"{_STATS_START}\n{stats_block}\n{_STATS_END}"
    if _STATS_START in text and _STATS_END in text:
        head, _, rest = text.partition(_STATS_START)
        _, _, tail = rest.partition(_STATS_END)
        updated = head + block + tail
    else:
        updated = (text.rstrip("\n") + "\n\n" + block + "\n") if text.strip() else block + "\n"
    if updated == text:
        return False
    _write_text(index_path, updated)
    return True


# ---------------------------------------------------------------------------
# 追加条目内容
# ---------------------------------------------------------------------------
def _log_entry(
    verdict: str,
    run_id: str,
    parent_run_id: str | None,
    diff: PendingDiff | None,
    *,
    note: str | None = None,
) -> str:
    suffix = f" (parent {parent_run_id})" if parent_run_id else ""
    lines = [f"## [{_timestamp()}] {verdict} | run {run_id}{suffix}"]
    if diff is not None and diff.commits:
        lines.append(f"- commits: {diff.commits[-1][:12]}..{diff.commits[0][:12]}")
        files = ", ".join(diff.files[:5]) or "none"
        lines.append(f"- files: +{diff.insertions}/-{diff.deletions} ({files})")
    if note:
        lines.append(f"- note: {note}")
    return "\n".join(lines) + "\n"


def _audit_section(
    run_id: str,
    parent_run_id: str | None,
    report: dict[str, Any] | None,
) -> str:
    report = report or {}
    levels = report.get("levels", {})
    gating_status = levels.get("L0", {}).get("status", "unknown")
    lines = [
        "## Audit snapshot",
        "",
        f"- run: {run_id}",
        f"- parent: {parent_run_id or 'none'}",
        f"- time: {_timestamp()}",
        f"- status: {report.get('status', 'unknown')}",
        f"- pages: {report.get('page_count', 0)}",
        f"- issues: {report.get('issue_count', 0)} "
        f"(errors {report.get('error_count', 0)}, warnings {report.get('warning_count', 0)})",
        f"- gating (L0): {gating_status}",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# git：系统维护 commit
# ---------------------------------------------------------------------------
# 线程内最近一次维护的外来暂存告警清单（方案 D：从"中止"降为"告警"）。
# 维护调用本身由 runtime 的 _maintenance_lock 串行化，模块级暂存在此前提下安全。
_LAST_MAINTENANCE_WARNING: list[str] = []


def take_maintenance_warning() -> list[str]:
    """Pop the foreign-staged warning collected by the last commit attempt."""
    warning = list(_LAST_MAINTENANCE_WARNING)
    _LAST_MAINTENANCE_WARNING.clear()
    return warning


def _paths_with_changes(git: GitExecutor, paths: tuple[str, ...]) -> list[str]:
    """Own paths that differ from HEAD, with **no** dependence on the index.

    ``git status --porcelain -- <paths>`` reports worktree-vs-HEAD state for the
    given pathspec; staged columns of foreign files are irrelevant because the
    pathspec already scopes the check to maintenance-owned files.
    """
    changed: list[str] = []
    for line in git.run("status", "--porcelain", "--", *paths).splitlines():
        if len(line) < 4:
            continue
        # porcelain v1: XY<space>path — any non-blank status letter = change.
        if line[0] != " " or line[1] != " ":
            changed.append(line[3:])
    return changed


def _foreign_staged_paths(git: GitExecutor, own: set[str]) -> list[str]:
    """Index-staged paths outside the maintenance-owned set (warning, not abort)."""
    foreign: list[str] = []
    for line in git.run("status", "--short").splitlines():
        if len(line) < 3:
            continue
        if line[0] in "AMDRC" and line[1] in " \t" and line[3:] not in own:
            foreign.append(line[3:])
    return foreign


def _commit_maintenance(
    root: Path,
    run_id: str,
    verdict: str,
    files: tuple[str, ...],
) -> str | None:
    """Path-scoped system maintenance commit (ADR-0009 + 方案 D).

    ``git commit --only -- <paths>`` 只提交维护自己的文件，index 里的外来暂存
    改动保持原样、不进本提交。旧实现的全局 staged 守卫会把维护永久饿死
    （外来暂存不清理则每次判定都 maintenance_failed）；现在降级为可观测告警，
    清单通过 ``last_maintenance_warning`` 暴露给调用方写进维护事件。
    """
    git = GitExecutor(root)
    foreign = _foreign_staged_paths(git, set(files))
    # 告警暂存必须在每次调用开始时刷新：commit 中途失败时上层 take() 读到的
    # 也必须本次的状态，而不是上一次成功调用的残留。
    _LAST_MAINTENANCE_WARNING[:] = foreign
    changed = _paths_with_changes(git, files)
    if not changed:
        return None  # 文件内容无变化，无需提交
    message = f"{MAINTENANCE_COMMIT_PREFIX} after run {run_id} ({verdict})"
    # add 仅限维护自己的路径：首次生成的 statistics.md 等可能尚未被 git 跟踪，
    # `commit --only` 对未跟踪 pathspec 会直接报错。add 是路径限定的，外来 staged
    # 不受影响；随后 --only 提交保证 commit 内容严格等于 changed 集合。
    git.run("add", "--", *changed)
    git.run("commit", "--only", "-m", message, "--", *changed)
    return git.current_head()


# ---------------------------------------------------------------------------
# 公开维护入口（按 ADR-0009 事件表）
# ---------------------------------------------------------------------------
def maintain_after_lint(
    root: Path,
    *,
    run_id: str,
    parent_run_id: str | None = None,
    report: dict[str, Any] | None = None,
) -> MaintenanceOutcome:
    """Run-end forced lint snapshot -> append one section to audit_report.md."""
    section = _audit_section(run_id, parent_run_id, report)
    changed = _append_section(root / "audit_report.md", section, marker=f"- run: {run_id}")
    if not changed:
        return MaintenanceOutcome(skipped=True)
    sha = _commit_maintenance(root, run_id, "lint", ("audit_report.md",))
    return MaintenanceOutcome(files_written=("audit_report.md",), commit_sha=sha)


def maintain_after_accept(
    root: Path,
    *,
    run_id: str,
    parent_run_id: str | None = None,
    diff: PendingDiff | None = None,
) -> MaintenanceOutcome:
    """Accepted diff: rebuild derived files, inject index stats, append log record."""
    stats = _collect_stats(root)
    snapshot = diff.snapshot_commit if diff is not None else None
    _write_text(root / "overview.md", _overview_content(stats, snapshot))
    _write_text(root / "statistics.md", _statistics_content(stats, snapshot))
    _inject_index_stats(root / "index.md", _stats_block(stats))
    _append_section(
        root / "log.md",
        _log_entry("accepted", run_id, parent_run_id, diff),
        marker=f"accepted | run {run_id}",
    )
    files = ("overview.md", "statistics.md", "index.md", "log.md")
    sha = _commit_maintenance(root, run_id, "accepted", files)
    return MaintenanceOutcome(files_written=files, commit_sha=sha)


def maintain_after_reject(
    root: Path,
    *,
    run_id: str,
    parent_run_id: str | None = None,
    diff: PendingDiff | None = None,
) -> MaintenanceOutcome:
    """Rejected diff: append the rejection record to log.md (derived files stay)."""
    changed = _append_section(
        root / "log.md",
        _log_entry("rejected", run_id, parent_run_id, diff),
        marker=f"rejected | run {run_id}",
    )
    if not changed:
        return MaintenanceOutcome(skipped=True)
    sha = _commit_maintenance(root, run_id, "rejected", ("log.md",))
    return MaintenanceOutcome(files_written=("log.md",), commit_sha=sha)


def maintain_after_unfinished(
    root: Path,
    *,
    run_id: str,
    parent_run_id: str | None = None,
    reason: str | None = None,
) -> MaintenanceOutcome:
    """Unfinished/interrupted run: append the pause record to log.md."""
    changed = _append_section(
        root / "log.md",
        _log_entry("unfinished", run_id, parent_run_id, None, note=reason),
        marker=f"unfinished | run {run_id}",
    )
    if not changed:
        return MaintenanceOutcome(skipped=True)
    sha = _commit_maintenance(root, run_id, "unfinished", ("log.md",))
    return MaintenanceOutcome(files_written=("log.md",), commit_sha=sha)