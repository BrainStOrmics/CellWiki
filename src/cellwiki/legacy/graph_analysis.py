# =============================================================================
# 知识图谱分析 —— CellWiki 的多层有向图构建与分析
# =============================================================================
# 从 Wiki 页面数据（细胞类型、标记基因、Wiki 链接、前置元数据）构建多层
# 有向图，并运行结构分析：基于 Louvain 算法的社区检测、基于介数中心性的
# 桥接节点识别、连通组件分析和孤立页面的知识缺口检测。
# 设计用于发现细胞类型本体论中缺失的链接和聚类模式。
# =============================================================================

"""Knowledge graph analysis for CellWiki.

Builds a multi-layer directed graph from wiki page data (cell types, marker genes,
wikilinks, frontmatter) and runs structural analyses: community detection via Louvain,
bridge-node identification via betweenness centrality, connectivity components, and
knowledge-gap detection for isolated pages.  Designed to surface missing links and
clustering patterns in the cell-type ontology.

Usage:
    from cellwiki.graph_analysis import CellWikiGraph
    graph = CellWikiGraph.build()
    insights = graph.analyze()
"""

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# networkx is optional; all graph methods degrade gracefully when it is absent
# so the rest of the codebase never needs to guard against ImportError.
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


# Canonical edge semantics.  Keys are stored as edge attributes under "relation"
# so downstream consumers can filter or style by relationship type.
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
    """Multi-layer directed graph over CellWiki pages with analysis methods.

    Nodes are wiki pages (cell types, marker genes, etc.); edges represent
    typed relationships parsed from page frontmatter and wikilinks.  Analysis
    results are cached in the ``insights`` dict after a call to ``analyze()``.
    """

    def __init__(self):
        self.G = None
        self.insights = {}

    @classmethod
    def build(cls):
        """Factory: parse all wiki pages and return a populated CellWikiGraph."""
        from cellwiki.config import settings

        graph = cls()

        if not HAS_NETWORKX:
            logger.warning("networkx not installed. Install with: pip install networkx")
            return graph

        G = nx.DiGraph()

        # Load cell types — each .md page becomes a node; frontmatter
        # and wikilinks supply the edges.
        ct_dir = settings.wiki_cell_types_dir
        if ct_dir.exists():
            for page_file in ct_dir.glob("*.md"):
                page_id = page_file.stem
                G.add_node(page_id, type="cell_type", label=page_id)

                content = page_file.read_text(encoding="utf-8")

                # parent_type in frontmatter defines an "is_a" edge,
                # creating a lightweight ontology hierarchy.
                import re
                parent_match = re.search(r'parent_type:\s*\w+', content)
                if parent_match:
                    parent = parent_match.group(1)
                    G.add_node(parent, type="cell_type", label=parent)
                    G.add_edge(page_id, parent, relation="is_a")

                # Wikilinks [[...]] represent cross-references; treat them
                # as directional edges from the current page to the target.
                wikilinks = re.findall(r'\[\[(.+?)\]\]', content)
                for link in wikilinks:
                    if link != page_id:
                        G.add_edge(page_id, link, relation="references")

        # Load marker genes as standalone nodes; they gain edges later
        # when cell-type pages reference them via wikilinks.
        mg_dir = settings.wiki_marker_genes_dir
        if mg_dir.exists():
            for page_file in mg_dir.glob("*.md"):
                page_id = page_file.stem
                G.add_node(page_id, type="marker_gene", label=page_id)

        graph.G = G
        return graph

    def analyze(self) -> dict:
        """Run full graph analysis and return a dict of insights.

        Metrics computed: node/edge counts, type distribution, hub nodes
        (highest degree), isolated nodes, weakly connected components,
        Louvain communities (if python-louvain is installed), betweenness
        centrality-based bridge nodes, and knowledge-gap candidates.
        """
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
        # Degree <= 1 means the node has at most one connection — effectively
        # isolated or a leaf in the graph.  These are candidates for enrichment.
        isolated = [n for n, d in G.degree() if d <= 1]
        insights["isolated_nodes"] = isolated[:20]

        # 5. Weakly connected components
        # Using WCC (not SCC) because a directed edge from A to B still means
        # A and B belong to the same conceptual cluster even if there is no
        # reverse edge.
        components = list(nx.weakly_connected_components(G))
        insights["components"] = len(components)
        if len(components) > 1:
            insights["component_sizes"] = sorted([len(c) for c in components], reverse=True)

        # 6. Try Louvain community detection
        # python-louvain is an optional dependency; we fall back gracefully.
        # Louvain works on undirected graphs, so we convert for this step.
        try:
            import community as community_louvain  # python-louvain package
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
        # Betweenness centrality measures how often a node lies on shortest
        # paths between others — high values indicate potential bridges.
        # Wrapped in try/except because the computation can be expensive
        # on large graphs and may also fail on disconnected graphs.
        try:
            betweenness = nx.betweenness_centrality(G)
            sorted_betweenness = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)
            insights["bridge_nodes"] = [{"node": n, "betweenness": round(b, 4)}
                                        for n, b in sorted_betweenness[:10]]
        except Exception:
            insights["bridge_nodes"] = "Could not compute betweenness"

        # 8. Knowledge gaps
        # Any isolated node is a candidate gap: it has no connections in the
        # graph, suggesting missing links in the wiki content.
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
        """Export graph to DOT format for Graphviz visualization."""
        if self.G is None:
            return ""

        lines = ["digraph CellWiki {"]
        lines.append('  rankdir=BT;')
        lines.append('  node [shape=box, style=rounded, fontname="Helvetica"];')

        # Map node types to distinct colors so the visual output immediately
        # distinguishes cell types, genes, tissues, etc.
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
        """Export graph as a JSON-serializable dict with nodes and edges arrays."""
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
    """Convenience entry point: build the graph, run analysis, print results."""
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
        print("\nTop hubs:")
        for h in insights["top_hubs"][:5]:
            print(f"  {h['node']}: degree {h['degree']}")

    if insights.get("isolated_nodes"):
        print(f"\nIsolated pages ({len(insights['isolated_nodes'])}):")
        for n in insights["isolated_nodes"][:10]:
            print(f"  - {n}")

    return graph, insights