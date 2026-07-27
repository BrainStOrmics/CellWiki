# =============================================================================
# Wiki 页面生成 —— 带 YAML 前置元数据和结构化 Markdown 的页面生成
# =============================================================================
# 负责生成细胞类型页面、索引页面（README.md）、标记基因页面等。
# 支持 YAML 前置元数据、Markdown 表格、交叉引用链接、人工注释保留等特性。
# 页面内容通过合并的多源数据（标记物、功能、背景、引用）自动生成。
# =============================================================================

"""Wiki page generation with YAML frontmatter and structured Markdown."""

import hashlib
import json
import re
from pathlib import Path

import yaml

from cellwiki.config import settings
from cellwiki.models import WikiCellType


# ---------------------------------------------------------------------------
# 将蛇形命名或错误大小写的名称转换为正确的大写标题格式
# 处理常见的生物学术语：CD8+ -> CD8+, T cell -> T cell 等
# 使用词边界正则表达式避免部分匹配（如 "T Cell-like" 中的 "T Cell"）
# ---------------------------------------------------------------------------
def _proper_title_case(s: str) -> str:
    """Convert a snake_case or poorly cased name to proper title case.

    Handles common biology terms: CD8+ -> CD8+, T cell -> T cell, etc.
    """
    # 将下划线替换为空格
    s = s.replace("_", " ")
    # 应用 Python 的 title() 大小写转换
    s = s.title()
    # 修正常见的生物学术语，因为 title() 会错误地转换它们
    # 例如 "CD4" -> "Cd4", "T Cell" -> "T Cell" 等
    fixes = {
        "Cd4": "CD4",
        "Cd8": "CD8",
        "T Cell": "T Cell",
        "T Cells": "T Cells",
        "B Cell": "B Cell",
        "B Cells": "B Cells",
        "Nk Cell": "NK Cell",
        "Nk Cells": "NK Cells",
        "T H": "Th",
        "T Reg": "T Reg",
        "Treg": "Treg",
        "T Em": "T EM",
        "T Cm": "T CM",
        "T Rm": "T RM",
        "T Emra": "T EMRA",
        "Mait": "MAIT",
        "Ifng": "IFNG",
        "Ifnγ": "IFN-γ",
        "Spp1": "SPP1",
        "Cxcl": "CXCL",
        "Ccr": "CCR",
        "Cd6": "CD6",
        "Cd160": "CD160",
        "Gzmk": "GZMK",
        "Gzmb": "GZMB",
        "Lef1": "LEF1",
        "Gpr183": "GPR183",
        "Cx3Cr1": "CX3CR1",
        "Layn": "LAYN",
        "Il": "IL",
        "Foxp3": "FOXP3",
        "Ctla4": "CTLA4",
        "Cxcr": "CXCR",
        "Slc4A10": "SLC4A10",
        "Anxa1": "ANXA1",
        "Gnly": "GNLY",
        "Tcf7": "TCF7",
        "Il23R": "IL23R",
        "Il10": "IL10",
        "Tex": "TEX",
    }
    # 使用词边界正则表达式，避免 "T Cell" 匹配到 "T Cell-like" 中的 "T Cell"
    for old, new in fixes.items():
        s = re.sub(rf"\b{re.escape(old)}\b", new, s)
    return s


def _value_of(value):
    """Return the serialized value for enum-like model fields."""
    return value.value if hasattr(value, "value") else value


def _marker_type(entry: dict) -> str:
    """Normalize marker type values from Pydantic and merged dictionaries."""
    return str(_value_of(entry.get("marker_type", "")))


