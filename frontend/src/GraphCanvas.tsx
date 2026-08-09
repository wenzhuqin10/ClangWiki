import { useEffect, useRef } from "react";
import cytoscape, { Core } from "cytoscape";
import svg from "cytoscape-svg";
import { Download, Focus } from "lucide-react";

cytoscape.use(svg);

type Props = {
  graph: { nodes: any[]; edges: any[]; truncated?: boolean };
  onSelect: (node: any | null) => void;
};

const colors: Record<string, string> = {
  repository: "#5965d8", module: "#7b86ee", file: "#4ca58a", symbol: "#d59649",
  document: "#9c6ad6", external: "#8b93a4",
};

export default function GraphCanvas({ graph, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<Core | null>(null);

  useEffect(() => {
    if (!host.current) return;
    instance.current?.destroy();
    const cy = cytoscape({
      container: host.current,
      elements: [
        ...graph.nodes.map((node) => ({ data: { ...node, label: node.name || node.qualified_name || node.id } })),
        ...graph.edges.map((edge) => ({ data: { ...edge, label: edge.kind } })),
      ],
      style: [
        {
          selector: "node",
          style: {
            "background-color": (element) => colors[String(element.data("kind"))] || "#8b93a4",
            label: "data(label)", color: "#343949", "font-size": 10,
            "font-family": "Cascadia Code, Microsoft YaHei, sans-serif",
            "text-valign": "bottom", "text-margin-y": 7,
            width: 23, height: 23, "border-width": 3, "border-color": "#ffffff",
          },
        },
        { selector: "node[kind = 'repository']", style: { width: 42, height: 42, "font-size": 12, "font-weight": 700 } },
        { selector: "node[kind = 'module']", style: { width: 32, height: 32, "font-size": 11 } },
        { selector: "node:selected", style: { "border-color": "#171a24", "border-width": 4 } },
        {
          selector: "edge",
          style: {
            width: "mapData(confidence, 0, 1, 0.7, 2.2)", "line-color": "#b7bdca",
            "target-arrow-color": "#9da5b5", "target-arrow-shape": "triangle",
            "curve-style": "bezier", "arrow-scale": 0.75, opacity: 0.72,
          },
        },
        { selector: "edge[certainty = 'candidate']", style: { "line-style": "dashed", "line-color": "#d59649", "target-arrow-color": "#d59649" } },
        { selector: "edge[kind = 'CALLS']", style: { "line-color": "#5965d8", "target-arrow-color": "#5965d8" } },
        { selector: "edge[kind = 'CONTAINS']", style: { "line-color": "#a5acbb", "target-arrow-shape": "none" } },
      ],
      layout: { name: graph.nodes.length > 120 ? "cose" : "cose", animate: false, randomize: true, padding: 44, nodeRepulsion: () => 7000, idealEdgeLength: () => 90 },
      minZoom: 0.15,
      maxZoom: 3,
    });
    cy.on("tap", "node", (event) => onSelect(event.target.data()));
    cy.on("tap", (event) => { if (event.target === cy) onSelect(null); });
    instance.current = cy;
    return () => cy.destroy();
  }, [graph, onSelect]);

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
      <button className="icon-button" title="适应窗口" onClick={() => instance.current?.fit(undefined, 40)}><Focus size={16} /></button>
      <span className="toolbar-separator" />
      {(["json", "svg", "png"] as const).map((kind) => <button className="mini-button" key={kind} onClick={() => download(kind)}><Download size={13} />{kind.toUpperCase()}</button>)}
    </div>
    <div ref={host} className="cytoscape-host" />
    {!graph.nodes.length && <div className="center-empty">当前范围还没有可显示的图谱，请先运行分析。</div>}
    {graph.truncated && <div className="graph-warning">图谱已聚合并截断，请缩小层级或筛选关系。</div>}
  </div>;
}
