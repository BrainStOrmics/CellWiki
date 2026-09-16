"""Run-scoped context for tools that need the active run's git baseline.

Runs are strictly serialized, so a module-level scope follows the existing
attachment-scope pattern and stays visible to tools that LangGraph executes on
worker threads (a plain ContextVar can be lost when execution hops threads).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cellwiki.services.git_executor import GitCommandError, GitExecutor


@dataclass(frozen=True)
class RunScope:
    """Identity and publish baseline of the active run."""

    run_id: str
    snapshot_commit: str | None


_SCOPE: RunScope | None = None


def set_run_scope(run_id: str, snapshot_commit: str | None) -> None:
    """Install the active run scope (called once per run segment)."""

    global _SCOPE
    _SCOPE = RunScope(run_id=run_id, snapshot_commit=snapshot_commit)


def clear_run_scope() -> None:
    """Drop the active run scope when the run reaches a terminal state."""

    global _SCOPE
    _SCOPE = None


def current_run_scope() -> RunScope | None:
    """Return the active run scope, or ``None`` outside a run."""

    return _SCOPE


def porcelain_paths(porcelain: str) -> list[str]:
    """Parse ``git status --porcelain`` v1 output into workspace-relative paths.

    Any non-space status column counts as dirty; both sides of a rename are
    returned because the old path must be staged as well.
    """

    dirty: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        if line[0] == " " and line[1] == " ":
            continue
        path = line[3:]
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if " -> " in path:
            dirty.extend(part for part in path.split(" -> ") if part)
        else:
            dirty.append(path)
    return dirty


def _expand_directory_paths(root: Path, paths: list[str]) -> list[str]:
    """Expand porcelain directory entries (``?? wiki/``) into their files."""

    expanded: list[str] = []
    for path in paths:
        if path.endswith(("/", "\\")):
            base = root / path
            if base.is_dir():
                expanded.extend(
                    entry.relative_to(root).as_posix()
                    for entry in base.rglob("*")
                    if entry.is_file()
                )
                continue
        expanded.append(path)
    return expanded


def changed_paths_for_scope(project_root: Path) -> list[str] | None:
    """Workspace paths changed in the active run, or ``None`` without a scope.

    Read-only: combines dirty worktree paths with commits made after the run's
    snapshot commit, mirroring the publish gate's changed-file set.
    """

    scope = current_run_scope()
    if scope is None:
        return None
    paths: list[str] = []
    try:
        git = GitExecutor(project_root)
        dirty = porcelain_paths(git.run("status", "--porcelain"))
        paths.extend(_expand_directory_paths(Path(project_root).resolve(), dirty))
        refs = (
            frozenset({scope.snapshot_commit, "HEAD"})
            if scope.snapshot_commit
            else frozenset({"HEAD"})
        )
        diff = git.diff_between(scope.snapshot_commit, "HEAD", enabled_refs=refs)
        paths.extend(diff.files)
    except (GitCommandError, OSError):
        return []
    normalized = {
        path.replace("\\", "/").removeprefix("./")
        for path in paths
        if path and path.strip()
    }
    return sorted(normalized)