def _context_values(wt: WikiCellType) -> tuple[list[str], list[str]]:
    """Collect deterministic tissue and species values from merged contexts."""
    tissues: set[str] = set()
    species: set[str] = set(wt.contexts)
    for info in wt.contexts.values():
        tissues.update(info.get("tissues", []))

    # ``context`` is retained for v2 compatibility and may contain flattened
    # values when a page was assembled outside the legacy merge function.
    if isinstance(wt.context, dict):
        context_species = wt.context.get("species", [])
        context_tissues = wt.context.get("tissues", wt.context.get("tissue", []))
        species.update(
            context_species if isinstance(context_species, list) else [context_species]
        )
        tissues.update(
            context_tissues if isinstance(context_tissues, list) else [context_tissues]
        )

    return sorted(value for value in tissues if value), sorted(value for value in species if value)


def _negative_marker_details(wt: WikiCellType) -> list[dict]:
    """Return negative-marker evidence from both legacy and v2 model fields."""
    details: list[dict] = []
    for gene, entries in wt.markers.items():
        for entry in entries:
            if _marker_type(entry) == "negative":
                details.append(
                    {
                        "gene_symbol": gene,
                        "evidence": entry.get("evidence", ""),
                        "paper_id": entry.get("paper_id", ""),
                    }
                )
    details.extend(wt.negative_markers)

    unique: dict[str, dict] = {}
    for detail in details:
        if isinstance(detail, str):
            detail = {"gene_symbol": detail}
        gene = detail.get("gene_symbol") or detail.get("gene") or ""
        if not gene:
            continue
        key = json.dumps(detail, sort_keys=True, ensure_ascii=False)
        unique[key] = {**detail, "gene_symbol": gene}
    return sorted(unique.values(), key=lambda item: (item["gene_symbol"], json.dumps(item, sort_keys=True)))


def _positive_marker_symbols(wt: WikiCellType) -> list[str]:
    """Return unique positive marker symbols in stable order."""
    return sorted(
        gene
        for gene, entries in wt.markers.items()
        if any(_marker_type(entry) == "positive" for entry in entries)
    )


def _conflict_descriptions(wt: WikiCellType) -> list[str]:
    """Return explicit conflicts, deriving a description for flagged markers if needed."""
    conflicts = list(wt.conflicts)
    if conflicts:
        return sorted(set(conflicts))
    existing = set(conflicts)
    for gene, entries in wt.markers.items():
        if not any(entry.get("conflict") for entry in entries):
            continue
        marker_types = sorted({_marker_type(entry) for entry in entries})
        description = f"{gene}: {' vs '.join(marker_types)}"
        if description not in existing:
            conflicts.append(description)
            existing.add(description)
    return sorted(conflicts)


