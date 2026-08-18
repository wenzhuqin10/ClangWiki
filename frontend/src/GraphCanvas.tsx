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
type GraphView = "hierarchy" | "community" | "dependency" | "callflow" | "dataflow" | "interface" | "knowledge";
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
  PARTICIPATES_IN: "#b38842", DOCUMENTS: "#9c6ad6", MATCHES_DECLARATION: "#4c70a8",
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
    if (!cy) return;
    cy.fit(undefined, view === "community" ? 90 : 65);
    if (cy.zoom() > 1.08) { cy.zoom(1.08); cy.center(); }
  };

  useEffect(() => {
    if (!host.current) return;
    instance.current?.destroy();
    const elements = [
      ...graph.nodes.map((node) => ({ data: {
        ...node, label: nodeLabel(node, level), size: sizeFor(node, level),
        fill: node.color || nodeColors[String(node.kind)] || "#8b93a4",
        shape: shapeFor(node), compact: showLabels ? "false" : "true",
        path: pathNodeIds.includes(node.id) ? "true" : "false",
      } })),
      ...graph.edges.map((edge) => ({ data: {
        ...edge, label: showEdgeLabels ? (edge.relation_label || edge.kind || "关系") : "",
        edgeColor: relationColors[String(edge.kind)] || "#a7afbd",
        aggregateWidth: Math.max(1, Math.min(7, 1 + Math.log2(Number(edge.count || edge.weight || 1)))),
      } })),
    ];
    const cy = cytoscape({
      container: host.current, elements,
      style: [
        { selector: "node", style: {
          "background-color": "data(fill)", shape: (element) => shapeFor(element.data()), width: "data(size)", height: "data(size)",
          label: "data(label)", color: "#293040", "font-size": level === "module" ? 12 : 10,
          "font-family": "Microsoft YaHei UI, Microsoft YaHei, sans-serif", "font-weight": 600,
          "min-zoomed-font-size": 9, "text-valign": "bottom", "text-halign": "center", "text-margin-y": 7,
          "text-wrap": "ellipsis", "text-max-width": view === "community" ? "160px" : level === "module" ? "150px" : "124px",
          "border-width": 2, "border-color": "#fff", "overlay-opacity": 0,
        } },
        { selector: "node[compact = 'true']", style: { label: "" } },
        { selector: "node[path = 'true']", style: { "border-color": "#161a25", "border-width": 4, label: "data(label)", "z-index": 12 } },
        { selector: "node:selected", style: { "border-color": "#161a25", "border-width": 4, label: "data(label)", "z-index": 15 } },
        { selector: "edge", style: {
          width: "data(aggregateWidth)", "line-color": "data(edgeColor)", "target-arrow-color": "data(edgeColor)",
          "target-arrow-shape": "triangle", "curve-style": view === "community" ? "bezier" : "taxi",
          "taxi-direction": "rightward", "arrow-scale": 0.7, opacity: 0.62, label: "data(label)",
          color: "#5b6475", "font-size": 8, "font-family": "Microsoft YaHei UI, sans-serif",
          "min-zoomed-font-size": 7, "text-background-color": "#fff", "text-background-opacity": 0.94,
          "text-background-padding": "3px", "text-margin-y": -7,
        } },
        { selector: "edge[status = 'candidate']", style: { "line-style": "dashed", opacity: 0.72 } },
        { selector: "edge[origin = 'rule']", style: { "line-style": "dotted" } },
        { selector: "edge:selected", style: { width: 4, opacity: 1, "z-index": 10 } },
      ],
      layout: { name: "preset" }, minZoom: 0.08, maxZoom: 2.5, wheelSensitivity: 0.16,
    });
    const layout = cy.layout(layoutFor(view, level, graph.nodes.length));
    layout.on("layoutstop", fitView);
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
    return () => { resizeObserver.disconnect(); cy.destroy(); };
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
      link.href = cy.png({ full: true, scale: 2, bg: "#f8f9fc" });
      link.download = "clangwiki-graph.png"; link.click(); return;
    }
    const content = kind === "json" ? JSON.stringify({ nodes: graph.nodes, edges: graph.edges }, null, 2) : (cy as any).svg({ full: true, scale: 1 });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([content], { type: kind === "json" ? "application/json" : "image/svg+xml" }));
    link.download = `clangwiki-graph.${kind}`; link.click(); URL.revokeObjectURL(link.href);
  };

  return <div className="graph-stage graph-stage-v2">
    <div className="graph-toolbar floating">
      <button className="icon-button" title="适应窗口" onClick={fitView}><Focus size={16} /></button>
      <button className="icon-button" title="放大" onClick={() => instance.current?.zoom({ level: (instance.current?.zoom() || 1) * 1.18, renderedPosition: { x: 420, y: 300 } })}><Plus size={15} /></button>
      <button className="icon-button" title="缩小" onClick={() => instance.current?.zoom({ level: (instance.current?.zoom() || 1) / 1.18, renderedPosition: { x: 420, y: 300 } })}><Minus size={15} /></button>
      <span className="toolbar-separator" />
      {(["json", "svg", "png"] as const).map((kind) => <button className="mini-button" key={kind} onClick={() => download(kind)}><Download size={13} />{kind.toUpperCase()}</button>)}
    </div>
    <div ref={host} className="cytoscape-host" />
    {!graph.nodes.length && <div className="center-empty">当前范围没有可显示的图谱，请先运行分析或重建图谱。</div>}
    {graph.truncated && <div className="graph-warning">当前视图已聚合或截断，请聚焦模块或展开节点继续分析。</div>}
  </div>;
}

function layoutFor(view: GraphView, level: Level, nodeCount: number): cytoscape.LayoutOptions {
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
