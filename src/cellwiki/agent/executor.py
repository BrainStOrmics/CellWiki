# =============================================================================
# 白名单工具执行器 —— 九工具 + P1-P4 沙箱 + P4 审计
# =============================================================================
# File/Glob/Grep/Git/PowerShell 工具进入白名单，作为 Coordinator 的默认工具集：
#   glob / grep / read_file / write_file / edit_file / delete_file /
#   rename_file / git / run_powershell
# 工具名与规范顺序的唯一定义在 domain/agent_tools.py，此处只实现工具本身。

# - P1 路径校验、P2 symlink 策略：统一走 services/path_guard.py；
# - P3 进程白名单：git 仅白名单六动作（services/git_executor.py）；
#   run_powershell 仅只读 examine 命令（动词白名单 + 分隔符/危险动词拒绝）；
# - P4 审计：工具输入参数与输出哈希由运行时 Seam 记录（run 级只读），
#   不重复实现框架级日志；本模块不依赖任何真实工具化/AST 方案。
# =============================================================================

"""Whitelisted workspace tools: File ops, Glob, Grep, Git, and read-only PowerShell."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from cellwiki.domain.agent_tools import (
    AGENT_VISIBLE_TOOL_NAMES,
    MEMORY_TOOL_NAMES,
    agent_tool_names,
)
from cellwiki.config import settings
from cellwiki.services.git_executor import GitCommandError, GitExecutor
from cellwiki.services.path_guard import PathGuardError, validate_workspace_path
from cellwiki.services.workspace import SYSTEM_OWNED_FILES

AGENT_READ_ONLY_FILES = SYSTEM_OWNED_FILES | {"schema.md"}

MAX_READ_BYTES = 20 * 1024 * 1024  # read_file/edit_file 单文件字节上限（范围读取取代 200KB 硬失败）
MAX_WRITE_BYTES = 400_000         # write_file 单次写入上限
MAX_GLOB_RESULTS = 500
MAX_GREP_RESULTS = 200
MAX_TOOL_OUTPUT = 60_000          # 工具返回给模型的输出上限
MAX_ATTACHMENT_READ_BYTES = MAX_READ_BYTES  # 附件读取沿用同一字节上限

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
# 管道符单独处理：每个管道段的首个 token 都必须命中只读动词白名单。
_PS_FORBIDDEN_SEPARATORS = (";", ">", "&", "`n", "`r", "&&", "||")
# 脚本块、子表达式与静态方法调用可以绕过动词白名单，按子串直接拒绝。
_PS_FORBIDDEN_SUBSTRINGS = ("$(", "::", "{", "}")


# 工具清单由 domain/agent_tools.py 的注册表派生——它是"Agent 能干什么"的
# 唯一事实源。变量名保持不变：services/subagents.py 用前者校验子 Agent 的
# 工具声明必须落在主白名单内。
WHITELISTED_TOOL_NAMES: frozenset[str] = AGENT_VISIBLE_TOOL_NAMES


def current_tool_order() -> tuple[str, ...]:
    """Canonical order for this process: memory tools append when enabled."""

    return agent_tool_names(settings.agent_memory_enabled)


def effective_whitelist() -> frozenset[str]:
    """Allowlist for this process; memory tools only when the switch is on."""

    if settings.agent_memory_enabled:
        return WHITELISTED_TOOL_NAMES | frozenset(MEMORY_TOOL_NAMES)
    return WHITELISTED_TOOL_NAMES


def canonical_tool_sort_key(tool_name: str) -> tuple[int, str]:
    order = current_tool_order()
    try:
        return (order.index(tool_name), tool_name)
    except ValueError:
        return (len(order), tool_name)


def tool_schema_text(tools: list[Any]) -> str:
    """Canonical tool-definition text: fingerprint and context estimate share one rendering."""

    payload: list[dict[str, Any]] = []
    for tool_item in sorted(
        tools,
        key=lambda item: canonical_tool_sort_key(
            str(getattr(item, "name", "") or "")
        ),
    ):
        name = str(getattr(tool_item, "name", "") or "")
        description = str(getattr(tool_item, "description", "") or "")
        args_schema = getattr(tool_item, "args_schema", None)
        if args_schema is not None and hasattr(args_schema, "model_json_schema"):
            schema = args_schema.model_json_schema()
        else:
            schema = {}
        payload.append(
            {
                "name": name,
                "description": description,
                "schema": schema,
            }
        )
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def tool_schema_fingerprint(tools: list[Any]) -> str:
    """Hash tool names, descriptions, schemas, and canonical ordering."""

    return hashlib.sha256(tool_schema_text(tools).encode("utf-8")).hexdigest()

# read_attachment 的线程作用域解析器与附件读取预算：由 AgentRuntimeManager 在每次 run 前安装
# （严格串行执行，因此单一槽位即可；run 结束或异常后必须清除）。
_ATTACHMENT_RESOLVER: Any = None
_ATTACHMENT_WORKSPACE_ROOT: Path | None = None
_ATTACHMENT_THREAD_DIR: Path | None = None
_ATTACHMENT_READ_CHARS: int = 0
_ATTACHMENT_BUDGET_TOTAL: int = 0


def set_attachment_resolver(resolver: Any) -> None:
    """Install the thread-scoped attachment resolver for the current serial run."""
    global _ATTACHMENT_RESOLVER
    _ATTACHMENT_RESOLVER = resolver


def clear_attachment_resolver() -> None:
    """Drop the resolver after a run ends (never leak thread scope across runs)."""
    global _ATTACHMENT_RESOLVER
    _ATTACHMENT_RESOLVER = None


def set_attachment_scope(
    resolver: Any,
    workspace_root: Path,
    thread_dir: Path | None,
    budget_chars: int,
) -> None:
    """Install the current run attachment scope (resolver, allowed dir, read budget)."""
    global _ATTACHMENT_RESOLVER, _ATTACHMENT_WORKSPACE_ROOT, _ATTACHMENT_THREAD_DIR
    global _ATTACHMENT_READ_CHARS, _ATTACHMENT_BUDGET_TOTAL
    _ATTACHMENT_RESOLVER = resolver
    _ATTACHMENT_WORKSPACE_ROOT = Path(workspace_root).resolve() if workspace_root else None
    _ATTACHMENT_THREAD_DIR = Path(thread_dir).resolve() if thread_dir else None
    _ATTACHMENT_READ_CHARS = 0
    _ATTACHMENT_BUDGET_TOTAL = max(0, int(budget_chars or 0))


def clear_attachment_scope() -> None:
    """Drop the attachment scope after a run ends (never leak across runs)."""
    global _ATTACHMENT_RESOLVER, _ATTACHMENT_WORKSPACE_ROOT, _ATTACHMENT_THREAD_DIR
    global _ATTACHMENT_READ_CHARS, _ATTACHMENT_BUDGET_TOTAL
    _ATTACHMENT_RESOLVER = None
    _ATTACHMENT_WORKSPACE_ROOT = None
    _ATTACHMENT_THREAD_DIR = None
    _ATTACHMENT_READ_CHARS = 0
    _ATTACHMENT_BUDGET_TOTAL = 0
    global _PROMOTE_HANDLER
    _PROMOTE_HANDLER = None


def get_attachment_scope() -> tuple[Any, Any, Any]:
    """Return (resolver, workspace_root, thread_dir) for the current run."""
    return _ATTACHMENT_RESOLVER, _ATTACHMENT_WORKSPACE_ROOT, _ATTACHMENT_THREAD_DIR

def attachment_read_stats() -> tuple[int, int]:
    """Return (chars_read, est_tokens) consumed by attachment reads this run."""
    return _ATTACHMENT_READ_CHARS, (_ATTACHMENT_READ_CHARS + 3) // 4

# promote 回调：由 AgentRuntimeManager 安装，把登记结果写回附件记录
_PROMOTE_HANDLER: Any = None


def set_promotion_handler(handler: Any) -> None:
    """Install the thread-scoped post-promote callback for the current run."""
    global _PROMOTE_HANDLER
    _PROMOTE_HANDLER = handler


def get_promotion_handler() -> Any:
    """Return the installed post-promote callback (None when absent)."""
    return _PROMOTE_HANDLER


def _is_attachment_path(target: Path, root: Path) -> bool:
    """True when the target lives under data/runtime/attachments/ in the workspace."""
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        return False
    return rel.startswith('data/runtime/attachments/')


def _attachment_allowed(target: Path) -> bool:
    """Only the current thread attachment directory is readable."""
    if _ATTACHMENT_THREAD_DIR is None:
        return False
    try:
        target.relative_to(_ATTACHMENT_THREAD_DIR)
        return True
    except ValueError:
        return False


def _is_blocked_runtime_file(target: Path) -> bool:
    """Deny runtime databases, staging files, and git internals."""
    if target.name == 'cellwiki.db':
        return True
    if target.name.endswith('.staging'):
        return True
    if '.git' in target.parts:
        return True
    return False


def _is_agent_read_only_file(target: Path, root: Path) -> bool:
    """True when target is a root file the Agent must not edit directly."""
    try:
        rel = target.relative_to(root)
    except ValueError:
        return False
    return len(rel.parts) == 1 and rel.parts[0] in AGENT_READ_ONLY_FILES


def _remaining_budget() -> int | None:
    """Remaining attachment read budget; None when unlimited (budget 0)."""
    if _ATTACHMENT_BUDGET_TOTAL <= 0:
        return None
    return max(0, _ATTACHMENT_BUDGET_TOTAL - _ATTACHMENT_READ_CHARS)


def _rel_or_name(root: Path | None, target: Path) -> str:
    """Workspace-relative path, or the bare name when the root is unknown."""
    if root is not None:
        try:
            return target.relative_to(root).as_posix()
        except ValueError:
            pass
    return target.name


def _normalize_newlines(text: str) -> str:
    """Collapse CRLF and lone CR line endings to LF so tool I/O stays stable."""

    return text.replace("\r\n", "\n").replace("\r", "\n")


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """Replace a file atomically via a same-directory temp file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _split_brace_alternatives(body: str) -> list[str]:
    """Split a brace body on top-level commas, keeping nested groups intact."""
    alternatives: list[str] = []
    current: list[str] = []
    depth = 0
    for char in body:
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            alternatives.append("".join(current))
            current = []
            continue
        current.append(char)
    alternatives.append("".join(current))
    return alternatives


