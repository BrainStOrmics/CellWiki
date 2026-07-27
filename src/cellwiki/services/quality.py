# =============================================================================
# 质量检查服务 —— Wiki 投影的确定性结构和引用 lint
# =============================================================================

"""Deterministic structural and referential lint for the Wiki projection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from cellwiki.domain.linting import LintFinding, LintLevel, LintSeverity
from cellwiki.domain.extraction import ExtractionResult


# ---------------------------------------------------------------------------
# ProjectionQualityError —— 投影质量异常
# 当 L0 门控问题使投影不安全发布时抛出
# ---------------------------------------------------------------------------
class ProjectionQualityError(RuntimeError):
    """Raised when a gating L0 issue makes a projection unsafe to publish."""


# 常用正则表达式
_CL_ID = re.compile(r"^CL:\d{7}$")                       # 细胞本体论 ID 格式
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")    # Markdown 链接
_MARKER_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")  # 标记物符号格式


# ---------------------------------------------------------------------------
# 检查已发布的 Markdown 投影，返回门控和建议性发现
# 检查项包括：无效的前置元数据、空页面、断链引用、CL ID 格式等
# 按严重级别分为 L0（阻塞）、L1（警告）、L2（信息）
# ---------------------------------------------------------------------------
def inspect_projection(project_root: Path) -> dict[str, Any]:
    """Inspect published Markdown and return both gating and advisory findings."""
    root = Path(project_root).resolve()
    pages_dir = root / "wiki" / "cell_types"
    issues: list[dict[str, Any]] = []
    page_count = 0

    if pages_dir.exists():
        for path in sorted(pages_dir.glob("*.md")):
            page_count += 1
            raw = path.read_text(encoding="utf-8")
            frontmatter, body, frontmatter_error = _split_frontmatter(raw)
            if frontmatter_error:
                issues.append(
                    _issue(
                        path,
                        "invalid_frontmatter",
                        frontmatter_error,
                        level="L0",          # L0 阻塞级别
                        category="structure",
                        severity="error",
                    )
                )
            if not body.strip():
                issues.append(
                    _issue(
                        path,
                        "empty_page",
                        "Published page has no body.",
                        level="L0",
                        category="structure",
                        severity="error",
                    )
                )
            if not any(line.startswith("# ") for line in body.splitlines()):
                issues.append(
                    _issue(
                        path,
                        "missing_title",
                        "Published page has no H1 title.",
                        level="L0",
                        category="structure",
                        severity="error",
                        auto_fixable=True,
                    )
                )
            standard_name = frontmatter.get("standard_name")
            if standard_name is None:
                issues.append(
                    _issue(
                        path,
                        "missing_standard_name",
                        "Frontmatter has no standard_name.",
                        level="L0",
                        category="identity",
                        severity="error",
                        auto_fixable=True,
                    )
                )
            elif standard_name != path.stem:
                issues.append(
                    _issue(
                        path,
                        "id_mismatch",
                        f"standard_name is {standard_name!r}; expected {path.stem!r}.",
                        level="L0",
                        category="identity",
                        severity="error",
                    )
                )

            cl_id = frontmatter.get("cl_id")
            if cl_id is not None and not _CL_ID.fullmatch(str(cl_id)):
                issues.append(
                    _issue(
                        path,
                        "invalid_cl_id",
                        f"Cell Ontology identifier {cl_id!r} is not in CL:0000000 form.",
                        level="L1",
                        category="ontology",
                        severity="warning",
                    )
                )

            references = frontmatter.get("references")
            if not references:
                issues.append(
                    _issue(
                        path,
                        "missing_references",
                        "Page has no source references in frontmatter.",
                        level="L1",
                        category="provenance",
                        severity="warning",
                    )
                )
            elif isinstance(references, list):
                reference_ids = [_reference_id(reference) for reference in references]
                populated_ids = [reference_id for reference_id in reference_ids if reference_id]
                duplicates = sorted(
                    {reference_id for reference_id in populated_ids if populated_ids.count(reference_id) > 1}
                )
                if duplicates:
                    issues.append(
                        _issue(
                            path,
                            "duplicate_references",
                            f"Duplicate reference IDs: {', '.join(duplicates)}.",
                            level="L1",
                            category="provenance",
                            severity="warning",
                            auto_fixable=True,
                        )
                    )
            else:
                issues.append(
                    _issue(
                        path,
                        "invalid_references",
                        "Frontmatter references must be a list.",
                        level="L1",
                        category="provenance",
                        severity="warning",
                    )
                )

            issues.extend(_broken_local_links(path, body))

    issues.extend(_inspect_extractions(root))

    error_count = sum(issue["severity"] == "error" for issue in issues)
    warning_count = sum(issue["severity"] == "warning" for issue in issues)
    status = "failed" if error_count else "passed_with_warnings" if warning_count else "passed"
    return {
        "status": status,
        "page_count": page_count,
        "issue_count": len(issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "levels": {
            "L0": {
                "status": "failed" if error_count else "passed",
                "issue_count": error_count,
                "description": "Gating structure and identity checks",
            },
            "L1": {
                "status": "warning" if warning_count else "passed",
                "issue_count": warning_count,
                "description": "Advisory provenance, ontology, and link checks",
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
    """Reject a CentralWriter transaction only for deterministic gating errors."""
    report = inspect_projection(project_root)
    gating_issues = [issue for issue in report["issues"] if issue["severity"] == "error"]
    if gating_issues:
        first = gating_issues[0]
        raise ProjectionQualityError(
            f"projection lint failed with {len(gating_issues)} gating issue(s): "
            f"{first['page_id']} {first['detail']}"
        )


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


def _reference_id(reference: Any) -> str | None:
    if isinstance(reference, str):
        return reference
    if isinstance(reference, dict):
        value = reference.get("paper_id") or reference.get("source_id")
        return str(value) if value else None
    return None


def _broken_local_links(path: Path, body: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for line_number, line in enumerate(body.splitlines(), start=1):
        for target in _MARKDOWN_LINK.findall(line):
            target_path = target.split("#", 1)[0].strip()
            if not target_path.lower().endswith(".md"):
                continue
            if target_path.startswith(("http://", "https://", "/")):
                continue
            if not (path.parent / target_path).resolve().is_file():
                issues.append(
                    _issue(
                        path,
                        "broken_local_link",
                        f"Local Wiki link target does not exist: {target_path}.",
                        level="L1",
                        category="links",
                        severity="warning",
                        line=line_number,
                    )
                )
    return issues


def _inspect_extractions(root: Path) -> list[dict[str, Any]]:
    """Apply L0/L1 rules to the formal fact layer without mutating it."""

    issues: list[dict[str, Any]] = []
    extraction_dir = root / "data" / "extraction"
    if not extraction_dir.exists():
        return issues
    for path in sorted(extraction_dir.glob("*.json")):
        locator = f"data/extraction/{path.name}"
        try:
            extraction = ExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as error:
            issues.append(
                _issue(
                    path,
                    "invalid_extraction",
                    f"Formal extraction does not match its schema: {error}",
                    level="L0",
                    category="rebuildability",
                    severity="error",
                    target_id=path.stem,
                    locator=locator,
                )
            )
            continue

        if extraction.cell_types and not extraction.claims:
            issues.append(
                _issue(
                    path,
                    "missing_claim_evidence",
                    "Extraction contains entities but no claim-level evidence.",
                    level="L1",
                    category="provenance",
                    severity="warning",
                    target_id=path.stem,
                    locator=locator,
                )
            )
        for claim in extraction.claims:
            for evidence in claim.evidence:
                missing = [
                    name
                    for name, value in {
                        "source_id": evidence.source_id,
                        "page_start": evidence.page_start,
                        "block_id": evidence.block_id,
                        "excerpt": evidence.excerpt,
                    }.items()
                    if value in (None, "")
                ]
                if missing:
                    issues.append(
                        _issue(
                            path,
                            "incomplete_evidence_locator",
                            f"Claim {claim.claim_id} is missing: {', '.join(missing)}.",
                            level="L1",
                            category="provenance",
                            severity="warning",
                            target_id=claim.subject,
                            locator=f"{locator}#claim={claim.claim_id}",
                            evidence=[item.model_dump(mode="json") for item in claim.evidence],
                        )
                    )

        for cell in extraction.cell_types:
            directions: dict[str, set[str]] = {}
            for marker in cell.markers:
                gene = marker.gene_symbol.upper()
                directions.setdefault(gene, set()).add(marker.marker_type.value)
                if not _MARKER_SYMBOL.fullmatch(marker.gene_symbol):
                    issues.append(
                        _issue(
                            path,
                            "invalid_marker_symbol",
                            f"Marker symbol {marker.gene_symbol!r} has an unsupported format.",
                            level="L1",
                            category="marker",
                            severity="warning",
                            target_id=cell.standard_name,
                            locator=f"{locator}#cell={cell.standard_name}",
                        )
                    )
            for gene, marker_types in directions.items():
                if {"positive", "negative"} <= marker_types:
                    issues.append(
                        _issue(
                            path,
                            "marker_direction_conflict",
                            f"Marker {gene} is both positive and negative without a resolved context.",
                            level="L1",
                            category="conflict",
                            severity="warning",
                            target_id=cell.standard_name,
                            locator=f"{locator}#cell={cell.standard_name}&marker={gene}",
                        )
                    )

        source_document = extraction.source_document
        source_id = str(source_document.get("source_id", ""))
        parse_hash = str(source_document.get("parse_hash", ""))
        record_path = root / "data" / "runtime" / "sources" / f"{source_id}.json"
        if re.fullmatch(r"src_[a-f0-9]{20}", source_id) and record_path.is_file():
            try:
                record = yaml.safe_load(record_path.read_text(encoding="utf-8")) or {}
                current_hash = str(record.get("parse_hash", ""))
            except (OSError, yaml.YAMLError):
                current_hash = ""
            if parse_hash and current_hash and parse_hash != current_hash:
                issues.append(
                    _issue(
                        path,
                        "stale_extraction_parse_version",
                        "Extraction parse_hash differs from the current registered source parse.",
                        level="L1",
                        category="version",
                        severity="warning",
                        target_id=source_id,
                        locator=locator,
                    )
                )
    return issues


def _issue(
    path: Path,
    issue_type: str,
    detail: str,
    *,
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
    resolved_locator = locator or f"wiki/cell_types/{path.name}" + (f":{line}" if line else "")
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
    # Compatibility keys remain while frontend consumers migrate to the stable contract.
    payload.update({
        "page_id": path.stem,
        "type": issue_type,
        "detail": detail,
    })
    return payload
