"""Generate reproducible evidence for one Windows installer build.

The manifest is intentionally generated outside version control. It binds a concrete
installer to the repository revision and working-tree state that produced it, avoiding
stale hashes copied into README files or release runbooks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def version() -> str:
    """Read the single project version source."""

    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def git_output(*arguments: str) -> str:
    """Read Git evidence without making a release build depend on shell state."""

    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def sha256(path: Path) -> str:
    """Hash large installers incrementally instead of loading them into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def default_installer() -> Path:
    """Find the versioned NSIS artifact while rejecting ambiguous output folders."""

    candidates = sorted(
        (ROOT / "frontend" / "src-tauri" / "target" / "release" / "bundle" / "nsis").glob(
            f"*{version()}*setup.exe"
        )
    )
    if len(candidates) != 1:
        raise ValueError(
            "expected exactly one versioned NSIS installer; pass --installer explicitly"
        )
    return candidates[0]


def build_manifest(installer: Path, *, signed: bool) -> dict[str, object]:
    """Create the portable evidence record consumed by release review and support."""

    path = installer.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"installer does not exist: {path}")
    try:
        relative_installer = path.relative_to(ROOT).as_posix()
    except ValueError:
        relative_installer = str(path)
    dirty = git_output("status", "--porcelain")
    return {
        "schema_version": 1,
        "version": version(),
        "built_at": datetime.now(UTC).isoformat(),
        "git_commit": git_output("rev-parse", "HEAD"),
        "git_dirty": dirty != "",
        "installer": {
            "path": relative_installer,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "signed": signed,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, default=None)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "build" / "release-manifest.json"
    )
    parser.add_argument("--signed", action="store_true")
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="fail instead of recording a dirty Git working tree",
    )
    arguments = parser.parse_args()
    installer = arguments.installer or default_installer()
    manifest = build_manifest(installer, signed=arguments.signed)
    if arguments.require_clean and manifest["git_dirty"]:
        raise SystemExit("refusing release manifest from dirty working tree")
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(output)


if __name__ == "__main__":
    main()
