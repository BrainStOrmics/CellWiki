"""Build the Python Product API as a target-named Tauri external binary."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "sidecar_entry.py"
DIST = ROOT / "build" / "sidecar-dist"
WORK = ROOT / "build" / "sidecar-work"
BINARY_DIR = ROOT / "frontend" / "src-tauri" / "binaries"


def target_triple() -> str:
    result = subprocess.run(
        ["rustc", "--print", "host-tuple"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> None:
    try:
        import PyInstaller.__main__
    except ImportError as error:
        raise SystemExit("Install the desktop extra before building: uv sync --extra desktop") from error

    for directory in (DIST, WORK):
        if directory.exists():
            shutil.rmtree(directory)
    BINARY_DIR.mkdir(parents=True, exist_ok=True)
    PyInstaller.__main__.run(
        [
            str(ENTRY),
            "--name",
            "cellwiki-sidecar",
            "--onefile",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(WORK),
            "--specpath",
            str(ROOT / "build"),
            "--collect-all",
            "cellwiki",
            "--collect-all",
            "deepagents",
            "--collect-all",
            "langgraph",
            "--copy-metadata",
            "cellwiki",
            # Development-only test frameworks must not inflate the installed binary.
            "--exclude-module",
            "pytest",
            "--exclude-module",
            "mypy",
            "--exclude-module",
            "ruff",
        ]
    )
    extension = ".exe" if sys.platform == "win32" else ""
    built = DIST / f"cellwiki-sidecar{extension}"
    target = BINARY_DIR / f"cellwiki-sidecar-{target_triple()}{extension}"
    shutil.copy2(built, target)
    print(target)


if __name__ == "__main__":
    main()