def _write_entity_page(frontmatter: dict, lines: list[str], destination: Path) -> None:
    """Write a deterministic YAML-frontmatter Markdown page."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not frontmatter:
        destination.write_text("\n".join(lines), encoding="utf-8")
        return
    header = yaml.dump(
        frontmatter,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    destination.write_text(f"---\n{header}\n---\n\n" + "\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# 生成单个细胞类型的 Wiki 页面
# 页面结构：
# 1. YAML 前置元数据（standard_name, cl_id, 别名, 引用等）
# 2. 标题和描述
# 3. 标记物表格（含冲突标记）
# 4. 功能特征
# 5. 上下文（按物种分组）
# 6. 子群
# 7. 相关细胞类型
# 8. 人工注释（可选，在自动重建后保留）
# 9. 引用列表
# ---------------------------------------------------------------------------
def generate_cell_type_page(
    key: str,
    wt: WikiCellType,
    destination: Path | None = None,
    curated_content: str = "",
):
    """Generate a single cell type wiki page."""
    # 如果未指定目标路径，则使用键名生成
    dest = destination or (settings.wiki_cell_types_dir / f"{key}.md")

    tissues, species = _context_values(wt)
    negative_details = _negative_marker_details(wt)
    conflicts = _conflict_descriptions(wt)

    # ---- 构建 YAML 前置元数据 ----
    # 对别名和派生列表排序以确保输出确定性，保留原有字段。
    frontmatter = {
        "standard_name": wt.standard_name,
        "display_name": wt.display_name,
        "cl_id": wt.cl_id,
        "parent_type": wt.parent_type,
        "aliases": sorted(wt.aliases),
        "references": [{"paper_id": r["paper_id"], "title": r["title"]} for r in wt.references],
        "evidence_tier": int(_value_of(wt.evidence_tier)),
        "source_count": len(wt.sources),
        "positive_markers": _positive_marker_symbols(wt),
        "negative_markers": sorted({detail["gene_symbol"] for detail in negative_details}),
        "tissues": tissues,
        "species": species,
        "conflicts": conflicts,
    }

    # ---- 构建页面主体 ----
    lines = []

    # 标题：如果没有策展的显示名称，则使用格式化后的键名
    display = wt.display_name or _proper_title_case(key)
    lines.append(f"# {display}")
    lines.append("")

    # 描述（以块引用形式展示）
    if wt.description:
        lines.append(f"> {wt.description}")
        lines.append("")

    # ---- 标记物表格 ----
    if wt.markers:
        lines.append("## Markers")
        lines.append("")
        lines.append("| Marker | Type | Evidence | Source |")
        lines.append("|--------|------|----------|--------|")
        for gene, entries in sorted(wt.markers.items()):
            for entry in entries:
                mtype = entry["marker_type"]
                # 截断证据文本以免破坏表格布局
                evidence = entry.get("evidence", "")[:60]
                paper_id = entry.get("paper_id", "")
                # 对冲突标记物添加视觉标记
                conflict_marker = " ⚠️ CONFLICT" if entry.get("conflict") else ""
                lines.append(f"| {gene}{conflict_marker} | {mtype} | {evidence} | [{paper_id}]() |")
        lines.append("")

        # 展示冲突标记物详情
        conflict_markers = [e for entries in wt.markers.values() for e in entries if e.get("conflict")]
        if conflict_markers:
            lines.append("### Marker Conflicts")
            lines.append("")
            lines.append("The following markers have conflicting reports across papers:")
            lines.append("")
            for entry in conflict_markers:
                # 反向查找基因名称
                gene = next(g for g, es in wt.markers.items() if entry in es)
                lines.append(f"- **{gene}**: conflicting marker types detected")
            lines.append("")

    # ---- 阴性标记物 ----
    if negative_details:
        lines.append("## Negative Markers")
        lines.append("")
        lines.append("| Marker | Evidence | Source |")
        lines.append("|--------|----------|--------|")
        for entry in negative_details:
            lines.append(
                f"| {entry['gene_symbol']} | {entry.get('evidence', '')} | "
                f"{entry.get('paper_id', '')} |"
            )
        lines.append("")

    # ---- 未解决冲突 ----
    if conflicts:
        lines.append("## Conflicts")
        lines.append("")
        for conflict in conflicts:
            lines.append(f"- {conflict}")
        lines.append("")

    # ---- 功能特征 ----
    if wt.functions:
        lines.append("## Functional Characteristics")
        lines.append("")
        for desc, entries in wt.functions.items():
            # 只有在有通路时才添加通路注释，避免孤立的括号
            pathways = [e.get("pathway") for e in entries if e.get("pathway")]
            pathway_str = f" ({', '.join(pathways)})" if pathways else ""
            lines.append(f"- **{desc}**{pathway_str}")
            for entry in entries:
                paper_id = entry.get("paper_id", "")
                if paper_id:
                    lines.append(f"  - Source: [{paper_id}]()")
        lines.append("")

    # ---- 上下文（按物种分组）----
    if wt.contexts:
        lines.append("## Contexts")
        lines.append("")
        for species, info in sorted(wt.contexts.items()):
            lines.append(f"### {species}")
            lines.append("")
            if info["tissues"]:
                lines.append("**Tissues:** " + ", ".join(info["tissues"]))
                lines.append("")
            if info["diseases"]:
                lines.append("**Diseases:** " + ", ".join(info["diseases"]))
                lines.append("")

    # ---- 子群 ----
    if wt.subpopulations:
        lines.append("## Subpopulations")
        lines.append("")
        for sub in sorted(wt.subpopulations):
            # 生成简单链接：小写+下划线，细胞类型名称不需要编码
            sub_link = sub.lower().replace(" ", "_")
            lines.append(f"- [{sub}]({sub_link}.md)")
        lines.append("")

    # ---- 相关细胞类型 ----
    related = _find_related(wt)
    if related:
        lines.append("## Related Cell Types")
        lines.append("")
        if wt.parent_type:
            lines.append(f"- Parent: [{wt.parent_type}]({wt.parent_type}.md)")
        for rel in sorted(related):
            if rel != wt.parent_type and rel != key:
                lines.append(f"- [{rel}]({rel}.md)")
        lines.append("")

    # ---- 引用 ----
    if wt.references:
        lines.append("## References")
        lines.append("")

    # ---- 人工注释 ----
    # 在自动重建后保留，与生成的投影分开存储以防止覆盖
    if curated_content.strip():
        lines.append("## Curated Notes")
        lines.append("")
        lines.extend(curated_content.strip().splitlines())
        lines.append("")
        for ref in wt.references:
            # 如果有 DOI 则链接化，没有 DOI 的引用仍然列出
            doi_link = f" [{ref['doi']}](https://doi.org/{ref['doi']})" if ref.get("doi") else ""
            lines.append(f"- {ref.get('title', ref['paper_id'])} ({ref.get('year', 'n.d.')}){doi_link}")
        lines.append("")

    # ---- 写入文件 ----
    # 使用块标量 YAML 提高可读性，allow_unicode 处理希腊字母（如 IFN-γ）
    fm_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True).strip()
    content = f"---\n{fm_str}\n---\n\n" + "\n".join(lines)

    # 确保输出目录存在
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# 查找相关细胞类型
# 基于父类型、子群和共享标记物来查找相关细胞类型。
# ---------------------------------------------------------------------------
def _find_related(wt: WikiCellType) -> list[str]:
    """Find related cell types based on parent_type, subpopulations, and shared markers."""
    related = set()
    if wt.parent_type:
        related.add(wt.parent_type)
    for sub in wt.subpopulations:
        related.add(sub.lower().replace(" ", "_"))
    return list(related)


# ---------------------------------------------------------------------------
# 生成 Wiki 索引页面（README.md）
# 按父类型分组显示层次结构。
# 只有父类型也在索引中时才缩进子类型。
# ---------------------------------------------------------------------------
def generate_index_page(
    wiki: dict[str, WikiCellType] | None = None,
    destination: Path | None = None,
):
    """Generate the wiki README.md index page."""
    dest = destination or (settings.wiki_dir / "README.md")

    lines = [
        "# CellWiki - Single Cell Type Knowledge Base",
        "",
        "A knowledge base of cell types and subpopulations built from scientific literature.",
        "",
        "## Cell Types",
        "",
    ]

    if wiki:
        # 按父类型分组建立层次结构
        roots = []
        children = {}
        for key, wt in sorted(wiki.items()):
            # 只有父类型也在索引中时才嵌套
            if wt.parent_type and wt.parent_type in wiki:
                children.setdefault(wt.parent_type, []).append((key, wt))
            else:
                roots.append((key, wt))

        # 渲染根节点和子节点
        for key, wt in roots:
            cl_tag = f" ({wt.cl_id})" if wt.cl_id else ""
            lines.append(f"- [{wt.display_name or _proper_title_case(key)}]({key}.md){cl_tag}")
            if key in children:
                for child_key, child_wt in children[key]:
                    cl_tag = f" ({child_wt.cl_id})" if child_wt.cl_id else ""
                    lines.append(f"  - [{child_wt.display_name or _proper_title_case(child_key)}]({child_key}.md){cl_tag}")

        # 捕获既不是根节点也不是子节点的孤立条目
        remaining = [k for k in wiki if k not in roots and k not in children]
        for k in remaining:
            wt = wiki[k]
            cl_tag = f" ({wt.cl_id})" if wt.cl_id else ""
            lines.append(f"- [{wt.display_name or _proper_title_case(k)}]({k}.md){cl_tag}")
    else:
        lines.append("No cell types yet. Add reference papers with `cellwiki add <paper.pdf>`.")

    # 关系图链接
    lines.append("")
    lines.append("## Relationship Graph")
    lines.append("")
    lines.append("- [relationships.json](relationships.json) - Machine-readable relationship data")
    lines.append("- [graph.dot](graph.dot) - Graphviz DOT format")
    lines.append("- [graph.mmd](graph.mmd) - Mermaid diagram format")
    lines.append("")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# 生成标记基因的 Wiki 页面
# 包含表达谱、阴性证据、共表达信息、相关页面和来源。
# 手动序列化前置元数据（避免仅为这部分引入 yaml.dump 导入）。
# ---------------------------------------------------------------------------
def generate_marker_gene_page(
    symbol: str,
    mg: dict,
    destination: Path | None = None,
):
    """Generate a marker gene wiki page at an explicit or configured path."""
    dest = destination or (settings.wiki_marker_genes_dir / f"{symbol}.md")

    # 构建 YAML 前置元数据
    frontmatter = {
        "entity_type": "marker_gene",
        "gene_symbol": mg.get("gene_symbol", symbol),
        "gene_name": mg.get("gene_name", ""),
        "specificity": mg.get("specificity", ""),
        "evidence_tier": mg.get("evidence_tier", 5),
        "source_count": mg.get("source_count", 0),
        "last_updated": mg.get("last_updated", ""),
    }

    # 构建页面主体
    lines = []
    lines.append(f"# {symbol}")
    lines.append("")

    # 描述
    if mg.get("description"):
        lines.append(f"> {mg['description']}")
        lines.append("")

    # 表达谱表格
    if mg.get("cell_types_expressed"):
        lines.append("## Expression")
        lines.append("")
        lines.append("| Cell Type | Level | Evidence |")
        lines.append("|-----------|-------|----------|")
        for ct in mg["cell_types_expressed"]:
            lines.append(f"| [[{ct}]] | | |")
        lines.append("")

    # 阴性证据
    if mg.get("negative_evidence"):
        lines.append("## Negative Evidence")
        lines.append("")
        lines.append("| Cell Type | Evidence | Sources |")
        lines.append("|-----------|----------|---------|")
        for ne in mg["negative_evidence"]:
            lines.append(f"| {ne.get('cell_type', '')} | {ne.get('evidence', '')} | {', '.join(ne.get('sources', []))} |")
        lines.append("")

    # 共表达信息
    if mg.get("co_expression"):
        lines.append("## Co-expression")
        lines.append("")
        lines.append("| Gene | Cell Type | Correlation |")
        lines.append("|------|-----------|-------------|")
        for ce in mg["co_expression"]:
            lines.append(f"| {ce.get('gene', '')} | {ce.get('cell_type', '')} | {ce.get('correlation', '')} |")
        lines.append("")

    # 相关页面（限制为 5 个以保持简洁）
    lines.append("## Related Pages")
    lines.append("")
    for ct in mg.get("cell_types_expressed", [])[:5]:
        lines.append(f"- [[{ct}]]")
    lines.append("")

    # 来源列表
    if mg.get("sources"):
        lines.append("## Sources")
        lines.append("")
        for s in mg["sources"]:
            lines.append(f"- {s}")
        lines.append("")

    # 手动序列化前置元数据（避免仅为这部分引入 yaml.dump）
    header = "---\n"
    for k, v in frontmatter.items():
        header += f"{k}: {json.dumps(v) if isinstance(v, (list, dict)) else v}\n"
    header += "---\n\n"

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(header + "\n".join(lines), encoding="utf-8")


def generate_tissue_page(
    key: str,
    tissue_data: dict,
    destination: Path | None = None,
):
    """Generate a tissue navigation page from merged projection data."""
    dest = destination or (settings.wiki_tissues_dir / f"{key}.md")
    display_name = tissue_data.get("display_name") or _proper_title_case(key)
    cell_types = tissue_data.get("cell_types_found", {})
    frontmatter = {
        "entity_type": "tissue",
        "name": tissue_data.get("name", key),
        "display_name": display_name,
        "source_count": tissue_data.get("source_count", 0),
        "sources": sorted(tissue_data.get("sources", [])),
    }
    lines = [f"# {display_name}", "", "## Cell Types", ""]
    if cell_types:
        lines.extend(["| Cell Type | Status |", "|-----------|--------|"])
        for cell_type, status in sorted(cell_types.items()):
            lines.append(f"| [{cell_type}](../cell_types/{cell_type}.md) | {status} |")
        lines.append("")
    else:
        lines.append("_(No cell types recorded.)_")
        lines.append("")
    if frontmatter["sources"]:
        lines.extend(["## Sources", ""])
        lines.extend(f"- {source}" for source in frontmatter["sources"])
        lines.append("")
    _write_entity_page(frontmatter, lines, dest)


def generate_disease_page(
    key: str,
    disease_data: dict,
    destination: Path | None = None,
):
    """Generate a disease navigation page from merged projection data."""
    dest = destination or (settings.wiki_diseases_dir / f"{key}.md")
    display_name = disease_data.get("display_name") or _proper_title_case(key)
    cell_types = disease_data.get("associated_cell_types", {})
    frontmatter = {
        "entity_type": "disease",
        "name": disease_data.get("name", key),
        "display_name": display_name,
        "source_count": disease_data.get("source_count", 0),
        "sources": sorted(disease_data.get("sources", [])),
    }
    lines = [f"# {display_name}", "", "## Associated Cell Types", ""]
    if cell_types:
        lines.extend(["| Cell Type | Association |", "|-----------|-------------|"])
        for cell_type, association in sorted(cell_types.items()):
            lines.append(
                f"| [{cell_type}](../cell_types/{cell_type}.md) | {association} |"
            )
        lines.append("")
    else:
        lines.append("_(No cell types recorded.)_")
        lines.append("")
    if frontmatter["sources"]:
        lines.extend(["## Sources", ""])
        lines.extend(f"- {source}" for source in frontmatter["sources"])
        lines.append("")
    _write_entity_page(frontmatter, lines, dest)


def _slugify(value: str) -> str:
    """Convert a conflict description into a stable filename fragment."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return slug or "conflict"


