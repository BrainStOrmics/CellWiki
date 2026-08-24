# =============================================================================
# git 白名单执行器 —— P3 边界
# =============================================================================
# 白名单六动作：status / diff / log / add / commit / revert。
# - 参数不拼接 shell（subprocess 列表参数直传）；
# - 路径参数用 `--` 分隔并再走 P1 校验；`add` 仅显式路径（禁 -A/-u/-p/-i/-e）；
# - `commit` 仅 `-m/--message` 单参数（禁 --amend/--fixup/--squash/-c/-C/-F/
#   --author/-a/--allow-empty）；`revert` 必须生成 commit（禁 -n），v1 不给
#   merge 的 -m；
# - 执行前 `git rev-parse --show-toplevel` 必须等于工作目录根；
# - 历史永不改写：reset --hard / clean / rm / rebase / amend / push / fetch /
#   checkout -- 一律不在白名单内，直接拒绝。
# =============================================================================

"""Whitelisted git executor: the P3 sandbox boundary for all agent git work."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cellwiki.services.path_guard import PathGuardError, validate_workspace_path


class GitCommandError(RuntimeError):
    """Base error for the whitelisted git executor."""


class GitForbiddenCommandError(GitCommandError):
    """Raised when the action or a flag/ref is not on the whitelist."""


class GitPathError(GitCommandError):
    """Raised when a path argument violates the P1 sandbox boundary."""


class GitToplevelMismatchError(GitCommandError):
    """Raised when the repository toplevel differs from the workspace root."""


ALLOWED_ACTIONS = frozenset({"status", "diff", "log", "add", "commit", "revert"})
FORBIDDEN_GLOBAL_HISTORY_COMMANDS = frozenset(
    {"reset", "clean", "rm", "rebase", "amend", "push", "fetch", "checkout", "restore", "cherry-pick", "merge"}
)

# 每个动作允许的非路径标志（值标志单独处理）
_ALLOWED_FLAGS: dict[str, frozenset[str]] = {
    "status": frozenset({"--short", "--branch", "--porcelain"}),
    "diff": frozenset({"--stat", "--name-only", "--name-status", "--numstat"}),
    "log": frozenset({"--oneline", "--max-count"}),
    "add": frozenset(),
    "commit": frozenset({"-m", "--message"}),
    "revert": frozenset({"--no-edit"}),
}
# 每个动作显式禁止的危险标志（即使不在 is-allowed 集合也给出明确错误）
_FORBIDDEN_FLAGS: dict[str, frozenset[str]] = {
    "add": frozenset(
        {"-A", "--all", "-u", "--update", "-p", "--patch", "-i", "--interactive",
         "-e", "--edit", "-f", "--force", "-n", "--dry-run", "-N", "--intent-to-add"}
    ),
    "commit": frozenset(
        {"--amend", "--fixup", "--squash", "-c", "-C", "-F", "--author", "-a",
         "--all", "--allow-empty", "-e", "--edit", "-n", "--no-verify", "-S", "--gpg-sign"}
    ),
    "revert": frozenset({"-n", "--no-commit", "-m", "--mainline"}),
    "status": frozenset(),
    "diff": frozenset(),
    "log": frozenset({"--follow", "-p", "--all", "--graph", "--grep", "--author"}),
}
# git 空树（empty tree）的规范哈希：用于 fresh 工作区（无 HEAD）的根 diff
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_REF_RE = re.compile(r"^(HEAD|[0-9a-fA-F]{7,40})(\^[0-9]*|~[0-9]*)?$")
_LOG_COUNT_FLAGS = re.compile(r"^-\d+$")


@dataclass(frozen=True)
class GitDiff:
    """Parsed diff between two refs for the pending-diff review UI."""

    left: str
    right: str
    patch: str
    files: list[str]
    insertions: int
    deletions: int


class GitExecutor:
    """Execute only the whitelisted git actions against one workspace root."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        timeout: float = 30.0,
        max_output_bytes: int = 200_000,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes
        self._toplevel: Path | None = None

    # ---- 公共 API ----
    def run(self, *args: str) -> str:
        """Validate and execute one whitelisted git command; returns stdout."""
        tokens = [str(arg) for arg in args]
        if not tokens:
            raise GitForbiddenCommandError("git command is empty")
        action = self._parse_action(tokens)
        self._validate_tokens(action, tokens)
        return self._run_unchecked(*tokens, label=action)

    def _run_unchecked(self, *args: str, label: str = "git") -> str:
        """System-owned git call with no agent input (ref queries only)."""
        self._assert_toplevel()
        completed = subprocess.run(
            ["git", *args],
            cwd=str(self.workspace_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
        )
        if completed.returncode != 0:
            raise GitCommandError(
                f"git {label} failed: {(completed.stderr or '').strip()[:500]}"
            )
        return completed.stdout[: self.max_output_bytes]

    def toplevel(self) -> Path:
        return self._assert_toplevel()

    # ---- 待确认 diff 与 revert 语义 ----
    def current_head(self) -> str:
        """Return the current HEAD sha, or raise when the repo has no commits."""
        return self._run_unchecked("rev-parse", "HEAD").strip()

    def has_commits(self) -> bool:
        try:
            self._run_unchecked("rev-parse", "--verify", "HEAD")
            return True
        except GitCommandError:
            return False

    def commits_since(self, snapshot: str | None) -> list[str]:
        """Return run commits after ``snapshot``, newest first (excluding merge commits).

        ``None`` means the workspace had no commits when the run started; all
        current commits are returned (the run produced the repo's first commit(s)).
        """
        if snapshot is None:
            output = self._run_unchecked("log", "--no-merges", "--format=%H", "HEAD")
        else:
            self._validate_ref(snapshot, None)
            output = self._run_unchecked(
                "log", "--no-merges", "--format=%H", f"{snapshot}..HEAD"
            )
        return [line.strip() for line in output.splitlines() if line.strip()]

    def diff_between(
        self,
        left: str | None,
        right: str = "HEAD",
        *,
        include_paths: Iterable[str] = (),
        exclude_paths: Iterable[str] = (),
        enabled_refs: frozenset[str] | None = None,
    ) -> GitDiff:
        """Diff ``left``..``right`` with optional pathspec include/exclude filters."""
        if left is None:
            # 系统级空树：工作区首个提交与空快照之间不存在可引用的 ref
            left = _EMPTY_TREE
        else:
            self._validate_ref(left, enabled_refs)
        self._validate_ref(right, enabled_refs)
        pathspec = self._build_pathspec(include_paths, exclude_paths)
        padding = ["--", *pathspec] if pathspec else []
        numstat = self.run("diff", "--numstat", left, right, *padding)
        insertions = 0
        deletions = 0
        files: list[str] = []
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added, removed, path = parts[0], parts[1], "\t".join(parts[2:])
            if added == "-" or removed == "-":
                continue
            try:
                insertions += int(added)
                deletions += int(removed)
            except ValueError:
                continue
            files.append(path)
        patch = self.run("diff", left, right, *padding)
        return GitDiff(
            left=left,
            right=right,
            patch=patch,
            files=files,
            insertions=insertions,
            deletions=deletions,
        )

    def revert_commits(self, shas: Iterable[str]) -> list[str]:
        """Revert run commits newest-first; each revert creates a new commit."""
        created: list[str] = []
        for sha in shas:
            value = str(sha).strip()
            self._validate_ref(value, None)
            self.run("revert", "--no-edit", value)
            created.append(self.current_head())
        return created

    # ---- 内部校验 ----
    def _parse_action(self, tokens: list[str]) -> str:
        for token in tokens:
            if token == "--":
                break
            if token.startswith("-"):
                continue
            action = token
            if action not in ALLOWED_ACTIONS:
                if action in FORBIDDEN_GLOBAL_HISTORY_COMMANDS:
                    raise GitForbiddenCommandError(
                        f"git action '{action}' rewrites history or touches remotes and is forbidden"
                    )
                raise GitForbiddenCommandError(
                    f"git action '{action}' is not on the whitelist"
                )
            return action
        raise GitForbiddenCommandError("git command has no whitelisted action")

    def _validate_token_before_separator(self, action: str, token: str) -> None:
        if token == "--":
            return
        if token.startswith("-"):
            name = token.split("=", 1)[0]
            if name in _FORBIDDEN_FLAGS.get(action, frozenset()):
                raise GitForbiddenCommandError(f"flag '{token}' is forbidden for git {action}")
            allowed = _ALLOWED_FLAGS.get(action, frozenset())
            if name in allowed:
                return
            if action == "log" and (_LOG_COUNT_FLAGS.match(token) or token.startswith("--max-count=")):
                return
            raise GitForbiddenCommandError(f"flag '{token}' is not allowed for git {action}")
        # 非标志 token：add 的显式路径（P1 校验）或 ref
        if action == "add":
            if token == ".":
                return  # 工作区根的全量 add（路径安全，等价于显式列出全部）
            self._validate_git_path(token)
            return
        if action == "commit":
            return  # -m 的取值是自由文本
        self._validate_ref(token, None)

    def _validate_tokens(self, action: str, tokens: list[str]) -> None:
        saw_separator = False
        message_flags = 0
        for index, token in enumerate(tokens):
            if index == 0:
                continue  # 跳过动作 token 本身（已由 _parse_action 校验）
            if token == "--":
                saw_separator = True
                continue
            if saw_separator:
                self._validate_git_path(token)
                continue
            if token in {"-m", "--message"}:
                message_flags += 1
                continue
            if token.startswith(("-m", "--message=")):
                message_flags += 1
                continue
            self._validate_token_before_separator(action, token)
        if action == "commit":
            if message_flags != 1:
                raise GitForbiddenCommandError(
                    "git commit requires exactly one -m/--message value"
                )


    def _validate_git_path(self, raw: str) -> None:
        if raw == ".":
            return  # git pathspec 的根基准（路径安全）
        try:
            validate_workspace_path(self.workspace_root, raw, allow_missing=True)
        except PathGuardError as error:
            raise GitPathError(str(error)) from error

    def _build_pathspec(
        self,
        include_paths: Iterable[str],
        exclude_paths: Iterable[str],
    ) -> list[str]:
        included = [str(path) for path in include_paths]
        excluded = [str(path) for path in exclude_paths]
        for path in [*included, *excluded]:
            self._validate_git_path(path)
        pathspec: list[str] = []
        if included:
            pathspec.extend(included)
        elif excluded:
            pathspec.append(".")
        pathspec.extend(f":(exclude){path}" for path in excluded)
        return pathspec

    def _validate_ref(self, ref: str, enabled_refs: frozenset[str] | None) -> None:
        value = str(ref).strip()
        if enabled_refs is not None:
            if value in enabled_refs:
                return
            raise GitForbiddenCommandError(f"ref '{ref}' is not in the enabled refs")
        if not _REF_RE.match(value):
            raise GitForbiddenCommandError(f"ref '{ref}' is not an allowed reference")

    def _assert_toplevel(self) -> Path:
        if self._toplevel is not None:
            return self._toplevel
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(self.workspace_root),
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if completed.returncode != 0:
            raise GitToplevelMismatchError("workspace is not a git repository")
        toplevel = Path(os.path.normpath((completed.stdout or "").strip())).resolve()
        if os.path.normcase(str(toplevel)) != os.path.normcase(str(self.workspace_root)):
            raise GitToplevelMismatchError(
                f"toplevel {toplevel} differs from workspace root {self.workspace_root}"
            )
        self._toplevel = toplevel
        return toplevel