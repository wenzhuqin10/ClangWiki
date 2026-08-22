import { useEffect, useRef } from "react";
import cytoscape, { Core } from "cytoscape";
import dagre from "cytoscape-dagre";
import fcose from "cytoscape-fcose";
import svg from "cytoscape-svg";
import { Download, Focus, Minus, Plus } from "lucide-react";

cytoscape.use(dagre);
cytoscape.use(fcose);
cytoscape.use(svg);

type GraphPayload = { nodes: any[]; edges: any[]; truncated?: boolean };
type Level = "repository" | "module" | "file" | "symbol";
type GraphView = "hierarchy" | "callflow" | "dataflow" | "impact" | "community" | "dependency" | "interface" | "knowledge" | "coremap" | "surprises";
type Props = {
  graph: GraphPayload;
  level: Level;
  view?: GraphView;
  selectedNodeId?: string | null;
  selectedEdgeId?: string | null;
  showLabels?: boolean;
  showEdgeLabels?: boolean;
  pathNodeIds?: string[];
  onSelect: (node: any | null) => void;
  onSelectEdge?: (edge: any | null) => void;
  onPathPick?: (node: any) => void;
};

const nodeColors: Record<string, string> = {
  repository: "#5965d8", module: "#7581e8", file: "#48a487", symbol: "#d59649",
  domain: "#d55f6b", document: "#9c6ad6", community: "#5965d8", external: "#8b93a4",
};
const relationColors: Record<string, string> = {
  CONTAINS: "#8d98aa", DEPENDS_ON: "#6674da", INCLUDES: "#43a080", CALLS: "#4f5fd3",
  POSSIBLE_CALL: "#d59649", REFERENCES: "#9d62b4", READS: "#3d91b7", WRITES: "#d55f6b",
  USES_TYPE: "#71839b", CONFIGURES: "#ba6b3d", IMPLEMENTS_CHANNEL: "#d55f6b",
  ALLOCATES: "#c77b51", INITIALIZES: "#ad9b56", OWNS: "#a469c0", BORROWS: "#6a9cc4",
  RELEASES: "#d26d66", LOCKS: "#b8784f", UNLOCKS: "#70a587",
  PARTICIPATES_IN: "#b38842", DOCUMENTS: "#9c6ad6", MATCHES_DECLARATION: "#4c70a8",
  SURPRISING_CONNECTION: "#ffb347",
};

function nodeLabel(node: any, level: Level): string {
  if (level === "file" && node.path) {
    const pieces = String(node.path).split(/[\\/]/).filter(Boolean);
    return pieces.slice(-2).join("/") || String(node.display_name || node.name || node.id);
  }
  return String(node.display_name || node.name || node.qualified_name || node.id);
}

function sizeFor(node: any, level: Level): number {
  if (node.kind === "community") return Math.max(38, Math.min(92, 30 + Math.sqrt(Number(node.member_count || 1)) * 7));
  const degree = Number(node.metrics?.degree || node.degree || 0);
  const base = level === "repository" ? 42 : level === "module" ? 30 : level === "file" ? 16 : 14;
  return Math.max(base, Math.min(base + 22, base + Math.sqrt(degree) * 2.4));
}

function shapeFor(node: any): cytoscape.Css.NodeShape {
  if (node.kind === "repository" || node.kind === "file") return "round-rectangle";
  if (node.kind === "module" || node.kind === "community") return "ellipse";
  if (node.kind === "domain") return "diamond";
  if (node.kind === "document") return "tag";
  if (["struct", "union", "enum", "typedef"].includes(node.subtype)) return "round-hexagon";
  if (["field", "parameter", "enum_value"].includes(node.subtype)) return "rectangle";
  return "hexagon";
}

