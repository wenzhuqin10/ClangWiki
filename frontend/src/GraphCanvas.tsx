import { useEffect, useRef } from "react";
import cytoscape, { Core } from "cytoscape";
import svg from "cytoscape-svg";
import { Download, Focus, Minus, Plus } from "lucide-react";

cytoscape.use(svg);

type GraphPayload = { nodes: any[]; edges: any[]; truncated?: boolean };
type Level = "repository" | "module" | "file" | "symbol";
type Props = {
  graph: GraphPayload;
  level: Level;
  selectedNodeId?: string | null;
  selectedEdgeId?: string | null;
  showLabels?: boolean;
  showEdgeLabels?: boolean;
  onSelect: (node: any | null) => void;
  onSelectEdge?: (edge: any | null) => void;
};

const nodeColors: Record<string, string> = {
  repository: "#5965d8", module: "#7581e8", file: "#48a487",
  symbol: "#d59649", document: "#9c6ad6", external: "#8b93a4",
};
const relationColors: Record<string, string> = {
  CONTAINS: "#8d98aa", DEPENDS_ON: "#6c78d9", INCLUDES: "#4ca58a",
  CALLS: "#5965d8", POSSIBLE_CALL: "#d59649", REFERENCES: "#a35db8",
  DEFINES: "#46a09a", DOCUMENTS: "#9c6ad6", RELATED_TO: "#7d8798",
};

function nodeLabel(node: any, level: Level): string {
  if (level === "file" && node.path) {
    const pieces = String(node.path).split(/[\\/]/).filter(Boolean);
    return pieces.slice(-2).join("/") || String(node.display_name || node.name || node.id);
  }
  return String(node.display_name || node.name || node.qualified_name || node.id);
}

function edgeCurve(edge: any, edges: any[]): number {
  const parallel = edges.filter((item) =>
    (item.source === edge.source && item.target === edge.target) ||
    (item.source === edge.target && item.target === edge.source));
  if (parallel.length <= 1) return 0;
  return (parallel.findIndex((item) => item.id === edge.id) - (parallel.length - 1) / 2) * 34;
}

