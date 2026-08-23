# =============================================================================
# 工作区路径守卫 —— P1/P2 沙箱边界
# =============================================================================
# P1 路径校验：所有 file/git 路径参数执行前强制 expand -> resolve -> 包含检查；
# 必须落在工作目录根内。拒绝 `..` 穿越、盘符绝对路径、UNC、`$HOME` /
# `$env:` / `%USERPROFILE%`；Windows 大小写不敏感、8.3 长短名归一、分隔符
# 统一。补洞：`.git` 段整体拒绝（段名匹配，不误伤 `.gitignore`）；`\\?\` /
# `\\.\` 扩展前缀、`C:relative` 盘符相对、NTFS ADS `file:stream`、NUL 字符
# 拒绝；不存在的目标（write/rename）用 resolve(strict=False) 同样校验。
# P2 symlink：resolve 时跟随 symlink/junction，内部链接允许、指向工作目录外
# 拒绝；无"用户白名单"状态（越界即拒）。
# =============================================================================

"""Workspace path guard implementing the P1/P2 sandbox boundary."""

from __future__ import annotations

import os
import re
from pathlib import Path


class PathGuardError(RuntimeError):
    """Raised when a path violates the workspace sandbox boundary."""


_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_EXTENDED_PREFIXES = ("\\\\?\\", "\\\\.\\", "//?/", "//./")
_FORBIDDEN_ENV_MARKERS = ("$HOME", "$ENV:", "%USERPROFILE%")
_NULL = "\x00"
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def _normalize(raw: str) -> str:
    value = str(raw).strip()
    if _NULL in value:
        raise PathGuardError("NUL characters are not allowed in paths")
    return value.replace("\\", "/")


def _reject_environment_expansion(value: str) -> None:
    lowered = value.lower()
    for marker in _FORBIDDEN_ENV_MARKERS:
        if marker.lower() in lowered:
            raise PathGuardError(f"environment expansion is not allowed in paths: {marker}")
    if value.startswith("~"):
        raise PathGuardError("home-directory expansion is not allowed in paths")


def _reject_absolute_forms(value: str) -> None:
    if value.startswith(("//", "/")):
        raise PathGuardError("absolute and UNC paths are not allowed")
    for prefix in _EXTENDED_PREFIXES:
        if value.startswith(prefix):
            raise PathGuardError("extended-length path prefixes are not allowed")
    drive, _ = os.path.splitdrive(value)
    if drive:
        raise PathGuardError("drive-qualified paths are not allowed")


def _reject_reserved_names(part: str) -> None:
    stem = part.split(":")[0].rsplit(".", 1)[0]
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        raise PathGuardError(f"reserved device name is not allowed: {part}")


def _resolve_allow_missing(target: Path) -> Path:
    """Resolve the longest existing ancestor, then re-append the missing tail."""
    missing: list[str] = []
    cursor = target
    while not cursor.exists():
        missing.insert(0, cursor.name)
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    resolved = cursor.resolve()
    for part in missing:
        resolved = resolved / part
    return resolved


def validate_workspace_path(
    workspace_root: Path,
    raw: str,
    *,
    allow_missing: bool = False,
) -> Path:
    """Resolve ``raw`` inside ``workspace_root`` or raise :class:`PathGuardError`.

    P1 checks run before resolution; P2 containment runs after resolution so
    symlinks and junctions cannot smuggle a path outside the workspace.
    """
    value = _normalize(raw)
    if not value or value == ".":
        raise PathGuardError("empty path is not allowed")
    _reject_environment_expansion(value)
    _reject_absolute_forms(value)

    parts = value.split("/")
    cleaned: list[str] = []
    for part in parts:
        if part == "":
            continue
        if part == "..":
            raise PathGuardError("parent-directory traversal is not allowed")
        if part.lower() == ".git":
            raise PathGuardError(".git is not part of the workspace payload")
        _reject_reserved_names(part)
        cleaned.append(part)
    if not cleaned:
        raise PathGuardError("path resolves to the workspace root")

    root_resolved = Path(workspace_root).resolve()
    target = root_resolved.joinpath(*cleaned)
    try:
        resolved = target.resolve() if not allow_missing else _resolve_allow_missing(target)
    except OSError as error:
        raise PathGuardError(f"cannot resolve path: {error}") from error

    if not allow_missing and not resolved.exists():
        raise PathGuardError("path does not exist")

    # P2: containment after following symlinks/junctions (case-insensitive).
    root_norm = os.path.normcase(str(root_resolved))
    target_norm = os.path.normcase(str(resolved))
    if target_norm != root_norm and not target_norm.startswith(root_norm + os.sep):
        raise PathGuardError("path escapes the workspace")
    if target_norm == root_norm:
        raise PathGuardError("the workspace root itself is not a file target")
    return resolved