def _conflict_page_id(cell_type_key: str, description: str) -> str:
    """Build a unique, stable conflict page identifier."""
    return f"{cell_type_key}_{_slugify(description)}"


def generate_conflict_pages(
    wiki: dict[str, WikiCellType],
    dest_dir: Path,
) -> list[str]:
    """Generate one review page for every unresolved merged conflict."""
    page_ids: list[str] = []
    seen: set[str] = set()
    for key, wt in sorted(wiki.items()):
        for description in _conflict_descriptions(wt):
            conflict_id = _conflict_page_id(key, description)
            if conflict_id in seen:
                continue
            seen.add(conflict_id)
            page_ids.append(conflict_id)
            frontmatter = {
                "conflict_id": conflict_id,
                "affected_cell_types": [key],
                "severity": "medium",
                "sources": sorted(wt.sources),
            }
            lines = [
                f"# {wt.display_name or _proper_title_case(key)}: {description}",
                "",
                "## Conflict Description",
                "",
                description,
                "",
                "## Affected Cell Types",
                "",
                f"- [{wt.display_name or key}](../cell_types/{key}.md)",
                "",
                "## Sources",
                "",
            ]
            if wt.sources:
                lines.extend(f"- {source}" for source in sorted(wt.sources))
            else:
                lines.append("_(No source identifiers recorded.)_")
            lines.append("")
            _write_entity_page(frontmatter, lines, dest_dir / f"{conflict_id}.md")
    return sorted(page_ids)