export default function GraphCanvas({
  graph, level, selectedNodeId, selectedEdgeId, showLabels = true,
  showEdgeLabels = true, onSelect, onSelectEdge,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<Core | null>(null);
  const fitView = () => {
    const cy = instance.current;
    if (!cy) return;
    cy.fit(undefined, level === "module" ? 110 : 70);
    const cap = initialZoomCap(level, graph.nodes.length);
    if (cy.zoom() > cap) { cy.zoom(cap); cy.center(); }
  };

  useEffect(() => {
    if (!host.current) return;
    instance.current?.destroy();
    const cy = cytoscape({
      container: host.current,
      elements: [
        ...graph.nodes.map((node) => ({ data: {
          ...node, label: nodeLabel(node, level), compact: showLabels ? "false" : "true",
        } })),
        ...graph.edges.map((edge) => ({ data: {
          ...edge, label: showEdgeLabels ? (edge.relation_label || edge.kind || "关系") : "",
          curve: edgeCurve(edge, graph.edges),
        } })),
      ],
      style: [
        { selector: "node", style: {
          "background-color": (element) => nodeColors[String(element.data("kind"))] || "#8b93a4",
          label: "data(label)", color: "#303646",
          "font-size": level === "repository" ? 13 : level === "module" ? 11 : 9,
          "font-family": "Microsoft YaHei UI, Microsoft YaHei, sans-serif",
          "font-weight": level === "repository" || level === "module" ? 650 : 550,
          "min-zoomed-font-size": 8,
          "text-valign": "bottom", "text-halign": "center",
          "text-margin-y": level === "module" ? 9 : 6,
          "text-wrap": "ellipsis", "text-overflow-wrap": "whitespace",
          "text-max-width": `${level === "module" ? 132 : 116}px`,
          width: level === "repository" ? 44 : level === "module" ? 30 : level === "file" ? 14 : 13,
          height: level === "repository" ? 44 : level === "module" ? 30 : level === "file" ? 14 : 13,
          "border-width": level === "file" || level === "symbol" ? 1.5 : 2.5,
          "border-color": "#ffffff", "overlay-opacity": 0,
        } },
        { selector: "node[compact = 'true']", style: { label: "" } },
        { selector: "node:selected", style: {
          label: "data(label)", "border-color": "#171a24", "border-width": 3.5, "z-index": 10,
        } },
        { selector: "node[kind = 'repository']", style: { shape: "round-rectangle" } },
        { selector: "node[kind = 'module']", style: { shape: "ellipse" } },
        { selector: "node[kind = 'file']", style: { shape: "round-rectangle" } },
        { selector: "node[kind = 'symbol']", style: { shape: "hexagon" } },
        { selector: "edge", style: {
          width: "mapData(confidence, 0, 1, 0.8, 2.4)",
          "line-color": (element) => relationColors[String(element.data("kind"))] || "#b7bdca",
          "target-arrow-color": (element) => relationColors[String(element.data("kind"))] || "#b7bdca",
          "target-arrow-shape": "triangle", "curve-style": "unbundled-bezier",
          "control-point-distances": "data(curve)", "control-point-weights": 0.5,
          "arrow-scale": 0.72, opacity: 0.68, label: "data(label)", color: "#606878",
          "font-size": level === "module" ? 9 : 8,
          "font-family": "Microsoft YaHei UI, Microsoft YaHei, sans-serif",
          "font-weight": 500, "min-zoomed-font-size": 7, "text-rotation": "none",
          "text-background-color": "#ffffff", "text-background-opacity": 0.96,
          "text-background-padding": "3px", "text-margin-y": -8,
        } },
        { selector: "edge[certainty = 'candidate']", style: { "line-style": "dashed", opacity: 0.75 } },
        { selector: "edge:selected", style: { width: 3.5, opacity: 1, "text-background-opacity": 1, "z-index": 9 } },
      ],
      layout: { name: "preset" }, minZoom: 0.12, maxZoom: 2.2, wheelSensitivity: 0.18,
    });

    const layout = cy.layout(layoutFor(level, graph.nodes, graph.edges));
    layout.on("layoutstop", () => {
      cy.fit(undefined, level === "module" ? 110 : 70);
      const cap = initialZoomCap(level, graph.nodes.length);
      if (cy.zoom() > cap) { cy.zoom(cap); cy.center(); }
    });
    layout.run();
    cy.on("tap", "node", (event) => {
      cy.elements().unselect(); event.target.select(); onSelect(event.target.data()); onSelectEdge?.(null);
    });
    cy.on("tap", "edge", (event) => {
      cy.elements().unselect(); event.target.select(); onSelectEdge?.(event.target.data()); onSelect(null);
    });
    cy.on("tap", (event) => {
      if (event.target === cy) { cy.elements().unselect(); onSelect(null); onSelectEdge?.(null); }
    });
    instance.current = cy;
    return () => cy.destroy();
  }, [graph, level, showLabels, showEdgeLabels, onSelect, onSelectEdge]);

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
      link.href = cy.png({ full: true, scale: 2, bg: "#f7f8fb" });
      link.download = "clangwiki-graph.png"; link.click(); return;
    }
    const content = kind === "json"
      ? JSON.stringify(cy.json().elements, null, 2)
      : (cy as any).svg({ full: true, scale: 1 });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([content], {
      type: kind === "json" ? "application/json" : "image/svg+xml",
    }));
    link.download = `clangwiki-graph.${kind}`; link.click(); URL.revokeObjectURL(link.href);
  };

  return <div className="graph-stage">
    <div className="graph-toolbar floating">
      <button className="icon-button" title="适应窗口" onClick={fitView}><Focus size={16} /></button>
      <button className="icon-button" title="放大" onClick={() => instance.current?.zoom({ level: (instance.current?.zoom() || 1) * 1.18, renderedPosition: { x: 420, y: 300 } })}><Plus size={15} /></button>
      <button className="icon-button" title="缩小" onClick={() => instance.current?.zoom({ level: (instance.current?.zoom() || 1) / 1.18, renderedPosition: { x: 420, y: 300 } })}><Minus size={15} /></button>
      <span className="toolbar-separator" />
      {(["json", "svg", "png"] as const).map((kind) => <button className="mini-button" key={kind} onClick={() => download(kind)}><Download size={13} />{kind.toUpperCase()}</button>)}
    </div>
    <div ref={host} className="cytoscape-host" />
    {!graph.nodes.length && <div className="center-empty">当前范围还没有可显示的图谱，请先运行分析。</div>}
    {graph.truncated && <div className="graph-warning">图谱已聚合或截断，请切换层级、隐藏标签或展开单个节点查看局部关系。</div>}
  </div>;
}

function layoutFor(level: Level, nodes: any[], _edges: any[]): cytoscape.LayoutOptions {
  if (level === "repository") return {
    name: "breadthfirst", directed: true, circle: false, spacingFactor: 2,
    padding: 80, animate: false, fit: false,
  } as cytoscape.LayoutOptions;
  if (level === "module" && nodes.length <= 18) return {
    name: "grid", rows: nodes.length <= 6 ? 2 : undefined, cols: nodes.length <= 6 ? 3 : undefined,
    avoidOverlap: true, avoidOverlapPadding: 80, spacingFactor: 1.35,
    condense: false, padding: 110, animate: false, fit: false,
  } as cytoscape.LayoutOptions;
  if (level === "file" && nodes.length <= 120) {
    return {
      name: "grid", cols: 10, avoidOverlap: true, avoidOverlapPadding: 20,
      spacingFactor: 1.32, condense: false, padding: 100, animate: false, fit: false,
    } as cytoscape.LayoutOptions;
  }
  return {
    name: "cose", animate: false, randomize: true, padding: 80,
    nodeRepulsion: level === "symbol" ? 22000 : level === "file" ? 26000 : 22000,
    idealEdgeLength: level === "symbol" ? 150 : level === "file" ? 170 : 180,
    edgeElasticity: 0.22, nestingFactor: 1.1, gravity: 0.3,
    numIter: nodes.length > 450 ? 450 : 800, tile: true, fit: false,
  } as cytoscape.LayoutOptions;
}

function initialZoomCap(level: Level, nodeCount: number): number {
  if (level === "repository") return 1.05;
  if (level === "module") return nodeCount <= 18 ? 1.05 : 0.9;
  if (level === "file") return nodeCount <= 120 ? 1.05 : 0.95;
  return 0.85;
}
