# =============================================================================
# 路径守卫契约测试 —— P1/P2 沙箱边界
# =============================================================================

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from cellwiki.services.path_guard import PathGuardError, validate_workspace_path


def _root(tmp_path: Path) -> Path:
    inner = tmp_path / "workspace"
    inner.mkdir(parents=True, exist_ok=True)
    (inner / "wiki").mkdir(exist_ok=True)
    (inner / "wiki" / "a.md").write_text("# a\n", encoding="utf-8")
    return inner


def test_accepts_relative_paths_inside_workspace(tmp_path: Path):
    root = _root(tmp_path)
    resolved = validate_workspace_path(root, "wiki/a.md")
    assert resolved == (root / "wiki" / "a.md").resolve()


def test_rejects_parent_traversal(tmp_path: Path):
    root = _root(tmp_path)
    for candidate in ("../secret.txt", "wiki/../../secret.txt", "..", "a/../.."):
        with pytest.raises(PathGuardError):
            validate_workspace_path(root, candidate)


def test_rejects_absolute_drive_unc_and_extended_paths(tmp_path: Path):
    root = _root(tmp_path)
    for candidate in (
        "C:\\Windows\\win.ini",
        "C:/Windows/win.ini",
        "/etc/passwd",
        "\\\\server\\share\\x",
        "//server/share/x",
        "\\\\?\\C:\\Windows",
        "C:relative\\file",
    ):
        with pytest.raises(PathGuardError):
            validate_workspace_path(root, candidate)


def test_rejects_environment_and_home_expansion(tmp_path: Path):
    root = _root(tmp_path)
    for candidate in ("$HOME/.ssh/id_rsa", "$env:USERPROFILE\\x", "%USERPROFILE%\\x", "~/x", "sub/%Temp%/x"):
        with pytest.raises(PathGuardError):
            validate_workspace_path(root, candidate)


def test_rejects_git_segment_but_allows_gitignore(tmp_path: Path):
    root = _root(tmp_path)
    with pytest.raises(PathGuardError):
        validate_workspace_path(root, "wiki/.git/config")
    with pytest.raises(PathGuardError):
        validate_workspace_path(root, ".git/HEAD")
    # .gitignore 是工作区有效文件（段名不同，不误伤）
    (root / "wiki" / ".gitignore").write_text("", encoding="utf-8")
    resolved = validate_workspace_path(root, "wiki/.gitignore")
    assert resolved.name == ".gitignore"


def test_rejects_nul_and_reserved_device_names(tmp_path: Path):
    root = _root(tmp_path)
    with pytest.raises(PathGuardError):
        validate_workspace_path(root, "wiki/a\x00b.md")
    with pytest.raises(PathGuardError):
        validate_workspace_path(root, "wiki/CON")


def test_missing_targets_allowed_only_with_allow_missing(tmp_path: Path):
    root = _root(tmp_path)
    with pytest.raises(PathGuardError):
        validate_workspace_path(root, "wiki/new/untracked.md")
    resolved = validate_workspace_path(root, "wiki/new/untracked.md", allow_missing=True)
    assert resolved == (root / "wiki" / "new" / "untracked.md").resolve()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction escape is platform-specific")
def test_windows_junction_below_root_is_rejected(tmp_path: Path):
    root = _root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    junction = root / "wiki" / "linked"
    try:
        os.symlink(outside, junction, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create directory junction/symlink")
    with pytest.raises(PathGuardError):
        validate_workspace_path(root, "wiki/linked/secret.txt")