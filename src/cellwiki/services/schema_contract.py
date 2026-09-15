"""Load and match the workspace page extraction contract from ``schema.md``."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from cellwiki.domain.page_schema import (
    FieldRule,
    PageContract,
    PageTemplate,
    SectionRule,
    WorkspacePageSchema,
)

SCHEMA_FILE_NAME = "schema.md"
SCHEMA_FENCE = re.compile(
    r"```(?:yaml|yml)\s+cellwiki-schema\s*\r?\n(?P<body>.*?)\r?\n```",
    re.IGNORECASE | re.DOTALL,
)
TEMPLATE_FENCE = re.compile(
    r"```markdown\s+cellwiki-template\s+(?P<page_type>[A-Za-z0-9_-]+)\s*\r?\n"
    r"(?P<body>.*?)\r?\n```",
    re.IGNORECASE | re.DOTALL,
)
PAGE_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
MAX_SCHEMA_CHARS = 1_000_000
_COMMENT_START = "<!-- cellwiki"
_COMMENT_END = "-->"
_HEADING_H1 = re.compile(r"^#\s+(.+?)\s*$")
_HEADING_H2 = re.compile(r"^##\s+(.+?)\s*$")


class SchemaContractError(ValueError):
    """Raised when the workspace schema file or its contract block is invalid."""


def _comment_payload(lines: list[str]) -> dict[str, Any]:
    body = "\n".join(lines).strip()
    if not body:
        return {}
    try:
        payload = yaml.safe_load(body)
    except yaml.YAMLError as error:
        raise SchemaContractError(f"template directive is not valid YAML: {error}") from error
    if not isinstance(payload, dict):
        raise SchemaContractError("template directive must be a YAML mapping")
    return payload


def _parse_template(page_type: str, body: str) -> PageTemplate:
    lines = body.splitlines()
    sections: list[SectionRule] = []
    page_payload: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    in_comment = False
    buffer: list[str] = []

    for line in lines:
        stripped = line.strip()
        if in_comment:
            if stripped == _COMMENT_END:
                pending = _comment_payload(buffer)
                buffer = []
                in_comment = False
            else:
                buffer.append(line)
            continue
        if stripped == _COMMENT_START:
            if pending is not None:
                raise SchemaContractError("template directives must directly precede a heading")
            buffer = []
            in_comment = True
            continue
        h1 = _HEADING_H1.match(line)
        if h1 is not None:
            if page_payload is not None:
                raise SchemaContractError(f"template {page_type!r} contains more than one H1")
            if pending is None:
                raise SchemaContractError(f"template {page_type!r} H1 is missing its directive")
            page_payload = pending
            pending = None
            continue
        h2 = _HEADING_H2.match(line)
        if h2 is not None:
            if pending is None:
                raise SchemaContractError(
                    f"template {page_type!r} section {h2.group(1)!r} is missing its directive"
                )
            payload = {"name": h2.group(1).strip(), **pending}
            try:
                sections.append(SectionRule.model_validate(payload))
            except ValidationError as error:
                first = error.errors()[0]
                location = ".".join(str(part) for part in first.get("loc", ()))
                raise SchemaContractError(
                    f"invalid template section {h2.group(1)!r} at {location}: {first.get('msg')}"
                ) from error
            pending = None
    if in_comment:
        raise SchemaContractError(f"template {page_type!r} has an unterminated directive")
    if pending is not None:
        raise SchemaContractError(f"template {page_type!r} has a directive without a heading")
    if page_payload is None:
        raise SchemaContractError(f"template {page_type!r} has no H1 directive")
    page_payload.setdefault("title_field", "")
    page_payload["page_type"] = page_type
    try:
        return PageTemplate.model_validate(page_payload | {"sections": sections})
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        raise SchemaContractError(
            f"invalid template {page_type!r} at {location}: {first.get('msg')}"
        ) from error


def load_workspace_schema(root: Path) -> WorkspacePageSchema:
    """Parse the single YAML contract plus one Markdown template per page type."""

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
    if payload.get("schema_version") == 1:
        raise SchemaContractError(
            "schema_version 1 is no longer supported; migrate schema.md to schema_version 2"
        )
    pages_payload = payload.get("pages")
    if not isinstance(pages_payload, dict):
        raise SchemaContractError("schema contract pages must be a mapping")

    page_contracts: dict[str, PageContract] = {}
    for page_type, page_payload in pages_payload.items():
        if not isinstance(page_payload, dict):
            raise SchemaContractError(f"page contract {page_type!r} must be a mapping")
        try:
            page_contracts[str(page_type)] = PageContract.model_validate(page_payload)
        except ValidationError as error:
            first = error.errors()[0]
            location = ".".join(str(part) for part in first.get("loc", ()))
            raise SchemaContractError(
                f"invalid page contract {page_type!r} at {location}: {first.get('msg')}"
            ) from error

    templates: dict[str, PageTemplate] = {}
    for match in TEMPLATE_FENCE.finditer(text):
        page_type = match.group("page_type")
        if page_type in templates:
            raise SchemaContractError(f"schema.md contains duplicate template {page_type!r}")
        templates[page_type] = _parse_template(page_type, match.group("body"))
    if set(templates) != set(page_contracts):
        missing = sorted(set(page_contracts) - set(templates))
        extra = sorted(set(templates) - set(page_contracts))
        raise SchemaContractError(
            f"schema templates must match page types exactly; missing={missing}, extra={extra}"
        )

    attached: dict[str, PageContract] = {}
    for page_type, page in page_contracts.items():
        attached[page_type] = page.model_copy(update={"template": templates[page_type]})
    try:
        return WorkspacePageSchema.model_validate(
            {"schema_version": payload.get("schema_version"), "pages": attached}
        )
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        raise SchemaContractError(
            f"invalid schema contract at {location}: {first.get('msg')}"
        ) from error


def workspace_schema_hash(root: Path) -> str:
    """Return a deterministic hash of the parsed v2 contract and templates."""

    schema = load_workspace_schema(root)
    canonical = json.dumps(
        schema.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def source_ids_from_frontmatter(page: PageContract, frontmatter: dict[str, Any]) -> list[str]:
    """Extract declared source identifiers using the page's source field contract."""

    raw = frontmatter.get(page.source_field)
    if not isinstance(raw, list):
        return []
    identifiers: list[str] = []
    for item in raw:
        if page.source_id_field:
            if isinstance(item, dict):
                value = item.get(page.source_id_field)
                if isinstance(value, str) and value.strip():
                    identifiers.append(value.strip())
        elif isinstance(item, str) and item.strip():
            identifiers.append(item.strip())
    return identifiers


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
    "source_ids_from_frontmatter",
    "workspace_schema_hash",
]
