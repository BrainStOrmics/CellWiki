import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Graph from "graphology";
import {
  ControlsContainer,
  SigmaContainer,
  ZoomControl,
  useLoadGraph,
  useRegisterEvents,
} from "@react-sigma/core";
import "@react-sigma/core/lib/style.css";
import { Filter, Focus, Network, RefreshCw, Unplug } from "lucide-react";
import { getJson, postJson } from "../../lib/product-api";
import type { GraphNode, GraphNodeType, KnowledgeGraph } from "../../types";
import { useI18n } from "../../i18n";

const nodeColors: Record<GraphNodeType, string> = {
  cell_type: "#5e9cff",
  marker: "#4fd0a3",
  tissue: "#d89b62",
  species: "#c58be2",
  source: "#e5b54d",
  claim: "#8b95a7",
};

function GraphLoader({ data, onSelect }: { data: KnowledgeGraph; onSelect: (nodeId: string) => void }) {
  const loadGraph = useLoadGraph();
  const registerEvents = useRegisterEvents();

  useEffect(() => {
    const graph = new Graph({ multi: true, type: "directed" });
    data.nodes.forEach((node, index) => {
      const angle = (index / Math.max(1, data.nodes.length)) * Math.PI * 2;
      graph.addNode(node.node_id, {
        label: node.label,
        x: Math.cos(angle),
        y: Math.sin(angle),
        size: node.type === "cell_type" ? 11 : node.type === "source" ? 8 : 6,
        color: nodeColors[node.type],
      });
    });
    data.edges.forEach((edge) => {
      if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
        graph.addDirectedEdgeWithKey(edge.edge_id, edge.source, edge.target, {
          label: edge.type,
          size: Math.max(1, Math.min(4, edge.evidence_count)),
          color: edge.type === "contradicts" ? "#d76565" : "#3b4555",
        });
      }
    });
    loadGraph(graph);
  }, [data, loadGraph]);

  useEffect(() => registerEvents({ clickNode: ({ node }) => onSelect(node) }), [registerEvents, onSelect]);
  return null;
}

type GraphWorkspaceProps = {
  focus?: string | null;
  onOpenPage: (pageId: string) => void;
  onOpenSource: (sourceId: string) => void;
};

export function GraphWorkspace({ focus, onOpenPage, onOpenSource }: GraphWorkspaceProps) {
  const { t } = useI18n();
  const [selectedId, setSelectedId] = useState<string | null>(focus ?? null);
  const [localFocus, setLocalFocus] = useState<string | null>(focus ?? null);
  const [types, setTypes] = useState<GraphNodeType[]>([]);
  const query = useMemo(() => {
    const parameters = new URLSearchParams({ limit: "600" });
    if (localFocus) parameters.set("focus", localFocus);
    types.forEach((type) => parameters.append("node_type", type));
    return `/api/graph?${parameters}`;
  }, [localFocus, types]);
  const graph = useQuery({
    queryKey: ["knowledge-graph", localFocus, types],
    queryFn: () => getJson<KnowledgeGraph>(query),
  });
  const selected = graph.data?.nodes.find((node) => node.node_id === selectedId);

  async function rebuild() {
    await postJson("/api/discovery/rebuild", {});
    await graph.refetch();
  }

  return (
    <div className="graph-workspace">
      <header className="feature-header">
        <div><Network size={17} /><span><strong>{t("graph.title")}</strong><small>{localFocus ? t("graph.local") : t("graph.global")}</small></span></div>
        <span className="feature-header-actions">
          <button onClick={() => setLocalFocus((current) => current ? null : focus ?? null)}><Focus size={14} />{localFocus ? t("graph.globalView") : t("graph.pageView")}</button>
          <button onClick={() => void rebuild()}><RefreshCw size={14} />{t("graph.rebuild")}</button>
        </span>
      </header>
      <div className="graph-filter-bar">
        <Filter size={13} />
        {(Object.keys(nodeColors) as GraphNodeType[]).map((type) => (
          <button
            key={type}
            className={types.includes(type) ? "active" : ""}
            onClick={() => setTypes((current) => current.includes(type) ? current.filter((item) => item !== type) : [...current, type])}
          >
            <i style={{ background: nodeColors[type] }} />{type.replaceAll("_", " ")}
          </button>
        ))}
      </div>
      <div className="graph-stage">
        {graph.isLoading && <div className="feature-state"><RefreshCw className="spin" />{t("graph.loading")}</div>}
        {graph.isError && <div className="feature-state error"><Unplug />{t("graph.error")}</div>}
        {graph.data && graph.data.nodes.length === 0 && <div className="feature-state"><Network />{t("graph.empty")}</div>}
        {graph.data && graph.data.nodes.length > 0 && (
          <SigmaContainer settings={{ renderEdgeLabels: false, labelDensity: 0.08, labelGridCellSize: 90 }}>
            <GraphLoader data={graph.data} onSelect={setSelectedId} />
            <ControlsContainer position="bottom-right"><ZoomControl /></ControlsContainer>
          </SigmaContainer>
        )}
        {selected && (
          <aside className="graph-inspector">
            <span className={`graph-node-kind ${selected.type}`}><i style={{ background: nodeColors[selected.type] }} />{selected.type.replaceAll("_", " ")}</span>
            <h3>{selected.label}</h3>
            <code>{selected.node_id}</code>
            <div className="graph-inspector-actions">
              {selected.page_id && <button onClick={() => onOpenPage(selected.page_id!)}><Focus size={13} />{t("graph.openWiki")}</button>}
              {selected.source_id && <button onClick={() => onOpenSource(selected.source_id!)}><Focus size={13} />{t("graph.openEvidence")}</button>}
            </div>
          </aside>
        )}
      </div>
      <footer className="graph-footer">
        <span>{graph.data?.nodes.length ?? 0} {t("common.nodes")}</span>
        <span>{graph.data?.edges.length ?? 0} {t("common.edges")}</span>
        {graph.data?.truncated && <strong>{t("graph.truncated")}</strong>}
      </footer>
    </div>
  );
}
