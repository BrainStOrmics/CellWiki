"""Synchronize generated frontend and Tauri versions from the root VERSION file."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def expected_version() -> str:
    value = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("VERSION must use x.y.z format")
    return value


def synchronize(*, check: bool) -> list[str]:
    version = expected_version()
    changed: list[str] = []
    for relative in ("frontend/package.json", "frontend/src-tauri/tauri.conf.json"):
        path = ROOT / relative
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != version:
            changed.append(relative)
            if not check:
                payload["version"] = version
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cargo = ROOT / "frontend" / "src-tauri" / "Cargo.toml"
    text = cargo.read_text(encoding="utf-8")
    current = re.search(r"(?m)^version = \"([^\"]+)\"", text)
    if not current or current.group(1) != version:
        changed.append("frontend/src-tauri/Cargo.toml")
        if not check:
            text = re.sub(r"(?m)^version = \"[^\"]+\"", f'version = "{version}"', text, count=1)
            cargo.write_text(text, encoding="utf-8")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed = synchronize(check=args.check)
    if args.check and changed:
        raise SystemExit("version drift: " + ", ".join(changed))
    print("versions synchronized" if changed else "versions already synchronized")


if __name__ == "__main__":
    main()

