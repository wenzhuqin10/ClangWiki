import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowRight, ArrowUpFromLine, Boxes, Braces,
  CheckCircle2, ChevronRight, CircleDot, Code2, Download, FileCode2, FileText, GitCompare,
  Layers3, Link2, LoaderCircle, Network, RefreshCw, Route, Search, ShieldCheck, Sparkles,
  Split, Target, X, Zap,
} from "lucide-react";
import { api, query } from "./api";
import GraphCanvas from "./GraphCanvas";

type Scope = { type: "repository" | "collection"; id: string; name: string } | null;
type Level = "repository" | "module" | "file" | "symbol";
type GraphView = "hierarchy" | "community" | "dependency" | "callflow" | "dataflow" | "interface" | "knowledge" | "coremap" | "surprises";

const VIEWS: Array<{ id: GraphView; label: string; description: string; level: Level; kinds?: string[]; icon: typeof Network }> = [
  { id: "hierarchy", label: "架构导航", description: "仓库、信道、模块和文件层级", level: "module", icon: Layers3 },
  { id: "community", label: "社区耦合", description: "发现实际高耦合代码群与桥梁", level: "symbol", icon: Boxes },
  { id: "dependency", label: "模块依赖", description: "模块与文件的跨边界依赖", level: "module", kinds: ["CALLS", "INCLUDES", "REFERENCES", "READS", "WRITES", "DEPENDS_ON"], icon: Split },
  { id: "callflow", label: "调用链", description: "确定调用、回调和候选调用", level: "symbol", kinds: ["CALLS", "REGISTER_CALLBACK", "INVOKES_CALLBACK", "POSSIBLE_CALL"], icon: Route },
  { id: "dataflow", label: "数据与配置", description: "字段读写、参数和配置传播", level: "symbol", kinds: ["READS", "WRITES", "USES_TYPE", "PASSES_TO", "CONFIGURES"], icon: Braces },
  { id: "interface", label: "接口与消息", description: "接口、PDU、消息与跨仓关联", level: "symbol", kinds: ["PROVIDES_INTERFACE", "CONSUMES_INTERFACE", "MATCHES_DECLARATION", "CROSS_REPO_CALL", "SENDS", "RECEIVES", "PRODUCES", "CONSUMES"], icon: Link2 },
  { id: "knowledge", label: "Wiki 知识", description: "文档、领域概念与源码证据", level: "symbol", kinds: ["DOCUMENTS", "MENTIONS", "EXPLAINS", "EVIDENCE_FOR", "IMPLEMENTS_CHANNEL", "PARTICIPATES_IN", "SPECIFIED_BY"], icon: FileText },
  { id: "coremap", label: "核心星图", description: "以高连接核心节点为导航锚点", level: "symbol", icon: Sparkles },
  { id: "surprises", label: "惊喜链接", description: "发现跨模块的隐性强关联", level: "symbol", icon: Zap },
];

const RELATION_LABELS: Record<string, string> = {
  CONTAINS: "包含", BUILDS: "构建", COMPILES: "编译", DECLARES: "声明", DEFINES: "定义",
  CALLS: "调用", POSSIBLE_CALL: "可能调用", REFERENCES: "引用", READS: "读取", WRITES: "写入",
  USES_TYPE: "使用类型", PASSES_TO: "参数传递", REGISTER_CALLBACK: "注册回调",
  INVOKES_CALLBACK: "触发回调", INCLUDES: "包含头文件", CONFIGURES: "配置",
  IMPLEMENTS_CHANNEL: "实现信道", PARTICIPATES_IN: "参与流程", DOCUMENTS: "文档对应",
  MATCHES_DECLARATION: "声明匹配", SPECIFIED_BY: "协议依据", RELATED_TO: "相关",
  SURPRISING_CONNECTION: "惊喜链接",
};

