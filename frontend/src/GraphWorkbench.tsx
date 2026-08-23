import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowRight, ArrowUpFromLine, Boxes, Braces,
  CheckCircle2, ChevronRight, CircleDot, Code2, Download, FileCode2, FileText, GitCompare,
  Layers3, Link2, LoaderCircle, Network, RefreshCw, Route, Search, ShieldCheck, Sparkles,
  Split, Target, X, Zap,
} from "lucide-react";
import { api, query } from "./api";
import GraphCanvas from "./GraphCanvas";
const Graph3D = lazy(() => import("./Graph3D"));

type Scope = { type: "repository" | "collection"; id: string; name: string } | null;
type Level = "repository" | "module" | "file" | "symbol";
type GraphView = "hierarchy" | "callflow" | "dataflow" | "impact";
type RenderMode = "2d" | "3d";
type ThreeDPreset = "universe" | "community" | "ego" | "impact" | "surprise";

const VIEWS: Array<{ id: GraphView; label: string; description: string; level: Level; kinds?: string[]; icon: typeof Network }> = [
  { id: "hierarchy", label: "代码地图", description: "仓库、信道、模块、文件的导航骨架", level: "module", icon: Layers3 },
  { id: "callflow", label: "执行链路", description: "从核心函数逐层展开调用与回调", level: "symbol", kinds: ["CALLS", "REGISTER_CALLBACK", "INVOKES_CALLBACK", "POSSIBLE_CALL", "SENDS", "RECEIVES"], icon: Route },
  { id: "dataflow", label: "数据与状态", description: "字段、配置、读写和状态传播", level: "symbol", kinds: ["READS", "WRITES", "USES_TYPE", "PASSES_TO", "CONFIGURES", "TRANSITIONS_TO", "PRODUCES", "CONSUMES", "LOCKS", "UNLOCKS"], icon: Braces },
  { id: "impact", label: "变更影响", description: "选择实体后定位必须检查和验证范围", level: "symbol", icon: Split },
];