def _expand_braces(pattern: str, limit: int = 32) -> list[str]:
    """Expand simple {a,b} alternatives; non-comma groups stay literal."""
    start = pattern.find("{")
    while start != -1:
        depth = 0
        end = -1
        for index in range(start, len(pattern)):
            if pattern[index] == "{":
                depth += 1
            elif pattern[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end == -1:
            break
        alternatives = _split_brace_alternatives(pattern[start + 1 : end])
        if len(alternatives) > 1:
            expanded: list[str] = []
            for alternative in alternatives:
                expanded.extend(
                    _expand_braces(
                        pattern[:start] + alternative + pattern[end + 1 :], limit
                    )
                )
                if len(expanded) >= limit:
                    return expanded[:limit]
            return expanded
        start = pattern.find("{", end + 1)
    return [pattern]


def _normalize_glob_pattern(pattern: str) -> str:
    """Normalize a user glob so a trailing '**' also matches files."""
    normalized = pattern.strip().replace("\\", "/")
    if normalized in ("", "."):
        return "*"
    normalized = normalized.rstrip("/")
    if normalized == "**":
        return "**/*"
    if normalized.endswith("/**"):
        return normalized + "/*"
    return normalized


def _glob_pattern_is_unsafe(pattern: str) -> bool:
    """Reject absolute, drive-qualified, and parent-traversal glob patterns."""
    normalized = pattern.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    if re.match(r"^[A-Za-z]:", normalized):
        return True
    return ".." in normalized.split("/")


def _read_workspace_text(
    root: Path | None,
    target: Path,
    *,
    offset: int = 0,
    length: int = 0,
    start_line: int = 0,
    end_line: int = 0,
    attachment: bool = False,
) -> dict[str, Any]:
    """Read UTF-8 text with char or 1-based line ranges, output caps, and budget."""
    global _ATTACHMENT_READ_CHARS
    try:
        data = target.read_bytes()
    except OSError as error:
        return {"error": f"cannot read {target.name}: {error}"}
    if len(data) > MAX_READ_BYTES:
        return {
            "error": f"file exceeds the {MAX_READ_BYTES}-byte read limit; use the extracted text when present",
            "path": _rel_or_name(root, target),
        }
    if b"\x00" in data[:4096]:
        return {"error": "file is not valid UTF-8 text", "path": _rel_or_name(root, target)}
    text = _normalize_newlines(data.decode("utf-8", errors="replace"))
    total = len(text)
    total_lines: int | None = None
    returned_start_line: int | None = None
    returned_end_line: int | None = None
    requested_start_line = int(start_line or 0)
    requested_end_line = int(end_line or 0)
    if requested_start_line > 0 or requested_end_line > 0:
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        first = max(1, requested_start_line)
        last = (
            min(total_lines, requested_end_line)
            if requested_end_line > 0
            else total_lines
        )
        if total_lines == 0 or last < first:
            start = 0
            end = 0
            returned_start_line = first
            returned_end_line = first - 1
        else:
            start = sum(len(line) for line in lines[: first - 1])
            end = start + sum(len(line) for line in lines[first - 1 : last])
            returned_start_line = first
            returned_end_line = last
    else:
        start = min(total, max(0, int(offset or 0)))
        end = total
        if length and int(length) > 0:
            end = min(total, start + int(length))
    if end < start:
        end = start
    sliced = text[start:end]
    if attachment:
        remaining = _remaining_budget()
        if remaining is not None and remaining <= 0:
            return {
                "error": "attachment_read_budget_exceeded",
                "budget_chars": _ATTACHMENT_BUDGET_TOTAL,
                "read_chars": _ATTACHMENT_READ_CHARS,
                "suggestion": "focus on one paper or use the preview to triage",
            }
        if remaining is not None and len(sliced) > remaining:
            sliced = sliced[:remaining]
    if len(sliced) > MAX_TOOL_OUTPUT:
        sliced = sliced[:MAX_TOOL_OUTPUT]
    if (
        total_lines is not None
        and returned_start_line is not None
        and returned_end_line is not None
    ):
        span = sliced.count("\n")
        if sliced and not sliced.endswith("\n"):
            span += 1
        if span <= 0:
            returned_end_line = returned_start_line - 1
        else:
            returned_end_line = min(returned_end_line, returned_start_line + span - 1)
    if attachment:
        _ATTACHMENT_READ_CHARS += len(sliced)
    next_offset = start + len(sliced)
    payload: dict[str, Any] = {
        "path": _rel_or_name(root, target),
        "content": sliced,
        "offset": start,
        "next_offset": next_offset if next_offset < total else None,
        "truncated": next_offset < total,
        "total_chars": total,
    }
    if total_lines is not None:
        payload["start_line"] = returned_start_line
        payload["end_line"] = returned_end_line
        payload["total_lines"] = total_lines
    return payload




def build_attachment_tools() -> list[BaseTool]:
    """Provide thread-scoped read of uploaded attachments (temporary Agent context)."""

    @tool("read_attachment")
    def read_attachment(
        attachment_id: str,
        offset: int = 0,
        length: int = 0,
        start_line: int = 0,
        end_line: int = 0,
    ) -> str:
        """Read one thread-scoped attachment as UTF-8 text (alias of read_file with
        the same range/budget semantics)."""
        resolver = _ATTACHMENT_RESOLVER
        if resolver is None:
            return _tool_json({"error": "no active run context"})
        try:
            target = resolver(attachment_id)
        except Exception as error:  # 解析器异常不应让 run 崩溃
            return _tool_json({"error": f"cannot resolve attachment: {error}"})
        if target is None:
            return _tool_json({"error": "attachment_not_found"})
        return _tool_json(
            _read_workspace_text(
                _ATTACHMENT_WORKSPACE_ROOT,
                target,
                offset=offset,
                length=length,
                start_line=start_line,
                end_line=end_line,
                attachment=True,
            )
        )

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
        text = data.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        raise ValueError("file is not valid UTF-8 text") from None
    return _normalize_newlines(text)


def build_workspace_tools(project_root: Path) -> list[BaseTool]:
    """Assemble the nine whitelisted workspace tools for the coordinator.

    ``ls`` 已于 2026-09-21 退役：它不返回任何目录，能力被 ``glob``
    （列文件）与 ``run_powershell`` 的只读 ``Get-*``（列目录）完全覆盖。
    """

    root = Path(project_root).resolve()
    file_write_lock = threading.Lock()

    @tool("read_file")
    def read_file(
        path: str,
        offset: int = 0,
        length: int = 0,
        start_line: int = 0,
        end_line: int = 0,
    ) -> str:
        """Read a UTF-8 text file inside the workspace; supports char-based
        offset/length and 1-based inclusive start_line/end_line ranges."""
        try:
            target = validate_workspace_path(root, path)
        except PathGuardError as error:
            return _tool_json({"error": str(error)})
        if _is_blocked_runtime_file(target):
            return _tool_json({"error": "runtime file is not readable", "path": path})
        if not target.is_file():
            return _tool_json({"error": "file_not_found", "path": _rel_or_name(root, target)})
        attachment = _is_attachment_path(target, root)
        if attachment and not _attachment_allowed(target):
            return _tool_json({"error": "attachment_not_found", "path": path})
        return _tool_json(
            _read_workspace_text(
                root,
                target,
                offset=offset,
                length=length,
                start_line=start_line,
                end_line=end_line,
                attachment=attachment,
            )
        )

    @tool("write_file")
    def write_file(path: str, content: str) -> str:
        """Write UTF-8 text to a workspace file (creates parents); binary and oversized writes are rejected."""
        try:
            target = validate_workspace_path(root, path, allow_missing=True)
        except PathGuardError as error:
            return _tool_json({"error": str(error)})
        if _is_agent_read_only_file(target, root):
            return _tool_json({"error": "system-owned file is not writable", "path": _rel_or_name(root, target)})
        if "\x00" in content:
            return _tool_json({"error": "binary content is not allowed"})
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            return _tool_json({"error": f"content exceeds the {MAX_WRITE_BYTES}-byte limit"})
        try:
            with file_write_lock:
                _atomic_write_bytes(target, data)
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
        if _is_agent_read_only_file(target, root):
            return _tool_json({"error": "system-owned file is not writable", "path": _rel_or_name(root, target)})
        if not old_string:
            return _tool_json({"error": "old_string must not be empty"})
        try:
            with file_write_lock:
                if not target.is_file():
                    return _tool_json({"error": "file_not_found", "path": target.relative_to(root).as_posix()})
                content = _read_text_safely(target, MAX_READ_BYTES)
                count = content.count(old_string)
                if count == 0:
                    return _tool_json({"error": "old_string not found"})
                if count > 1:
                    return _tool_json({"error": "old_string is ambiguous; include more context"})
                updated = content.replace(old_string, new_string, 1)
                encoded = updated.encode("utf-8")
                if len(encoded) > MAX_WRITE_BYTES:
                    return _tool_json({"error": f"result exceeds the {MAX_WRITE_BYTES}-byte limit"})
                _atomic_write_bytes(target, encoded)
        except (OSError, ValueError) as error:
            return _tool_json({"error": f"edit failed: {error}"})
        return _tool_json({"ok": True, "path": target.relative_to(root).as_posix(), "bytes": len(encoded)})

    @tool("delete_file")
    def delete_file(path: str) -> str:
        """Delete one file inside the workspace (never directories)."""
        try:
            target = validate_workspace_path(root, path)
        except PathGuardError as error:
            return _tool_json({"error": str(error)})
        if _is_agent_read_only_file(target, root):
            return _tool_json({"error": "system-owned file is not writable", "path": _rel_or_name(root, target)})
        try:
            with file_write_lock:
                if not target.is_file():
                    return _tool_json({"error": "file_not_found", "path": path})
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
        if _is_agent_read_only_file(source, root) or _is_agent_read_only_file(target, root):
            return _tool_json({"error": "system-owned file is not writable", "path": _rel_or_name(root, source)})
        if target == source:
            return _tool_json({"error": "new_path must differ from path"})
        try:
            with file_write_lock:
                if not source.is_file():
                    return _tool_json({"error": "file_not_found", "path": path})
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
        """List workspace files matching a glob pattern (e.g. **/*.md);
        a trailing ** matches every file below it and simple {a,b} expands."""
        if not (pattern or "").strip():
            return _tool_json({"error": "pattern must not be empty"})
        patterns = [
            _normalize_glob_pattern(item) for item in _expand_braces(pattern.strip())
        ]
        for item in patterns:
            if _glob_pattern_is_unsafe(item):
                return _tool_json({"error": "pattern must stay inside the workspace"})
        base = root
        if (folder or ".") != ".":
            try:
                base = validate_workspace_path(root, folder, allow_missing=True)
            except PathGuardError as error:
                return _tool_json({"error": str(error)})
        results: list[str] = []
        seen: set[str] = set()
        directories_matched = 0
        for glob_pattern in patterns:
            if not base.is_dir():
                break
            for candidate in sorted(base.rglob(glob_pattern)):
                if not candidate.is_file():
                    directories_matched += 1
                    continue
                rel = candidate.relative_to(root).as_posix()
                if ".git/" in f"/{rel}" or rel in seen:
                    continue
                seen.add(rel)
                results.append(rel)
                if len(results) >= MAX_GLOB_RESULTS:
                    break
            if len(results) >= MAX_GLOB_RESULTS:
                break
        payload: dict[str, Any] = {
            "results": results,
            "truncated": len(results) >= MAX_GLOB_RESULTS,
        }
        if not results and directories_matched:
            payload["directories_matched"] = directories_matched
            payload["hint"] = (
                "glob returns files only; use run_powershell Get-ChildItem for directories"
            )
        return _tool_json(payload)

    @tool("grep")
    def grep(
        pattern: str,
        path: str = ".",
        case_sensitive: bool = False,
        max_results: int = MAX_GREP_RESULTS,
    ) -> str:
        """Search workspace text files line by line for a literal pattern; excludes .git."""
        if (path or ".") == ".":
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
        """Run a read-only PowerShell command inside the workspace; pipelines are
        allowed only when every segment starts with an allowlisted read-only verb."""
        cleaned = command.strip()
        if not cleaned:
            return _tool_json({"error": "empty command"})
        lowered = f" {cleaned.lower()} "
        for separator in _PS_FORBIDDEN_SEPARATORS:
            if separator in lowered:
                return _tool_json({"error": f"forbidden separator '{separator.strip()}'"})
        for token in _PS_FORBIDDEN_SUBSTRINGS:
            if token in lowered:
                return _tool_json({"error": f"forbidden PowerShell token '{token}'"})
        for token in _PS_FORBIDDEN_TOKENS:
            if f" {token} " in lowered or lowered.startswith(f"{token} ") or lowered.endswith(f" {token}"):
                return _tool_json({"error": f"forbidden PowerShell token '{token.strip()}'"})
        try:
            tokens = shlex.split(cleaned, posix=False)
        except ValueError as error:
            return _tool_json({"error": f"cannot parse command: {error}"})
        if not tokens:
            return _tool_json({"error": "empty command"})
        segments: list[list[str]] = [[]]
        for token in tokens:
            if token == "|":
                segments.append([])
            else:
                segments[-1].append(token)
        if any(not segment for segment in segments):
            return _tool_json({"error": "empty pipeline segment"})
        for segment in segments:
            verb = segment[0].lower()
            if not verb.startswith(_PS_EXAMINE_VERBS):
                return _tool_json(
                    {"error": f"verb '{segment[0]}' is not on the read-only whitelist"}
                )
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

    return [
        read_file,
        write_file,
        edit_file,
        glob,
        grep,
        git,
        run_powershell,
        delete_file,
        rename_file,
    ]