def _cell_type_tree_lines(wiki: dict[str, WikiCellType]) -> list[str]:
    """Render the stable parent/child cell-type navigation used by index pages."""
    roots: list[tuple[str, WikiCellType]] = []
    children: dict[str, list[tuple[str, WikiCellType]]] = {}
    for key, wt in sorted(wiki.items()):
        if wt.parent_type and wt.parent_type in wiki:
            children.setdefault(wt.parent_type, []).append((key, wt))
        else:
            roots.append((key, wt))

    lines: list[str] = []
    rendered: set[str] = set()
    for key, wt in roots:
        cl_tag = f" ({wt.cl_id})" if wt.cl_id else ""
        lines.append(f"- [{wt.display_name or _proper_title_case(key)}](cell_types/{key}.md){cl_tag}")
        rendered.add(key)
        for child_key, child_wt in children.get(key, []):
            cl_tag = f" ({child_wt.cl_id})" if child_wt.cl_id else ""
            lines.append(
                f"  - [{child_wt.display_name or _proper_title_case(child_key)}]"
                f"(cell_types/{child_key}.md){cl_tag}"
            )
            rendered.add(child_key)

    for key, wt in sorted(wiki.items()):
        if key in rendered:
            continue
        cl_tag = f" ({wt.cl_id})" if wt.cl_id else ""
        lines.append(f"- [{wt.display_name or _proper_title_case(key)}](cell_types/{key}.md){cl_tag}")
    return lines


