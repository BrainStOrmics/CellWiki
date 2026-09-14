"""Deterministic schema-driven lint for workspace Markdown pages."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from cellwiki.domain.linting import LintFinding, LintLevel, LintSeverity
from cellwiki.domain.page_schema import PageContract
from cellwiki.services.schema_contract import (
    SCHEMA_FILE_NAME,
    SchemaContractError,
    field_rule_error,
    load_workspace_schema,
    matching_page_types,
)


class ProjectionQualityError(RuntimeError):
    """Raised when a gating issue makes a wiki projection unsafe to publish."""


_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def inspect_projection(
    project_root: Path,
    *,
    changed_paths: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Inspect Markdown pages and return gating and advisory findings.

    ``changed_paths=None`` means the caller is linting the whole workspace and
    contract violations are errors. Runtime pre-diff checks pass the run's
    changed paths so unchanged historical pages remain advisory migration work.
    """

    root = Path(project_root).resolve()
    changed = (
        None
        if changed_paths is None
        else {
            str(path).replace("\\", "/").removeprefix("./")
            for path in changed_paths
            if str(path).strip()
        }
    )
    issues: list[dict[str, Any]] = []
    schema = None
    schema_status = "valid"
    schema_error: str | None = None
    try:
        schema = load_workspace_schema(root)
    except SchemaContractError as error:
        schema_status = "missing" if "is missing" in str(error) else "invalid"
        schema_error = str(error)

    wiki_root = root / "wiki"
    all_pages = sorted(wiki_root.rglob("*.md")) if wiki_root.is_dir() else []
    indexed_pages: dict[str, list[dict[str, Any]]] = {}
    page_count = 0

    records: list[tuple[Path, str, str, PageContract, str]] = []
    for path in all_pages:
        relative = path.relative_to(root).as_posix()
        matches = matching_page_types(schema, relative) if schema is not None else []
        if len(matches) > 1:
            page_changed = _page_changed(relative, changed)
            issues.append(
                _issue(
                    path,
                    "ambiguous_page_type",
                    "Page matches more than one schema page type.",
                    root=root,
                    level="L0" if page_changed else "L1",
                    category="schema",
                    severity="error" if page_changed else "warning",
                    target_id=path.stem,
                    locator=relative,
                )
            )
            continue
        if matches:
            page_type, contract, page_id = matches[0]
            records.append((path, relative, page_type, contract, page_id))
            indexed_pages.setdefault(page_id, []).append(
                {"path": relative, "page_type": page_type, "file": path}
            )
            page_count += 1
        else:
            indexed_pages.setdefault(path.stem, []).append(
                {"path": relative, "page_type": None, "file": path}
            )
            if len(path.relative_to(wiki_root).parts) >= 2:
                page_changed = _page_changed(relative, changed)
                detail = (
                    f"Page path does not match any schema page type: {relative}."
                    if schema is not None
                    else f"Page cannot be matched because {SCHEMA_FILE_NAME} is unavailable."
                )
                issues.append(
                    _issue(
                        path,
                        "unmatched_page",
                        detail,
                        root=root,
                        level="L0" if page_changed else "L1",
                        category="schema",
                        severity="error" if page_changed else "warning",
                        target_id=path.stem,
                        locator=relative,
                    )
                )

    if schema_error is not None:
        wiki_pages_exist = page_count > 0 or any(
            len(path.relative_to(wiki_root).parts) >= 2 for path in all_pages
        )
        schema_changed = changed is None or SCHEMA_FILE_NAME in changed
        changed_wiki = schema_changed or (
            any(
                _page_changed(path.relative_to(root).as_posix(), changed)
                for path in all_pages
                if len(path.relative_to(wiki_root).parts) >= 2
            )
            if changed is not None
            else wiki_pages_exist
        )
        schema_path = root / SCHEMA_FILE_NAME
        issues.append(
            _issue(
                schema_path,
                "invalid_schema" if schema_status == "invalid" else "missing_schema",
                schema_error,
                root=root,
                level="L0" if changed_wiki else "L1",
                category="schema",
                severity="error" if changed_wiki else "warning",
                target_id=SCHEMA_FILE_NAME,
                locator=SCHEMA_FILE_NAME,
            )
        )

    for path, relative, page_type, contract, page_id in records:
        page_changed = _page_changed(relative, changed)
        issues.extend(
            _inspect_page(
                path,
                relative,
                page_type,
                contract,
                page_id,
                root,
                page_changed=page_changed,
            )
        )

    for page_id, entries in indexed_pages.items():
        if len(entries) < 2:
            continue
        for entry in entries:
            relative = str(entry["path"])
            page_changed = _page_changed(relative, changed)
            issues.append(
                _issue(
                    Path(entry["file"]),
                    "duplicate_page_id",
                    f"Page id {page_id!r} is used by: {', '.join(item['path'] for item in entries)}.",
                    root=root,
                    level="L0" if page_changed else "L1",
                    category="identity",
                    severity="error" if page_changed else "warning",
                    target_id=page_id,
                    locator=relative,
                )
            )

    if schema is not None:
        for path, relative, page_type, contract, page_id in records:
            if not contract.links.check:
                continue
            page_changed = _page_changed(relative, changed)
            issues.extend(
                _broken_links(
                    path,
                    relative,
                    contract,
                    schema,
                    indexed_pages,
                    root,
                    page_changed=page_changed,
                )
            )

    error_count = sum(issue["severity"] == "error" for issue in issues)
    warning_count = sum(issue["severity"] == "warning" for issue in issues)
    status = "failed" if error_count else "passed_with_warnings" if warning_count else "passed"
    return {
        "status": status,
        "page_count": page_count,
        "issue_count": len(issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "schema": {
            "path": SCHEMA_FILE_NAME,
            "status": schema_status,
            "version": schema.schema_version if schema is not None else None,
        },
        "scope": {
            "changed_pages_only": changed is not None,
            "changed_path_count": len(changed or ()),
        },
        "levels": {
            "L0": {
                "status": "failed" if error_count else "passed",
                "issue_count": error_count,
                "description": "Gating path, structure, contract, and identity checks",
            },
            "L1": {
                "status": "warning" if warning_count else "passed",
                "issue_count": warning_count,
                "description": "Advisory migration, provenance, and link checks",
            },
            "L2": {
                "status": "not_run",
                "issue_count": 0,
                "description": "Semantic review is opt-in and never auto-fixes formal knowledge",
            },
        },
        "issues": issues,
    }


def verify_projection(project_root: Path) -> None:
    """Raise when a deterministic gating error makes a projection unsafe."""

    report = inspect_projection(project_root)
    gating_issues = [issue for issue in report["issues"] if issue["severity"] == "error"]
    if gating_issues:
        first = gating_issues[0]
        raise ProjectionQualityError(
            f"projection lint failed with {len(gating_issues)} gating issue(s): "
            f"{first['page_id']} {first['detail']}"
        )


def _page_changed(relative_path: str, changed: set[str] | None) -> bool:
    return True if changed is None else relative_path in changed


def _inspect_page(
    path: Path,
    relative: str,
    page_type: str,
    contract: PageContract,
    page_id: str,
    root: Path,
    *,
    page_changed: bool,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    level = "L0" if page_changed else "L1"
    severity = "error" if page_changed else "warning"
    raw = path.read_text(encoding="utf-8")
    frontmatter, body, frontmatter_error = _split_frontmatter(raw)
    if frontmatter_error:
        issues.append(
            _issue(
                path,
                "invalid_frontmatter",
                frontmatter_error,
                root=root,
                level=level,
                category="structure",
                severity=severity,
                target_id=page_id,
                locator=relative,
            )
        )
    if not body.strip():
        issues.append(
            _issue(
                path,
                "empty_page",
                "Published page has no body.",
                root=root,
                level=level,
                category="structure",
                severity=severity,
                target_id=page_id,
                locator=relative,
            )
        )
    if not any(line.startswith("# ") for line in body.splitlines()):
        issues.append(
            _issue(
                path,
                "missing_title",
                "Published page has no H1 title.",
                root=root,
                level=level,
                category="structure",
                severity=severity,
                target_id=page_id,
                locator=relative,
            )
        )

    for field_name, rule in contract.frontmatter.required.items():
        if field_name not in frontmatter:
            issues.append(
                _issue(
                    path,
                    "missing_required_field",
                    f"Page type {page_type!r} requires frontmatter field {field_name!r}.",
                    root=root,
                    level=level,
                    category="frontmatter",
                    severity=severity,
                    target_id=page_id,
                    locator=f"{relative}#field={field_name}",
                )
            )
            continue
        detail = field_rule_error(rule, frontmatter[field_name])
        if detail is not None:
            issues.append(
                _issue(
                    path,
                    "invalid_field_value",
                    f"Frontmatter field {field_name!r} {detail}.",
                    root=root,
                    level=level,
                    category="frontmatter",
                    severity=severity,
                    target_id=page_id,
                    locator=f"{relative}#field={field_name}",
                )
            )

    for field_name, rule in contract.frontmatter.optional.items():
        if field_name not in frontmatter:
            continue
        detail = field_rule_error(rule, frontmatter[field_name])
        if detail is not None:
            issues.append(
                _issue(
                    path,
                    "invalid_field_value",
                    f"Frontmatter field {field_name!r} {detail}.",
                    root=root,
                    level=level,
                    category="frontmatter",
                    severity=severity,
                    target_id=page_id,
                    locator=f"{relative}#field={field_name}",
                )
            )

    identity_value = frontmatter.get(contract.identity)
    if isinstance(identity_value, str) and identity_value != page_id:
        issues.append(
            _issue(
                path,
                "id_mismatch",
                f"Frontmatter {contract.identity!r} is {identity_value!r}; expected {page_id!r}.",
                root=root,
                level=level,
                category="identity",
                severity=severity,
                target_id=page_id,
                locator=f"{relative}#field={contract.identity}",
            )
        )

    headings = {
        match.group(1).strip() for match in _H2.finditer(body)
    }
    for section in contract.sections.required:
        if section not in headings:
            issues.append(
                _issue(
                    path,
                    "missing_required_section",
                    f"Page type {page_type!r} requires section {section!r}.",
                    root=root,
                    level=level,
                    category="structure",
                    severity=severity,
                    target_id=page_id,
                    locator=f"{relative}#section={section}",
                )
            )

    issues.extend(
        _reference_issues(
            path,
            relative,
            page_id,
            contract,
            frontmatter,
            root,
            level=level,
            severity=severity,
        )
    )
    return issues


def _reference_issues(
    path: Path,
    relative: str,
    page_id: str,
    contract: PageContract,
    frontmatter: dict[str, Any],
    root: Path,
    *,
    level: str,
    severity: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    references = frontmatter.get("references")
    if not references:
        if contract.references.required:
            issues.append(
                _issue(
                    path,
                    "missing_references",
                    "Page has no source references in frontmatter.",
                    root=root,
                    level=level,
                    category="provenance",
                    severity=severity,
                    target_id=page_id,
                    locator=f"{relative}#field=references",
                )
            )
        return issues
    if not isinstance(references, list):
        issues.append(
            _issue(
                path,
                "invalid_references",
                "Frontmatter references must be a list.",
                root=root,
                level=level,
                category="provenance",
                severity=severity,
                target_id=page_id,
                locator=f"{relative}#field=references",
            )
        )
        return issues

    identifiers: list[str] = []
    for reference in references:
        identifier = _reference_id(reference, contract.references.id_fields)
        if not identifier:
            issues.append(
                _issue(
                    path,
                    "invalid_reference",
                    "Reference has no usable source identifier.",
                    root=root,
                    level=level,
                    category="provenance",
                    severity=severity,
                    target_id=page_id,
                    locator=f"{relative}#field=references",
                )
            )
            continue
        identifiers.append(identifier)
        if contract.references.require_source:
            source_dir = root / contract.references.source_root / identifier
            if not source_dir.is_dir():
                issues.append(
                    _issue(
                        path,
                        "missing_reference_source",
                        f"Reference source {identifier!r} has no directory under "
                        f"{contract.references.source_root}/.",
                        root=root,
                        level=level,
                        category="provenance",
                        severity=severity,
                        target_id=page_id,
                        locator=f"{relative}#source={identifier}",
                    )
                )
    duplicates = sorted({value for value in identifiers if identifiers.count(value) > 1})
    for duplicate in duplicates:
        issues.append(
            _issue(
                path,
                "duplicate_references",
                f"Duplicate reference ID: {duplicate}.",
                root=root,
                level=level,
                category="provenance",
                severity=severity,
                target_id=page_id,
                locator=f"{relative}#source={duplicate}",
            )
        )
    return issues


def _broken_links(
    path: Path,
    relative: str,
    contract: PageContract,
    schema,
    indexed_pages: dict[str, list[dict[str, Any]]],
    root: Path,
    *,
    page_changed: bool,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    level = "L0" if page_changed else "L1"
    severity = "error" if page_changed else "warning"
    body = _split_frontmatter(path.read_text(encoding="utf-8"))[1]
    for line_number, line in enumerate(body.splitlines(), start=1):
        for target in _MARKDOWN_LINK.findall(line):
            normalized = target.strip().strip("<>").split("#", 1)[0]
            if not normalized.lower().endswith(".md"):
                continue
            if normalized.startswith(("http://", "https://", "/")):
                continue
            resolved = (path.parent / normalized).resolve()
            if not resolved.is_file():
                issues.append(
                    _issue(
                        path,
                        "broken_local_link",
                        f"Local Wiki link target does not exist: {normalized}.",
                        root=root,
                        level=level,
                        category="links",
                        severity=severity,
                        line=line_number,
                        locator=f"{relative}:{line_number}",
                    )
                )
                continue
            target_type = _page_type_for_path(schema, resolved, root)
            if contract.links.targets and target_type not in contract.links.targets:
                issues.append(
                    _issue(
                        path,
                        "invalid_link_target_type",
                        f"Link target {normalized!r} has type {target_type!r}; "
                        f"allowed targets are {contract.links.targets!r}.",
                        root=root,
                        level=level,
                        category="links",
                        severity=severity,
                        line=line_number,
                        locator=f"{relative}:{line_number}",
                    )
                )
        for wikilink in _WIKILINK.findall(line):
            target = wikilink.split("|", 1)[0].split("#", 1)[0].strip()
            if not target:
                continue
            key = Path(target).stem if target.lower().endswith(".md") else target.split("/")[-1]
            entries = indexed_pages.get(key, [])
            if len(entries) != 1:
                issues.append(
                    _issue(
                        path,
                        "broken_wikilink",
                        f"Wikilink target is missing or ambiguous: {target!r}.",
                        root=root,
                        level=level,
                        category="links",
                        severity=severity,
                        line=line_number,
                        locator=f"{relative}:{line_number}",
                    )
                )
                continue
            target_type = entries[0].get("page_type")
            if contract.links.targets and target_type not in contract.links.targets:
                issues.append(
                    _issue(
                        path,
                        "invalid_link_target_type",
                        f"Wikilink target {target!r} has type {target_type!r}; "
                        f"allowed targets are {contract.links.targets!r}.",
                        root=root,
                        level=level,
                        category="links",
                        severity=severity,
                        line=line_number,
                        locator=f"{relative}:{line_number}",
                    )
                )
    return issues


def _page_type_for_path(schema, path: Path, root: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None
    matches = matching_page_types(schema, relative)
    return matches[0][0] if len(matches) == 1 else None


def _reference_id(reference: Any, id_fields: list[str]) -> str | None:
    if isinstance(reference, str):
        return reference or None
    if isinstance(reference, dict):
        for field_name in id_fields:
            value = reference.get(field_name)
            if value not in (None, ""):
                return str(value)
    return None


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str, str | None]:
    if not raw.startswith("---"):
        return {}, raw, "Page is missing YAML frontmatter."
    parts = raw.split("---", 2)
    if len(parts) != 3:
        return {}, raw, "YAML frontmatter is not closed with ---."
    try:
        parsed = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as error:
        return {}, parts[2].lstrip("\r\n"), f"Invalid YAML frontmatter: {error}"
    if not isinstance(parsed, dict):
        return {}, parts[2].lstrip("\r\n"), "YAML frontmatter must be a mapping."
    return parsed, parts[2].lstrip("\r\n"), None


def _issue(
    path: Path,
    issue_type: str,
    detail: str,
    *,
    root: Path,
    level: str,
    category: str,
    severity: str,
    auto_fixable: bool = False,
    line: int | None = None,
    target_id: str | None = None,
    locator: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target = target_id or path.stem
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.as_posix()
    resolved_locator = locator or relative + (f":{line}" if line else "")
    lint_level = LintLevel(level)
    lint_severity = LintSeverity(severity)
    suggested_operation = (
        {
            "type": "apply_lint_fix",
            "target_id": path.stem,
            "payload": {
                "action": "rebuild_projection",
                "finding_type": issue_type,
            },
        }
        if auto_fixable
        else None
    )
    finding = LintFinding(
        finding_id=LintFinding.stable_id(
            level=lint_level,
            category=f"{category}:{issue_type}",
            target_id=target,
            locator=resolved_locator,
        ),
        level=lint_level,
        severity=lint_severity,
        category=category,
        target_id=target,
        locator=resolved_locator,
        message=detail,
        evidence=evidence or [],
        blocking=lint_severity == LintSeverity.ERROR,
        auto_fixable=auto_fixable,
        suggested_operation=suggested_operation,
    )
    payload = finding.model_dump(mode="json")
    payload.update(
        {
            "page_id": path.stem,
            "type": issue_type,
            "detail": detail,
            "page_path": relative,
        }
    )
    return payload


__all__ = ["ProjectionQualityError", "inspect_projection", "verify_projection"]