export default function GraphCanvas({
  graph, level, view = "hierarchy", selectedNodeId, selectedEdgeId, showLabels = true,
  showEdgeLabels = false, pathNodeIds = [], onSelect, onSelectEdge, onPathPick,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<Core | null>(null);

  const fitView = () => {
    const cy = instance.current;
    if (!cy || cy.destroyed()) return;
    cy.fit(undefined, view === "community" || view === "coremap" || view === "surprises" ? 90 : 65);
    if (cy.zoom() > (view === "coremap" ? 1.2 : 1.08)) { cy.zoom(view === "coremap" ? 1.2 : 1.08); cy.center(); }
  };

  useEffect(() => {
    if (!host.current) return;
    instance.current?.destroy();
    const focusView = view === "coremap" || view === "surprises";
    const endpointIds = new Set((graph.edges || []).flatMap((edge: any) => [edge.source, edge.target]));
    const positions = focusPositions(graph.nodes, graph.edges, view);
    const elements = [
      ...graph.nodes.map((node) => ({ data: {
        ...node, label: nodeLabel(node, level), size: node.metrics?.is_hub ? Math.max(56, sizeFor(node, level) * 1.45) : sizeFor(node, level),
         fill: node.impact_tier === 0 ? "#ff9b3d" : node.impact_tier === 1 ? "#e86d5c" : node.impact_tier === 2 ? "#d59c4a" : node.impact_tier === 3 ? "#6485be" : node.color || nodeColors[String(node.kind)] || "#8b93a4",
        shape: focusView || view === "community" ? "ellipse" : shapeFor(node), compact: showLabels && (!focusView || Boolean(node.metrics?.is_hub) || endpointIds.has(node.id)) ? "false" : "true",
         god: node.metrics?.is_hub || node.impact_tier === 0 ? "true" : "false",
         impactTier: String(node.impact_tier ?? ""),
        focusEndpoint: endpointIds.has(node.id) ? "true" : "false",
        path: pathNodeIds.includes(node.id) ? "true" : "false",
      }, position: positions.get(node.id) })),
      ...graph.edges.map((edge) => ({ data: {
        ...edge, label: showEdgeLabels ? (edge.relation_label || edge.kind || "关系") : "",
        edgeColor: relationColors[String(edge.kind)] || "#a7afbd",
        insightKind: edge.insight_kind || "",
        aggregateWidth: Math.max(1, Math.min(7, 1 + Math.log2(Number(edge.count || edge.weight || 1)))),
      } })),
    ];
    const cy = cytoscape({
      container: host.current, elements,
      style: [
        { selector: "node", style: {
          "background-color": "data(fill)", shape: (element) => element.data("shape") as cytoscape.Css.NodeShape, width: "data(size)", height: "data(size)",
          label: "data(label)", color: "#dce3f1", "font-size": level === "module" ? 11 : 9,
          "font-family": "Inter, Microsoft YaHei UI, Microsoft YaHei, sans-serif", "font-weight": 500,
          "min-zoomed-font-size": 8, "text-valign": "bottom", "text-halign": "center", "text-margin-y": 8,
          "text-wrap": "ellipsis", "text-max-width": view === "community" ? "160px" : level === "module" ? "150px" : "124px",
          "text-background-color": "#11141b", "text-background-opacity": focusView ? 0.76 : 0,
          "text-background-padding": focusView ? "3px" : "0px",
          "border-width": 1.2, "border-color": "#202733", "overlay-opacity": 0,
        } },
        { selector: "node[compact = 'true']", style: { label: "" } },
         { selector: "node[god = 'true']", style: {
          "background-color": "#ff9b3d", "border-color": "#ffd49a", "border-width": 3,
          "underlay-color": "#ff8a36", "underlay-opacity": 0.62, "underlay-padding": 18, "underlay-shape": "ellipse",
          "z-index": 20,
          label: "data(label)", "font-size": 12, "font-weight": 700, color: "#fff",
          "text-valign": "center", "text-margin-y": 0,
          "text-background-color": "#19130e", "text-background-opacity": 0.18,
          "text-background-padding": "3px",
         } },
         { selector: "node[impactTier = '1']", style: { "border-color": "#ff7669", "border-width": 3 } },
         { selector: "node[impactTier = '2']", style: { "border-color": "#e3b15d", "border-width": 2.2 } },
         { selector: "node[impactTier = '3']", style: { "border-color": "#83a9e4", "border-width": 2 } },
        { selector: "node[focusEndpoint = 'true']", style: { "border-color": "#ffcf70", "border-width": 2.5 } },
        { selector: "node[path = 'true']", style: { "border-color": "#161a25", "border-width": 4, label: "data(label)", "z-index": 12 } },
        { selector: "node:selected", style: { "border-color": "#161a25", "border-width": 4, label: "data(label)", "z-index": 15 } },
        { selector: "edge", style: {
          width: "data(aggregateWidth)", "line-color": "data(edgeColor)", "target-arrow-color": "data(edgeColor)",
           "target-arrow-shape": "triangle", "curve-style": ["community", "coremap", "surprises", "impact"].includes(view) ? "bezier" : "taxi",
          "taxi-direction": "rightward", "arrow-scale": 0.55, opacity: focusView ? 0.48 : 0.44, label: "data(label)",
          color: "#cbd5e8", "font-size": 8, "font-family": "Inter, Microsoft YaHei UI, sans-serif",
          "min-zoomed-font-size": 7, "text-background-color": "#11141b", "text-background-opacity": 0.9,
          "text-background-padding": "3px", "text-margin-y": -7,
        } },
        { selector: "edge[insightKind = 'surprising_connection']", style: {
          "line-color": "#ffb347", "target-arrow-color": "#ffb347", width: 3.2,
          "line-style": "solid", opacity: 0.95, "curve-style": "bezier",
          "underlay-color": "#ff9b3d", "underlay-opacity": 0.32, "underlay-padding": 4,
          "z-index": 11,
        } },
        { selector: "edge[status = 'candidate']", style: { "line-style": "dashed", opacity: 0.72 } },
        { selector: "edge[origin = 'rule']", style: { "line-style": "dotted" } },
        { selector: "edge:selected", style: { width: 4, opacity: 1, "z-index": 10 } },
      ],
      layout: { name: "preset" }, minZoom: 0.08, maxZoom: 2.5,
    });
    const layout = cy.layout(layoutFor(view, level, graph.nodes.length));
    layout.on("layoutstop", () => {
      if (cy.destroyed()) return;
      cy.fit(undefined, view === "community" || view === "coremap" || view === "surprises" ? 90 : 65);
      if (cy.zoom() > (view === "coremap" ? 1.2 : 1.08)) { cy.zoom(view === "coremap" ? 1.2 : 1.08); cy.center(); }
    });
    layout.run();
    cy.on("tap", "node", (event) => {
      const data = event.target.data();
      if (event.originalEvent?.shiftKey && onPathPick) { onPathPick(data); return; }
      cy.elements().unselect(); event.target.select(); onSelect(data); onSelectEdge?.(null);
    });
    cy.on("tap", "edge", (event) => {
      cy.elements().unselect(); event.target.select(); onSelectEdge?.(event.target.data()); onSelect(null);
    });
    cy.on("tap", (event) => {
      if (event.target === cy) { cy.elements().unselect(); onSelect(null); onSelectEdge?.(null); }
    });
    const resizeObserver = new ResizeObserver(() => {
      cy.resize();
      requestAnimationFrame(fitView);
    });
    resizeObserver.observe(host.current);
    instance.current = cy;
    return () => {
      resizeObserver.disconnect();
      if (instance.current === cy) instance.current = null;
      cy.destroy();
    };
  }, [graph, level, view, showLabels, showEdgeLabels, pathNodeIds.join("|"), onSelect, onSelectEdge, onPathPick]);

  useEffect(() => {
    const cy = instance.current;
    if (!cy) return;
    cy.elements().unselect();
    if (selectedNodeId) cy.getElementById(selectedNodeId).select();
    if (selectedEdgeId) cy.getElementById(selectedEdgeId).select();
  }, [selectedNodeId, selectedEdgeId]);

  const download = (kind: "json" | "png" | "svg") => {
    const cy = instance.current;
    if (!cy) return;
    if (kind === "png") {
      const link = document.createElement("a");
      link.href = cy.png({ full: true, scale: 2, bg: "#0d0f14" });
      link.download = "clangwiki-graph.png"; link.click(); return;
    }
    const content = kind === "json" ? JSON.stringify({ nodes: graph.nodes, edges: graph.edges }, null, 2) : (cy as any).svg({ full: true, scale: 1 });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([content], { type: kind === "json" ? "application/json" : "image/svg+xml" }));
    link.download = `clangwiki-graph.${kind}`; link.click(); URL.revokeObjectURL(link.href);
  };

  return <div className={`graph-stage graph-stage-v2 ${view === "coremap" ? "graph-focus-stage graph-god-stage" : view === "surprises" ? "graph-focus-stage graph-surprise-stage" : ""}`}>
    <div className="graph-toolbar floating graph-camera-tools">
      <button className="icon-button" title="适应窗口" onClick={fitView}><Focus size={16} /></button>
      <button className="icon-button" title="放大" onClick={() => instance.current?.zoom({ level: (instance.current?.zoom() || 1) * 1.18, renderedPosition: { x: 420, y: 300 } })}><Plus size={15} /></button>
      <button className="icon-button" title="缩小" onClick={() => instance.current?.zoom({ level: (instance.current?.zoom() || 1) / 1.18, renderedPosition: { x: 420, y: 300 } })}><Minus size={15} /></button>
    </div>
    <div className="graph-toolbar floating graph-export-tools">
      {(["json", "svg", "png"] as const).map((kind) => <button className="icon-button" title={`导出 ${kind.toUpperCase()}`} key={kind} onClick={() => download(kind)}><Download size={14} /><small>{kind.toUpperCase()}</small></button>)}
    </div>
    <div ref={host} className="cytoscape-host" />
    {!graph.nodes.length && <div className="center-empty">当前范围没有可显示的图谱，请先运行分析或重建图谱。</div>}
    {graph.truncated && <div className="graph-warning">当前视图已聚合或截断，请聚焦模块或展开节点继续分析。</div>}
  </div>;
}

