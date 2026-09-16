"""Deterministic template-driven lint for workspace Markdown pages."""

from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from markdown_it import MarkdownIt

from cellwiki.domain.linting import LintFinding, LintLevel, LintSeverity
from cellwiki.domain.page_schema import ColumnRule, PageContract, SectionRule
from cellwiki.services.schema_contract import (
    SCHEMA_FILE_NAME,
    SchemaContractError,
    field_rule_error,
    load_workspace_schema,
    matching_page_types,
    source_ids_from_frontmatter,
)


class ProjectionQualityError(RuntimeError):
    """Raised when a gating issue makes a wiki projection unsafe to publish."""


class _StrictFrontmatterLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of last-wins."""

    def construct_mapping(self, node: Any, deep: bool = False) -> Any:
        keys = [key_node.value for key_node, _value in node.value]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate mapping keys: {duplicates}", node.start_mark
            )
        return super().construct_mapping(node, deep=deep)


_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
_WIKILINK_FULL = re.compile(r"^\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]$")
_SOURCE_LINK = re.compile(r"\[([^\]]+)\]\(#references\)")
_EVIDENCE_TIER = re.compile(r"^Tier ([1-5])$")
_EVIDENCE_LINE = re.compile(r"^\*{0,2}Evidence:?\*{0,2}\s*Tier\s*([1-5])$", re.IGNORECASE)
_SOURCE_LINE = re.compile(r"^\*{0,2}Source:?\*{0,2}\s*(.+)$", re.IGNORECASE)
_TABLE_DIVIDER = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$")
_HEADING_H1 = re.compile(r"^#\s+(.+?)\s*$")
_HEADING_H2 = re.compile(r"^##\s+(.+?)\s*$")
_HEADING_H3 = re.compile(r"^###\s+(.+?)\s*$")
_BULLET = re.compile(r"^(?:[-*]|\d+\.)\s+(.+?)\s*$")
_MD = MarkdownIt("gfm-like", {"linkify": False})


def _strip_list_marker(text: str) -> str:
    """Return a bullet or ordered-list line without its leading marker."""

    stripped = text.strip()
    match = _BULLET.match(stripped)
    return match.group(1) if match else stripped


@lru_cache(maxsize=None)
def _term_pattern(term: str) -> re.Pattern[str]:
    """Word-bounded, casefolded term matcher for free-prose scans."""

    return re.compile(rf"(?<![0-9a-z]){re.escape(term)}(?![0-9a-z])")


def inspect_projection(
    project_root: Path,
    *,
    changed_paths: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Inspect changed Markdown pages against the workspace template contract."""

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
        issues.append(
            _issue(
                root / SCHEMA_FILE_NAME,
                "invalid_schema" if schema_status == "invalid" else "missing_schema",
                schema_error,
                root=root,
                level="L0",
                category="schema",
                severity="error",
                target_id=SCHEMA_FILE_NAME,
                locator=SCHEMA_FILE_NAME,
            )
        )

    wiki_root = root / "wiki"
    all_pages = sorted(wiki_root.rglob("*.md")) if wiki_root.is_dir() else []
    page_count = 0
    if schema is not None and changed is not None:
        index, terms = _index_pages(root, schema, all_pages)
        page_count = len(index)
        for page_id, entries in index.items():
            if len(entries) < 2 or not any(_page_changed(entry["path"], changed) for entry in entries):
                continue
            for entry in entries:
                issues.append(
                    _issue(
                        Path(entry["file"]),
                        "duplicate_page_id",
                        f"Page id {page_id!r} is used by multiple pages.",
                        root=root,
                        level="L0",
                        category="identity",
                        severity="error",
                        target_id=page_id,
                        locator=str(entry["path"]),
                    )
                )
        for path in all_pages:
            relative = path.relative_to(root).as_posix()
            if not _page_changed(relative, changed):
                continue
            matches = matching_page_types(schema, relative)
            if len(matches) > 1:
                issues.append(
                    _issue(
                        path,
                        "ambiguous_page_type",
                        "Page matches more than one schema page type.",
                        root=root,
                        level="L0",
                        category="schema",
                        severity="error",
                        target_id=path.stem,
                        locator=relative,
                    )
                )
                continue
            if not matches:
                if len(path.relative_to(wiki_root).parts) >= 2:
                    issues.append(
                        _issue(
                            path,
                            "unmatched_page",
                            f"Page path does not match any schema page type: {relative}.",
                            root=root,
                            level="L0",
                            category="schema",
                            severity="error",
                            target_id=path.stem,
                            locator=relative,
                        )
                    )
                continue
            page_type, contract, page_id = matches[0]
            issues.extend(
                _inspect_page(
                    path, relative, page_type, contract, page_id, root, index, terms
                )
            )
    return _report(issues, page_count=page_count, schema=schema, schema_status=schema_status, changed=changed)


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


