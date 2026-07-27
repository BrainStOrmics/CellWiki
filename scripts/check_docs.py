"""Validate CellWiki documentation metadata and local links.

The checker deliberately validates only current documentation and indexes. Historical
research can reference external repositories or snapshots that are not part of this
workspace, so treating every historical link as a local release blocker is misleading.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_ROOTS = (ROOT / "docs", ROOT / "design")
ROOT_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
)
REQUIRED_FIELDS = {"title", "status", "type", "last_updated"}
ALLOWED_STATUSES = {
    "draft",
    "active",
    "accepted",
    "reference",
    "superseded",
    "archived",
    "generated",
}
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def markdown_documents() -> list[Path]:
    """Return every governed Markdown file, excluding generated build artifacts."""

    documents = [path for root in DOCUMENT_ROOTS for path in root.rglob("*.md")]
    return sorted(documents)


def current_link_documents() -> list[Path]:
    """Select current docs and indexes whose relative links must resolve locally."""

    documents = list((ROOT / "docs").rglob("*.md"))
    documents.extend(path for path in ROOT_DOCUMENTS if path.exists())
    documents.extend((ROOT / "design").glob("README.md"))
    documents.extend((ROOT / "design").glob("*/README.md"))
    return sorted(set(documents))


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Read YAML frontmatter without interpreting normal Markdown as YAML."""

    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    raw, separator, body = content[4:].partition("\n---\n")
    if not separator:
        raise ValueError("frontmatter closing delimiter is missing")
    metadata = yaml.safe_load(raw) or {}
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter must be a mapping")
    return metadata, body


def is_external_link(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "#"))


def resolve_link(path: Path, target: str) -> Path | None:
    """Resolve a local Markdown target while ignoring anchors and quoted paths."""

    target = target.strip().strip("<>").split("#", maxsplit=1)[0]
    if not target or is_external_link(target):
        return None
    return (path.parent / target).resolve()


def validate() -> list[str]:
    """Return every governance error so one run gives maintainers the full repair set."""

    errors: list[str] = []
    canonical_owners: dict[str, list[Path]] = defaultdict(list)
    for path in markdown_documents():
        relative = path.relative_to(ROOT)
        try:
            metadata, _ = parse_frontmatter(path)
        except ValueError as error:
            errors.append(f"{relative}: {error}")
            continue
        missing = REQUIRED_FIELDS - set(metadata)
        if missing:
            errors.append(f"{relative}: missing required fields: {', '.join(sorted(missing))}")
        status = metadata.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{relative}: unsupported status: {status!r}")
        if status == "superseded" and not metadata.get("superseded_by"):
            errors.append(f"{relative}: superseded documents require superseded_by")
        if status in {"active", "accepted"}:
            canonical_for = metadata.get("canonical_for", [])
            if not isinstance(canonical_for, list):
                errors.append(f"{relative}: canonical_for must be a list")
            else:
                for topic in canonical_for:
                    canonical_owners[str(topic)].append(path)

    for topic, owners in canonical_owners.items():
        if len(owners) > 1:
            names = ", ".join(str(path.relative_to(ROOT)) for path in owners)
            errors.append(f"canonical topic {topic!r} has multiple active owners: {names}")

    for path in current_link_documents():
        content = path.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(content):
            target = match.group(1)
            resolved = resolve_link(path, target)
            if resolved is not None and not resolved.exists():
                errors.append(
                    f"{path.relative_to(ROOT)}: broken local link {target!r}"
                )
    return errors


def main() -> None:
    errors = validate()
    if errors:
        print("documentation governance check failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        raise SystemExit(1)
    print(f"documentation governance check passed: {len(markdown_documents())} governed files")


if __name__ == "__main__":
    main()
