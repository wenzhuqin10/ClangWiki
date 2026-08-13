import { useEffect, useRef } from "react";
import cytoscape, { Core } from "cytoscape";
import svg from "cytoscape-svg";
import { Download, Focus, Minus, Plus } from "lucide-react";

cytoscape.use(svg);

type GraphPayload = {
  nodes: any[];
  edges: any[];
  truncated?: boolean;
};

function edgeCurve(edge: any, edges: any[]): number {
  const parallel = edges.filter((candidate) => (
    candidate.source === edge.source && candidate.target === edge.target
  ) || (
    candidate.source === edge.target && candidate.target === edge.source
  ));
  if (parallel.length <= 1) return 0;
  const index = parallel.findIndex((candidate) => candidate.id === edge.id);
  const midpoint = (parallel.length - 1) / 2;
  return (index - midpoint) * 28;
}

type Props = {
  graph: GraphPayload;
  level: "repository" | "module" | "file" | "symbol";
  selectedNodeId?: string | null;
  selectedEdgeId?: string | null;
  showLabels?: boolean;
  showEdgeLabels?: boolean;
  onSelect: (node: any | null) => void;
  onSelectEdge?: (edge: any | null) => void;
};

const nodeColors: Record<string, string> = {
  repository: "#5965d8",
  module: "#7b86ee",
  file: "#4ca58a",
  symbol: "#d59649",
  document: "#9c6ad6",
  external: "#8b93a4",
};

const relationColors: Record<string, string> = {
  CONTAINS: "#8d98aa",
  DEPENDS_ON: "#6c78d9",
  INCLUDES: "#4ca58a",
  CALLS: "#5965d8",
  POSSIBLE_CALL: "#d59649",
  REFERENCES: "#a35db8",
  DEFINES: "#46a09a",
  DOCUMENTS: "#9c6ad6",
  RELATED_TO: "#7d8798",
};

function nodeLabel(node: any, level: Props["level"]): string {
  if (level === "file" && node.path) {
    const pieces = String(node.path).split(/[\\/]/).filter(Boolean);
    return pieces.slice(-2).join("/") || String(node.display_name || node.name || node.id);
  }
  return String(node.display_name || node.name || node.qualified_name || node.id);
}

