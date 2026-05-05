"""Knowledge graph analysis for CellWiki.

Multi-layer relationship graph, community detection, bridge nodes, knowledge gaps.
Defined in MASTER_PLAN.md Section 4.7.

Usage:
    from cellwiki.graph_analysis import CellWikiGraph
    graph = CellWikiGraph.build()
    insights = graph.analyze()
"""

import json
import logging
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

# Try to import networkx
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


# Relationship types
RELATION_TYPES = {
    "is_a": "cell type hierarchy",
    "expresses": "cell -> gene expression",
    "found_in": "cell -> tissue distribution",
    "associated_with": "cell/gene -> disease",
    "studied_by": "method -> study",
    "differentiates_to": "trajectory transition",
    "inhibits": "functional inhibition",
    "co_expressed": "gene co-expression",
}


class CellWikiGraph:
    """Multi-layer knowledge graph for CellWiki."""

    def __init__(self):
        self.G = None
        self.insights = {}

    @classmethod
    def build(cls):
        """Build the graph from wiki data."""
        from cellwiki.config import settings

        graph = cls()

        if not HAS_NETWORKX:
            logger.warning("networkx not installed. Install with: pip install networkx")
            return graph

        G = nx.DiGraph()

        # Load cell types
        ct_dir = settings.wiki_cell_types_dir
        if ct_dir.exists():
            for page_file in ct_dir.glob("*.md"):
                page_id = page_file.stem
                G.add_node(page_id, type="cell_type", label=page_id)

                # Parse frontmatter for relationships
                content = page_file.read_text(encoding="utf-8")

                # Extract parent_type
                import re
                parent_match = re.search(r'parent_type:\s*\w+', content)
                if parent_match:
                    parent = parent_match.group(1)
                    G.add_node(parent, type="cell_type", label=parent)
                    G.add_edge(page_id, parent, relation="is_a")

                # Extract wikilinks as relationships
                wikilinks = re.findall(r'\[\[(.+?)\]\]', content)
                for link in wikilinks:
                    if link != page_id:
                        G.add_edge(page_id, link, relation="references")

        # Load marker genes if directory exists
        mg_dir = settings.wiki_marker_genes_dir
        if mg_dir.exists():
            for page_file in mg_dir.glob("*.md"):
                page_id = page_file.stem
                G.add_node(page_id, type="marker_gene", label=page_id)

        graph.G = G
        return graph

    def analyze(self) -> dict:
        """Run graph analysis and return insights."""
        if self.G is None or not HAS_NETWORKX:
            return {"error": "Graph not built or networkx not available"}

        G = self.G
        insights = {}

        # 1. Basic stats
        insights["total_nodes"] = G.number_of_nodes()
        insights["total_edges"] = G.number_of_edges()

        # 2. Node types
        type_counts = defaultdict(int)
        for node, data in G.nodes(data=True):
            node_type = data.get("type", "unknown")
            type_counts[node_type] += 1
        insights["node_types"] = dict(type_counts)

        # 3. Hub nodes (highest degree)
        degrees = dict(G.degree())
        sorted_nodes = sorted(degrees.items(), key=lambda x: x[1], reverse=True)
        insights["top_hubs"] = [{"node": n, "degree": d} for n, d in sorted_nodes[:10]]

        # 4. Isolated nodes (degree <= 1)
        isolated = [n for n, d in G.degree() if d <= 1]
        insights["isolated_nodes"] = isolated[:20]

        # 5. Weakly connected components
        components = list(nx.weakly_connected_components(G))
        insights["components"] = len(components)
        if len(components) > 1:
            insights["component_sizes"] = sorted([len(c) for c in components], reverse=True)

        # 6. Try Louvain community detection
        try:
            import community as community_louvain
            partition = community_louvain.best_partition(G.to_undirected())
            communities = defaultdict(list)
            for node, comm_id in partition.items():
                communities[comm_id].append(node)
            insights["communities"] = {
                str(k): {"size": len(v), "members": v[:10]}
                for k, v in sorted(communities.items(), key=lambda x: -len(x[1]))
            }
        except ImportError:
            insights["communities"] = "Install python-louvain for community detection"

        # 7. Bridge nodes (connect different parts)
        try:
            betweenness = nx.betweenness_centrality(G)
            sorted_betweenness = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)
            insights["bridge_nodes"] = [{"node": n, "betweenness": round(b, 4)}
                                        for n, b in sorted_betweenness[:10]]
        except Exception:
            insights["bridge_nodes"] = "Could not compute betweenness"

        # 8. Knowledge gaps
        knowledge_gaps = []
        for node in isolated[:10]:
            knowledge_gaps.append({
                "type": "isolated_page",
                "entity": node,
                "suggestion": f"Page '{node}' has no connections. Consider adding links.",
            })
        insights["knowledge_gaps"] = knowledge_gaps

        self.insights = insights
        return insights

    def export_dot(self, path: str = None) -> str:
        """Export graph to DOT format for Graphviz."""
        if self.G is None:
            return ""

        lines = ["digraph CellWiki {"]
        lines.append('  rankdir=BT;')
        lines.append('  node [shape=box, style=rounded, fontname="Helvetica"];')

        # Color by type
        type_colors = {
            "cell_type": "#4CAF50",
            "marker_gene": "#2196F3",
            "tissue": "#FF9800",
            "disease": "#F44336",
            "method": "#9C27B0",
            "trajectory": "#00BCD4",
        }

        for node, data in self.G.nodes(data=True):
            node_type = data.get("type", "unknown")
            color = type_colors.get(node_type, "#9E9E9E")
            label = data.get("label", node)
            lines.append(f'  "{node}" [label="{label}", fillcolor="{color}", style=filled];')

        for source, target, data in self.G.edges(data=True):
            relation = data.get("relation", "references")
            lines.append(f'  "{source}" -> "{target}" [label="{relation}"];')

        lines.append("}")

        dot_content = "\n".join(lines)

        if path:
            with open(path, "w") as f:
                f.write(dot_content)

        return dot_content

    def to_json(self) -> dict:
        """Export graph as JSON."""
        if self.G is None:
            return {"nodes": [], "edges": []}

        nodes = []
        for node, data in self.G.nodes(data=True):
            nodes.append({"id": node, **data})

        edges = []
        for source, target, data in self.G.edges(data=True):
            edges.append({"source": source, "target": target, **data})

        return {"nodes": nodes, "edges": edges}


def build_and_analyze():
    """Build graph, run analysis, and print insights."""
    graph = CellWikiGraph.build()
    insights = graph.analyze()

    print("\n" + "=" * 60)
    print("CellWiki Knowledge Graph Analysis")
    print("=" * 60)

    print(f"\nNodes: {insights.get('total_nodes', 0)}")
    print(f"Edges: {insights.get('total_edges', 0)}")
    print(f"Node types: {insights.get('node_types', {})}")
    print(f"Components: {insights.get('components', 0)}")

    if insights.get("top_hubs"):
        print(f"\nTop hubs:")
        for h in insights["top_hubs"][:5]:
            print(f"  {h['node']}: degree {h['degree']}")

    if insights.get("isolated_nodes"):
        print(f"\nIsolated pages ({len(insights['isolated_nodes'])}):")
        for n in insights["isolated_nodes"][:10]:
            print(f"  - {n}")

    return graph, insights