const RELATION_LABELS: Record<string, string> = {
  CONTAINS: "包含", BUILDS: "构建", COMPILES: "编译", DECLARES: "声明", DEFINES: "定义",
  CALLS: "调用", POSSIBLE_CALL: "可能调用", REFERENCES: "引用", READS: "读取", WRITES: "写入",
  USES_TYPE: "使用类型", PASSES_TO: "参数传递", REGISTER_CALLBACK: "注册回调",
  INVOKES_CALLBACK: "触发回调", INCLUDES: "包含头文件", CONFIGURES: "配置",
  ALLOCATES: "分配", INITIALIZES: "初始化", OWNS: "拥有", BORROWS: "借用", RELEASES: "释放", LOCKS: "加锁", UNLOCKS: "解锁",
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
  const [inspectorOpen, setInspectorOpen] = useState(false);
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
  const [symbolResults, setSymbolResults] = useState<any[]>([]);
  const [symbolSearching, setSymbolSearching] = useState(false);
  const [callflowEntries, setCallflowEntries] = useState<any[]>([]);
  const [impactKind, setImpactKind] = useState("implementation");
  const [impactSummary, setImpactSummary] = useState<any>(null);
  const [renderMode, setRenderMode] = useState<RenderMode>("2d");
  const [threeDPreset, setThreeDPreset] = useState<ThreeDPreset>("universe");
  const loadVersion = useRef(0);
  const searchInput = useRef<HTMLInputElement>(null);

  const preset = VIEWS.find((item) => item.id === view) || VIEWS[0];
  const callableSelected = selected?.kind === "symbol" && ["function", "method", "callback"].includes(String(selected?.subtype || "").toLowerCase());
  const threeDEligible = view === "hierarchy" || (view === "callflow" && callableSelected) || (view === "impact" && Boolean(impactSummary));
  const callAnchorId = view === "callflow" && callableSelected ? selected.id : null;
  const threeDAnchorId = renderMode === "3d" && (view === "callflow" || view === "impact") ? selected?.id || null : null;

  const load = useCallback(async () => {
    if (!scope) return;
    const requestVersion = ++loadVersion.current;
    if (view === "impact") {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const statuses = includeCandidates ? ["confirmed", "candidate"] : ["confirmed"];
      const activeLayers = Object.entries(layers).filter(([, enabled]) => enabled).map(([name]) => name);
      let value: any;
      if (view === "callflow" && callAnchorId) {
        value = await api.get<any>(neighborUrl({
          node_id: callAnchorId, depth: neighborDepth, limit: 80,
          scope_type: scope.type, scope_id: scope.id, level: "symbol",
          direction: "both", include_candidates: includeCandidates,
        }, preset.kinds));
      } else if (view === "callflow" && level === "symbol" && scope.type === "repository" && !focusedCommunity) {
        value = await api.get<any>(`/api/graph/core-functions?${query({ repository_id: scope.id, limit: 80 })}`);
        if (requestVersion !== loadVersion.current) return;
        setCallflowEntries(value.nodes || []);
        setGraph({
          ...value,
          nodes: [], edges: [],
          displayed_nodes: 0,
          total_matching_nodes: value.total || value.nodes?.length || 0,
          displayed_edges: 0,
          total_matching_edges: 0,
        });
        setDiagnostics(value.diagnostics || null);
        setPath(null);
        return;
      } else {
        const graphView = view === "hierarchy" && renderMode === "3d"
          ? threeDPreset === "surprise" ? "surprises" : "universe"
          : view;
        const graphLevel = view === "hierarchy" && renderMode === "3d" ? "symbol" : level;
        const params = new URLSearchParams({
          scope_type: scope.type, scope_id: scope.id, level: graphLevel,
          view: graphView, limit: renderMode === "3d" ? "500" : graphLevel === "symbol" ? "250" : "220",
        });
        statuses.forEach((item) => params.append("statuses", item));
        activeLayers.forEach((item) => params.append("layers", item));
        preset.kinds?.forEach((item) => params.append("kinds", item));
        if (focusedCommunity && threeDPreset !== "surprise") params.set("community_id", focusedCommunity);
        value = await api.get<any>(`/api/graph?${params.toString()}`);
      }
      if (requestVersion !== loadVersion.current) return;
      setGraph(value); setDiagnostics((current: any) => value.diagnostics || (view === "callflow" ? current : null)); setPath(null);
    } catch (error) { if (requestVersion === loadVersion.current) notify(message(error), true); }
    finally { if (requestVersion === loadVersion.current) setLoading(false); }
  }, [scope?.type, scope?.id, view, level, includeCandidates, layers.code, layers.domain, layers.knowledge, focusedCommunity, renderMode, threeDPreset, callAnchorId, neighborDepth]);

  useEffect(() => {
    setLevel(preset.level);
    setSymbolResults([]);
    if (view !== "impact") setImpactSummary(null);
    if (view === "dataflow" || (view === "callflow" && !selected) || (view === "impact" && !impactSummary)) setRenderMode("2d");
    setSelectedEdge(null);
    setEdgeDetail(null);
  }, [view]);
  useEffect(() => {
    setSelected(null); setSelectedEdge(null); setInspectorOpen(false); setDetail(null); setEdgeDetail(null); setSourceSnippet(null); setCallflowEntries([]); setDiagnostics(null);
    setPathEndpoints([]); setPath(null); setRenderMode("2d"); setThreeDPreset("universe");
  }, [scope?.type, scope?.id]);
  useEffect(() => {
    if (renderMode === "3d" && !threeDEligible) setRenderMode("2d");
  }, [renderMode, threeDEligible]);
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
    if (!node && view === "callflow" && callableSelected) {
      setSelectedEdge(null); setInspectorOpen(false); setEdgeDetail(null); setDetail(null); setSourceSnippet(null);
      return;
    }
    setSelected(node); setSelectedEdge(null); setEdgeDetail(null); setDetail(null); setSourceSnippet(null);
    setInspectorOpen(Boolean(node));
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
  }, [notify, scope?.type, scope?.id, view, callableSelected]);

  const selectEdge = useCallback(async (edge: any | null) => {
    setSelectedEdge(edge); setInspectorOpen(Boolean(edge));
    if (view !== "callflow") setSelected(null);
    setDetail(null); setEdgeDetail(null);
    if (!edge?.id || edge.id.startsWith("module-edge:") || edge.id.startsWith("community-edge:")) return;
    if (edge.kind === "SURPRISING_CONNECTION") {
      const nodes = new Map((graph.nodes || []).map((node: any) => [node.id, node]));
      setEdgeDetail({ edge, source_node: nodes.get(edge.source), target_node: nodes.get(edge.target), evidence: edge.metadata?.evidence || [] });
      return;
    }
    try { setEdgeDetail(await api.get(`/api/graph/edges/${encodeURIComponent(edge.id)}`)); }
    catch (error) { notify(message(error), true); }
  }, [notify, graph.nodes, view]);

  const activateView = (nextView: GraphView) => {
    setRenderMode("2d");
    setThreeDPreset(nextView === "callflow" ? "ego" : nextView === "impact" ? "impact" : "universe");
    setFocusedCommunity(null);
    setView(nextView);
  };

  const openCommunityUniverse = (community: any) => {
    setView("hierarchy");
    setLevel("module");
    setFocusedCommunity(community.id);
    setThreeDPreset("community");
    setRenderMode("3d");
  };

  const openInsightNode = (node: any) => {
    setView("hierarchy");
    setFocusedCommunity(null);
    setThreeDPreset("universe");
    setRenderMode("3d");
    void selectNode(node);
  };

  const openSurpriseUniverse = (item: any) => {
    setView("hierarchy");
    setFocusedCommunity(null);
    setThreeDPreset("surprise");
    setRenderMode("3d");
    void selectEdge({
      id: item.id, kind: "SURPRISING_CONNECTION", source: item.source_id, target: item.target_id,
      metadata: { insight: item.reason, evidence: item.evidence }, score: item.score, status: "confirmed",
    });
  };

  const drill3DNode = useCallback(async (node: any) => {
    if (!scope) return;
    if (node.kind === "community") {
      setFocusedCommunity(node.id);
      setThreeDPreset("community");
      return;
    }
    await selectNode(node);
    try {
      const value = await api.get<any>(`/api/graph/neighbors?${query({
        node_id: node.id, depth: 1, limit: 80, scope_type: scope.type, scope_id: scope.id,
        level: node.kind === "module" ? "file" : "symbol", direction: "both",
        include_candidates: includeCandidates,
      })}`);
      setGraph(value);
      if (node.kind !== "module") setThreeDPreset("ego");
    } catch (error) { notify(message(error), true); }
  }, [scope?.type, scope?.id, includeCandidates, notify, selectNode]);

  const reviewEdge = async (confirmed: boolean) => {
    if (!selectedEdge?.id) return;
    try {
      const value: any = await api.patch(`/api/graph/edges/${encodeURIComponent(selectedEdge.id)}?confirmed=${confirmed}`, {});
      notify(confirmed ? "候选关系已确认为事实关系。" : "候选关系已否决并从默认视图隐藏。");
      setSelectedEdge(value); setEdgeDetail((current: any) => current ? { ...current, edge: value } : current);
      await load();
    } catch (error) { notify(message(error), true); }
  };

  const searchSymbols = async () => {
    if (!scope || !search.trim()) { setSymbolResults([]); return; }
    setSymbolSearching(true);
    try {
      const value = await api.get<any>(`/api/graph/symbol-search?${query({ scope_type: scope.type, scope_id: scope.id, query: search.trim(), limit: 12 })}`);
      setSymbolResults(value.results || []);
      if (!value.results?.length) notify("没有找到匹配的函数或方法。");
    } catch (error) { notify(message(error), true); }
    finally { setSymbolSearching(false); }
  };

  const focusSymbol = async (node: any) => {
    if (!scope) return;
    setSymbolResults([]);
    setSearch("");
    setRenderMode("2d");
    setThreeDPreset("ego");
    setView("callflow");
    setLevel("symbol");
    setSelected(node);
    try {
      const value = await api.get<any>(neighborUrl({
        node_id: node.id, depth: 1, limit: 40, scope_type: scope.type, scope_id: scope.id,
        level: "symbol", direction: "both", include_candidates: includeCandidates,
      }, VIEWS.find((item) => item.id === "callflow")?.kinds));
      setGraph(value);
      setDiagnostics(value.diagnostics || diagnostics);
      await selectNode(node);
    } catch (error) { notify(message(error), true); }
  };

  const runImpact = async () => {
    if (!scope || !selected) return;
    setLoading(true);
    try {
      const value = await api.post<any>("/api/graph/impact", {
        scope_type: scope.type, scope_id: scope.id, anchor_id: selected.id,
        change_kind: impactKind, depth: neighborDepth, include_candidates: includeCandidates, limit: 250,
      });
      setGraph(value);
      setImpactSummary(value);
      setDiagnostics(value.diagnostics || null);
      setSelected(value.anchor || selected);
      setSelectedEdge(null);
    } catch (error) { notify(message(error), true); }
    finally { setLoading(false); }
  };

  const expand = async () => {
    if (!selected || !scope) return;
    setLoading(true);
    try {
      const value = await api.get<any>(neighborUrl({
        node_id: selected.id, depth: neighborDepth, limit: view === "callflow" ? (neighborDepth === 1 ? 40 : 80) : 80, scope_type: scope.type, scope_id: scope.id,
        level, direction, include_candidates: includeCandidates,
      }, view === "callflow" ? preset.kinds : undefined));
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
  const renderedGraph = useMemo(
    () => view === "callflow" && callAnchorId ? callflowProjection(focusedGraph, callAnchorId) : focusedGraph,
    [focusedGraph, view, callAnchorId],
  );
  const activeItem = selectedEdge || (inspectorOpen ? selected : null);
  const relatedNodes = detail?.node ? relationRows(detail, graph.nodes || []) : [];

  if (!scope) return <div className="center-empty">请先选择代码仓或知识空间。</div>;
  return <section className="kg-workbench kg-graphify">
    <aside className="kg-navigator">
      <div className="kg-graph-brand"><span><Network size={17} /></span><div><strong>ClangWiki Graph</strong><small>代码知识图谱</small></div></div>
      <div className="kg-section-title"><span>分析视图</span><small>{VIEWS.length}</small></div>
      <div className="kg-view-list">{VIEWS.map((item) => { const Icon = item.icon; return <button className={view === item.id ? "active" : ""} key={item.id} onClick={() => activateView(item.id)}><Icon size={15} /><span><strong>{item.label}</strong><small>{item.description}</small></span></button>; })}</div>
      {scope.type === "repository" && <>
        <div className="kg-insight-tabs">{(["community", "hub", "bridge", "cycle", "orphan", "surprise"] as const).map((item) => <button key={item} className={insight === item ? "active" : ""} onClick={() => setInsight(item)}>{({ community: "社区", hub: "核心", bridge: "桥梁", cycle: "循环", orphan: "孤点", surprise: "惊喜" } as any)[item]}</button>)}</div>
        <div className="kg-insight-list">
          {insight === "community" ? communities.map((item) => <button key={item.id} onClick={() => openCommunityUniverse(item)}><i style={{ background: item.color }} /><span><strong>{item.name}</strong><small>{item.member_count} 节点 · 内聚 {Number(item.cohesion || 0).toFixed(2)}</small></span><ChevronRight size={13} /></button>) : insight === "cycle" ? insights.cycle.map((item, index) => <button key={`${item.size}-${index}`} onClick={() => item.nodes?.[0] && void selectNode(item.nodes[0])}><RefreshCw size={12} /><span><strong>{item.size} 节点循环</strong><small>{item.nodes?.slice(0, 3).map((node: any) => node.display_name || node.name).join(" → ")}</small></span><ChevronRight size={13} /></button>) : insight === "surprise" ? insights.surprise.map((item) => <button className="kg-surprise-row" key={item.id} onClick={() => openSurpriseUniverse(item)}><Zap size={12} /><span><strong>{item.source?.display_name || item.source_id} → {item.target?.display_name || item.target_id}</strong><small>{item.reason?.summary || "跨模块确定关系"} · 得分 {Number(item.score || 0).toFixed(2)}</small></span><ChevronRight size={13} /></button>) : insights[insight].map((item) => <button key={item.id} onClick={() => insight === "hub" || insight === "bridge" ? openInsightNode(item) : void selectNode(item)}><CircleDot size={12} /><span><strong>{item.display_name || item.name}</strong><small>{item.module_id || item.path || item.subtype}</small></span><ChevronRight size={13} /></button>)}
          {insight === "community" && !communities.length && <p>重建图谱后将在这里显示耦合社区。</p>}
          {insight === "surprise" && !insights.surprise.length && <p>当前运行尚未发现跨模块的确定性惊喜链接。</p>}
        </div>
      </>}
    </aside>

    <div className="kg-main">
      <div className="kg-command-search-wrap">
        <div className="kg-command-search"><Search size={15} /><input ref={searchInput} value={search} onChange={(event) => { setSearch(event.target.value); if (!event.target.value.trim()) setSymbolResults([]); }} onKeyDown={(event) => { if (event.key === "Enter") void searchSymbols(); }} placeholder={view === "callflow" ? "搜索执行入口函数后按 Enter…" : "搜索函数后按 Enter，或过滤当前图…"} /><kbd>{symbolSearching ? "…" : "Enter"}</kbd></div>
        {symbolResults.length > 0 && <div className="kg-symbol-results">{symbolResults.map((item) => <button key={item.id} onClick={() => void focusSymbol(item)}><Code2 size={14} /><span><strong>{item.display_name || item.name}</strong><small>{item.path || item.qualified_name || "未定位源码"}</small></span><ChevronRight size={13} /></button>)}</div>}
      </div>
      {diagnostics?.warnings?.length > 0 && <div className="kg-coverage-warning"><AlertTriangle size={16} /><div><strong>{diagnostics.analysis_mode === "full" ? "图谱证据仍需检查" : "当前为部分分析"}</strong><span>{diagnostics.warnings.join(" ")}</span></div><em>{diagnostics.confirmed_calls} 确定调用 / {diagnostics.candidate_relations} 候选关系</em></div>}
      <div className="kg-toolbar">
        <div className="kg-levels">{(["repository", "module", "file", "symbol"] as Level[]).map((item) => <button disabled={view === "impact" || view === "callflow" || renderMode === "3d"} className={level === item ? "active" : ""} key={item} onClick={() => setLevel(item)}>{({ repository: "仓库", module: "模块", file: "文件", symbol: "符号" } as any)[item]}</button>)}</div>
        <label><input type="checkbox" checked={layers.domain} onChange={(event) => setLayers((value) => ({ ...value, domain: event.target.checked }))} />领域知识</label>
        <label><input type="checkbox" checked={layers.knowledge} onChange={(event) => setLayers((value) => ({ ...value, knowledge: event.target.checked }))} />Wiki</label>
        <label className="candidate-switch"><input type="checkbox" checked={includeCandidates} onChange={(event) => setIncludeCandidates(event.target.checked)} />候选关系</label>
        {renderMode === "2d" && <button className={showLabels ? "active" : ""} onClick={() => setShowLabels((value) => !value)}>节点名称</button>}
        {renderMode === "2d" && <button className={showEdgeLabels ? "active" : ""} onClick={() => setShowEdgeLabels((value) => !value)}>关系名称</button>}
        {threeDEligible && <div className="kg-render-modes" aria-label="图谱显示模式"><button className={renderMode === "2d" ? "active" : ""} onClick={() => setRenderMode("2d")}>2D分析</button><button className={renderMode === "3d" ? "active" : ""} onClick={() => { setThreeDPreset(view === "callflow" ? "ego" : view === "impact" ? "impact" : threeDPreset); setRenderMode("3d"); }}>3D沉浸</button></div>}
        {view === "impact" && <><select className="kg-impact-select" value={impactKind} onChange={(event) => setImpactKind(event.target.value)}><option value="implementation">实现修改</option><option value="signature">接口签名</option><option value="data_layout">数据结构</option><option value="header">头文件</option><option value="interface">跨模块接口</option><option value="config">配置项</option><option value="module">模块边界</option></select><button className="active" disabled={!selected || loading} onClick={() => void runImpact()}><Target size={14} />分析影响</button></>}
        <button title="刷新" onClick={() => void load()}><RefreshCw className={loading ? "spin" : ""} size={14} /></button>
        {scope.type === "repository" && <button onClick={rebuild}><Activity size={14} />重建图谱</button>}
        {scope.type === "repository" && <button disabled={runs.length < 2} onClick={compareVersions} title={runs.length < 2 ? "至少需要两个图谱运行快照" : "比较最近两个运行快照"}><GitCompare size={14} />版本差异</button>}
        <a href={`/api/graph/export.graphml?${query({ scope_type: scope.type, scope_id: scope.id, level })}`}><Download size={14} />GraphML</a>
      </div>
      {focusedCommunity && <div className="kg-focus-bar"><Target size={14} />正在分析社区 <code>{focusedCommunity.split(":").pop()}</code><button onClick={() => setFocusedCommunity(null)}><X size={13} />清除</button></div>}
      {renderMode === "3d" && <div className={`kg-focus-bar kg-focus-explainer kg-3d-explainer ${threeDPreset === "surprise" ? "surprise" : ""}`}><Sparkles size={14} /><span><strong>{threeDPresetLabel(threeDPreset)}</strong> {threeDPresetDescription(threeDPreset)}</span><em>3D用于探索，证据与精确路径仍以2D分析为准</em></div>}
      {view === "impact" && <div className="kg-focus-bar kg-focus-explainer"><Target size={14} /><span><strong>变更影响</strong> 先在其他视图中选择要修改的函数、结构体、文件或模块，再选择影响类型并执行分析。结果按“必须检查 / 可能需要修改 / 需要验证”分层展示。</span></div>}
      {graphDiff && <div className="kg-diff-bar"><GitCompare size={14} /><strong>最近版本变化</strong><span>节点 +{graphDiff.summary.nodes_added} / -{graphDiff.summary.nodes_removed} / 改 {graphDiff.summary.nodes_changed}</span><span>关系 +{graphDiff.summary.edges_added} / -{graphDiff.summary.edges_removed} / 改 {graphDiff.summary.edges_changed}</span><button onClick={() => setGraphDiff(null)}><X size={13} />关闭</button></div>}
      {view === "impact" && impactSummary && <div className="kg-impact-summary"><span><strong>{impactSummary.impact_tiers?.must_review?.length || 0}</strong> 必须检查</span><span><strong>{impactSummary.impact_tiers?.possible_change?.length || 0}</strong> 可能修改</span><span><strong>{impactSummary.impact_tiers?.verify?.length || 0}</strong> 需要验证</span><small>{impactSummary.truncated ? "结果已截断，可继续缩小范围" : "已覆盖当前证据范围"}</small></div>}
      {view === "callflow" && callAnchorId && <div className="kg-callflow-summary">
        <span className="anchor"><Route size={14} /><strong>{selected?.display_name || selected?.name}</strong></span>
        <span><b>{graph.by_direction?.incoming || 0}</b> 上游关系</span>
        <span><b>{graph.by_direction?.outgoing || 0}</b> 下游关系</span>
        <span><b>{(graph.by_relation?.REGISTER_CALLBACK || 0) + (graph.by_relation?.INVOKES_CALLBACK || 0)}</b> 回调</span>
        <span><b>{graph.direct_neighbors || 0}</b> 一跳</span>
        <span><b>{graph.second_hop_neighbors || 0}</b> 二跳</span>
        <em>{graph.confirmed_edges || 0} 确定 / {graph.candidate_edges || 0} 候选</em>
        <button onClick={() => { setSelected(null); setInspectorOpen(false); setDetail(null); setSourceSnippet(null); setRenderMode("2d"); }}><X size={13} />更换入口</button>
      </div>}
      {(view !== "callflow" || callAnchorId) && <div className="kg-pathbar">
        <span><Route size={14} />有向路径</span>
        <button className={pathEndpoints[0] ? "filled" : ""}>{pathEndpoints[0]?.display_name || "Shift+点击选择起点"}</button><ArrowRight size={14} />
        <button className={pathEndpoints[1] ? "filled" : ""}>{pathEndpoints[1]?.display_name || "Shift+点击选择终点"}</button>
        <button className="run" disabled={pathEndpoints.length !== 2 || loading} onClick={findPath}>查找路径</button>
        {pathEndpoints.length > 0 && <button onClick={() => { setPathEndpoints([]); setPath(null); }}><X size={13} />清除</button>}
        {path?.found && <em>{path.edges?.length || 0} 跳 · {includeCandidates ? "含候选" : "仅确定关系"}</em>}
      </div>}
      {view === "impact" && !impactSummary && <div className="kg-impact-empty"><Target size={28} /><h3>选择一个变更锚点</h3><p>返回代码地图或执行链路，点击目标节点后再进入本视图。</p></div>}
      {view === "callflow" && !callAnchorId && <CallflowEntryPicker
        entries={callflowEntries}
        diagnostics={diagnostics}
        includeCandidates={includeCandidates}
        loading={loading}
        onSearch={() => searchInput.current?.focus()}
        onSelect={(node) => void focusSymbol(node)}
        onEnableCandidates={() => setIncludeCandidates(true)}
      />}
      {view === "impact" && !impactSummary ? null : view === "callflow" && !callAnchorId ? null : renderMode === "3d" ? <Suspense fallback={<div className="graph-3d-fallback">正在加载 3D 沉浸视图…</div>}><Graph3D graph={renderedGraph} preset={threeDPreset} selectedNodeId={selected?.id || null} anchorId={threeDAnchorId} onSelect={selectNode} onNodeDoubleClick={drill3DNode} onFallback={(reason) => { setRenderMode("2d"); notify(`3D视图不可用，已返回2D分析：${reason}`, true); }} /></Suspense> : <GraphCanvas graph={renderedGraph} level={level} view={view} callflowAnchorId={callAnchorId} selectedNodeId={selected?.id} selectedEdgeId={selectedEdge?.id} showLabels={showLabels} showEdgeLabels={showEdgeLabels} pathNodeIds={path?.nodes?.map((node: any) => node.id) || []} onSelect={selectNode} onSelectEdge={selectEdge} onPathPick={pickPathNode} />}
      <div className="kg-statusbar"><span><ShieldCheck size={13} />{diagnostics?.compiler_grade ? "编译器级图谱" : diagnostics ? "部分分析图谱" : "等待影响分析"}</span><span>{renderedGraph.displayed_nodes ?? renderedGraph.nodes?.length ?? 0} / {renderedGraph.total_matching_nodes ?? renderedGraph.nodes?.length ?? 0} 节点</span><span>{renderedGraph.displayed_edges ?? renderedGraph.edges?.length ?? 0} / {renderedGraph.total_matching_edges ?? renderedGraph.edges?.length ?? 0} 关系</span><span>{communities.length} 社区</span>{renderedGraph.truncated && <strong>当前视图已渐进加载</strong>}</div>
    </div>

    <aside className={`kg-inspector ${activeItem ? "open" : ""}`}>
      {selectedEdge ? <>
        <header><span className="kg-kind relation"><Link2 size={17} /></span><button onClick={() => { setSelectedEdge(null); setInspectorOpen(false); }}><X size={15} /></button></header><small>关系证据</small><h3>{RELATION_LABELS[selectedEdge.kind] || selectedEdge.kind}</h3>
        <div className="kg-badges"><span className={selectedEdge.status === "confirmed" ? "confirmed" : "candidate"}>{selectedEdge.status || selectedEdge.certainty}</span><span>{selectedEdge.origin || "source"}</span></div>
        <dl><Info label="起点" value={edgeDetail?.source_node?.display_name || selectedEdge.source} /><Info label="终点" value={edgeDetail?.target_node?.display_name || selectedEdge.target} /><Info label="置信度" value={Number(selectedEdge.confidence || 0).toFixed(2)} /><Info label="证据数量" value={edgeDetail?.evidence?.length ?? selectedEdge.evidence_count ?? selectedEdge.count ?? 0} /></dl>
        {selectedEdge.status === "candidate" && <div className="kg-review-actions"><button className="confirm" onClick={() => void reviewEdge(true)}><CheckCircle2 size={14} />确认为关系</button><button className="reject" onClick={() => void reviewEdge(false)}><X size={14} />否决候选</button></div>}
        {selectedEdge.kind === "SURPRISING_CONNECTION" && <section className="kg-insight-card"><h4>为什么是惊喜链接</h4><p>{selectedEdge.metadata?.insight?.summary || "该关系跨越了目录或社区边界，值得作为导航线索进一步检查。"}</p><small>惊喜得分：{Number(selectedEdge.score || selectedEdge.confidence || 0).toFixed(3)}</small></section>}
        <section><h4>来源证据<em>{edgeDetail?.evidence?.length || 0}</em></h4>{edgeDetail?.evidence?.map((item: any, index: number) => <div className="kg-evidence-row" key={item.id || `${item.source_uri}-${index}`}><strong>{item.source_uri || "结构化分析"}</strong><span>{item.line_start ? `${item.line_start}-${item.line_end || item.line_start}` : "无行号"} · {item.extractor || selectedEdge.origin}</span>{item.reason && <p>{item.reason}</p>}</div>)}{edgeDetail && !edgeDetail.evidence?.length && <p className="kg-note">该聚合关系没有独立源码位置，请进入两端节点检查结构来源。</p>}</section>
        <p className="kg-note">候选边不会进入默认确定调用链；只有人工确认后才会作为确定关系参与导航和检索。</p>
      </> : selected && inspectorOpen ? <>
        <header><span className={`kg-kind ${selected.kind}`}><Code2 size={17} /></span><button onClick={() => { setInspectorOpen(false); setDetail(null); setSourceSnippet(null); }}><X size={15} /></button></header>
        <small>{selected.kind_label || selected.kind} · {selected.subtype || selected.layer}</small><h3>{selected.display_name || selected.name}</h3><code>{selected.qualified_name || selected.path || selected.id}</code>
        <div className="kg-badges"><span className={selected.certainty === "compiler" ? "confirmed" : "candidate"}>{selected.certainty || "source"}</span>{selected.metrics?.is_hub && <span>核心节点</span>}{selected.metrics?.is_bridge && <span>桥接节点</span>}{selected.impact_label && <span className={`impact-tier-${selected.impact_tier}`}>{selected.impact_label}</span>}</div>
        <dl><Info label="模块" value={selected.module_id || "—"} /><Info label="源码" value={selected.path || "—"} /><Info label="位置" value={selected.line_start ? `${selected.line_start}-${selected.line_end || selected.line_start}` : "—"} /><Info label="社区" value={selected.community_id?.split(":").pop() || "—"} /><Info label="入度 / 出度" value={`${selected.metrics?.in_degree || 0} / ${selected.metrics?.out_degree || 0}`} /><Info label="上帝得分" value={Number(selected.metrics?.god_score || 0).toFixed(3)} /><Info label="介数中心性" value={Number(selected.metrics?.betweenness || 0).toFixed(4)} /></dl>
        <div className="kg-expand"><select value={direction} onChange={(event) => setDirection(event.target.value as any)}><option value="both">双向邻居</option><option value="incoming">上游调用者</option><option value="outgoing">下游依赖</option></select><select value={neighborDepth} onChange={(event) => setNeighborDepth(Number(event.target.value))}>{[1, 2, 3].map((item) => <option key={item} value={item}>{item} 跳</option>)}</select><button onClick={expand} disabled={loading}><Network size={14} />展开</button></div>
        {sourceSnippet && <section><h4>源码片段 <em>{sourceSnippet.line_start}-{sourceSnippet.line_end}</em></h4><pre className="kg-source-snippet"><code>{sourceSnippet.content}</code></pre></section>}
        <section><h4>关系与证据 <em>{detail?.edges?.length || 0}</em></h4>{relatedNodes.slice(0, 80).map((item: any) => <button className="kg-relation-row" key={item.edge.id} onClick={() => item.node && void selectNode(item.node)}><i className={item.edge.status} /><span><strong>{RELATION_LABELS[item.edge.kind] || item.edge.kind}</strong><small>{item.direction === "out" ? "→" : "←"} {item.node?.display_name || item.node?.name || item.otherId}</small>{item.edge.evidence?.[0] && <code>{item.edge.evidence[0].source_uri}:{item.edge.evidence[0].line_start || ""}</code>}</span><ChevronRight size={13} /></button>)}</section>
      </> : <div className="kg-inspector-empty"><Sparkles size={26} /><h3>证据检查器</h3><p>点击节点查看源码位置、指标、上下游关系和每条边的来源证据。</p></div>}
    </aside>
  </section>;
}

function Info({ label, value }: { label: string; value: any }) { return <div><dt>{label}</dt><dd>{String(value)}</dd></div>; }
function message(error: unknown) { return error instanceof Error ? error.message : String(error); }

function CallflowEntryPicker({
  entries, diagnostics, includeCandidates, loading, onSearch, onSelect, onEnableCandidates,
}: {
  entries: any[];
  diagnostics: any;
  includeCandidates: boolean;
  loading: boolean;
  onSearch: () => void;
  onSelect: (node: any) => void;
  onEnableCandidates: () => void;
}) {
  const confirmedCalls = Number(diagnostics?.confirmed_calls || 0);
  const candidates = Number(diagnostics?.candidate_relations || 0);
  return <div className={`kg-callflow-entry-picker ${diagnostics?.warnings?.length ? "with-warning" : ""}`}>
    <header>
      <span><Route size={20} /></span>
      <div><small>EXECUTION ENTRY</small><h3>先选择一个执行入口</h3><p>执行链路只展示与目标函数真实相连的一跳或两跳关系，不再把无关系的核心函数排列成“假链路”。</p></div>
      <button onClick={onSearch}><Search size={14} />精确搜索函数</button>
    </header>
    {confirmedCalls === 0 && <div className="kg-callflow-evidence-block">
      <AlertTriangle size={16} />
      <div><strong>当前仓库没有编译器确认的 CALLS</strong><span>原生分析尚未产出确定调用，因此不能生成可信执行链。{candidates > 0 ? `当前可用 ${candidates} 条词法候选关系，仅适合预览。` : "请先重新执行原生代码分析。"}</span></div>
      {!includeCandidates && candidates > 0 && <button onClick={onEnableCandidates}>预览候选关系</button>}
    </div>}
    <div className="kg-callflow-entry-title"><span>推荐入口函数</span><small>{entries.length ? `按入口特征和中心性排序，显示前 ${Math.min(entries.length, 12)} 个` : loading ? "正在读取…" : "暂无可选函数"}</small></div>
    <div className="kg-callflow-entry-grid">
      {entries.slice(0, 12).map((node) => <button key={node.id} onClick={() => onSelect(node)}>
        <Code2 size={15} />
        <span><strong title={node.display_name || node.name}>{middleEllipsis(node.display_name || node.name || node.id, 34)}</strong><small title={node.path || node.qualified_name}>{compactPath(node.path || node.qualified_name || "未定位源码")}</small></span>
        <em>{node.core_reason || "核心函数"}</em>
        <ChevronRight size={14} />
      </button>)}
    </div>
    {!entries.length && !loading && <div className="kg-callflow-no-entry"><Code2 size={22} /><span>未发现可作为入口的函数，请先构建代码图谱。</span></div>}
  </div>;
}

function callflowProjection(graph: any, anchorId: string) {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  if (!nodes.length || !anchorId) return graph;
  const incoming = new Map<string, number>();
  const outgoing = new Map<string, number>();
  const walk = (reverse: boolean, distances: Map<string, number>) => {
    let frontier = new Set([anchorId]);
    for (let hop = 1; hop <= 2; hop += 1) {
      const next = new Set<string>();
      edges.forEach((edge: any) => {
        const from = reverse ? edge.target : edge.source;
        const to = reverse ? edge.source : edge.target;
        if (frontier.has(from) && !distances.has(to) && to !== anchorId) {
          distances.set(to, hop);
          next.add(to);
        }
      });
      frontier = next;
    }
  };
  walk(true, incoming);
  walk(false, outgoing);
  const callbackIds = new Set<string>();
  edges.forEach((edge: any) => {
    if (!["REGISTER_CALLBACK", "INVOKES_CALLBACK"].includes(edge.kind)) return;
    callbackIds.add(edge.source === anchorId ? edge.target : edge.source);
    callbackIds.add(edge.target === anchorId ? edge.source : edge.target);
  });
  const lane = (node: any) => {
    if (node.id === anchorId) return "anchor";
    if (callbackIds.has(node.id)) return "callback";
    const up = incoming.get(node.id);
    const down = outgoing.get(node.id);
    if (up != null && (down == null || up <= down)) return `up${up}`;
    if (down != null) return `down${down}`;
    return "related";
  };
  const quotas: Record<string, number> = { up2: 5, up1: 6, anchor: 1, down1: 6, down2: 5, callback: 5, related: 2 };
  const buckets = new Map<string, any[]>();
  nodes.forEach((node: any) => buckets.set(lane(node), [...(buckets.get(lane(node)) || []), node]));
  const rank = (node: any) => -Number(node.metrics?.degree || node.metrics?.core_score || 0);
  const selectedNodes: any[] = [];
  ["up2", "up1", "anchor", "down1", "down2", "callback", "related"].forEach((name) => {
    selectedNodes.push(...(buckets.get(name) || []).sort((a, b) => rank(a) - rank(b) || String(a.id).localeCompare(String(b.id))).slice(0, quotas[name]));
  });
  const ids = new Set(selectedNodes.map((node) => node.id));
  const selectedEdges = edges.filter((edge: any) => ids.has(edge.source) && ids.has(edge.target));
  return {
    ...graph,
    nodes: selectedNodes,
    edges: selectedEdges,
    displayed_nodes: selectedNodes.length,
    total_matching_nodes: graph.visible_nodes ?? nodes.length,
    displayed_edges: selectedEdges.length,
    total_matching_edges: graph.visible_edges ?? edges.length,
    truncated: Boolean(graph.truncated || selectedNodes.length < nodes.length || selectedEdges.length < edges.length),
  };
}

function middleEllipsis(value: unknown, limit = 30) {
  const text = String(value || "");
  if (text.length <= limit) return text;
  const left = Math.ceil((limit - 1) * 0.58);
  return `${text.slice(0, left)}…${text.slice(-(limit - 1 - left))}`;
}

function compactPath(value: unknown) {
  const pieces = String(value || "").split(/[\\/]/).filter(Boolean);
  return middleEllipsis(pieces.slice(-3).join("/"), 42);
}

function neighborUrl(
  values: Record<string, string | number | boolean | undefined | null>,
  kinds?: string[],
) {
  const params = new URLSearchParams(query(values));
  kinds?.forEach((kind) => params.append("kinds", kind));
  return `/api/graph/neighbors?${params.toString()}`;
}

function threeDPresetLabel(preset: ThreeDPreset) {
  return ({ universe: "知识宇宙", community: "社区星云", ego: "核心星图", impact: "影响宇宙", surprise: "惊喜链接" } as const)[preset];
}

function threeDPresetDescription(preset: ThreeDPreset) {
  return ({
    universe: "以社区为星系展示仓库全局结构、核心节点和跨社区桥梁。",
    community: "聚焦一个高耦合社区，观察内部核心函数及其边界关系。",
    ego: "以当前函数为中心，分离上游调用者和下游被调用函数。",
    impact: "以变更锚点为中心，按必须检查、可能修改和需要验证分层扩散。",
    surprise: "突出跨模块、低语义相似但具有确定源码证据的连接。",
  } as const)[preset];
}

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
