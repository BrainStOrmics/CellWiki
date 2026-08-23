# =============================================================================
# 工作区服务 —— 目录初始化、git init 与 repo-local 身份
# =============================================================================
# 工作区 = 用户选定的知识库目录。系统负责：创建 wiki/、raw/ 与六个根 Markdown
# 文件（缺失时用模板补齐）、确保目录是 git 仓库（缺失时 git init）、写入
# repo-local 身份（user.name="CellWiki Agent" 与固定 email）、校验 toplevel
# 边界。内容归 Agent，派生与门禁归系统，人工负责接受/拒绝 diff。
# =============================================================================

"""Workspace initialization: directories, six root files, and a governed git repo."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path



WORKSPACE_DIR_NAMES = ("wiki", "raw")
WORKSPACE_FILE_NAMES = (
    "index.md",
    "contradiction.md",
    "overview.md",
    "statistics.md",
    "log.md",
    "audit_report.md",
)
AGENT_GIT_IDENTITY_NAME = "CellWiki Agent"
AGENT_GIT_IDENTITY_EMAIL = "cellwiki-agent@cellwiki.local"

# 系统拥有的文件：Agent 不可手写（overview/statistics 系统重建，
# log/audit_report 系统 append-only）。
SYSTEM_OWNED_FILES = frozenset({"overview.md", "statistics.md", "log.md", "audit_report.md"})
# Agent 维护的文件：导航正文与矛盾台账。
AGENT_OWNED_FILES = frozenset({"index.md", "contradiction.md"})


class WorkspaceNotInitializedError(RuntimeError):
    """Raised when the selected directory is not a governed git workspace."""


class ToplevelMismatchError(WorkspaceNotInitializedError):
    """Raised when the repository toplevel differs from the selected workspace root."""


@dataclass(frozen=True)
class WorkspaceLayout:
    """The canonical, system-owned view of one knowledge-base workspace."""

    root: Path
    wiki_dir: Path
    raw_dir: Path
    files: dict[str, Path]

    def file_for(self, name: str) -> Path:
        try:
            return self.files[name]
        except KeyError as error:
            raise ValueError(f"unknown workspace file: {name}") from error


def _file_template(name: str) -> str:
    templates = {
        "index.md": (
            "# 知识库导航\n\n"
            "(系统注入统计与目录；正文由 Agent 维护)\n"
        ),
        "contradiction.md": (
            "# 矛盾台账\n\n"
            "(Agent 维护：记录知识条目之间的冲突、证据缺口与跟踪状态)\n"
        ),
        "overview.md": "# 知识库概览\n\n(系统重建，Agent 不可手写)\n",
        "statistics.md": "# 统计\n\n(系统重建，Agent 不可手写)\n",
        "log.md": "(系统 append-only，Agent 不可写)\n",
        "audit_report.md": "(系统 append-only，Agent 不可写)\n",
    }
    return templates.get(name, f"# {name}\n")


def _run_git_system(root: Path, *args: str) -> str:
    """Run a system-owned git command with no agent input (init/config only)."""
    completed = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if completed.returncode != 0:
        raise WorkspaceNotInitializedError(
            f"git {' '.join(args)} failed: {completed.stderr.strip()[:500]}"
        )
    return completed.stdout


def ensure_workspace(root: Path) -> WorkspaceLayout:
    """Create the workspace layout and govern the repository, then verify toplevel."""
    root_resolved = Path(root).resolve()
    root_resolved.mkdir(parents=True, exist_ok=True)
    wiki = root_resolved / "wiki"
    raw = root_resolved / "raw"
    wiki.mkdir(exist_ok=True)
    raw.mkdir(exist_ok=True)

    files: dict[str, Path] = {}
    for name in WORKSPACE_FILE_NAMES:
        path = root_resolved / name
        if not path.exists():
            path.write_text(_file_template(name), encoding="utf-8")
        files[name] = path

    # git init（仅当目录还不是仓库时）
    if not (root_resolved / ".git").exists():
        _run_git_system(root_resolved, "init")
        # repo-local 身份：不污染全局 git 配置
        _run_git_system(root_resolved, "config", "user.name", AGENT_GIT_IDENTITY_NAME)
        _run_git_system(
            root_resolved,
            "config",
            "user.email",
            AGENT_GIT_IDENTITY_EMAIL,
        )

    # toplevel 校验：仓库根必须等于工作区目录根
    workspace_toplevel(root_resolved)
    return WorkspaceLayout(
        root=root_resolved,
        wiki_dir=wiki,
        raw_dir=raw,
        files=files,
    )


def workspace_toplevel(root: Path) -> Path:
    """Return the git toplevel; raise unless it equals the selected workspace root."""
    root_resolved = Path(root).resolve()
    try:
        output = _run_git_system(root_resolved, "rev-parse", "--show-toplevel")
    except WorkspaceNotInitializedError as error:
        raise WorkspaceNotInitializedError(
            "the selected directory is not a git workspace; run ensure_workspace first"
        ) from error
    toplevel = Path(os.path.normpath(str(output).strip())).resolve()
    if os.path.normcase(str(toplevel)) != os.path.normcase(str(root_resolved)):
        raise ToplevelMismatchError(
            f"repository toplevel {toplevel} differs from workspace root {root_resolved}"
        )
    return toplevel