def generate_navigation_index_page(
    wiki: dict[str, WikiCellType],
    marker_genes: dict,
    tissues: dict,
    diseases: dict,
    conflict_ids: list[str],
    destination: Path,
    knowledge_version: str,
) -> None:
    """Generate the modern human- and agent-readable root index."""
    source_ids = sorted({source for wt in wiki.values() for source in wt.sources})
    lines = [
        "# CellWiki Index",
        "",
        "## 统计概览",
        f"- 细胞类型页面: {len(wiki)}",
        f"- 标记基因页面: {len(marker_genes)}",
        f"- 组织页面: {len(tissues)}",
        f"- 疾病页面: {len(diseases)}",
        f"- 来源论文: {len(source_ids)}",
        f"- 未解决矛盾: {len(conflict_ids)}",
        f"- 知识库版本: {knowledge_version}",
        "",
        "## 按维度浏览",
        "",
        f"- [按组织](tissues/) -- {', '.join(sorted(tissues)) or '暂无'}",
        f"- [按疾病](diseases/) -- {', '.join(sorted(diseases)) or '暂无'}",
        "",
        "## 按细胞类型",
        "",
    ]
    lines.extend(_cell_type_tree_lines(wiki) or ["_(暂无细胞类型页面)_"])
    lines.extend(["", "## 未解决矛盾", ""])
    if conflict_ids:
        lines.extend(f"- [{conflict_id}](conflicts/{conflict_id}.md)" for conflict_id in conflict_ids)
    else:
        lines.append("_(暂无未解决矛盾)_")
    lines.append("")
    _write_entity_page({}, lines, destination)


