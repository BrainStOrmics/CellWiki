"""Generate relationship graph in JSON, DOT, and Mermaid formats."""

import json
from pathlib import Path
from cellwiki.config import settings
from cellwiki.models import WikiCellType
from cellwiki.knowledge import load_all_extractions, merge_to_wiki


def generate_relationship_graph():
    """Generate all three graph formats from current wiki data."""
    extractions = load_all_extractions()
    if not extractions:
        print("No extractions found. Add papers first.")
        return

    wiki = merge_to_wiki(extractions)

    # Resolve CL IDs
    from cellwiki.ontology import load_cell_ontology, resolve_cell_type_to_cl
    ontology = load_cell_ontology()
    for key, wt in wiki.items():
        if not wt.cl_id:
            wt.cl_id = resolve_cell_type_to_cl(wt.display_name or key, ontology)

    # 1. JSON relationships
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
    dot_lines = [
        "digraph CellTypes {",
        '  rankdir=BT;',
        '  node [shape=box, style=rounded, fontname="Helvetica"];',
        "",
    ]
    for key, wt in wiki.items():
        label = wt.display_name or key
        cl_tag = f"\\n{wt.cl_id}" if wt.cl_id else ""
        dot_lines.append(f'  "{key}" [label="{label}{cl_tag}"];')
    dot_lines.append("")
    for key, wt in wiki.items():
        if wt.parent_type and wt.parent_type in wiki:
            dot_lines.append(f'  "{key}" -> "{wt.parent_type}" [label="is_a"];')
    dot_lines.append("}")

    dot_path = settings.wiki_dir / "graph.dot"
    with open(dot_path, "w") as f:
        f.write("\n".join(dot_lines) + "\n")

    # 3. Mermaid format
    mmd_lines = [
        "graph BT",
    ]
    for key, wt in wiki.items():
        label = wt.display_name or key
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
        print("  SVG render skipped: graphviz system binary (dot) not found")
        return None
    except Exception as e:
        print(f"  SVG render failed: {e}")
        return None