function layoutFor(view: GraphView, level: Level, nodeCount: number): cytoscape.LayoutOptions {
  if (view === "coremap" || view === "surprises") {
    return { name: "preset", fit: false, padding: 80 } as cytoscape.LayoutOptions;
  }
  if (["hierarchy", "callflow", "dataflow", "interface"].includes(view)) {
    return {
      name: "dagre", rankDir: view === "hierarchy" ? "TB" : "LR",
      nodeSep: level === "symbol" ? 44 : level === "file" ? 84 : level === "module" ? 112 : 150,
      rankSep: level === "symbol" ? 70 : 100, edgeSep: 18, padding: 70, animate: false, fit: false,
    } as cytoscape.LayoutOptions;
  }
  return {
    name: "fcose", quality: nodeCount > 350 ? "default" : "proof", randomize: true,
    animate: false, fit: false, padding: 70, nodeRepulsion: 8500,
    idealEdgeLength: view === "community" ? 170 : level === "symbol" ? 115 : 145,
    edgeElasticity: 0.42, nestingFactor: 0.8, gravity: 0.22, numIter: nodeCount > 450 ? 900 : 1800,
  } as cytoscape.LayoutOptions;
}

function focusPositions(nodes: any[], edges: any[], view: GraphView): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  if (view !== "coremap" && view !== "surprises") return positions;
  if (view === "surprises") {
    const pairs = new Map<string, { source: string; target: string }>();
    edges.forEach((edge: any) => pairs.set(edge.id, { source: edge.source, target: edge.target }));
    [...pairs.values()].forEach((pair, index) => {
      const y = 150 + index * 125;
      if (!positions.has(pair.source)) positions.set(pair.source, { x: 260, y });
      if (!positions.has(pair.target)) positions.set(pair.target, { x: 820, y });
    });
    return positions;
  }
  const hubs = nodes.filter((node) => node.metrics?.is_hub).sort((a, b) => Number(b.metrics?.god_score || 0) - Number(a.metrics?.god_score || 0));
  const anchors = hubs.length ? hubs.slice(0, 8) : [...nodes].sort((a, b) => Number(b.metrics?.degree || 0) - Number(a.metrics?.degree || 0)).slice(0, 6);
  const center = { x: 620, y: 420 };
  const hubRadius = anchors.length <= 1 ? 0 : 270;
  anchors.forEach((hub, index) => {
    const angle = anchors.length <= 1 ? -Math.PI / 2 : (index / anchors.length) * Math.PI * 2 - Math.PI / 2;
    positions.set(hub.id, { x: center.x + Math.cos(angle) * hubRadius, y: center.y + Math.sin(angle) * hubRadius });
  });
  const neighbors = new Map<string, string[]>();
  edges.forEach((edge: any) => {
    const hub = positions.has(edge.source) ? edge.source : positions.has(edge.target) ? edge.target : null;
    const other = hub === edge.source ? edge.target : hub === edge.target ? edge.source : null;
    if (hub && other && !positions.has(other)) neighbors.set(hub, [...(neighbors.get(hub) || []), other]);
  });
  neighbors.forEach((items, hubId) => {
    const hub = positions.get(hubId)!;
    [...new Set(items)].slice(0, 20).forEach((nodeId, index) => {
      const angle = (index / Math.max(1, Math.min(20, items.length))) * Math.PI * 2;
      positions.set(nodeId, { x: hub.x + Math.cos(angle) * 118, y: hub.y + Math.sin(angle) * 118 });
    });
  });
  let cursor = 0;
  nodes.forEach((node) => {
    if (positions.has(node.id)) return;
    positions.set(node.id, { x: 220 + (cursor % 8) * 110, y: 120 + Math.floor(cursor / 8) * 92 });
    cursor += 1;
  });
  return positions;
}
