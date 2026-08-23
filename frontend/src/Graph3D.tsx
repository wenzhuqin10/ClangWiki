import { Component, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import ForceGraph3D from "react-force-graph-3d";
import * as THREE from "three";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { Camera, Maximize2, Pause, Play, RotateCcw, ScanSearch } from "lucide-react";

export type Graph3DPreset = "universe" | "community" | "ego" | "impact" | "surprise";
export type Graph3DProps = {
  graph: { nodes?: any[]; edges?: any[]; impact_tiers?: Record<string, any[]>; [key: string]: any };
  preset?: Graph3DPreset;
  selectedNodeId?: string | null;
  anchorId?: string | null;
  reducedMotion?: boolean;
  onSelect: (node: any | null) => void;
  onNodeSelect?: (node: any | null) => void;
  onNodeDoubleClick?: (node: any) => void;
  onDoubleClick?: (node: any) => void;
  onWebGLError?: (error: Error) => void;
  onFallback?: (reason: string) => void;
};
type PreparedGraph = { nodes: RenderNode[]; links: RenderEdge[]; truncated: boolean };
type RenderNode = any & { id: string; label: string; community: string; color: string; impactTier?: ImpactTier; isCore: boolean; isBridge: boolean; isAnchor: boolean; isPath: boolean; isInnerCommunity: boolean; x: number; y: number; z: number };
type RenderEdge = any & { id: string; source: string; target: string; isCandidate: boolean; isSurprise: boolean };
type ImpactTier = "must_review" | "possible_change" | "verify" | "unknown";

const NODE_LIMIT = 1500;
const EDGE_LIMIT = 3500;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const IMPACT_COLORS: Record<ImpactTier, string> = { must_review: "#f0784f", possible_change: "#e3b24f", verify: "#4e9bdd", unknown: "#778398" };
const NODE_SPHERE = new THREE.SphereGeometry(1, 12, 8);

/** Advanced WebGL exploration view; Cytoscape remains the precise 2D source of truth. */
export default function Graph3D({ graph, preset = "universe", selectedNodeId = null, anchorId = null, reducedMotion, onSelect, onNodeSelect, onNodeDoubleClick, onDoubleClick, onWebGLError, onFallback }: Graph3DProps) {
  const graphRef = useRef<any>(null);
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const [webglError, setWebglError] = useState<Error | null>(null);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [paused, setPaused] = useState(Boolean(reducedMotion));
  const [userInteracted, setUserInteracted] = useState(false);
  const [systemReducedMotion, setSystemReducedMotion] = useState(false);
  const interactionLock = useRef(false);
  const sceneDecorated = useRef(false);
  const initialFitDone = useRef(false);
  const lastNodeClick = useRef<{ id: string; at: number } | null>(null);
  useEffect(() => {
    if (reducedMotion !== undefined) return;
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return;
    const update = () => setSystemReducedMotion(query.matches);
    update(); query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, [reducedMotion]);
  const motionReduced = reducedMotion ?? systemReducedMotion;
  useEffect(() => {
    const host = canvasHostRef.current;
    if (!host) return;
    const measure = () => setViewport({ width: Math.max(1, host.clientWidth), height: Math.max(1, host.clientHeight) });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (typeof document === "undefined") return;
    try {
      const canvas = document.createElement("canvas");
      if (!(canvas.getContext("webgl2") || canvas.getContext("webgl"))) throw new Error("WebGL is unavailable in this browser or has been disabled.");
    } catch (error) {
      const value = error instanceof Error ? error : new Error(String(error));
      setWebglError(value); onWebGLError?.(value); onFallback?.(value.message);
    }
  }, [onFallback, onWebGLError]);
  const prepared = useMemo(() => prepareGraph(graph, preset, selectedNodeId, anchorId), [graph, preset, selectedNodeId, anchorId]);
  useEffect(() => { initialFitDone.current = false; }, [preset, graph.nodes, graph.edges]);
  const activeNodeId = selectedNodeId || anchorId;
  const nodeById = useMemo(() => new Map(prepared.nodes.map((node) => [node.id, node])), [prepared.nodes]);
  const autoRotate = !motionReduced && !paused && !userInteracted;
  useEffect(() => {
    const controls = graphRef.current?.controls?.();
    if (controls) { controls.autoRotate = autoRotate; controls.autoRotateSpeed = 0.18; }
  }, [autoRotate]);
  useEffect(() => {
    if (!activeNodeId) return;
    const node = nodeById.get(activeNodeId);
    if (!node || !graphRef.current?.cameraPosition) return;
    interactionLock.current = true;
    graphRef.current.cameraPosition({ x: node.x + 90, y: node.y + 40, z: node.z + 90 }, { x: node.x, y: node.y, z: node.z }, 780);
    window.setTimeout(() => { interactionLock.current = false; }, 820);
  }, [activeNodeId, nodeById]);
  const notifyInteraction = useCallback(() => {
    if (interactionLock.current) return;
    setUserInteracted(true); setPaused(true);
  }, []);
  useEffect(() => {
    const controls = graphRef.current?.controls?.();
    if (!controls?.addEventListener) return;
    controls.addEventListener("start", notifyInteraction);
    return () => controls.removeEventListener?.("start", notifyInteraction);
  }, [notifyInteraction, viewport.width, viewport.height]);
  useEffect(() => {
    if (!viewport.width || !viewport.height || sceneDecorated.current) return;
    const scene = graphRef.current?.scene?.() as THREE.Scene | undefined;
    const composer = graphRef.current?.postProcessingComposer?.();
    if (!scene || !composer) return;
    sceneDecorated.current = true;
    scene.background = new THREE.Color("#060a12");
    graphRef.current?.renderer?.()?.setClearColor?.("#060a12", 1);
    const starCount = 3000;
    const positions = new Float32Array(starCount * 3);
    for (let index = 0; index < starCount; index += 1) {
      const seed = hashString(`clangwiki-star-${index}`);
      const radius = 170 + (seed % 86);
      const theta = index * GOLDEN_ANGLE;
      const vertical = 1 - (2 * (index + 0.5)) / starCount;
      const radial = Math.sqrt(Math.max(0, 1 - vertical * vertical));
      positions[index * 3] = Math.cos(theta) * radial * radius;
      positions[index * 3 + 1] = vertical * radius;
      positions[index * 3 + 2] = Math.sin(theta) * radial * radius;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const material = new THREE.PointsMaterial({ color: "#f2f6fc", size: 0.86, transparent: true, opacity: 0.58, depthWrite: false });
    const stars = new THREE.Points(geometry, material);
    stars.name = "clangwiki-starfield";
    scene.add(stars);
    scene.fog = new THREE.FogExp2("#0b1018", 0.00045);
    const bloom = new UnrealBloomPass(new THREE.Vector2(viewport.width, viewport.height), 0.28, 0.36, 0.24);
    composer.addPass(bloom);
    return () => {
      composer.removePass?.(bloom);
      bloom.dispose();
      scene.remove(stars);
      geometry.dispose(); material.dispose();
      if (scene.fog instanceof THREE.FogExp2) scene.fog = null;
      sceneDecorated.current = false;
    };
  }, [viewport.width > 0, viewport.height > 0]);
  const selectNode = useCallback((node: any | null) => { const value = node?.__source || node || null; onSelect(value); onNodeSelect?.(value); }, [onNodeSelect, onSelect]);
  const doubleClick = useCallback((node: any) => { const value = node?.__source || node; onNodeDoubleClick?.(value); onDoubleClick?.(value); }, [onDoubleClick, onNodeDoubleClick]);
  const handleNodeClick = useCallback((node: RenderNode) => {
    const now = Date.now();
    const last = lastNodeClick.current;
    if (last && last.id === node.id && now - last.at < 360) doubleClick(node);
    else selectNode(node);
    lastNodeClick.current = { id: node.id, at: now };
  }, [doubleClick, selectNode]);
  const fit = useCallback(() => {
    interactionLock.current = true;
    const padding = prepared.nodes.length < 30 ? 24 : prepared.nodes.length < 120 ? 38 : 60;
    graphRef.current?.zoomToFit?.(700, padding);
    window.setTimeout(() => { interactionLock.current = false; }, 740);
  }, [prepared.nodes.length]);
  useEffect(() => {
    if (!viewport.width || !viewport.height || !prepared.nodes.length) return;
    initialFitDone.current = false;
    const timer = window.setTimeout(() => {
      initialFitDone.current = true;
      fit();
    }, preset === "impact" || preset === "ego" ? 260 : 520);
    return () => window.clearTimeout(timer);
  }, [fit, preset, prepared.nodes.length, prepared.links.length, viewport.width, viewport.height]);
  const reset = useCallback(() => { setUserInteracted(false); setPaused(Boolean(motionReduced)); fit(); }, [fit, motionReduced]);
  const togglePause = useCallback(() => setPaused((value) => !value), []);
  const focusSelected = useCallback(() => { const node = activeNodeId ? nodeById.get(activeNodeId) : null; if (!node || !graphRef.current?.cameraPosition) return fit(); interactionLock.current = true; graphRef.current.cameraPosition({ x: node.x + 90, y: node.y + 40, z: node.z + 90 }, { x: node.x, y: node.y, z: node.z }, 780); window.setTimeout(() => { interactionLock.current = false; }, 820); }, [activeNodeId, fit, nodeById]);
  const screenshot = useCallback(() => { const canvas = graphRef.current?.renderer?.()?.domElement as HTMLCanvasElement | undefined; if (!canvas) return; const link = document.createElement("a"); link.download = `clangwiki-${preset}-3d.png`; link.href = canvas.toDataURL("image/png"); link.click(); }, [preset]);
  if (webglError) return <Fallback error={webglError} />;
  return <div className="graph-3d-host graph-3d-root" role="application" aria-label="3D 知识图谱">
    <div ref={canvasHostRef} className="graph-3d-canvas"><Graph3DErrorBoundary onError={(error) => { setWebglError(error); onWebGLError?.(error); onFallback?.(error.message); }}>
      {viewport.width > 0 && viewport.height > 0 && <ForceGraph3D ref={graphRef} width={viewport.width} height={viewport.height} graphData={{ nodes: prepared.nodes, links: prepared.links }} backgroundColor="#060a12" showNavInfo={false} controlType="orbit" enableNodeDrag enableNavigationControls warmupTicks={preset === "ego" ? 0 : 40} cooldownTicks={motionReduced ? 0 : 80} d3AlphaDecay={0.04} d3VelocityDecay={0.45} rendererConfig={{ antialias: true, alpha: false, preserveDrawingBuffer: true }} nodeLabel={(node: RenderNode) => node.label} nodeColor={(node: RenderNode) => node.color} nodeVal={(node: RenderNode) => nodeRadius(node, activeNodeId)} nodeThreeObject={(node: RenderNode) => nodeObject(node, activeNodeId, preset)} nodeThreeObjectExtend={false} linkColor={(link: RenderEdge) => linkColor(link, activeNodeId)} linkOpacity={0.03} linkWidth={(link: RenderEdge) => link.isSurprise ? 1.1 : activeNodeId && isIncident(link, activeNodeId) ? 0.72 : 0.07} linkMaterial={(link: RenderEdge) => linkMaterial(link, activeNodeId)} linkDirectionalParticles={(link: RenderEdge) => particleCount(link, activeNodeId, motionReduced)} linkDirectionalParticleSpeed={0.004} linkDirectionalParticleWidth={(link: RenderEdge) => link.isSurprise ? 1.7 : 0.7} linkDirectionalArrowLength={(link: RenderEdge) => link.isCandidate ? 0 : 2.2} linkDirectionalArrowRelPos={0.9} onEngineStop={() => { if (!initialFitDone.current) { initialFitDone.current = true; fit(); } }} onNodeClick={(node: RenderNode) => { notifyInteraction(); handleNodeClick(node); }} onNodeRightClick={(node: RenderNode) => { notifyInteraction(); selectNode(node); }} onNodeDrag={() => notifyInteraction()} onBackgroundClick={notifyInteraction} />}
    </Graph3DErrorBoundary></div>
    <div className="graph-3d-toolbar" aria-label="3D 控制"><button type="button" title={paused ? "继续旋转" : "暂停旋转"} onClick={togglePause}>{paused ? <Play size={14} /> : <Pause size={14} />}</button><button type="button" title="适应画面" onClick={fit}><Maximize2 size={14} /></button><button type="button" title="聚焦选中节点" onClick={focusSelected} disabled={!activeNodeId}><ScanSearch size={14} /></button><button type="button" title="复位镜头和旋转" onClick={reset}><RotateCcw size={14} /></button><button type="button" title="导出 PNG" onClick={screenshot}><Camera size={14} /></button></div>
    <div className="graph-3d-legend" aria-label="3D 图例"><span><i className="graph-3d-legend-dot community" />社区</span>{preset === "impact" && <><span><i className="graph-3d-legend-dot must" />必须检查</span><span><i className="graph-3d-legend-dot verify" />需要验证</span></>}{preset === "surprise" && <span><i className="graph-3d-legend-dot surprise" />惊喜链接</span>}<span><i className="graph-3d-legend-dot candidate" />候选关系</span></div>
    {prepared.truncated && <span className="graph-3d-limit">3D 展示已限制为 {NODE_LIMIT} 个节点 / {EDGE_LIMIT} 条关系；聚焦或搜索可查看局部图。</span>}
  </div>;
}

function Fallback({ error }: { error: Error }) { return <div className="graph-3d-fallback graph-3d-error" role="status">当前浏览器无法初始化 WebGL，已保留 2D 图谱。{error.message}</div>; }
class Graph3DErrorBoundary extends Component<{ children: ReactNode; onError: (error: Error) => void }, { error: Error | null }> { state = { error: null as Error | null }; static getDerivedStateFromError(error: Error) { return { error }; } componentDidCatch(error: Error) { this.props.onError(error); } render() { return this.state.error ? <Fallback error={this.state.error} /> : this.props.children; } }

function prepareGraph(graph: Graph3DProps["graph"], preset: Graph3DPreset, selectedNodeId: string | null, anchorId: string | null): PreparedGraph {
  const rawNodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const rawEdges = Array.isArray(graph?.edges) ? graph.edges : [];
  const tiers = impactTierMap(graph?.impact_tiers);
  const keptNodes = rawNodes.slice(0, NODE_LIMIT);
  const keptIds = new Set(keptNodes.map((node: any) => String(node.id)));
  const edgePairs = rawEdges.filter((edge: any) => keptIds.has(String(edge.source)) && keptIds.has(String(edge.target)));
  const adjacency = new Map<string, string[]>();
  const anchor = anchorId || selectedNodeId;
  const egoSides = new Map<string, -1 | 1>();
  edgePairs.forEach((edge: any) => {
    const source = String(edge.source); const target = String(edge.target);
    adjacency.set(source, [...(adjacency.get(source) || []), target]);
    adjacency.set(target, [...(adjacency.get(target) || []), source]);
    if (anchor && source === anchor) egoSides.set(target, 1);
    if (anchor && target === anchor) egoSides.set(source, -1);
  });
  const distances = anchor ? bfsDistances(anchor, adjacency) : new Map<string, number>();
  const groupFor = (node: any) => String(node.community_id || node.module_id || node.repository_id || "default");
  const groupMembers = new Map<string, number>();
  keptNodes.forEach((node: any) => { const group = groupFor(node); const current = groupMembers.get(group) || 0; const declared = Number(node.member_count || node.metrics?.community_size || 0); groupMembers.set(group, Math.max(current + 1, declared)); });
  const groupIds = [...new Set(keptNodes.map(groupFor))].sort((left, right) => (groupMembers.get(right) || 0) - (groupMembers.get(left) || 0) || left.localeCompare(right));
  const topCommunities = new Set(groupIds.slice(0, 3));
  const groupCenters = communityCenters(groupIds, preset);
  const nodes = keptNodes.map((source: any, index: number) => {
    const id = String(source.id);
    const community = groupFor(source);
    const impactTier = tiers.get(id) || inferImpactTier(source);
    const isCore = Boolean(source.metrics?.is_hub || source.is_hub || source.core || Number(source.metrics?.god_score || 0) > 0.75);
    const isBridge = Boolean(source.metrics?.is_bridge || source.is_bridge);
    const isAnchor = id === anchor;
    const isPath = Boolean(anchor && distances.has(id) && distances.get(id)! <= 3);
    const position = initialPosition({
      id, index, preset, distance: distances.get(id), anchor: isAnchor, core: isCore,
      impactTier, egoSide: egoSides.get(id), groupCenter: groupCenters.get(community) || { x: 0, y: 0, z: 0 }, innerCommunity: topCommunities.has(community),
      communityNode: source.kind === "community",
    });
    return {
      ...source, __source: source, id,
      label: String(source.display_name || source.name || source.qualified_name || id).slice(0, 96),
      community, color: preset === "impact" && impactTier ? IMPACT_COLORS[impactTier] : topCommunities.has(community) ? ["#f2c86b", "#63c8bd", "#9b8bc4"][groupIds.indexOf(community)] : "#d3d9e3",
      impactTier, isCore, isBridge, isAnchor, isPath, isInnerCommunity: topCommunities.has(community), ...position,
      fx: position.x, fy: position.y, fz: position.z,
    };
  });
  const links = edgePairs.slice(0, EDGE_LIMIT).map((source: any, index: number) => {
    const id = String(source.id || `${source.source}->${source.target}:${index}`);
    const kind = String(source.kind || source.relation_label || "").toUpperCase();
    const isCandidate = source.status === "candidate" || source.certainty === "candidate" || source.origin === "rule";
    const isSurprise = kind === "SURPRISING_CONNECTION" || kind === "SURPRISE";
    return { ...source, id, source: String(source.source), target: String(source.target), isCandidate, isSurprise };
  });
  return { nodes, links, truncated: rawNodes.length > NODE_LIMIT || rawEdges.length > EDGE_LIMIT || edgePairs.length < rawEdges.length };
}
function communityCenters(groupIds: string[], preset: Graph3DPreset) {
  const centers = new Map<string, { x: number; y: number; z: number }>();
  groupIds.forEach((id, index) => {
    if (groupIds.length <= 1 || preset === "community" || preset === "ego" || preset === "impact") {
      centers.set(id, { x: 0, y: 0, z: 0 }); return;
    }
    if (preset === "surprise") {
      centers.set(id, { x: (index - (groupIds.length - 1) / 2) * 150, y: 0, z: index % 2 ? 22 : -22 }); return;
    }
    if (preset === "universe" && index < 3) {
      const inner = [{ x: -52, y: 18, z: 0 }, { x: 0, y: -10, z: 24 }, { x: 52, y: 16, z: -12 }][index];
      centers.set(id, inner); return;
    }
    if (preset === "universe") {
      const shellSeed = hashString(id);
      const shellIndex = index - 3;
      const shellCount = Math.max(1, groupIds.length - 3);
      const theta = shellIndex * GOLDEN_ANGLE;
      const vertical = 1 - (2 * (shellIndex + 0.5)) / shellCount;
      const radial = Math.sqrt(Math.max(0, 1 - vertical * vertical));
      const radius = 180 + (shellSeed % 51);
      centers.set(id, { x: Math.cos(theta) * radial * radius, y: vertical * radius, z: Math.sin(theta) * radial * radius }); return;
    }
    const y = 1 - (index / Math.max(1, groupIds.length - 1)) * 2;
    const radial = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = index * Math.PI * (3 - Math.sqrt(5));
    centers.set(id, { x: Math.cos(angle) * radial * 225, y: y * 225, z: Math.sin(angle) * radial * 225 });
  });
  return centers;
}
function initialPosition(options: { id: string; index: number; preset: Graph3DPreset; distance?: number; anchor: boolean; core: boolean; impactTier?: ImpactTier; egoSide?: -1 | 1; groupCenter: { x: number; y: number; z: number }; innerCommunity: boolean; communityNode: boolean }) {
  const { id, index, preset, distance, anchor, core, impactTier, egoSide, groupCenter, innerCommunity, communityNode } = options;
  if (anchor) return { x: 0, y: 0, z: 0 };
  if (communityNode) return groupCenter;
  const hash = hashString(id);
  const thetaSeed = hashString(`${id}:theta`);
  const verticalSeed = hashString(`${id}:vertical`);
  const angle = ((thetaSeed % 3600) / 3600) * Math.PI * 2 + index * 0.071;
  const vertical = ((verticalSeed % 1001) / 500) - 1;
  const planar = Math.sqrt(Math.max(0, 1 - vertical * vertical));
  if (preset === "ego") {
    const hop = Math.max(1, distance || 1); const side = egoSide || (hash % 2 ? 1 : -1);
    const radial = 22 + (hash % 38);
    return { x: side * (hop * 58 + 24), y: Math.sin(angle) * radial, z: Math.cos(angle) * radial };
  }
  if (preset === "impact") {
    const radius = impactTier === "must_review" ? 42 : impactTier === "possible_change" ? 82 : impactTier === "verify" ? 124 : 162;
    return { x: Math.cos(angle) * planar * radius, y: vertical * radius, z: Math.sin(angle) * planar * radius };
  }
  const localRadius = innerCommunity ? 25 + (hash % 21) : core ? 5 + (hash % 5) : 9 + (hash % 16);
  return {
    x: groupCenter.x + Math.cos(angle) * planar * localRadius,
    y: groupCenter.y + vertical * localRadius,
    z: groupCenter.z + Math.sin(angle) * planar * localRadius,
  };
}
function nodeObject(node: RenderNode, selectedNodeId: string | null, preset: Graph3DPreset) { const selected = node.id === selectedNodeId; const related = !selectedNodeId || node.isPath || selected; const radius = nodeRadius(node, selectedNodeId); const material = new THREE.MeshStandardMaterial({ color: node.color, emissive: node.color, emissiveIntensity: node.isAnchor || selected ? 1.35 : node.isCore ? 0.82 : node.isInnerCommunity ? 0.5 : 0.1, transparent: !related, opacity: related ? 1 : 0.14, roughness: 0.3, metalness: 0.08 }); const group = new THREE.Group(); const sphere = new THREE.Mesh(NODE_SPHERE, material); sphere.scale.setScalar(radius); group.add(sphere); const showLabel = node.isAnchor || selected || node.isCore || (preset === "surprise" && node.isBridge); if (showLabel) group.add(labelSprite(node.label, node.color)); return group; }
function labelSprite(label: string, color: string) { const canvas = document.createElement("canvas"); canvas.width = 640; canvas.height = 72; const context = canvas.getContext("2d")!; context.font = "600 25px Inter, Arial, sans-serif"; context.textAlign = "center"; context.strokeStyle = "rgba(4, 8, 14, .92)"; context.lineWidth = 7; context.strokeText(label.slice(0, 42), canvas.width / 2, 46); context.fillStyle = color; context.fillText(label.slice(0, 42), canvas.width / 2, 46); const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthWrite: false })); sprite.scale.set(38, 4.3, 1); sprite.position.set(0, 7, 0); return sprite; }
function nodeRadius(node: RenderNode, selectedNodeId: string | null) { const degree = Number(node.metrics?.degree || node.metrics?.in_degree || 0) + Number(node.metrics?.out_degree || 0); const ordinaryMin = node.isInnerCommunity ? 1.05 : 0.32; const ordinaryMax = node.isInnerCommunity ? 2.35 : 1.05; const base = node.kind === "community" ? Math.max(1.35, Math.min(2.2, 1.35 + Math.sqrt(Number(node.member_count || 1)) * 0.05)) : Math.max(ordinaryMin, Math.min(ordinaryMax, ordinaryMin + Math.sqrt(degree + 1) * 0.16)); if (node.id === selectedNodeId || node.isAnchor) return Math.max(2.2, Math.min(3.6, base * 1.8)); if (node.isCore) return Math.max(2, Math.min(3.4, base * 1.65)); return base; }
function endpointId(value: unknown) { return typeof value === "object" && value !== null ? String((value as any).id) : String(value); }
function isIncident(link: RenderEdge, nodeId: string) { return endpointId(link.source) === nodeId || endpointId(link.target) === nodeId; }
function particleCount(link: RenderEdge, selectedNodeId: string | null, motionReduced: boolean) { if (motionReduced || link.isCandidate) return 0; if (link.isSurprise) return 3; const kind = String(link.kind || "").toUpperCase(); return selectedNodeId && isIncident(link, selectedNodeId) && ["CALLS", "REGISTER_CALLBACK", "INVOKES_CALLBACK", "SENDS", "RECEIVES"].includes(kind) ? 2 : 0; }
function linkMaterial(link: RenderEdge, selectedNodeId: string | null) { const focused = Boolean(selectedNodeId && isIncident(link, selectedNodeId)); if (link.isCandidate) return new THREE.LineDashedMaterial({ color: "#8b704d", dashSize: 1.5, gapSize: 2.5, transparent: true, opacity: focused ? 0.42 : 0.08, depthWrite: false }); if (focused || link.isSurprise) return new THREE.MeshBasicMaterial({ color: linkColor(link, selectedNodeId), transparent: true, opacity: focused ? 0.72 : 0.36, depthWrite: false }); return null; }
function linkColor(link: RenderEdge, selectedNodeId: string | null) { if (link.isSurprise) return "#e8b24d"; if (link.isCandidate) return "#8b704d"; if (selectedNodeId && isIncident(link, selectedNodeId)) return "#d8e6ff"; return "#53647b"; }
function impactTierMap(tiers?: Record<string, any[]>) { const result = new Map<string, ImpactTier>(); (Object.entries(tiers || {}) as Array<[string, any[]]>).forEach(([tier, values]) => { const normalized: ImpactTier = tier === "must_review" || tier === "possible_change" || tier === "verify" ? tier : "unknown"; (values || []).forEach((value: any) => { const id = typeof value === "string" ? value : value?.id; if (id) result.set(String(id), normalized); }); }); return result; }
function inferImpactTier(node: any): ImpactTier | undefined { const value = String(node.impact_tier || "").toLowerCase(); if (value.includes("must") || value.includes("review")) return "must_review"; if (value.includes("possible") || value.includes("change")) return "possible_change"; if (value.includes("verify")) return "verify"; return undefined; }
function bfsDistances(anchor: string, adjacency: Map<string, string[]>) { const result = new Map<string, number>([[anchor, 0]]); const queue = [anchor]; while (queue.length) { const current = queue.shift()!; const nextDistance = result.get(current)! + 1; if (nextDistance > 3) continue; (adjacency.get(current) || []).forEach((next) => { if (!result.has(next)) { result.set(next, nextDistance); queue.push(next); } }); } return result; }
function hashString(value: string) { let hash = 2166136261; for (let index = 0; index < value.length; index += 1) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619); return hash >>> 0; }