export default function GraphWorkbench({ scope, notify }: { scope: Scope; notify: (text: string, error?: boolean) => void }) {
  const [view, setView] = useState<GraphView>("hierarchy");
  const [level, setLevel] = useState<Level>("module");
  const [graph, setGraph] = useState<any>({ nodes: [], edges: [], relation_counts: {} });
  const [diagnostics, setDiagnostics] = useState<any>(null);
  const [communities, setCommunities] = useState<any[]>([]);
  const [insights, setInsights] = useState<{ hub: any[]; bridge: any[]; orphan: any[]; cycle: any[]; surprise: any[] }>({ hub: [], bridge: [], orphan: [], cycle: [], surprise: [] });
  const [insight, setInsight] = useState<"community" | "hub" | "bridge" | "orphan" | "cycle" | "surprise">("community");
  const [selected, setSelected] = useState<any>(null);
  const [selectedEdge, setSelectedEdge] = useState<any>(null);
  const [edgeDetail, setEdgeDetail] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);
  const [sourceSnippet, setSourceSnippet] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [includeCandidates, setIncludeCandidates] = useState(false);
  const [showLabels, setShowLabels] = useState(true);
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [layers, setLayers] = useState({ code: true, domain: false, knowledge: false });
  const [search, setSearch] = useState("");
  const [focusedCommunity, setFocusedCommunity] = useState<string | null>(null);
  const [pathEndpoints, setPathEndpoints] = useState<any[]>([]);
  const [path, setPath] = useState<any>(null);
  const [neighborDepth, setNeighborDepth] = useState(1);
  const [direction, setDirection] = useState<"incoming" | "outgoing" | "both">("both");
  const [runs, setRuns] = useState<any[]>([]);
  const [graphDiff, setGraphDiff] = useState<any>(null);

  const preset = VIEWS.find((item) => item.id === view) || VIEWS[0];

  const load = useCallback(async () => {
    if (!scope) return;
    setLoading(true);
    try {
      const statuses = includeCandidates ? ["confirmed", "candidate"] : ["confirmed"];
      const activeLayers = Object.entries(layers).filter(([, enabled]) => enabled).map(([name]) => name);
      const params = new URLSearchParams({
        scope_type: scope.type, scope_id: scope.id, level,
        view: view === "community" ? "community" : view, limit: view === "community" ? "250" : level === "symbol" ? "250" : "220",
      });
      statuses.forEach((value) => params.append("statuses", value));
      activeLayers.forEach((value) => params.append("layers", value));
      preset.kinds?.forEach((value) => params.append("kinds", value));
      if (focusedCommunity && view !== "community") params.set("community_id", focusedCommunity);
      const value = await api.get<any>(`/api/graph?${params.toString()}`);
      setGraph(value); setDiagnostics(value.diagnostics || null); setSelected(null); if (view !== "surprises") setSelectedEdge(null); setDetail(null); setPath(null);
    } catch (error) { notify(message(error), true); }
    finally { setLoading(false); }
  }, [scope?.type, scope?.id, view, level, includeCandidates, layers.code, layers.domain, layers.knowledge, focusedCommunity]);

  useEffect(() => { setLevel(preset.level); setFocusedCommunity(null); if (view !== "surprises") { setSelectedEdge(null); setEdgeDetail(null); } }, [view]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!scope || scope.type !== "repository") { setCommunities([]); setInsights({ hub: [], bridge: [], orphan: [], cycle: [], surprise: [] }); return; }
    Promise.all([
      api.get<any>(`/api/graph/communities?${query({ repository_id: scope.id })}`),
      api.get<any>(`/api/graph/hubs?${query({ repository_id: scope.id, limit: 25 })}`),
      api.get<any>(`/api/graph/bridges?${query({ repository_id: scope.id, limit: 25 })}`),
      api.get<any>(`/api/graph/orphans?${query({ repository_id: scope.id, limit: 25 })}`),
      api.get<any>(`/api/graph/cycles?${query({ repository_id: scope.id, limit: 25 })}`),
      api.get<any>(`/api/graph/surprising-connections?${query({ repository_id: scope.id, limit: 25 })}`),
    ]).then(([a, b, c, d, e, f]) => {
      setCommunities(a.communities || []); setInsights({ hub: b.nodes || [], bridge: c.nodes || [], orphan: d.nodes || [], cycle: e.cycles || [], surprise: f.connections || [] });
    }).catch((error) => notify(message(error), true));
  }, [scope?.type, scope?.id, graph.nodes?.length]);
  useEffect(() => {
    if (!scope || scope.type !== "repository") { setRuns([]); setGraphDiff(null); return; }
    api.get<any>(`/api/graph/snapshots?${query({ repository_id: scope.id })}`).then((value) => {
      setRuns(value.runs || []);
    }).catch(() => setRuns([]));
  }, [scope?.type, scope?.id]);

  const selectNode = useCallback(async (node: any | null) => {
    setSelected(node); setSelectedEdge(null); setEdgeDetail(null); setDetail(null); setSourceSnippet(null);
    if (!node || node.kind === "community") return;
    try {
      setDetail(await api.get(`/api/graph/nodes/${encodeURIComponent(node.id)}`));
      if (scope?.type === "repository" && node.path && ["symbol", "file"].includes(node.kind)) {
        const start = Math.max(1, Number(node.line_start || 1) - 4);
        const end = Number(node.line_end || node.line_start || start) + 8;
        setSourceSnippet(await api.get(`/api/repositories/${scope.id}/source?${query({ path: node.path, line_start: start, line_end: end })}`));
      }
    }
    catch (error) { notify(message(error), true); }
  }, [notify, scope?.type, scope?.id]);

  const selectEdge = useCallback(async (edge: any | null) => {
    setSelectedEdge(edge); setSelected(null); setDetail(null); setEdgeDetail(null);
    if (!edge?.id || edge.id.startsWith("module-edge:") || edge.id.startsWith("community-edge:")) return;
    if (edge.kind === "SURPRISING_CONNECTION") {
      const nodes = new Map((graph.nodes || []).map((node: any) => [node.id, node]));
      setEdgeDetail({ edge, source_node: nodes.get(edge.source), target_node: nodes.get(edge.target), evidence: edge.metadata?.evidence || [] });
      return;
    }
    try { setEdgeDetail(await api.get(`/api/graph/edges/${encodeURIComponent(edge.id)}`)); }
    catch (error) { notify(message(error), true); }
  }, [notify, graph.nodes]);

  const reviewEdge = async (confirmed: boolean) => {
    if (!selectedEdge?.id) return;
    try {
      const value: any = await api.patch(`/api/graph/edges/${encodeURIComponent(selectedEdge.id)}?confirmed=${confirmed}`, {});
      notify(confirmed ? "候选关系已确认为事实关系。" : "候选关系已否决并从默认视图隐藏。");
      setSelectedEdge(value); setEdgeDetail((current: any) => current ? { ...current, edge: value } : current);
      await load();
    } catch (error) { notify(message(error), true); }
  };

  const expand = async () => {
    if (!selected || !scope) return;
    setLoading(true);
    try {
      const value = await api.get<any>(`/api/graph/neighbors?${query({
        node_id: selected.id, depth: neighborDepth, limit: 80, scope_type: scope.type, scope_id: scope.id,
        level, direction, include_candidates: includeCandidates,
      })}`);
      setGraph(mergeGraphs(graph, value));
      if (value.truncated) notify("邻居数量超过 80，已显示最相关的局部子图。");
    } catch (error) { notify(message(error), true); }
    finally { setLoading(false); }
  };

  const pickPathNode = useCallback((node: any) => {
    setPathEndpoints((items) => items.length >= 2 ? [node] : [...items.filter((item) => item.id !== node.id), node]);
  }, []);

  const findPath = async () => {
    if (pathEndpoints.length !== 2) return;
    setLoading(true);
    try {
      const value = await api.post<any>("/api/graph/path", {
        source_id: pathEndpoints[0].id, target_id: pathEndpoints[1].id, max_depth: 12,
        directed: true, kinds: preset.kinds || null, include_candidates: includeCandidates,
      });
      setPath(value);
      if (value.found) setGraph(mergeGraphs(graph, value));
      else notify("在当前关系和证据范围内没有找到有向路径。", true);
    } catch (error) { notify(message(error), true); }
    finally { setLoading(false); }
  };

  const rebuild = async () => {
    if (!scope || scope.type !== "repository") return;
    try {
      await api.post(`/api/repositories/${scope.id}/graph/rebuild`, { overrides: {} });
      notify("图谱重建已进入任务队列，可在任务中心查看覆盖诊断和进度。");
    } catch (error) { notify(message(error), true); }
  };

  const compareVersions = async () => {
    if (!scope || scope.type !== "repository" || runs.length < 2) return;
    setLoading(true);
    try {
      const value = await api.get<any>(`/api/graph/diff?${query({
        repository_id: scope.id, from_run_id: runs[1].id, to_run_id: runs[0].id,
      })}`);
      setGraphDiff(value);
    } catch (error) { notify(message(error), true); }
    finally { setLoading(false); }
  };

  const filteredNodes = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return graph.nodes || [];
    return (graph.nodes || []).filter((node: any) => `${node.display_name || node.name} ${node.qualified_name || ""} ${node.path || ""}`.toLowerCase().includes(keyword));
  }, [graph.nodes, search]);
  const focusedGraph = useMemo(() => {
    if (!search.trim()) return graph;
    const ids = new Set(filteredNodes.map((node: any) => node.id));
    const edges = (graph.edges || []).filter((edge: any) => ids.has(edge.source) || ids.has(edge.target));
    edges.forEach((edge: any) => { ids.add(edge.source); ids.add(edge.target); });
    return { ...graph, nodes: (graph.nodes || []).filter((node: any) => ids.has(node.id)).slice(0, 120), edges: edges.slice(0, 180) };
  }, [graph, filteredNodes, search]);
  const activeItem = selected || selectedEdge;
  const relatedNodes = detail?.node ? relationRows(detail, graph.nodes || []) : [];

  if (!scope) return <div className="center-empty">请先选择代码仓或知识空间。</div>;
  return <section className="kg-workbench kg-graphify">
    <aside className="kg-navigator">
      <div className="kg-graph-brand"><span><Network size={17} /></span><div><strong>ClangWiki Graph</strong><small>代码知识图谱</small></div></div>
      <div className="kg-section-title"><span>分析视图</span><small>{VIEWS.length}</small></div>
      <div className="kg-view-list">{VIEWS.map((item) => { const Icon = item.icon; return <button className={view === item.id ? "active" : ""} key={item.id} onClick={() => setView(item.id)}><Icon size={15} /><span><strong>{item.label}</strong><small>{item.description}</small></span></button>; })}</div>
      {scope.type === "repository" && <>
        <div className="kg-insight-tabs">{(["community", "hub", "bridge", "cycle", "orphan", "surprise"] as const).map((item) => <button key={item} className={insight === item ? "active" : ""} onClick={() => setInsight(item)}>{({ community: "社区", hub: "核心", bridge: "桥梁", cycle: "循环", orphan: "孤点", surprise: "惊喜" } as any)[item]}</button>)}</div>
        <div className="kg-insight-list">
          {insight === "community" ? communities.map((item) => <button key={item.id} onClick={() => { setFocusedCommunity(item.id); setView("dependency"); setLevel("symbol"); }}><i style={{ background: item.color }} /><span><strong>{item.name}</strong><small>{item.member_count} 节点 · 内聚 {Number(item.cohesion || 0).toFixed(2)}</small></span><ChevronRight size={13} /></button>) : insight === "cycle" ? insights.cycle.map((item, index) => <button key={`${item.size}-${index}`} onClick={() => item.nodes?.[0] && void selectNode(item.nodes[0])}><RefreshCw size={12} /><span><strong>{item.size} 节点循环</strong><small>{item.nodes?.slice(0, 3).map((node: any) => node.display_name || node.name).join(" → ")}</small></span><ChevronRight size={13} /></button>) : insight === "surprise" ? insights.surprise.map((item) => <button className="kg-surprise-row" key={item.id} onClick={() => { setView("surprises"); void selectEdge({ id: item.id, kind: "SURPRISING_CONNECTION", source: item.source_id, target: item.target_id, metadata: { insight: item.reason, evidence: item.evidence }, score: item.score, status: "confirmed" }); }}><Zap size={12} /><span><strong>{item.source?.display_name || item.source_id} → {item.target?.display_name || item.target_id}</strong><small>{item.reason?.summary || "跨模块确定关系"} · 得分 {Number(item.score || 0).toFixed(2)}</small></span><ChevronRight size={13} /></button>) : insights[insight].map((item) => <button key={item.id} onClick={() => void selectNode(item)}><CircleDot size={12} /><span><strong>{item.display_name || item.name}</strong><small>{item.module_id || item.path || item.subtype}</small></span><ChevronRight size={13} /></button>)}
          {insight === "community" && !communities.length && <p>重建图谱后将在这里显示耦合社区。</p>}
          {insight === "surprise" && !insights.surprise.length && <p>当前运行尚未发现跨模块的确定性惊喜链接。</p>}
        </div>
      </>}
    </aside>

    <div className="kg-main">
      <div className="kg-command-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索节点、文件或符号…" /><kbd>Ctrl K</kbd></div>
      {diagnostics?.warnings?.length > 0 && <div className="kg-coverage-warning"><AlertTriangle size={16} /><div><strong>{diagnostics.analysis_mode === "full" ? "图谱证据仍需检查" : "当前为部分分析"}</strong><span>{diagnostics.warnings.join(" ")}</span></div><em>{diagnostics.confirmed_calls} 确定调用 / {diagnostics.candidate_relations} 候选关系</em></div>}
      <div className="kg-toolbar">
        <div className="kg-levels">{(["repository", "module", "file", "symbol"] as Level[]).map((item) => <button disabled={view === "coremap" || view === "surprises"} className={level === item ? "active" : ""} key={item} onClick={() => setLevel(item)}>{({ repository: "仓库", module: "模块", file: "文件", symbol: "符号" } as any)[item]}</button>)}</div>
        <label><input type="checkbox" checked={layers.domain} onChange={(event) => setLayers((value) => ({ ...value, domain: event.target.checked }))} />领域知识</label>
        <label><input type="checkbox" checked={layers.knowledge} onChange={(event) => setLayers((value) => ({ ...value, knowledge: event.target.checked }))} />Wiki</label>
        <label className="candidate-switch"><input type="checkbox" checked={includeCandidates} onChange={(event) => setIncludeCandidates(event.target.checked)} />候选关系</label>
        <button className={showLabels ? "active" : ""} onClick={() => setShowLabels((value) => !value)}>节点名称</button>
        <button className={showEdgeLabels ? "active" : ""} onClick={() => setShowEdgeLabels((value) => !value)}>关系名称</button>
        <button title="刷新" onClick={() => void load()}><RefreshCw className={loading ? "spin" : ""} size={14} /></button>
        {scope.type === "repository" && <button onClick={rebuild}><Activity size={14} />重建图谱</button>}
        {scope.type === "repository" && <button disabled={runs.length < 2} onClick={compareVersions} title={runs.length < 2 ? "至少需要两个图谱运行快照" : "比较最近两个运行快照"}><GitCompare size={14} />版本差异</button>}
        <a href={`/api/graph/export.graphml?${query({ scope_type: scope.type, scope_id: scope.id, level })}`}><Download size={14} />GraphML</a>
      </div>
      {focusedCommunity && <div className="kg-focus-bar"><Target size={14} />正在分析社区 <code>{focusedCommunity.split(":").pop()}</code><button onClick={() => setFocusedCommunity(null)}><X size={13} />清除</button></div>}
      {view === "coremap" && <div className="kg-focus-bar kg-focus-explainer"><Sparkles size={14} /><span><strong>核心星图</strong> 以 God Score 最高的确定性代码节点为锚点，只展开一跳关系；没有编译器确认关系时不会伪造核心链路。</span></div>}
      {view === "surprises" && <div className="kg-focus-bar kg-focus-explainer surprise"><Zap size={14} /><span><strong>惊喜链接</strong> 展示跨模块或跨社区、名称相似度较低但有源码证据的确定关系；它是导航线索，不是额外推断。</span></div>}
      {graphDiff && <div className="kg-diff-bar"><GitCompare size={14} /><strong>最近版本变化</strong><span>节点 +{graphDiff.summary.nodes_added} / -{graphDiff.summary.nodes_removed} / 改 {graphDiff.summary.nodes_changed}</span><span>关系 +{graphDiff.summary.edges_added} / -{graphDiff.summary.edges_removed} / 改 {graphDiff.summary.edges_changed}</span><button onClick={() => setGraphDiff(null)}><X size={13} />关闭</button></div>}
      <div className="kg-pathbar">
        <span><Route size={14} />有向路径</span>
        <button className={pathEndpoints[0] ? "filled" : ""}>{pathEndpoints[0]?.display_name || "Shift+点击选择起点"}</button><ArrowRight size={14} />
        <button className={pathEndpoints[1] ? "filled" : ""}>{pathEndpoints[1]?.display_name || "Shift+点击选择终点"}</button>
        <button className="run" disabled={pathEndpoints.length !== 2 || loading} onClick={findPath}>查找路径</button>
        {pathEndpoints.length > 0 && <button onClick={() => { setPathEndpoints([]); setPath(null); }}><X size={13} />清除</button>}
        {path?.found && <em>{path.edges?.length || 0} 跳 · {includeCandidates ? "含候选" : "仅确定关系"}</em>}
      </div>
      <GraphCanvas graph={focusedGraph} level={level} view={view} selectedNodeId={selected?.id} selectedEdgeId={selectedEdge?.id} showLabels={showLabels} showEdgeLabels={showEdgeLabels} pathNodeIds={path?.nodes?.map((node: any) => node.id) || []} onSelect={selectNode} onSelectEdge={selectEdge} onPathPick={pickPathNode} />
      <div className="kg-statusbar"><span><ShieldCheck size={13} />{diagnostics?.compiler_grade ? "编译器级图谱" : "部分分析图谱"}</span><span>{focusedGraph.nodes?.length || 0} 节点</span><span>{focusedGraph.edges?.length || 0} 关系</span><span>{communities.length} 社区</span>{focusedGraph.truncated && <strong>当前视图已渐进加载</strong>}</div>
    </div>

    <aside className={`kg-inspector ${activeItem ? "open" : ""}`}>
      {selected ? <>
        <header><span className={`kg-kind ${selected.kind}`}><Code2 size={17} /></span><button onClick={() => { setSelected(null); setDetail(null); setSourceSnippet(null); }}><X size={15} /></button></header>
        <small>{selected.kind_label || selected.kind} · {selected.subtype || selected.layer}</small><h3>{selected.display_name || selected.name}</h3><code>{selected.qualified_name || selected.path || selected.id}</code>
        <div className="kg-badges"><span className={selected.certainty === "compiler" ? "confirmed" : "candidate"}>{selected.certainty || "source"}</span>{selected.metrics?.is_hub && <span>核心节点</span>}{selected.metrics?.is_bridge && <span>桥接节点</span>}</div>
        <dl><Info label="模块" value={selected.module_id || "—"} /><Info label="源码" value={selected.path || "—"} /><Info label="位置" value={selected.line_start ? `${selected.line_start}-${selected.line_end || selected.line_start}` : "—"} /><Info label="社区" value={selected.community_id?.split(":").pop() || "—"} /><Info label="入度 / 出度" value={`${selected.metrics?.in_degree || 0} / ${selected.metrics?.out_degree || 0}`} /><Info label="上帝得分" value={Number(selected.metrics?.god_score || 0).toFixed(3)} /><Info label="介数中心性" value={Number(selected.metrics?.betweenness || 0).toFixed(4)} /></dl>
        <div className="kg-expand"><select value={direction} onChange={(event) => setDirection(event.target.value as any)}><option value="both">双向邻居</option><option value="incoming">上游调用者</option><option value="outgoing">下游依赖</option></select><select value={neighborDepth} onChange={(event) => setNeighborDepth(Number(event.target.value))}>{[1, 2, 3].map((item) => <option key={item} value={item}>{item} 跳</option>)}</select><button onClick={expand} disabled={loading}><Network size={14} />展开</button></div>
        {sourceSnippet && <section><h4>源码片段 <em>{sourceSnippet.line_start}-{sourceSnippet.line_end}</em></h4><pre className="kg-source-snippet"><code>{sourceSnippet.content}</code></pre></section>}
        <section><h4>关系与证据 <em>{detail?.edges?.length || 0}</em></h4>{relatedNodes.slice(0, 80).map((item: any) => <button className="kg-relation-row" key={item.edge.id} onClick={() => item.node && void selectNode(item.node)}><i className={item.edge.status} /><span><strong>{RELATION_LABELS[item.edge.kind] || item.edge.kind}</strong><small>{item.direction === "out" ? "→" : "←"} {item.node?.display_name || item.node?.name || item.otherId}</small>{item.edge.evidence?.[0] && <code>{item.edge.evidence[0].source_uri}:{item.edge.evidence[0].line_start || ""}</code>}</span><ChevronRight size={13} /></button>)}</section>
      </> : selectedEdge ? <>
        <header><span className="kg-kind relation"><Link2 size={17} /></span><button onClick={() => setSelectedEdge(null)}><X size={15} /></button></header><small>关系证据</small><h3>{RELATION_LABELS[selectedEdge.kind] || selectedEdge.kind}</h3>
        <div className="kg-badges"><span className={selectedEdge.status === "confirmed" ? "confirmed" : "candidate"}>{selectedEdge.status || selectedEdge.certainty}</span><span>{selectedEdge.origin || "source"}</span></div>
        <dl><Info label="起点" value={edgeDetail?.source_node?.display_name || selectedEdge.source} /><Info label="终点" value={edgeDetail?.target_node?.display_name || selectedEdge.target} /><Info label="置信度" value={Number(selectedEdge.confidence || 0).toFixed(2)} /><Info label="证据数量" value={edgeDetail?.evidence?.length ?? selectedEdge.evidence_count ?? selectedEdge.count ?? 0} /></dl>
        {selectedEdge.status === "candidate" && <div className="kg-review-actions"><button className="confirm" onClick={() => void reviewEdge(true)}><CheckCircle2 size={14} />确认为关系</button><button className="reject" onClick={() => void reviewEdge(false)}><X size={14} />否决候选</button></div>}
        {selectedEdge.kind === "SURPRISING_CONNECTION" && <section className="kg-insight-card"><h4>为什么是惊喜链接</h4><p>{selectedEdge.metadata?.insight?.summary || "该关系跨越了目录或社区边界，值得作为导航线索进一步检查。"}</p><small>惊喜得分：{Number(selectedEdge.score || selectedEdge.confidence || 0).toFixed(3)}</small></section>}
        <section><h4>来源证据<em>{edgeDetail?.evidence?.length || 0}</em></h4>{edgeDetail?.evidence?.map((item: any, index: number) => <div className="kg-evidence-row" key={item.id || `${item.source_uri}-${index}`}><strong>{item.source_uri || "结构化分析"}</strong><span>{item.line_start ? `${item.line_start}-${item.line_end || item.line_start}` : "无行号"} · {item.extractor || selectedEdge.origin}</span>{item.reason && <p>{item.reason}</p>}</div>)}{edgeDetail && !edgeDetail.evidence?.length && <p className="kg-note">该聚合关系没有独立源码位置，请进入两端节点检查结构来源。</p>}</section>
        <p className="kg-note">候选边不会进入默认确定调用链；只有人工确认后才会作为确定关系参与导航和检索。</p>
      </> : <div className="kg-inspector-empty"><Sparkles size={26} /><h3>证据检查器</h3><p>点击节点查看源码位置、指标、上下游关系和每条边的来源证据。</p></div>}
    </aside>
  </section>;
}

function Info({ label, value }: { label: string; value: any }) { return <div><dt>{label}</dt><dd>{String(value)}</dd></div>; }
function message(error: unknown) { return error instanceof Error ? error.message : String(error); }

function mergeGraphs(left: any, right: any) {
  const nodes = new Map<string, any>(); const edges = new Map<string, any>();
  [...(left.nodes || []), ...(right.nodes || [])].forEach((item) => nodes.set(item.id, item));
  [...(left.edges || []), ...(right.edges || [])].forEach((item) => edges.set(item.id, item));
  return { ...left, ...right, nodes: [...nodes.values()], edges: [...edges.values()], truncated: left.truncated || right.truncated };
}

function relationRows(detail: any, loadedNodes: any[]) {
  const nodes = new Map(loadedNodes.map((node) => [node.id, node]));
  return (detail.edges || []).map((edge: any) => {
    const direction = edge.source === detail.node.id ? "out" : "in";
    const otherId = direction === "out" ? edge.target : edge.source;
    return { edge, direction, otherId, node: nodes.get(otherId) };
  });
}