def _evidence_tier_distribution(wiki: dict[str, WikiCellType]) -> dict[int, int]:
    """Count cell-type pages by evidence tier."""
    distribution: dict[int, int] = {}
    for wt in wiki.values():
        tier = int(_value_of(wt.evidence_tier))
        distribution[tier] = distribution.get(tier, 0) + 1
    return dict(sorted(distribution.items()))


def generate_overview_page(
    wiki: dict[str, WikiCellType],
    marker_genes: dict,
    tissues: dict,
    diseases: dict,
    conflict_ids: list[str],
    destination: Path,
    knowledge_version: str,
) -> None:
    """Generate dynamic coverage, evidence, and knowledge-gap statistics."""
    source_ids = sorted({source for wt in wiki.values() for source in wt.sources})
    gaps = sorted(
        {
            wt.parent_type
            for wt in wiki.values()
            if wt.parent_type and wt.parent_type not in wiki
        }
    )
    lines = [
        "# CellWiki Overview",
        "",
        f"Knowledge version: {knowledge_version}",
        "",
        "## Entity Counts",
        "",
        "| Entity Type | Pages |",
        "|-------------|-------|",
        f"| cell_type | {len(wiki)} |",
        f"| marker_gene | {len(marker_genes)} |",
        f"| tissue | {len(tissues)} |",
        f"| disease | {len(diseases)} |",
        f"| conflict | {len(conflict_ids)} |",
        "",
        "## Evidence Tier",
        "",
        "| Tier | Cell Type Pages |",
        "|------|-----------------|"]
    lines.extend(
        f"| {tier} | {count} |" for tier, count in _evidence_tier_distribution(wiki).items()
    )
    if not wiki:
        lines.append("| - | 0 |")
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- Source papers: {len(source_ids)}",
            f"- Tissues represented: {', '.join(sorted(tissues)) or 'none'}",
            f"- Diseases represented: {', '.join(sorted(diseases)) or 'none'}",
            "",
            "## Knowledge Gaps",
            "",
        ]
    )
    lines.extend(f"- Parent type without a page: {gap}" for gap in gaps)
    if not gaps:
        lines.append("_(No missing parent pages detected.)_")
    lines.append("")
    _write_entity_page({}, lines, destination)