def _report(
    issues: list[dict[str, Any]],
    *,
    page_count: int,
    schema: Any,
    schema_status: str,
    changed: set[str] | None,
) -> dict[str, Any]:
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
            "legacy_pages_ignored": changed is None,
        },
        "levels": {
            "L0": {
                "status": "failed" if error_count else "passed",
                "issue_count": error_count,
                "description": "Gating template, evidence, source, and identity checks",
            },
            "L1": {
                "status": "warning" if warning_count else "passed",
                "issue_count": warning_count,
                "description": "Advisory free-prose wikilink checks",
            },
            "L2": {
                "status": "not_run",
                "issue_count": 0,
                "description": "Semantic review is opt-in and never auto-fixes formal knowledge",
            },
        },
        "issues": issues,
    }


def _page_changed(relative_path: str, changed: set[str] | None) -> bool:
    return True if changed is None else relative_path in changed


def _index_pages(
    root: Path,
    schema: Any,
    all_pages: list[Path],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[tuple[str, str]]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    terms: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path in all_pages:
        relative = path.relative_to(root).as_posix()
        matches = matching_page_types(schema, relative)
        page_type = matches[0][0] if len(matches) == 1 else None
        page_id = matches[0][2] if len(matches) == 1 else path.stem
        index[page_id].append({"path": relative, "page_type": page_type, "file": path})
        terms[page_id.casefold()].append((page_id, page_type or ""))
        for term in _frontmatter_terms(path):
            terms[term.casefold()].append((page_id, page_type or ""))
    return index, terms


def _frontmatter_terms(path: Path) -> list[str]:
    frontmatter, _body, error = _split_frontmatter(path.read_text(encoding="utf-8"))
    if error:
        return []
    values: list[str] = []
    for key in ("display_name", "standard_name", "gene_symbol", "gene_name", "name", "title"):
        value = frontmatter.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    aliases = frontmatter.get("aliases")
    if isinstance(aliases, list):
        values.extend(str(alias).strip() for alias in aliases if str(alias).strip())
    return values

def _inspect_page(
    path: Path,
    relative: str,
    page_type: str,
    contract: PageContract,
    page_id: str,
    root: Path,
    index: dict[str, list[dict[str, Any]]],
    terms: dict[str, list[tuple[str, str]]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    raw = path.read_text(encoding="utf-8")
    frontmatter, body, frontmatter_error = _split_frontmatter(raw)
    if frontmatter_error:
        issues.append(
            _issue(
                path,
                "invalid_frontmatter",
                frontmatter_error,
                root=root,
                level="L0",
                category="structure",
                severity="error",
                target_id=page_id,
                locator=relative,
            )
        )
        # Unparseable frontmatter cascades into every downstream rule; the
        # parse error alone is the actionable root cause.
        return issues
    if not body.strip():
        issues.append(
            _issue(
                path,
                "empty_page",
                "Published page has no body.",
                root=root,
                level="L0",
                category="structure",
                severity="error",
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
                    level="L0",
                    category="frontmatter",
                    severity="error",
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
                    level="L0",
                    category="frontmatter",
                    severity="error",
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
                    level="L0",
                    category="frontmatter",
                    severity="error",
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
                level="L0",
                category="identity",
                severity="error",
                target_id=page_id,
                locator=f"{relative}#field={contract.identity}",
            )
        )

    template = contract.template
    if template is None:
        issues.append(
            _issue(
                path,
                "missing_template",
                f"Page type {page_type!r} has no Markdown template.",
                root=root,
                level="L0",
                category="schema",
                severity="error",
                target_id=page_id,
                locator=relative,
            )
        )
        return issues

    title_value = frontmatter.get(template.title_field)
    h1 = next(iter(_h1_titles(body)), None)
    if h1 is None:
        issues.append(
            _issue(
                path,
                "missing_title",
                "Published page has no H1 title.",
                root=root,
                level="L0",
                category="structure",
                severity="error",
                target_id=page_id,
                locator=relative,
            )
        )
    elif isinstance(title_value, str) and h1 != title_value:
        issues.append(
            _issue(
                path,
                "title_mismatch",
                f"H1 {h1!r} does not match {template.title_field!r} value {title_value!r}.",
                root=root,
                level="L0",
                category="structure",
                severity="error",
                target_id=page_id,
                locator=relative,
            )
        )

    source_ids = source_ids_from_frontmatter(contract, frontmatter)
    duplicates = sorted({source for source in source_ids if source_ids.count(source) > 1})
    if duplicates:
        issues.append(
            _issue(
                path,
                "duplicate_references",
                f"Duplicate source IDs: {duplicates}.",
                root=root,
                level="L0",
                category="provenance",
                severity="error",
                target_id=page_id,
                locator=f"{relative}#field={contract.source_field}",
            )
        )
    source_count = frontmatter.get("source_count")
    if isinstance(source_count, int) and source_count != len(set(source_ids)):
        issues.append(
            _issue(
                path,
                "source_count_mismatch",
                f"source_count is {source_count}; declared sources are {len(set(source_ids))}.",
                root=root,
                level="L0",
                category="provenance",
                severity="error",
                target_id=page_id,
                locator=f"{relative}#field=source_count",
            )
        )

    headings = _headings(body)
    actual_names = [name for name, _start, _end in headings]
    template_names = [section.name for section in template.sections]
    unknown = [name for name in actual_names if name not in template_names]
    if unknown:
        issues.append(
            _issue(
                path,
                "unknown_section",
                f"Page contains sections not declared by the template: {unknown}.",
                root=root,
                level="L0",
                category="structure",
                severity="error",
                target_id=page_id,
                locator=relative,
            )
        )
    duplicates = sorted({name for name in actual_names if actual_names.count(name) > 1})
    if duplicates:
        issues.append(
            _issue(
                path,
                "duplicate_section",
                f"Page contains duplicate sections: {duplicates}.",
                root=root,
                level="L0",
                category="structure",
                severity="error",
                target_id=page_id,
                locator=relative,
            )
        )
    required_missing = [
        section.name
        for section in template.sections
        if section.required and section.name not in actual_names
    ]
    if required_missing:
        issues.append(
            _issue(
                path,
                "missing_required_section",
                f"Missing required sections: {required_missing}.",
                root=root,
                level="L0",
                category="structure",
                severity="error",
                target_id=page_id,
                locator=relative,
            )
        )
    if template.required_any and not any(name in actual_names for name in template.required_any):
        issues.append(
            _issue(
                path,
                "missing_required_any",
                f"At least one of these sections is required: {template.required_any}.",
                root=root,
                level="L0",
                category="structure",
                severity="error",
                target_id=page_id,
                locator=relative,
            )
        )
    ordered_actual = [name for name in template_names if name in actual_names]
    if [name for name in actual_names if name in template_names] != ordered_actual:
        issues.append(
            _issue(
                path,
                "section_order",
                "Page sections are not in template order.",
                root=root,
                level="L0",
                category="structure",
                severity="error",
                target_id=page_id,
                locator=relative,
            )
        )

    tiers: list[int] = []
    for name, start, end in headings:
        section_rule = template.section(name)
        if section_rule is None:
            continue
        section_lines = body.splitlines()[start + 1 : end]
        section_tiers, section_issues = _inspect_section(
            path,
            relative,
            page_id,
            name,
            section_rule,
            section_lines,
            frontmatter,
            source_ids,
            root,
            index,
        )
        tiers.extend(section_tiers)
        issues.extend(section_issues)

    page_tier = frontmatter.get("evidence_tier")
    if not tiers and _template_requires_evidence(template):
        issues.append(
            _issue(
                path,
                "missing_evidence",
                "Page has no claim rows with an Evidence tier.",
                root=root,
                level="L0",
                category="evidence",
                severity="error",
                target_id=page_id,
                locator=relative,
            )
        )
    elif tiers and isinstance(page_tier, int) and page_tier != max(tiers):
        issues.append(
            _issue(
                path,
                "page_evidence_tier_mismatch",
                f"Frontmatter evidence_tier is {page_tier}; weakest claim is Tier {max(tiers)}.",
                root=root,
                level="L0",
                category="evidence",
                severity="error",
                target_id=page_id,
                locator=f"{relative}#field=evidence_tier",
            )
        )

    issues.extend(
        _missing_wikilink_issues(
            path, relative, page_id, body, terms, root=root
        )
    )
    return issues

def _template_requires_evidence(template: Any) -> bool:
    for section in template.sections:
        if section.citation in {"required", "per-item"} or section.source == "raw":
            return True
        if section.evidence_items or "Evidence" in section.columns:
            return True
        if any(rule.evidence for rule in section.column_rules.values()):
            return True
        if any(rule.evidence_line for rule in section.line_rules):
            return True
    return False


def _inspect_section(
    path: Path,
    relative: str,
    page_id: str,
    section_name: str,
    rule: SectionRule,
    lines: list[str],
    frontmatter: dict[str, Any],
    source_ids: list[str],
    root: Path,
    index: dict[str, list[dict[str, Any]]],
) -> tuple[list[int], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    tiers: list[int] = []
    text = "\n".join(lines)
    h3_count = sum(1 for line in lines if _HEADING_H3.match(line))
    if h3_count and rule.children == "none":
        issues.append(
            _section_issue(
                path,
                relative,
                page_id,
                section_name,
                "unexpected_subsection",
                "Section contains undeclared H3 subsections.",
                root,
            )
        )
    table = _parse_table(lines)
    list_items = _parse_list_items(lines)
    if rule.block == "table":
        if table is None:
            issues.append(
                _section_issue(
                    path,
                    relative,
                    page_id,
                    section_name,
                    "missing_table",
                    "Section requires a Markdown table.",
                    root,
                )
            )
        else:
            tiers.extend(_evidence_from_table(table))
            issues.extend(
                _validate_table(
                    path,
                    relative,
                    page_id,
                    section_name,
                    rule,
                    table,
                    source_ids,
                    root,
                    index,
                )
            )
    elif rule.block == "bullets":
        if len(list_items) < max(rule.min, 1):
            issues.append(
                _section_issue(
                    path,
                    relative,
                    page_id,
                    section_name,
                    "missing_list_items",
                    "Section requires more list items.",
                    root,
                )
            )
        issues.extend(
            _validate_items(
                path, relative, page_id, section_name, rule, list_items, index, root
            )
        )
        if rule.evidence_items:
            for item in list_items:
                tier = _tier_from_lines(item)
                if tier is None:
                    issues.append(
                        _section_issue(
                            path,
                            relative,
                            page_id,
                            section_name,
                            "missing_item_evidence",
                            "List item is missing Evidence: Tier N.",
                            root,
                        )
                    )
                else:
                    tiers.append(tier)
                if not any(_SOURCE_LINE.match(_strip_list_marker(line)) for line in item):
                    issues.append(
                        _section_issue(
                            path,
                            relative,
                            page_id,
                            section_name,
                            "missing_item_source",
                            "List item is missing a Source line.",
                            root,
                        )
                    )
                else:
                    issues.extend(
                        _validate_source_lines(
                            path,
                            relative,
                            page_id,
                            section_name,
                            item,
                            source_ids,
                            root,
                        )
                    )
    elif rule.block == "paragraphs":
        paragraphs = _paragraphs(lines)
        if len(paragraphs) < max(rule.min, 1):
            issues.append(
                _section_issue(
                    path,
                    relative,
                    page_id,
                    section_name,
                    "missing_paragraphs",
                    "Section requires more paragraphs.",
                    root,
                )
            )
        for paragraph in paragraphs:
            tier = _tier_from_lines(paragraph)
            if tier is not None:
                tiers.append(tier)
    else:
        if not text.strip() or not (table or list_items or h3_count or _paragraphs(lines)):
            issues.append(
                _section_issue(
                    path,
                    relative,
                    page_id,
                    section_name,
                    "empty_section",
                    "Section has no substantive content.",
                    root,
                )
            )
        if h3_count:
            tiers.extend(
                _validate_context_h3(
                    path,
                    relative,
                    page_id,
                    section_name,
                    lines,
                    rule,
                    source_ids,
                    root,
                    index,
                    issues,
                )
            )

    if rule.citation == "required" and not _SOURCE_LINK.search(text):
        issues.append(
            _section_issue(
                path,
                relative,
                page_id,
                section_name,
                "missing_citation",
                "Section requires at least one source citation.",
                root,
            )
        )
    if rule.source == "raw":
        issues.extend(
            _validate_source_links(
                path,
                relative,
                page_id,
                section_name,
                _SOURCE_LINK.findall(text),
                source_ids,
                root,
            )
        )
    return tiers, issues


def _validate_table(
    path: Path,
    relative: str,
    page_id: str,
    section_name: str,
    rule: SectionRule,
    table: dict[str, Any],
    source_ids: list[str],
    root: Path,
    index: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    columns = table["columns"]
    if columns != rule.columns:
        return [
            _section_issue(
                path,
                relative,
                page_id,
                section_name,
                "invalid_table_columns",
                f"Expected columns {rule.columns}; found {columns}.",
                root,
            )
        ]
    rows = table["rows"]
    if len(rows) < max(rule.min, 1):
        issues.append(
            _section_issue(
                path,
                relative,
                page_id,
                section_name,
                "empty_table",
                "Table must contain at least one data row.",
                root,
            )
        )
    for row in rows:
        if len(row) != len(columns):
            issues.append(
                _section_issue(
                    path,
                    relative,
                    page_id,
                    section_name,
                    "invalid_table_row",
                    "Table row has the wrong number of cells.",
                    root,
                )
            )
            continue
        record = dict(zip(columns, row, strict=False))
        evidence_tier: int | None = None
        evidence_value = record.get("Evidence")
        if evidence_value is not None:
            match = _EVIDENCE_TIER.match(evidence_value.strip())
            if match is None:
                issues.append(
                    _section_issue(
                        path,
                        relative,
                        page_id,
                        section_name,
                        "invalid_evidence_tier",
                        f"Evidence {evidence_value!r} must be Tier 1 through Tier 5.",
                        root,
                    )
                )
            else:
                evidence_tier = int(match.group(1))
        for column, value in record.items():
            column_rule = rule.column_rules.get(column)
            if column_rule is not None:
                issues.extend(
                    _validate_cell(
                        path,
                        relative,
                        page_id,
                        section_name,
                        column,
                        value,
                        column_rule,
                        index,
                        root,
                    )
                )
        if "Source" in record:
            issues.extend(
                _validate_source_cell(
                    path,
                    relative,
                    page_id,
                    section_name,
                    record["Source"],
                    evidence_tier,
                    source_ids,
                    root,
                    index,
                )
            )
        elif evidence_tier in {1, 2, 3, 4}:
            issues.append(
                _section_issue(
                    path,
                    relative,
                    page_id,
                    section_name,
                    "missing_source",
                    "Tier 1 through Tier 4 rows require a Source column.",
                    root,
                )
            )
    return issues


def _validate_cell(
    path: Path,
    relative: str,
    page_id: str,
    section_name: str,
    column: str,
    value: str,
    rule: ColumnRule,
    index: dict[str, list[dict[str, Any]]],
    root: Path,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    stripped = value.strip().strip("`")
    if rule.enum is not None and stripped not in rule.enum:
        issues.append(
            _section_issue(
                path,
                relative,
                page_id,
                section_name,
                "invalid_controlled_value",
                f"{column}={stripped!r} is not in {rule.enum}.",
                root,
            )
        )
    if rule.number is not None:
        if stripped == "unknown":
            if not rule.allow_unknown:
                issues.append(
                    _section_issue(
                        path,
                        relative,
                        page_id,
                        section_name,
                        "invalid_controlled_value",
                        f"{column}=unknown is not allowed.",
                        root,
                    )
                )
        else:
            try:
                number = float(stripped)
            except ValueError:
                issues.append(
                    _section_issue(
                        path,
                        relative,
                        page_id,
                        section_name,
                        "invalid_controlled_value",
                        f"{column}={stripped!r} must be numeric or unknown.",
                        root,
                    )
                )
            else:
                if rule.number.min is not None and number < rule.number.min:
                    issues.append(
                        _section_issue(
                            path,
                            relative,
                            page_id,
                            section_name,
                            "invalid_controlled_value",
                            f"{column}={number} is below {rule.number.min}.",
                            root,
                        )
                    )
                if rule.number.max is not None and number > rule.number.max:
                    issues.append(
                        _section_issue(
                            path,
                            relative,
                            page_id,
                            section_name,
                            "invalid_controlled_value",
                            f"{column}={number} is above {rule.number.max}.",
                            root,
                        )
                    )
    if rule.wikilink is not None:
        issues.extend(
            _validate_wikilink_cell(
                path,
                relative,
                page_id,
                section_name,
                column,
                stripped,
                rule.wikilink,
                index,
                root,
            )
        )
    return issues

def _validate_wikilink_cell(
    path: Path,
    relative: str,
    page_id: str,
    section_name: str,
    column: str,
    value: str,
    target_type: str,
    index: dict[str, list[dict[str, Any]]],
    root: Path,
) -> list[dict[str, Any]]:
    match = _WIKILINK_FULL.match(value)
    if match is None:
        return [
            _section_issue(
                path,
                relative,
                page_id,
                section_name,
                "missing_wikilink",
                f"{column} must be a [[page_id]] wikilink.",
                root,
            )
        ]
    target = match.group(1).strip()
    entries = index.get(target, [])
    if len(entries) != 1:
        return [
            _section_issue(
                path,
                relative,
                page_id,
                section_name,
                "broken_wikilink",
                f"Wikilink target {target!r} is missing or ambiguous.",
                root,
            )
        ]
    actual_type = entries[0].get("page_type")
    if actual_type != target_type:
        return [
            _section_issue(
                path,
                relative,
                page_id,
                section_name,
                "invalid_link_target_type",
                f"Wikilink {target!r} has type {actual_type!r}; expected {target_type!r}.",
                root,
            )
        ]
    return []


def _validate_source_cell(
    path: Path,
    relative: str,
    page_id: str,
    section_name: str,
    value: str,
    tier: int | None,
    declared_sources: list[str],
    root: Path,
    index: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    stripped = value.strip()
    if tier == 5:
        if not stripped.lower().startswith(("inference", "hypothesis")):
            return [
                _section_issue(
                    path,
                    relative,
                    page_id,
                    section_name,
                    "invalid_tier5_source",
                    "Tier 5 Source must start with inference or hypothesis.",
                    root,
                )
            ]
        issues: list[dict[str, Any]] = []
        for target in _WIKILINK.findall(stripped):
            entries = index.get(target.strip(), [])
            if len(entries) != 1:
                issues.append(
                    _section_issue(
                        path,
                        relative,
                        page_id,
                        section_name,
                        "broken_wikilink",
                        f"Tier 5 internal source {target!r} is missing or ambiguous.",
                        root,
                    )
                )
        return issues
    match = _SOURCE_LINK.search(stripped)
    if match is None:
        return [
            _section_issue(
                path,
                relative,
                page_id,
                section_name,
                "missing_source",
                "Source must be [paper_id](#references).",
                root,
            )
        ]
    return _validate_source_links(
        path, relative, page_id, section_name, [match.group(1)], declared_sources, root
    )


def _validate_source_links(
    path: Path,
    relative: str,
    page_id: str,
    section_name: str,
    cited_sources: list[str],
    declared_sources: list[str],
    root: Path,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for source_id in cited_sources:
        if source_id not in declared_sources:
            issues.append(
                _section_issue(
                    path,
                    relative,
                    page_id,
                    section_name,
                    "undeclared_source",
                    f"Citation source {source_id!r} is not declared in frontmatter.",
                    root,
                )
            )
        if not (root / "raw" / source_id).is_dir():
            issues.append(
                _section_issue(
                    path,
                    relative,
                    page_id,
                    section_name,
                    "missing_reference_source",
                    f"Reference source {source_id!r} has no directory under raw/.",
                    root,
                )
            )
    return issues


def _validate_source_lines(
    path: Path,
    relative: str,
    page_id: str,
    section_name: str,
    lines: list[str],
    source_ids: list[str],
    root: Path,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for line in lines:
        match = _SOURCE_LINE.match(_strip_list_marker(line))
        if not match:
            continue
        value = match.group(1).strip()
        if value.lower().startswith(("inference", "hypothesis")):
            continue
        source = _SOURCE_LINK.search(value)
        if not source:
            issues.append(
                _section_issue(
                    path,
                    relative,
                    page_id,
                    section_name,
                    "missing_source",
                    "Source line must be [paper_id](#references).",
                    root,
                )
            )
            continue
        issues.extend(
            _validate_source_links(
                path, relative, page_id, section_name, [source.group(1)], source_ids, root
            )
        )
    return issues


def _validate_context_h3(
    path: Path,
    relative: str,
    page_id: str,
    section_name: str,
    lines: list[str],
    rule: SectionRule,
    source_ids: list[str],
    root: Path,
    index: dict[str, list[dict[str, Any]]],
    issues: list[dict[str, Any]],
) -> list[int]:
    tiers: list[int] = []
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if _HEADING_H3.match(line):
            if current is not None:
                blocks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append(current)
    for block in blocks:
        block_text = "\n".join(block)
        for line_rule in rule.line_rules:
            if line_rule.evidence_line:
                found = re.search(
                    r"\*{0,2}Evidence:?\*{0,2}\s*Tier\s*([1-5])",
                    block_text,
                    re.IGNORECASE,
                )
                if found is None:
                    issues.append(
                        _section_issue(
                            path,
                            relative,
                            page_id,
                            section_name,
                            "missing_context_evidence",
                            "Context block is missing Evidence: Tier N.",
                            root,
                        )
                    )
                else:
                    tiers.append(int(found.group(1)))
            elif line_rule.source_line:
                found = re.search(
                    r"\*{0,2}Source:?\*{0,2}\s*(.+)", block_text, re.IGNORECASE
                )
                if found is None:
                    issues.append(
                        _section_issue(
                            path,
                            relative,
                            page_id,
                            section_name,
                            "missing_context_source",
                            "Context block is missing a Source line.",
                            root,
                        )
                    )
                else:
                    issues.extend(
                        _validate_source_lines(
                            path,
                            relative,
                            page_id,
                            section_name,
                            [found.group(0)],
                            source_ids,
                            root,
                        )
                    )
            elif line_rule.wikilink:
                found = re.search(re.escape(line_rule.label) + r"\s*(.+)", block_text)
                if found is None:
                    issues.append(
                        _section_issue(
                            path,
                            relative,
                            page_id,
                            section_name,
                            "missing_context_line",
                            f"Context block is missing {line_rule.label}.",
                            root,
                        )
                    )
                    continue
                values = [
                    item.strip()
                    for item in found.group(1).split(line_rule.separator)
                    if item.strip()
                ]
                for value in values:
                    issues.extend(
                        _validate_wikilink_cell(
                            path,
                            relative,
                            page_id,
                            section_name,
                            line_rule.label,
                            value,
                            line_rule.wikilink,
                            index,
                            root,
                        )
                    )
    return tiers


def _validate_items(
    path: Path,
    relative: str,
    page_id: str,
    section_name: str,
    rule: SectionRule,
    items: list[list[str]],
    index: dict[str, list[dict[str, Any]]],
    root: Path,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for item in items:
        text = " ".join(line.strip() for line in item)
        for item_rule in rule.item_rules:
            if item_rule.wikilink:
                candidate = text
                for prefix in item_rule.allow_prefixes:
                    if candidate.startswith(prefix):
                        candidate = candidate[len(prefix) :].strip()
                issues.extend(
                    _validate_wikilink_cell(
                        path,
                        relative,
                        page_id,
                        section_name,
                        "list item",
                        candidate,
                        item_rule.wikilink,
                        index,
                        root,
                    )
                )
    return issues

def _evidence_from_table(table: dict[str, Any] | None) -> list[int]:
    if not table:
        return []
    columns = table.get("columns") or []
    if "Evidence" not in columns:
        return []
    index = columns.index("Evidence")
    tiers: list[int] = []
    for row in table.get("rows") or []:
        if len(row) <= index:
            continue
        match = _EVIDENCE_TIER.match(row[index].strip())
        if match:
            tiers.append(int(match.group(1)))
    return tiers


def _tier_from_lines(lines: list[str]) -> int | None:
    for line in lines:
        match = _EVIDENCE_LINE.match(_strip_list_marker(line))
        if match:
            return int(match.group(1))
    return None


def _parse_table(lines: list[str]) -> dict[str, Any] | None:
    for index in range(len(lines) - 1):
        header = lines[index].strip()
        if not header.startswith("|"):
            continue
        divider_index = index + 1
        while divider_index < len(lines) and not lines[divider_index].strip():
            divider_index += 1
        if divider_index >= len(lines):
            continue
        if not _TABLE_DIVIDER.match(lines[divider_index].strip()):
            continue
        columns = _table_cells(header)
        rows: list[list[str]] = []
        cursor = divider_index + 1
        while cursor < len(lines):
            stripped = lines[cursor].strip()
            if not stripped:
                cursor += 1
                continue
            if not stripped.startswith("|"):
                break
            rows.append(_table_cells(lines[cursor]))
            cursor += 1
        return {"columns": columns, "rows": rows}
    return None


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse_list_items(lines: list[str]) -> list[list[str]]:
    items: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if _BULLET.match(line):
            if current is not None:
                items.append(current)
            current = [_strip_list_marker(line)]
        elif current is not None and (line.startswith(" ") or line.startswith("\t")):
            current.append(line)
        elif current is not None and line.strip():
            items.append(current)
            current = None
    if current is not None:
        items.append(current)
    return items


def _paragraphs(lines: list[str]) -> list[list[str]]:
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", "-", "*")):
            if current:
                paragraphs.append(current)
                current = []
            continue
        if _BULLET.match(line):
            continue
        current.append(line)
    if current:
        paragraphs.append(current)
    return paragraphs


def _headings(body: str) -> list[tuple[str, int, int]]:
    lines = body.splitlines()
    tokens = _MD.parse(body)
    headings: list[tuple[str, int, int]] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.tag != "h2":
            continue
        content = tokens[index + 1].content if index + 1 < len(tokens) else ""
        start = token.map[0] if token.map else len(lines)
        headings.append((content.strip(), start, len(lines)))
    for position, (name, start, _end) in enumerate(headings):
        next_start = headings[position + 1][1] if position + 1 < len(headings) else len(lines)
        headings[position] = (name, start, next_start)
    return headings


def _h1_titles(body: str) -> list[str]:
    tokens = _MD.parse(body)
    titles: list[str] = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h1":
            content = tokens[index + 1].content if index + 1 < len(tokens) else ""
            titles.append(content.strip())
    return titles

def _missing_wikilink_issues(
    path: Path,
    relative: str,
    page_id: str,
    body: str,
    terms: dict[str, list[tuple[str, str]]],
    *,
    root: Path,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    in_references = False
    for line_number, line in enumerate(body.splitlines(), start=1):
        if _HEADING_H2.match(line):
            in_references = line.strip() == "## References"
            continue
        if in_references or not line.strip():
            continue
        if line.lstrip().startswith(("#", "|", "```", ">")):
            continue
        scan_line = _strip_list_marker(line)
        if scan_line.startswith(("**", "Source:", "Evidence:")):
            continue
        without_links = _WIKILINK.sub("", scan_line)
        lowered = without_links.casefold()
        for term, entries in terms.items():
            if not term or term not in lowered:
                continue
            if _term_pattern(term).search(lowered) is None:
                continue
            target_ids = {entry[0] for entry in entries}
            if page_id in target_ids:
                continue
            issues.append(
                _issue(
                    path,
                    "missing_wikilink",
                    f"Known entity {term!r} is mentioned without a wikilink.",
                    root=root,
                    level="L1",
                    category="links",
                    severity="warning",
                    target_id=page_id,
                    locator=f"{relative}:{line_number}",
                )
            )
            break
    return issues


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str, str | None]:
    if not raw.startswith("---"):
        return {}, raw, "Page is missing YAML frontmatter."
    parts = raw.split("---", 2)
    if len(parts) != 3:
        return {}, raw, "YAML frontmatter is not closed with ---."
    try:
        parsed = yaml.load(parts[1], Loader=_StrictFrontmatterLoader) or {}
    except yaml.YAMLError as error:
        return {}, parts[2].lstrip("\r\n"), f"Invalid YAML frontmatter: {error}"
    if not isinstance(parsed, dict):
        return {}, parts[2].lstrip("\r\n"), "YAML frontmatter must be a mapping."
    return parsed, parts[2].lstrip("\r\n"), None


def _section_issue(
    path: Path,
    relative: str,
    page_id: str,
    section_name: str,
    issue_type: str,
    detail: str,
    root: Path,
) -> dict[str, Any]:
    return _issue(
        path,
        issue_type,
        f"[{section_name}] {detail}",
        root=root,
        level="L0",
        category="template",
        severity="error",
        target_id=page_id,
        locator=f"{relative}#section={section_name}",
    )


def _issue(
    path: Path,
    issue_type: str,
    detail: str,
    *,
    root: Path,
    level: str,
    category: str,
    severity: str,
    line: int | None = None,
    target_id: str | None = None,
    locator: str | None = None,
) -> dict[str, Any]:
    target = target_id or path.stem
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.as_posix()
    resolved_locator = locator or relative + (f":{line}" if line else "")
    lint_level = LintLevel(level)
    lint_severity = LintSeverity(severity)
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
        evidence=[],
        blocking=lint_severity == LintSeverity.ERROR,
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
