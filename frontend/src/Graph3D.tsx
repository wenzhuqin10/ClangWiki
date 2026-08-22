import { Component, useMemo, type ReactNode } from "react";
import { GraphCanvas as ReagraphCanvas, darkTheme } from "reagraph";

type Props = {
  graph: { nodes: any[]; edges: any[] };
  onSelect: (node: any | null) => void;
};

/**
 * Optional WebGL overview. 2D Cytoscape remains the default and is used for
 * execution, data-flow, and impact analysis; this component is deliberately
 * capped so a browser never receives the whole symbol graph at once.
 */
export default function Graph3D({ graph, onSelect }: Props) {
  const data = useMemo(() => {
    const nodes = (graph.nodes || []).slice(0, 1500).map((node: any) => ({
      id: node.id,
      label: String(node.display_name || node.name || node.id).slice(0, 72),
      fill: node.color || colorFor(node),
      size: Math.max(3, Math.min(14, 3 + Math.sqrt(Number(node.metrics?.degree || node.member_count || 0) + 1))),
      cluster: node.community_id || node.module_id || node.repository_id || "default",
      data: node,
    }));
    const allowed = new Set(nodes.map((node: any) => node.id));
    const edges = (graph.edges || []).filter((edge: any) => allowed.has(edge.source) && allowed.has(edge.target)).slice(0, 4000).map((edge: any) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.relation_label || edge.kind,
      fill: edge.status === "candidate" ? "#c7904b" : "#69758a",
      dashed: edge.status === "candidate" || edge.origin === "rule",
      data: edge,
    }));
    return { nodes, edges };
  }, [graph]);

  return <div className="graph-3d-host">
    <Graph3DErrorBoundary>
      <ReagraphCanvas
        nodes={data.nodes}
        edges={data.edges}
        theme={darkTheme}
        layoutType="forceDirected3d"
        labelType="auto"
        edgeInterpolation="curved"
        aggregateEdges
        clusterAttribute="cluster"
        sizingType="attribute"
        sizingAttribute="size"
        minNodeSize={3}
        maxNodeSize={14}
        defaultNodeSize={5}
        animated={false}
        onNodeClick={(node: any) => onSelect(node?.data || node)}
      />
    </Graph3DErrorBoundary>
    {graph.nodes?.length > 1500 && <span className="graph-3d-limit">3D 总览已限制为 1500 个节点；请搜索函数后在 2D 视图展开局部图。</span>}
  </div>;
}

class Graph3DErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) return <div className="graph-3d-fallback">当前浏览器无法初始化 WebGL，已保留 2D 图谱。{this.state.error.message}</div>;
    return this.props.children;
  }
}

function colorFor(node: any) {
  if (node.kind === "module") return "#7d87ed";
  if (node.kind === "file") return "#48a487";
  if (node.kind === "document") return "#9c6ad6";
  if (node.kind === "domain") return "#d55f6b";
  return "#d59649";
}
