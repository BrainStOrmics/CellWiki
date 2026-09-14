"""Load and match the workspace page extraction contract from ``schema.md``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from cellwiki.domain.page_schema import FieldRule, PageContract, WorkspacePageSchema

SCHEMA_FILE_NAME = "schema.md"
SCHEMA_FENCE = re.compile(
    r"```(?:yaml|yml)\s+cellwiki-schema\s*\r?\n(?P<body>.*?)\r?\n```",
    re.IGNORECASE | re.DOTALL,
)
PAGE_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
MAX_SCHEMA_CHARS = 1_000_000


class SchemaContractError(ValueError):
    """Raised when the workspace schema file or its contract block is invalid."""


def load_workspace_schema(root: Path) -> WorkspacePageSchema:
    """Parse the single authoritative ``yaml cellwiki-schema`` block."""

    schema_path = Path(root).resolve() / SCHEMA_FILE_NAME
    if not schema_path.is_file():
        raise SchemaContractError(f"{SCHEMA_FILE_NAME} is missing")
    text = schema_path.read_text(encoding="utf-8")
    if len(text) > MAX_SCHEMA_CHARS:
        raise SchemaContractError(f"{SCHEMA_FILE_NAME} exceeds {MAX_SCHEMA_CHARS} characters")
    matches = list(SCHEMA_FENCE.finditer(text))
    if not matches:
        raise SchemaContractError(
            "schema.md has no fenced `yaml cellwiki-schema` contract block"
        )
    if len(matches) > 1:
        raise SchemaContractError("schema.md must contain exactly one cellwiki-schema block")
    try:
        payload = yaml.safe_load(matches[0].group("body"))
    except yaml.YAMLError as error:
        raise SchemaContractError(f"schema contract is not valid YAML: {error}") from error
    if not isinstance(payload, dict):
        raise SchemaContractError("schema contract must be a YAML mapping")
    try:
        return WorkspacePageSchema.model_validate(payload)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        detail = str(first.get("msg", "invalid contract"))
        raise SchemaContractError(f"invalid schema contract at {location}: {detail}") from error


def _compiled_path(path_template: str) -> re.Pattern[str]:
    prefix, suffix = path_template.split("{id}", 1)
    return re.compile(
        rf"^{re.escape(prefix)}(?P<id>{PAGE_ID_PATTERN}){re.escape(suffix)}$"
    )


def matching_page_types(
    schema: WorkspacePageSchema,
    relative_path: str,
) -> list[tuple[str, PageContract, str]]:
    """Return every page type matching a workspace-relative POSIX path."""

    matches: list[tuple[str, PageContract, str]] = []
    normalized = relative_path.replace("\\", "/")
    for page_type, contract in schema.pages.items():
        matched = _compiled_path(contract.path).fullmatch(normalized)
        if matched is not None:
            matches.append((page_type, contract, matched.group("id")))
    return matches


def field_rule_error(rule: FieldRule, value: Any) -> str | None:
    """Return a human-readable mismatch for one frontmatter value, else None."""

    if value is None:
        if rule.nullable:
            return None
        return "must not be null"

    expected = rule.type
    valid_type = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "list": isinstance(value, list),
        "mapping": isinstance(value, dict),
    }[expected]
    if not valid_type:
        return f"must be {expected}"

    if rule.const is not None and value != rule.const:
        return f"must equal {rule.const!r}"
    if rule.enum is not None and value not in rule.enum:
        return f"must be one of {rule.enum!r}"
    if rule.pattern is not None and isinstance(value, str):
        if re.fullmatch(rule.pattern, value) is None:
            return f"must match pattern {rule.pattern!r}"
    if rule.min_length is not None and hasattr(value, "__len__"):
        if len(value) < rule.min_length:
            return f"must contain at least {rule.min_length} item(s)"
    return None


__all__ = [
    "PAGE_ID_PATTERN",
    "SCHEMA_FILE_NAME",
    "SchemaContractError",
    "field_rule_error",
    "load_workspace_schema",
    "matching_page_types",
]