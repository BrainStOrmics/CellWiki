# =============================================================================
# 白名单工具执行器 —— 七工具 + P1-P4 沙箱 + P4 审计
# =============================================================================
# File/Glob/Grep/Git/PowerShell 工具进入白名单，作为 Coordinator 的默认工具集：
#   read_file / write_file / edit_file / glob / grep / git / run_powershell
# - P1 路径校验、P2 symlink 策略：统一走 services/path_guard.py；
# - P3 进程白名单：git 仅白名单六动作（services/git_executor.py）；
#   run_powershell 仅只读 examine 命令（动词白名单 + 分隔符/危险动词拒绝）；
# - P4 审计：工具输入参数与输出哈希由运行时 Seam 记录（run 级只读），
#   不重复实现框架级日志；本模块不依赖任何真实工具化/AST 方案。
# =============================================================================

"""Whitelisted workspace tools: File ops, Glob, Grep, Git, and read-only PowerShell."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from cellwiki.services.git_executor import GitCommandError, GitExecutor
from cellwiki.services.path_guard import PathGuardError, validate_workspace_path

MAX_READ_BYTES = 200_000          # read_file 单文件上限
MAX_WRITE_BYTES = 400_000         # write_file 单次写入上限
MAX_GLOB_RESULTS = 500
MAX_GREP_RESULTS = 200
MAX_TOOL_OUTPUT = 60_000          # 工具返回给模型的输出上限
MAX_ATTACHMENT_READ_BYTES = 200_000  # read_attachment 单文件读取上限

# run_powershell：只读 examine 动词白名单（其余动词一律拒绝）
_PS_EXAMINE_VERBS = (
    "get-",
    "test-",
    "measure-",
    "select-",
    "where-",
    "sort-",
    "group-",
    "compare-",
    "format-",
    "out-string",
    "write-output",
    "echo",
    "dir",
    "ls",
    "type",
    "cat",
)
# run_powershell：任何位置出现的危险 token 一律拒绝（含 PowerShell 分隔符）
_PS_FORBIDDEN_TOKENS = (
    "remove-item",
    "rm ",
    "del ",
    "new-item",
    "move-item",
    "copy-item",
    "rename-item",
    "clear-content",
    "set-content",
    "add-content",
    "append-content",
    "out-file",
    "set-item",
    "set-variable",
    "remove-variable",
    "new-alias",
    "set-alias",
    "import-module",
    "invoke-expression",
    "iex ",
    "invoke-webrequest",
    "invoke-restmethod",
    "invoke-command",
    "start-process",
    "start-job",
    "remove-job",
    "stop-process",
    "install-",
    "uninstall-",
    "set-executionpolicy",
    "downloadfile",
    "add-type",
    "register-",
    "unregister-",
    "write-eventlog",
    "clear-eventlog",
    "remove-eventlog",
    "disconnect-",
    "connect-",
    "enter-pssession",
    "exit-pssession",
    "sync-",
    "wait-",
)
_PS_FORBIDDEN_SEPARATORS = (";", "|", ">", "&", "`n", "`r", "&&", "||")



WHITELISTED_TOOL_NAMES = frozenset(
    {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "git",
        "run_powershell",
        "delete_file",
        "rename_file",
        "lint_knowledge_base",
        "ask_user_question",
        "read_attachment",
        "submit_agent_answer",
    }
)

# read_attachment 的线程作用域解析器：由 AgentRuntimeManager 在每次 run 前安装
# （严格串行执行，因此单一槽位即可；run 结束或异常后必须清除）。
_ATTACHMENT_RESOLVER: Any = None


def set_attachment_resolver(resolver: Any) -> None:
    """Install the thread-scoped attachment resolver for the current serial run."""
    global _ATTACHMENT_RESOLVER
    _ATTACHMENT_RESOLVER = resolver


def clear_attachment_resolver() -> None:
    """Drop the resolver after a run ends (never leak thread scope across runs)."""
    global _ATTACHMENT_RESOLVER
    _ATTACHMENT_RESOLVER = None


def build_attachment_tools() -> list[BaseTool]:
    """Provide thread-scoped read of uploaded attachments (temporary Agent context)."""

    @tool("read_attachment")
    def read_attachment(attachment_id: str) -> str:
        """Read one thread-scoped uploaded attachment as UTF-8 text (binary rejected)."""
        resolver = _ATTACHMENT_RESOLVER
        if resolver is None:
            return _tool_json({"error": "no active run context"})
        try:
            target = resolver(attachment_id)
        except Exception as error:  # 解析器异常不应让 run 崩溃
            return _tool_json({"error": f"cannot resolve attachment: {error}"})
        if target is None:
            return _tool_json({"error": "attachment_not_found"})
        content = _read_text_safely(target, MAX_ATTACHMENT_READ_BYTES)
        if len(content) > MAX_TOOL_OUTPUT:
            content = content[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
        return _tool_json({"attachment_id": attachment_id, "content": content})

    return [read_attachment]


def _tool_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _read_text_safely(path: Path, max_bytes: int) -> str:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ValueError(f"cannot read {path.name}: {error}") from error
    if len(data) > max_bytes:
        raise ValueError(f"file exceeds the {max_bytes}-byte read limit")
    try:
        return data.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        raise ValueError("file is not valid UTF-8 text") from None


def build_workspace_tools(project_root: Path) -> list[BaseTool]:
    """Assemble the seven whitelisted workspace tools for the coordinator."""
    root = Path(project_root).resolve()

    @tool("read_file")
    def read_file(path: str) -> str:
        """Read a UTF-8 text file inside the workspace; binary files and oversized files are rejected."""
        try:
            target = validate_workspace_path(root, path)
        except PathGuardError as error:
            return _tool_json({"error": str(error)})
        if not target.is_file():
            return _tool_json({"error": "file_not_found", "path": target.relative_to(root).as_posix()})
        content = _read_text_safely(target, MAX_READ_BYTES)
        if len(content) > MAX_TOOL_OUTPUT:
            content = content[:MAX_TOOL_OUTPUT] + "\n...[truncated]"
        return _tool_json(
            {"path": target.relative_to(root).as_posix(), "content": content}
        )

    @tool("write_file")
    def write_file(path: str, content: str) -> str:
        """Write UTF-8 text to a workspace file (creates parents); binary and oversized writes are rejected."""
        try:
            target = validate_workspace_path(root, path, allow_missing=True)
        except PathGuardError as error:
            return _tool_json({"error": str(error)})
        if "\x00" in content:
            return _tool_json({"error": "binary content is not allowed"})
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            return _tool_json({"error": f"content exceeds the {MAX_WRITE_BYTES}-byte limit"})
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as error:
            return _tool_json({"error": f"write failed: {error}"})
        return _tool_json({"ok": True, "path": target.relative_to(root).as_posix(), "bytes": len(data)})

    @tool("edit_file")
    def edit_file(path: str, old_string: str, new_string: str) -> str:
        """Replace one exact occurrence of old_string in a workspace file; ambiguous matches fail."""
        try:
            target = validate_workspace_path(root, path)
        except PathGuardError as error:
            return _tool_json({"error": str(error)})
        if not target.is_file():
            return _tool_json({"error": "file_not_found", "path": target.relative_to(root).as_posix()})
        content = _read_text_safely(target, MAX_READ_BYTES)
        if not old_string:
            return _tool_json({"error": "old_string must not be empty"})
        count = content.count(old_string)
        if count == 0:
            return _tool_json({"error": "old_string not found"})
        if count > 1:
            return _tool_json({"error": "old_string is ambiguous; include more context"})
        updated = content.replace(old_string, new_string, 1)
        if len(updated.encode("utf-8")) > MAX_WRITE_BYTES:
            return _tool_json({"error": f"result exceeds the {MAX_WRITE_BYTES}-byte limit"})
        target.write_text(updated, encoding="utf-8")
        return _tool_json({"ok": True, "path": target.relative_to(root).as_posix(), "bytes": len(updated.encode("utf-8"))})

    @tool("ls")
    def ls(folder: str = ".", recursive: bool = False) -> str:
        """List directory entries inside the workspace (excludes .git)."""
        try:
            base = validate_workspace_path(root, folder, allow_missing=True)
        except PathGuardError as error:
            return _tool_json({"error": str(error)})
        if not base.is_dir():
            return _tool_json({"error": "directory_not_found", "path": folder})
        entries: list[dict[str, object]] = []
        iterator = base.rglob("*") if recursive else base.iterdir()
        for candidate in sorted(iterator, key=lambda item: (not item.is_dir(), item.name.lower())):
            if candidate.is_dir():
                continue
            rel = candidate.relative_to(root).as_posix()
            if ".git/" in f"/{rel}":
                continue
            entries.append(
                {
                    "name": candidate.name,
                    "path": rel,
                    "size": candidate.stat().st_size if candidate.is_file() else 0,
                }
            )
            if len(entries) >= MAX_GLOB_RESULTS:
                break
        return _tool_json({"results": entries, "truncated": len(entries) >= MAX_GLOB_RESULTS})

    @tool("delete_file")
    def delete_file(path: str) -> str:
        """Delete one file inside the workspace (never directories)."""
        try:
            target = validate_workspace_path(root, path)
        except PathGuardError as error:
            return _tool_json({"error": str(error)})
        if not target.is_file():
            return _tool_json({"error": "file_not_found", "path": path})
        try:
            target.unlink()
        except OSError as error:
            return _tool_json({"error": f"delete failed: {error}"})
        return _tool_json({"ok": True, "path": target.relative_to(root).as_posix()})

    @tool("rename_file")
    def rename_file(path: str, new_path: str) -> str:
        """Rename or move one file to another workspace path (single-file move)."""
        try:
            source = validate_workspace_path(root, path)
            target = validate_workspace_path(root, new_path, allow_missing=True)
        except PathGuardError as error:
            return _tool_json({"error": str(error)})
        if not source.is_file():
            return _tool_json({"error": "file_not_found", "path": path})
        if target == source:
            return _tool_json({"error": "new_path must differ from path"})
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
        except OSError as error:
            return _tool_json({"error": f"rename failed: {error}"})
        return _tool_json(
            {
                "ok": True,
                "path": target.relative_to(root).as_posix(),
            }
        )

    @tool("glob")
    def glob(pattern: str, folder: str = ".") -> str:
        """List workspace files matching a glob pattern (e.g. **/*.md); excludes .git."""
        base = root
        if folder != ".":
            try:
                base = validate_workspace_path(root, folder, allow_missing=True)
            except PathGuardError as error:
                return _tool_json({"error": str(error)})
        results: list[str] = []
        for candidate in sorted(base.rglob(pattern)) if base.is_dir() else []:
            if not candidate.is_file():
                continue
            rel = candidate.relative_to(root).as_posix()
            if ".git/" in f"/{rel}":
                continue
            results.append(rel)
            if len(results) >= MAX_GLOB_RESULTS:
                break
        return _tool_json({"results": results, "truncated": len(results) >= MAX_GLOB_RESULTS})

    @tool("grep")
    def grep(
        pattern: str,
        path: str = ".",
        case_sensitive: bool = False,
        max_results: int = MAX_GREP_RESULTS,
    ) -> str:
        """Search workspace text files line by line for a literal pattern; excludes .git."""
        if path == ".":
            base = root
        else:
            try:
                base = validate_workspace_path(root, path, allow_missing=True)
            except PathGuardError as error:
                return _tool_json({"error": str(error)})
        needle = pattern if case_sensitive else pattern.lower()
        matches: list[dict[str, str | int]] = []
        if base.is_dir():
            candidates = sorted(base.rglob("*"))
        else:
            candidates = [base]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            rel = candidate.relative_to(root).as_posix()
            if ".git/" in f"/{rel}":
                continue
            try:
                size = candidate.stat().st_size
                if size > 2_000_000:
                    continue
                for lineno, line in enumerate(candidate.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                    haystack = line if case_sensitive else line.lower()
                    if needle in haystack:
                        matches.append({"file": rel, "line": lineno, "text": line[:400]})
                        if len(matches) >= max_results:
                            break
            except OSError:
                continue
            if len(matches) >= max_results:
                break
        return _tool_json({"results": matches, "truncated": len(matches) >= max_results})

    class _GitArgs(BaseModel):
        """Whitelisted git action plus its flags and explicit paths."""

        args: list[str] = Field(description="git subcommand tokens, e.g. ['status', '--short']")

    @tool("git", args_schema=_GitArgs)
    def git(args: list[str]) -> str:
        """Run a whitelisted git action (status/diff/log/add/commit/revert) inside the workspace."""
        if not args:
            return _tool_json({"error": "no git arguments provided"})
        try:
            return _tool_json({"stdout": GitExecutor(root).run(*args)})
        except GitCommandError as error:
            return _tool_json({"error": str(error)[:2000]})

    @tool("run_powershell")
    def run_powershell(command: str) -> str:
        """Run a read-only PowerShell examine command inside the workspace (Get-* only)."""
        cleaned = command.strip()
        if not cleaned:
            return _tool_json({"error": "empty command"})
        lowered = f" {cleaned.lower()} "
        for separator in _PS_FORBIDDEN_SEPARATORS:
            if separator in lowered:
                return _tool_json({"error": f"forbidden separator '{separator.strip()}'"})
        for token in _PS_FORBIDDEN_TOKENS:
            if f" {token} " in lowered or lowered.startswith(f"{token} ") or lowered.endswith(f" {token}"):
                return _tool_json({"error": f"forbidden PowerShell token '{token.strip()}'"})
        try:
            tokens = shlex.split(cleaned, posix=False)
        except ValueError as error:
            return _tool_json({"error": f"cannot parse command: {error}"})
        if not tokens:
            return _tool_json({"error": "empty command"})
        verb = tokens[0].lower()
        if not verb.startswith(_PS_EXAMINE_VERBS):
            return _tool_json({"error": f"verb '{tokens[0]}' is not on the read-only whitelist"})
        executable = "powershell.exe" if sys.platform == "win32" else "pwsh"
        try:
            completed = subprocess.run(
                [executable, "-NoProfile", "-NonInteractive", "-Command", cleaned],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=25,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return _tool_json({"error": f"powershell failed: {error}"})
        output = (completed.stdout or "")[:MAX_TOOL_OUTPUT]
        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "")[:2000]
            return _tool_json({"error": f"command failed with {completed.returncode}: {error_text}"})
        return _tool_json({"stdout": output, "returncode": completed.returncode})

    return [ls, read_file, write_file, edit_file, glob, grep, git, run_powershell, delete_file, rename_file]