def build_manifest(
    wiki: dict[str, WikiCellType],
    marker_genes: dict,
    tissues: dict,
    diseases: dict,
    conflict_ids: list[str],
) -> dict:
    """Build a deterministic machine-readable index for downstream agents."""
    pages = [
        {"id": "index", "type": "index", "path": "index.md"},
        {"id": "overview", "type": "overview", "path": "overview.md"},
    ]
    for key, wt in sorted(wiki.items()):
        tissues_for_page, _ = _context_values(wt)
        pages.append(
            {
                "id": key,
                "type": "cell_type",
                "path": f"cell_types/{key}.md",
                "display_name": wt.display_name,
                "cl_id": wt.cl_id,
                "evidence_tier": int(_value_of(wt.evidence_tier)),
                "positive_markers": _positive_marker_symbols(wt),
                "tissues": tissues_for_page,
            }
        )
    for key, data in sorted(marker_genes.items()):
        pages.append(
            {
                "id": key,
                "type": "marker_gene",
                "path": f"marker_genes/{key}.md",
                "source_count": data.get("source_count", 0),
                "evidence_tier": data.get("evidence_tier", 5),
            }
        )
    for key, data in sorted(tissues.items()):
        pages.append(
            {
                "id": key,
                "type": "tissue",
                "path": f"tissues/{key}.md",
                "display_name": data.get("display_name", key),
                "cell_types": sorted(data.get("cell_types_found", {})),
            }
        )
    for key, data in sorted(diseases.items()):
        pages.append(
            {
                "id": key,
                "type": "disease",
                "path": f"diseases/{key}.md",
                "display_name": data.get("display_name", key),
                "cell_types": sorted(data.get("associated_cell_types", {})),
            }
        )
    pages.extend(
        {
            "id": conflict_id,
            "type": "conflict",
            "path": f"conflicts/{conflict_id}.md",
        }
        for conflict_id in sorted(conflict_ids)
    )
    dimensions = {
        "tissues": sorted(tissues),
        "diseases": sorted(diseases),
    }
    payload = {"pages": pages, "dimensions": dimensions}
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    return {"version": f"projection-{digest}", **payload}


def generate_manifest_page(manifest: dict, destination: Path) -> None:
    """Write a previously built manifest as deterministic UTF-8 JSON."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
