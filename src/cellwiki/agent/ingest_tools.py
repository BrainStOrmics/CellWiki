# =============================================================================
# Ingest 工具（附件驱动导入）：promote_attachment + ingest_sources
# =============================================================================
# promote 在用户确认后把附件提升为 raw/<source_id>/ 正式源并提交；ingest 读取
# 已登记源 + 工作区根目录可插拔 schema.md（缺失回退内置契约），返回草稿页供
# 协调器用 write_file 写入。工具不直接写 wiki，也不绕开 pending diff 审批。
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool
from cellwiki.agent.executor import get_attachment_scope, get_promotion_handler
from cellwiki.services.git_executor import GitExecutor
from cellwiki.services.promotion import promote_to_raw


DEFAULT_SCHEMA_TEXT = (
    "CellWiki default extraction contract (no schema.md found in the workspace).\n"
    "Cell type pages use YAML frontmatter with entity_type, display_name, cl_id, "
    "positive_markers (list), evidence_tier, references; body sections: Markers, "
    "Functional Characteristics, Contexts, Related Cell Types.\n"
)

MAX_SOURCE_TEXT_CHARS = 2_000_000


def _tool_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _load_schema(root: Path) -> tuple[str, str, bool]:
    """Return (schema_text, schema_used_label, built_in_fallback)."""
    candidate = root / "schema.md"
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")[:200_000], "schema.md", False
    return DEFAULT_SCHEMA_TEXT, "built-in default", True


def _read_source_text(stored: Path) -> str | None:
    """Read source text: extracted sidecar first, then plain md/txt, else None."""
    sidecar = stored.with_name(stored.name + ".extracted.txt")
    candidates = [sidecar] if sidecar.is_file() else []
    if stored.suffix.lower() in {".md", ".txt"}:
        candidates.append(stored)
    for candidate in candidates:
        try:
            data = candidate.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:4096]:
            continue
        return data.decode("utf-8", errors="replace")[:MAX_SOURCE_TEXT_CHARS]
    return None


def _run_extraction(text: str, source_path: Path) -> Any:
    """Call the cell-type extraction adapter lazily (tests monkeypatch this)."""
    from cellwiki.llm_extract import extract_cell_types_from_paper

    return extract_cell_types_from_paper(text, source_path)


def _draft_page(cell: Any, source_id: str) -> dict[str, Any]:
    """Build one cell-type page draft (frontmatter + markdown body)."""
    name = str(getattr(cell, "name", "") or "")
    standard = str(getattr(cell, "standard_name", "") or "") or name.replace(" ", "_").lower()
    cl_id = str(getattr(cell, "cl_id", "") or "")
    positive: list[str] = []
    for marker in getattr(cell, "markers", []) or []:
        gene = str(getattr(marker, "gene_symbol", "") or "")
        if gene and gene not in positive:
            positive.append(gene)
    marker_rows: list[str] = []
    for marker in getattr(cell, "markers", []) or []:
        gene = str(getattr(marker, "gene_symbol", "") or "")
        mtype = str(getattr(marker, "marker_type", "") or "")
        evidence = str(getattr(marker, "evidence", "") or "")
        marker_rows.append(f"| {gene} | {mtype} | {evidence} |")
    markers_section = "\n## Markers\n\n| Gene | Type | Evidence |\n|------|------|----------|\n" + "\n".join(marker_rows) if marker_rows else "\n## Markers\n\n_(none extracted)_\n"
    description = str(getattr(cell, "description", "") or "")
    positive_yaml = (
        "\n".join(f"  - {gene}" for gene in positive) if positive else "  []"
    )
    frontmatter = [
        "---",
        "entity_type: cell_type",
        f"display_name: \"{name}\"",
        f"cl_id: \"{cl_id}\"",
        "positive_markers:",
        positive_yaml,
        "references:",
        f"  - source_id: \"{source_id}\"",
        "evidence_tier: 5",
        "---",
    ]
    body = [
        f"# {name}",
        description,
        markers_section,
        "## Functional Characteristics",
        "_(fill from extraction)_",
        "## Contexts",
        "### Homo sapiens",
        "- tissues: _(fill)_",
        "- diseases: _(fill)_",
        "## Related Cell Types",
        "_(fill from relationships)_",
    ]
    draft = "\n".join(frontmatter + ["", *body]) + "\n"
    return {"path": f"wiki/cell_types/{standard}.md", "standard_name": standard, "file_name": standard + ".md", "markdown": draft}


