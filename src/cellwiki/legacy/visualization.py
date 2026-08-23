# =============================================================================
# 可视化 —— 以 JSON、DOT 和 Mermaid 格式生成关系图
# =============================================================================
# 加载合并的 Wiki 数据，解析 CL ID 以丰富显示内容，
# 并写入三种图形表示以及可选的 SVG 渲染。
# 输出文件可用于第三方图谱可视化工具（如 Graphviz、Mermaid 等）。
# =============================================================================

"""Generate relationship graph in JSON, DOT, and Mermaid formats.

Loads merged wiki data, resolves CL IDs for display enrichment, and
writes three graph representations plus an optional SVG render."""

import json
from pathlib import Path
from cellwiki.config import settings
from cellwiki.knowledge import load_all_extractions, merge_to_wiki


def _escape_dot_label(text: str) -> str:
    """Escape special characters for DOT graph labels."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _escape_mermaid_label(text: str) -> str:
    """Escape special characters for Mermaid graph labels."""
    return text.replace('"', '&quot;').replace("]", "&#93;")


def generate_relationship_graph():
    """Generate all three graph formats from current wiki data.

    Loads extractions, merges them, resolves CL IDs for display, then
    writes JSON, DOT, and Mermaid files.  Optionally renders DOT to SVG.
    """
    extractions = load_all_extractions()
    if not extractions:
        print("No extractions found. Add papers first.")
        return

    wiki = merge_to_wiki(extractions)

    # Resolve CL IDs after merge — enrichment for graph display, not
    # required for ontology merging.  Skips cells already resolved.
    from cellwiki.legacy.ontology import load_cell_ontology, load_cl_id_registry, load_manual_corrections, resolve_cell_type_to_cl
    ontology = load_cell_ontology()
    registry = load_cl_id_registry()
    corrections = load_manual_corrections()
    for key, wt in wiki.items():
        if not wt.cl_id:
            wt.cl_id = resolve_cell_type_to_cl(wt.display_name or key, ontology, registry, corrections)

    # 1. JSON relationships
    # Edge direction: parent_type → child has "is_a" edge child→parent;
    # subpopulations get the reverse edge from subpopulation→parent.
    rel_data = {"nodes": [], "edges": []}
    for key, wt in wiki.items():
        rel_data["nodes"].append({
            "id": key,
            "label": wt.display_name or key,
            "cl_id": wt.cl_id,
        })
        if wt.parent_type:
            rel_data["edges"].append({
                "source": key,
                "target": wt.parent_type,
                "relation": "is_a",
            })
        for sub in wt.subpopulations:
            rel_data["edges"].append({
                "source": sub.lower().replace(" ", "_"),
                "target": key,
                "relation": "is_a",
            })

    json_path = settings.wiki_dir / "relationships.json"
    with open(json_path, "w") as f:
        json.dump(rel_data, f, indent=2, ensure_ascii=False)

    # 2. DOT format (Graphviz)
    # rankdir=BT so root types appear at the bottom, subtypes above.
    dot_lines = [
        "digraph CellTypes {",
        '  rankdir=BT;',
        '  node [shape=box, style=rounded, fontname="Helvetica"];',
        "",
    ]
    for key, wt in wiki.items():
        label = _escape_dot_label(wt.display_name or key)
        cl_tag = f"\\n{wt.cl_id}" if wt.cl_id else ""
        dot_lines.append(f'  "{key}" [label="{label}{cl_tag}"];')
    dot_lines.append("")
    for key, wt in wiki.items():
        # Guard against dangling edges: skip if parent_type is not in
        # the wiki (e.g. from a paper that references an unresolved type).
        if wt.parent_type and wt.parent_type in wiki:
            dot_lines.append(f'  "{key}" -> "{wt.parent_type}" [label="is_a"];')
    dot_lines.append("}")

    dot_path = settings.wiki_dir / "graph.dot"
    with open(dot_path, "w") as f:
        f.write("\n".join(dot_lines) + "\n")

    # 3. Mermaid format
    # Mermaid requires unique node IDs (no spaces), so we use the
    # internal key (underscored) rather than the display name.
    mmd_lines = [
        "graph BT",
    ]
    for key, wt in wiki.items():
        label = _escape_mermaid_label(wt.display_name or key)
        mmd_lines.append(f'  {key}["{label}"]')
    mmd_lines.append("")
    for key, wt in wiki.items():
        if wt.parent_type and wt.parent_type in wiki:
            parent_id = wt.parent_type
            mmd_lines.append(f"  {key} --> {parent_id}")

    mmd_path = settings.wiki_dir / "graph.mmd"
    with open(mmd_path, "w") as f:
        f.write("\n".join(mmd_lines) + "\n")

    # 4. Render SVG if graphviz is available
    # Graceful degradation: missing binary or library is non-fatal.
    _render_dot_to_svg(dot_path)


def _render_dot_to_svg(dot_path: Path) -> Path | None:
    """Render graph.dot to graph.svg using the graphviz Python library.

    Returns the SVG path if successful, None otherwise.
    """
    svg_path = dot_path.with_suffix(".svg")
    try:
        import graphviz as gv
        with open(dot_path) as f:
            dot_source = f.read()
        gv.Source(source=dot_source, format="svg").render(
            str(svg_path.with_suffix("")),
            cleanup=False,
        )
        print(f"  Rendered graph to {svg_path.resolve()}")
        return svg_path
    except ImportError:
        print("  SVG render skipped: install `pip install graphviz` and system graphviz")
        return None
    except gv.backend.ExecutableNotFound:
        # graphviz library found but system binary (dot) missing.
        print("  SVG render skipped: graphviz system binary (dot) not found")
        return None
    except Exception as e:
        # Catch-all — graphviz can raise on malformed DOT or file I/O.
        print(f"  SVG render failed: {e}")
        return None