export default function GraphCanvas({
  graph,
  level,
  selectedNodeId,
  selectedEdgeId,
  showLabels = true,
  showEdgeLabels = true,
  onSelect,
  onSelectEdge,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<Core | null>(null);

  useEffect(() => {
    if (!host.current) return;
    instance.current?.destroy();

    const compact = !showLabels;
    const cy = cytoscape({
      container: host.current,
      elements: [
        ...graph.nodes.map((node) => ({
          data: {
            ...node,
            label: nodeLabel(node, level),
            compact: compact ? "true" : "false",
          },
        })),
        ...graph.edges.map((edge) => ({
          data: {
            ...edge,
            label: showEdgeLabels ? (edge.relation_label || edge.kind || "关系") : "",
            curve: edgeCurve(edge, graph.edges),
          },
        })),
      ],
      style: [
        {
          selector: "node",
          style: {
            "background-color": (element) => nodeColors[String(element.data("kind"))] || "#8b93a4",
            label: "data(label)",
            color: "#343949",
            "font-size": level === "repository" ? 12 : level === "module" ? 10 : 9,
            "font-family": "Cascadia Code, Microsoft YaHei, sans-serif",
            "font-weight": level === "repository" ? 700 : 600,
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 7,
            "text-wrap": "ellipsis",
            "text-max-width": `${level === "module" ? 145 : 120}px`,
            "text-overflow-wrap": "whitespace",
            width: level === "repository" ? 48 : level === "module" ? 34 : 20,
            height: level === "repository" ? 48 : level === "module" ? 34 : 20,
            "border-width": 3,
            "border-color": "#ffffff",
            "overlay-opacity": 0,
          },
        },
        { selector: "node[compact = 'true']", style: { label: "" } },
        { selector: "node:selected", style: { label: "data(label)", "border-color": "#171a24", "border-width": 4, "z-index": 10 } },
        { selector: "node[kind = 'repository']", style: { shape: "round-rectangle" } },
        { selector: "node[kind = 'module']", style: { shape: "ellipse" } },
        { selector: "node[kind = 'file']", style: { shape: "round-rectangle" } },
        { selector: "node[kind = 'symbol']", style: { shape: "hexagon" } },
        {
          selector: "edge",
          style: {
            width: "mapData(confidence, 0, 1, 1, 3)",
            "line-color": (element) => relationColors[String(element.data("kind"))] || "#b7bdca",
            "target-arrow-color": (element) => relationColors[String(element.data("kind"))] || "#b7bdca",
            "target-arrow-shape": "triangle",
            "curve-style": "unbundled-bezier",
            "control-point-distances": "data(curve)",
            "control-point-weights": 0.5,
            "arrow-scale": 0.8,
            opacity: 0.72,
            label: "data(label)",
            color: "#5e6677",
            "font-size": 8,
            "font-family": "Microsoft YaHei, sans-serif",
            "text-rotation": "autorotate",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.92,
            "text-background-padding": "2px",
            "text-margin-y": -5,
          },
        },
        { selector: "edge[certainty = 'candidate']", style: { "line-style": "dashed", opacity: 0.78 } },
        { selector: "edge:selected", style: { width: 4, opacity: 1, "text-background-opacity": 1, "z-index": 9 } },
      ],
      layout: layoutFor(level, graph.nodes, graph.edges),
      minZoom: 0.12,
      maxZoom: 4,
      wheelSensitivity: 0.18,
    });

    if (selectedNodeId) cy.getElementById(selectedNodeId).select();
    if (selectedEdgeId) cy.getElementById(selectedEdgeId).select();
    cy.on("tap", "node", (event) => {
      cy.elements().unselect();
      event.target.select();
      onSelect(event.target.data());
      onSelectEdge?.(null);
    });
    cy.on("tap", "edge", (event) => {
      cy.elements().unselect();
      event.target.select();
      onSelectEdge?.(event.target.data());
      onSelect(null);
    });
    cy.on("tap", (event) => {
      if (event.target === cy) {
        cy.elements().unselect();
        onSelect(null);
        onSelectEdge?.(null);
      }
    });
    instance.current = cy;
    return () => cy.destroy();
  }, [graph, level, showLabels, showEdgeLabels, selectedNodeId, selectedEdgeId, onSelect, onSelectEdge]);

  const download = (kind: "json" | "png" | "svg") => {
    const cy = instance.current;
    if (!cy) return;
    let content: string;
    let mime: string;
    if (kind === "json") {
      content = JSON.stringify(cy.json().elements, null, 2);
      mime = "application/json";
    } else if (kind === "svg") {
      content = (cy as any).svg({ full: true, scale: 1 });
      mime = "image/svg+xml";
    } else {
      const link = document.createElement("a");
      link.href = cy.png({ full: true, scale: 2, bg: "#f7f8fb" });
      link.download = "clangwiki-graph.png";
      link.click();
      return;
    }
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([content], { type: mime }));
    link.download = `clangwiki-graph.${kind}`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  return <div className="graph-stage">
    <div className="graph-toolbar floating">
      <button className="icon-button" title="适应窗口" onClick={() => instance.current?.fit(undefined, 55)}><Focus size={16} /></button>
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

function layoutFor(level: Props["level"], nodes: any[], edges: any[]): cytoscape.LayoutOptions {
  if (level === "repository" || (level === "module" && nodes.length <= 12 && edges.length <= Math.max(1, Math.ceil(nodes.length * 1.4)))) {
    const incoming = new Set(edges.map((edge) => edge.target));
    const roots = nodes.filter((node) => !incoming.has(node.id)).map((node) => node.id);
    return {
      name: "breadthfirst",
      directed: true,
      circle: false,
      roots: roots.length ? roots : undefined,
      spacingFactor: level === "repository" ? 2.2 : 1.65,
      padding: 75,
      animate: false,
      fit: true,
    } as cytoscape.LayoutOptions;
  }
  return {
    name: "cose",
    animate: false,
    randomize: true,
    padding: 70,
    nodeRepulsion: level === "symbol" ? 18000 : 22000,
    idealEdgeLength: level === "symbol" ? 150 : 180,
    edgeElasticity: 0.25,
    nestingFactor: 1.1,
    gravity: 0.35,
    numIter: nodes.length > 450 ? 350 : 700,
    tile: true,
    fit: true,
  } as cytoscape.LayoutOptions;
}