def _extract_source_draft(
    root: Path, source_id: str, schema_text: str, schema_used: str
) -> dict[str, Any]:
    """Load one registered source and return draft pages plus a review summary."""
    record_path = root / "data" / "runtime" / "sources" / f"{source_id}.json"
    base = {
        "source_id": source_id,
        "schema_used": schema_used,
    }
    if not record_path.is_file():
        hint = f"source record not found: {source_id}"
        # 目录在 raw/ 里但没登记 = 预置源还没走"扫描并登记"（产品侧入口）。
        # 给出可执行提示而不是只报缺记录。
        if (root / "raw" / source_id).is_dir():
            hint += (
                " — the raw/ folder exists but is not registered; ask the user to "
                "run the raw/ scan (Register preplaced sources) in the workspace"
                " browser, or promote an attachment instead"
            )
        return {**base, "status": "error", "uncertainties": [hint]}
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {**base, "status": "error", "uncertainties": [f"invalid source record: {error}"]}
    if record.get("status") == "needs_extraction":
        return {
            **base,
            "status": "error",
            "uncertainties": [
                f"source {source_id} is a PDF without extracted text yet "
                "(needs_extraction); ask the user to provide its .extracted.txt "
                "sidecar in the same raw/ folder and rescan"
            ],
        }
    stored = Path(str(record.get("stored_path") or "")).resolve()
    # 预置登记把提取文本名记在 metadata.extracted_file（附件通路沿用
    # <stored>.extracted.txt 命名约定）。优先读登记的 sidecar，否则回退。
    sidecar_name = str((record.get("metadata") or {}).get("extracted_file") or "")
    text: str | None = None
    if sidecar_name and stored.is_file():
        sidecar = stored.parent / sidecar_name
        if sidecar.is_file():
            try:
                data = sidecar.read_bytes()
            except OSError:
                data = b""
            if data and b"\x00" not in data[:4096]:
                text = data.decode("utf-8", errors="replace")[:MAX_SOURCE_TEXT_CHARS]
    if text is None and stored.is_file():
        text = _read_source_text(stored)
    if not text or not text.strip():
        return {**base, "status": "error", "uncertainties": ["no readable extracted text (scan-only PDF?)"]}
    try:
        result = _run_extraction(text, stored)
    except Exception as error:  # 提取失败转为审阅信号，不炸 run
        return {**base, "status": "error", "uncertainties": [f"LLM extraction failed: {str(error)[:300]}"], "schema_hint": schema_text[:500]}
    cells = list(getattr(result, "cell_types", []) or [])
    drafts = [_draft_page(cell, source_id) for cell in cells]
    paper = getattr(result, "paper", None)
    paper_info: dict[str, Any] = {}
    if paper is not None:
        paper_info = {
            "title": str(getattr(paper, "title", "") or "")[:300],
            "doi": str(getattr(paper, "doi", "") or "")[:200],
            "year": getattr(paper, "year", None),
        }
    return {
        **base,
        "status": "ok",
        "paper_info": paper_info,
        "entities_found": len(cells),
        "drafts": drafts,
        "uncertainties": [],
        "conflicts": [],
    }


def build_ingest_tools(project_root: Path) -> list[BaseTool]:
    """Provide promote_attachment and ingest_sources for the coordinator."""
    root = Path(project_root).resolve()

    @tool("promote_attachment")
    def promote_attachment(attachment_id: str, source_type: str = "paper") -> str:
        """Promote one uploaded attachment into the formal raw/<source_id>/ source area.
        Call only after the user confirmed ingestion via ask_user_question. Copies
        the original (plus extracted text) into raw/, registers the source, commits
        the change, and removes the runtime copy."""
        resolver, _ws_root, thread_dir = get_attachment_scope()
        if resolver is None:
            return _tool_json({"error": "no active run context"})
        try:
            target = resolver(attachment_id)
        except Exception as error:
            return _tool_json({"error": f"cannot resolve attachment: {error}"})
        if target is None:
            return _tool_json({"error": "attachment_not_found"})
        try:
            record = promote_to_raw(root, attachment_path=target, source_type=source_type)
        except Exception as error:
            return _tool_json({"error": f"promote failed: {str(error)[:300]}"})
        source_id = str(record.get("source_id") or "")
        git_error = None
        try:
            git = GitExecutor(root)
            git.run("add", f"raw/{source_id}")
            git.run("commit", "-m", f"ingest: promote {source_id}")
        except Exception as error:
            git_error = str(error)[:300]
        removed = 0
        for candidate in (target, target.with_name(target.name + ".extracted.txt")):
            try:
                if candidate.is_file():
                    candidate.unlink()
                    removed += 1
            except OSError:
                pass
        handler = get_promotion_handler()
        if handler is not None and thread_dir is not None:
            try:
                handler(thread_dir.name, attachment_id, source_id)
            except Exception:
                pass
        return _tool_json(
            {
                "ok": True,
                "source_id": source_id,
                "raw_path": f"raw/{source_id}",
                "stored_path": record.get("stored_path"),
                "removed_runtime_files": removed,
                "git_error": git_error,
            }
        )

    @tool("ingest_sources")
    def ingest_sources(source_ids: list[str]) -> str:
        """Read registered raw/ sources plus the workspace schema and return page drafts.
        Reads schema.md from the workspace root when present (pluggable), otherwise
        uses a built-in default. Drafts are returned for the coordinator to review
        and write with write_file; this tool never writes wiki pages."""
        schema_text, schema_used, fallback = _load_schema(root)
        results = [
            _extract_source_draft(root, str(source_id), schema_text, schema_used)
            for source_id in (source_ids or [])
        ]
        return _tool_json(
            {
                "schema_used": schema_used,
                "built_in_schema_fallback": fallback,
                "sources": results,
            }
        )

    return [promote_attachment, ingest_sources]


__all__ = [
    "build_ingest_tools",
    "promote_to_raw",
    "_load_schema",
    "_run_extraction",
    "_extract_source_draft",
    "_draft_page",
    "DEFAULT_SCHEMA_TEXT",
]
