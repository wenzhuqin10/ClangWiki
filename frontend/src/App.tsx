import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity, Archive, BookOpen, Boxes, Braces, CheckCircle2, ChevronDown, ChevronRight,
  CircleHelp, Clock3, Code2, Database, FileCode2, FileText, Folder, FolderGit2, GitBranch,
  GitCommitHorizontal, Home, Layers3, LoaderCircle, Network, PanelLeftClose, Play, Plus,
  RefreshCw, Search, Send, Settings, Sparkles, Tags, X, XCircle, Zap,
} from "lucide-react";
import { api, query } from "./api";
import GraphCanvas from "./GraphCanvas";

type View = "overview" | "repositories" | "collections" | "wiki" | "graph" | "search" | "ask" | "jobs" | "settings";
type Scope = { type: "repository" | "collection"; id: string; name: string } | null;

const NAV: Array<{ id: View; label: string; icon: typeof Home }> = [
  { id: "overview", label: "总览", icon: Home },
  { id: "repositories", label: "代码仓", icon: FolderGit2 },
  { id: "collections", label: "知识空间", icon: Boxes },
  { id: "wiki", label: "知识 Wiki", icon: BookOpen },
  { id: "graph", label: "代码关系图", icon: Network },
  { id: "search", label: "全局检索", icon: Search },
  { id: "ask", label: "知识问答", icon: Sparkles },
  { id: "jobs", label: "任务中心", icon: Activity },
  { id: "settings", label: "系统设置", icon: Settings },
];

const PAGE: Record<View, [string, string]> = {
  overview: ["本地知识工作台", "把编译器事实、Wiki 与工程知识组织在一起。"],
  repositories: ["代码仓管理", "每个仓库独立分析、生成、索引和版本管理。"],
  collections: ["逻辑知识空间", "跨仓组织知识，不复制或修改任何源码。"],
  wiki: ["知识 Wiki", "浏览生成快照、集合文档和可版本化的人工知识页。"],
  graph: ["代码关系图", "从仓库级逐步下钻到模块、文件和符号。"],
  search: ["混合知识检索", "融合符号、全文、向量和图关系召回。"],
  ask: ["有引用的知识问答", "通过 opencode run 调用已认证模型，ClangWiki 不接触 API Key。"],
  jobs: ["持久化任务中心", "集中查看分析、生成、索引和集合任务。"],
  settings: ["系统设置", "检查离线运行环境和本地数据位置。"],
};

function App() {
  const [view, setView] = useState<View>("overview");
  const [status, setStatus] = useState<any>(null);
  const [repositories, setRepositories] = useState<any[]>([]);
  const [collections, setCollections] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [scope, setScope] = useState<Scope>(null);
  const [moduleTree, setModuleTree] = useState<any>({ roots: [], nodes: {} });
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(null);
  const [modal, setModal] = useState<"repo" | "collection" | "manual" | null>(null);
  const [busy, setBusy] = useState(false);

  const notify = useCallback((text: string, error = false) => {
    setToast({ text, error });
    window.setTimeout(() => setToast(null), 3800);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [s, r, c, j] = await Promise.all([
        api.get<any>("/api/status"), api.get<any>("/api/repositories"),
        api.get<any>("/api/collections"), api.get<any>("/api/jobs"),
      ]);
      setStatus(s); setRepositories(r.repositories || []); setCollections(c.collections || []); setJobs(j.jobs || []);
      setScope((current) => current || (r.repositories?.[0] ? { type: "repository", id: r.repositories[0].id, name: r.repositories[0].name } : null));
    } catch (error) { notify(message(error), true); }
  }, [notify]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const timer = window.setInterval(async () => {
      try { const value = await api.get<any>("/api/jobs"); setJobs(value.jobs || []); } catch { /* server may be restarting */ }
    }, 2500);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (scope?.type !== "repository") { setModuleTree({ roots: [], nodes: {} }); return; }
    api.get<any>(`/api/repositories/${scope.id}/tree?kind=module`).then((value) => setModuleTree(value.tree || { roots: [], nodes: {} })).catch(() => setModuleTree({ roots: [], nodes: {} }));
  }, [scope]);

  const chooseRepository = (repo: any, next: View = "repositories") => { setScope({ type: "repository", id: repo.id, name: repo.name }); setView(next); };
  const chooseCollection = (collection: any, next: View = "collections") => { setScope({ type: "collection", id: collection.id, name: collection.name }); setView(next); };
  const runAction = async (kind: "generate" | "index") => {
    if (!scope) return notify("请先选择代码仓或知识空间。", true);
    if (kind === "index" && scope.type !== "repository") return notify("集合索引会在集合生成时自动更新。", true);
    setBusy(true);
    try {
      const path = scope.type === "repository"
        ? `/api/repositories/${scope.id}/${kind}`
        : `/api/collections/${scope.id}/generate`;
      await api.post(path, { overrides: {} });
      notify(kind === "generate" ? "任务已进入生成队列。" : "索引任务已进入队列。");
      setView("jobs"); await refresh();
    } catch (error) { notify(message(error), true); } finally { setBusy(false); }
  };

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Braces size={19} /></div><div><strong>ClangWiki</strong><small>CODE KNOWLEDGE OS</small></div><span className="version">v{status?.version || "…"}</span></div>
      <nav className="main-nav">{NAV.map(({ id, label, icon: Icon }) => <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}><Icon size={16} /><span>{label}</span>{id === "jobs" && activeJobCount(jobs) > 0 && <b>{activeJobCount(jobs)}</b>}</button>)}</nav>
      <section className="scope-section">
        <div className="sidebar-heading"><span>代码仓</span><button onClick={() => setModal("repo")} title="注册代码仓"><Plus size={14} /></button></div>
        <div className="scope-list">{repositories.map((repo) => <button key={repo.id} className={scope?.type === "repository" && scope.id === repo.id ? "selected" : ""} onClick={() => chooseRepository(repo)}><FolderGit2 size={14} /><span><strong>{repo.name}</strong><small>{repo.status === "ready" ? "已就绪" : statusLabel(repo.status)}</small></span><StatusDot status={repo.status} /></button>)}{!repositories.length && <div className="sidebar-empty">还没有注册代码仓</div>}</div>
        <div className="sidebar-heading spaces"><span>知识空间</span><button onClick={() => setModal("collection")} title="新建知识空间"><Plus size={14} /></button></div>
        <div className="scope-list">{collections.map((item) => <button key={item.id} className={scope?.type === "collection" && scope.id === item.id ? "selected" : ""} onClick={() => chooseCollection(item)}><Boxes size={14} /><span><strong>{item.name}</strong><small>{item.repositories?.length || 0} 个成员仓</small></span></button>)}</div>
      </section>
      {scope?.type === "repository" && <section className="module-section"><div className="sidebar-heading"><span>模块层级</span><em>{Object.keys(moduleTree.nodes || {}).length}</em></div><ModuleTree tree={moduleTree} /></section>}
      <footer><span className={`server-dot ${status ? "online" : ""}`} /><div><strong>{status ? "本地服务已连接" : "正在连接服务"}</strong><small>{scope?.name || "请选择工作范围"}</small></div></footer>
    </aside>

    <main className="workspace">
      <header className="topbar"><div><span className="eyebrow">{scope ? `${scope.type === "repository" ? "代码仓" : "知识空间"} / ${scope.name}` : "ClangWiki"}</span><h1>{PAGE[view][0]}</h1><p>{PAGE[view][1]}</p></div><div className="top-actions"><button className="button ghost" onClick={refresh}><RefreshCw size={15} />刷新</button>{scope && <button className="button primary" disabled={busy} onClick={() => runAction("generate")}>{busy ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />}生成 Wiki</button>}</div></header>
      <div className="view-container">
        {view === "overview" && <Overview status={status} repositories={repositories} collections={collections} jobs={jobs} onRepo={chooseRepository} onView={setView} />}
        {view === "repositories" && <Repositories repositories={repositories} scope={scope} moduleTree={moduleTree} select={chooseRepository} onAdd={() => setModal("repo")} onGenerate={() => runAction("generate")} onIndex={() => runAction("index")} onJobs={() => setView("jobs")} notify={notify} refresh={refresh} />}
        {view === "collections" && <Collections collections={collections} repositories={repositories} scope={scope} select={chooseCollection} onAdd={() => setModal("collection")} notify={notify} refresh={refresh} />}
        {view === "wiki" && <Wiki scope={scope} onManual={() => setModal("manual")} notify={notify} />}
        {view === "graph" && <Graph scope={scope} notify={notify} />}
        {view === "search" && <KnowledgeSearch scope={scope} notify={notify} />}
        {view === "ask" && <KnowledgeAsk scope={scope} notify={notify} />}
        {view === "jobs" && <Jobs jobs={jobs} notify={notify} refresh={refresh} />}
        {view === "settings" && <SystemSettings status={status} />}
      </div>
    </main>

    {modal === "repo" && <RepositoryModal modelOptions={status?.model_options || []} defaultModel={status?.default_model || ""} close={() => setModal(null)} done={async (repo: any) => { setModal(null); await refresh(); chooseRepository(repo); notify("代码仓已注册，源码未被复制或修改。"); }} />}
    {modal === "collection" && <CollectionModal repositories={repositories} close={() => setModal(null)} done={async (item: any) => { setModal(null); await refresh(); chooseCollection(item); notify("知识空间已创建。"); }} />}
    {modal === "manual" && <ManualModal scope={scope} close={() => setModal(null)} done={() => { setModal(null); notify("人工知识页已保存并纳入检索。"); }} />}
    {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.error ? <XCircle size={17} /> : <CheckCircle2 size={17} />}{toast.text}</div>}
  </div>;
}

function Overview({ status, repositories, collections, jobs, onRepo, onView }: any) {
  const ready = repositories.filter((item: any) => item.status === "ready").length;
  return <>
    <section className="hero"><div><span className="pill"><Zap size={13} />Compiler-grounded knowledge</span><h2>从信道子模块出发，逐层汇聚为可检索、可追溯的工程知识。</h2><p>ClangWiki 在本机组织多个 C/C++ 仓库，以 Clang 事实为基础，通过 <code>opencode run</code> 生成 Wiki 与有引用回答。</p><div className="hero-actions"><button className="button primary" onClick={() => onView("repositories")}><FolderGit2 size={16} />管理代码仓</button><button className="button subtle" onClick={() => onView("ask")}><Sparkles size={16} />开始知识问答</button></div></div><div className="architecture-mini"><div><Code2 /><span>Clang 事实</span></div><i>→</i><div><BookOpen /><span>知识 Wiki</span></div><i>→</i><div><Sparkles /><span>引用问答</span></div></div></section>
    <section className="metric-row"><Metric icon={<FolderGit2 />} label="已注册代码仓" value={repositories.length} detail={`${ready} 个已完成生成`} /><Metric icon={<Boxes />} label="逻辑知识空间" value={collections.length} detail="跨仓检索与汇总" /><Metric icon={<Activity />} label="进行中的任务" value={activeJobCount(jobs)} detail="生成与索引串行受控" /><Metric icon={<Database />} label="本地向量运行时" value={status?.vector_runtime?.fastembed?.available && status?.vector_runtime?.usearch?.available ? "可用" : "已降级"} detail="符号、全文和图谱始终可用" /></section>
    <div className="two-column"><section className="card"><CardTitle title="代码仓状态" eyebrow="REPOSITORIES" action={<button className="text-action" onClick={() => onView("repositories")}>查看全部</button>} /><div className="repository-table">{repositories.slice(0, 6).map((repo: any) => <button key={repo.id} onClick={() => onRepo(repo)}><span className="repo-avatar">{repo.name.slice(0, 2).toUpperCase()}</span><span><strong>{repo.name}</strong><small>{repo.path}</small></span><StatusBadge status={repo.status} /><span className="commit"><GitCommitHorizontal size={13} />{repo.git_commit?.slice(0, 8) || "未检测"}</span><ChevronRight size={15} /></button>)}{!repositories.length && <Empty icon={<FolderGit2 />} title="尚未注册代码仓" text="注册一个包含 CMakeLists.txt 的本地仓库开始分析。" />}</div></section><section className="card"><CardTitle title="最近任务" eyebrow="ACTIVITY" action={<button className="text-action" onClick={() => onView("jobs")}>任务中心</button>} /><div className="compact-jobs">{jobs.slice(0, 7).map((job: any) => <div key={job.id}><JobIcon status={job.status} /><span><strong>{jobTitle(job.kind)}</strong><small>{job.message || job.status}</small></span><em>{Math.round(job.progress || 0)}%</em></div>)}{!jobs.length && <Empty icon={<Clock3 />} title="暂无任务" text="生成或索引任务会在这里显示。" />}</div></section></div>
  </>;
}

const LEAF_DOCUMENT_CHAPTERS = [
  "子模块概述", "职责与边界", "领域定位与设计约束", "系统交互与接口关系", "核心任务流程",
  "状态、事件与时序", "核心实现", "配置、宏与运行变体", "调试与故障定位", "Agent 开发导航", "证据、限制与待确认项",
];
const SUMMARY_DOCUMENT_CHAPTERS = [
  "层级定位", "子模块组成", "聚合职责与边界", "跨子模块协作", "业务流程汇聚", "公共数据与接口",
  "状态、时序与资源约束", "开发影响导航", "子文档导航", "汇聚证据与限制",
];

function DocumentGenerationPanel({ repositoryId, moduleTree, notify, onJobs }: any) {
  const [mode, setMode] = useState<"module" | "leaf-module" | "module-summary" | "repository">("module");
  const [selectedModules, setSelectedModules] = useState<Set<string>>(new Set());
  const [documents, setDocuments] = useState<any[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const nodes = Object.entries(moduleTree?.nodes || {}).map(([module_id, node]) => ({ module_id, ...(node as any) }));
  const moduleMode = mode !== "repository";
  const chapters = mode === "leaf-module" ? LEAF_DOCUMENT_CHAPTERS : mode === "module-summary" ? SUMMARY_DOCUMENT_CHAPTERS : mode === "module" ? [...LEAF_DOCUMENT_CHAPTERS, ...SUMMARY_DOCUMENT_CHAPTERS] : [];
  const generatedCount = documents.filter((doc) => {
    const path = String(doc.relative_path || "");
    if (mode === "repository") return ["Architecture.md", "README.md"].includes(path);
    return path.startsWith("Modules/");
  }).length;

  useEffect(() => {
    api.get<any>(`/api/wiki/documents?${query({ scope_type: "repository", scope_id: repositoryId })}`)
      .then((value) => setDocuments(value.documents || []))
      .catch(() => setDocuments([]));
  }, [repositoryId]);

  const toggleModule = (id: string) => {
    const next = new Set(selectedModules);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelectedModules(next);
  };
  const submit = async () => {
    setSubmitting(true);
    try {
      const only = mode === "repository" ? ["architecture", "readme"] : [mode];
      const module_ids = moduleMode ? Array.from(selectedModules) : [];
      await api.post(`/api/repositories/${repositoryId}/generate`, { overrides: { only, module_ids } });
      notify("文档生成任务已进入队列，可在任务中心查看阶段和错误原因。");
      onJobs();
    } catch (error) { notify(message(error), true); }
    finally { setSubmitting(false); }
  };

  return <section className="card document-generation-card">
    <CardTitle title="分层文档生成" eyebrow="DOCUMENT WORKBENCH" action={<span className="doc-status">已有 {generatedCount} 篇快照</span>} />
    <p className="section-intro">以信道根的下一层功能子模块作为叶子单元，先生成最小文档，再按依赖顺序向上汇聚；机器快照保持不可变。</p>
    <div className="generation-mode-grid">
      {[
        ["module", "模块全量", "叶子文档 + 层级汇总"],
        ["leaf-module", "叶子模块", "仅生成最小单元文档"],
        ["module-summary", "层级汇总", "读取子文档向上总结"],
        ["repository", "仓库级", "架构文档 + README"],
      ].map(([value, title, detail]) => <button key={value} className={`generation-mode ${mode === value ? "active" : ""}`} onClick={() => { setMode(value as typeof mode); setSelectedModules(new Set()); }}><strong>{title}</strong><small>{detail}</small></button>)}
    </div>
    {moduleMode && <div className="generation-modules"><div className="generation-modules-head"><strong>模块范围</strong><span>{selectedModules.size ? `已选 ${selectedModules.size} 个；未选择则生成全部` : "未选择则生成全部模块"}</span></div><div className="generation-module-list">{nodes.sort((a, b) => Number(a.depth || 0) - Number(b.depth || 0)).map((node) => <label key={node.module_id} className="generation-module-row" style={{ paddingLeft: `${10 + Number(node.depth || 0) * 16}px` }}><input type="checkbox" checked={selectedModules.has(node.module_id)} onChange={() => toggleModule(node.module_id)} /><span><strong>{node.display_name || node.source_path || node.module_id}</strong><small>{node.source_path || "根模块"} · {node.is_leaf ? "叶子模块" : "层级汇总"}</small></span></label>)}{!nodes.length && <span className="generation-empty">完成一次代码分析后可选择模块。</span>}</div></div>}
    {chapters.length > 0 && <div className="chapter-contract"><div><strong>{mode === "leaf-module" ? "叶子模块章节契约" : mode === "module-summary" ? "层级汇总章节契约" : "叶子 + 层级章节契约"}</strong><span>每篇文档严格按以下章节输出，证据不足时保留章节并标记无法确定。</span></div><ol>{chapters.map((chapter) => <li key={chapter}>{chapter}</li>)}</ol></div>}
    {mode === "repository" && <div className="chapter-contract compact"><div><strong>仓库级章节</strong><span>读取模块树、模块快照和关系图，汇聚系统边界、依赖、数据流、调用流与证据限制。</span></div></div>}
    <div className="generation-actions"><span>当前选择：{mode === "module" ? "叶子 + 层级汇总" : mode === "leaf-module" ? "叶子模块" : mode === "module-summary" ? "层级汇总" : "仓库级"}</span><button className="button primary" disabled={submitting || (moduleMode && !nodes.length)} onClick={submit}>{submitting ? <LoaderCircle className="spin" size={15} /> : <Play size={15} />}开始生成</button></div>
  </section>;
}

function Repositories({ repositories, scope, moduleTree, select, onAdd, onGenerate, onIndex, onJobs, notify, refresh }: any) {
  const selected = repositories.find((item: any) => scope?.type === "repository" && item.id === scope.id);
  const [detail, setDetail] = useState<any>(null);
  const [tree, setTree] = useState<any[]>([]);
  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    Promise.all([api.get<any>(`/api/repositories/${selected.id}`), api.get<any>(`/api/repositories/${selected.id}/tree?kind=source`)]).then(([a, b]) => { setDetail(a); setTree(b.tree || []); }).catch((error) => notify(message(error), true));
  }, [selected?.id]);
  const remove = async () => { if (!selected || !confirm(`仅删除“${selected.name}”的注册信息和平台记录？不会删除源码。`)) return; try { await api.delete(`/api/repositories/${selected.id}`); await refresh(); notify("仓库注册记录已删除，源码未受影响。"); } catch (error) { notify(message(error), true); } };
  const updateConcurrency = async (value: string) => { if (!selected) return; try { const concurrency = Number(value); const updated = await api.patch<any>(`/api/repositories/${selected.id}`, { config: { module_generation_concurrency: concurrency } }); setDetail(updated); await refresh(); notify(`模块生成并发数已设为 ${concurrency}。下次生成生效。`); } catch (error) { notify(message(error), true); } };
  return <div className="repository-layout"><section className="card repo-list-panel"><CardTitle title="本地代码仓" eyebrow={`${repositories.length} REPOSITORIES`} action={<button className="icon-button" onClick={onAdd}><Plus size={16} /></button>} /><div className="repo-cards">{repositories.map((repo: any) => <button key={repo.id} className={selected?.id === repo.id ? "selected" : ""} onClick={() => select(repo)}><span className="repo-avatar">{repo.name.slice(0, 2).toUpperCase()}</span><span><strong>{repo.name}</strong><small>{repo.path}</small></span><StatusDot status={repo.status} /></button>)}</div></section><section className="detail-column">{selected && detail ? <>
    <section className="card repo-hero"><div className="repo-title"><span className="repo-avatar large">{selected.name.slice(0, 2).toUpperCase()}</span><div><span className="eyebrow">REGISTERED REPOSITORY</span><h2>{selected.name}</h2><p className="mono">{selected.path}</p></div><StatusBadge status={selected.status} /></div><div className="action-row"><button className="button primary" onClick={onGenerate}><Play size={15} />生成 Wiki</button><button className="button subtle" onClick={onIndex}><Database size={15} />重建索引</button><button className="button danger-text" onClick={remove}><Archive size={15} />移除注册</button></div></section>
    <section className="metric-row compact"><Metric icon={<Layers3 />} label="模块" value={detail.stats?.modules || 0} detail="层级模块节点" /><Metric icon={<FileCode2 />} label="源码文件" value={detail.stats?.files || 0} detail="编译数据库覆盖范围" /><Metric icon={<Braces />} label="符号" value={detail.stats?.symbols || 0} detail="函数、类型与宏" /><Metric icon={<Network />} label="关系" value={detail.stats?.relations || 0} detail="调用、包含与引用" /></section>
    <DocumentGenerationPanel repositoryId={selected.id} moduleTree={moduleTree} notify={notify} onJobs={onJobs} />
    <div className="two-column repo-details"><section className="card"><CardTitle title="源码目录" eyebrow="READ-ONLY SOURCE TREE" /><FileTree nodes={tree} /></section><section className="card"><CardTitle title="生成与环境" eyebrow="CURRENT SNAPSHOT" /><DescriptionList rows={[["Git 分支", detail.git_branch || "未检测"], ["Git 提交", detail.git_commit || "未检测"], ["当前运行", detail.active_run_id || "尚未生成"], ["模型", detail.config?.model || "尚未配置"], ["叶子边界", (detail.config?.channel_module_paths || []).join(", ") || "自动识别"], ["索引状态", detail.index?.chunks ? `${detail.index.chunks} 个知识块` : "尚未索引"]]} /><label className="inline-setting"><span>模块生成并发</span><select value={String(detail.config?.module_generation_concurrency || 2)} onChange={(event) => updateConcurrency(event.target.value)}>{[1, 2, 3, 4].map((value) => <option key={value} value={value}>{value} 个叶子任务</option>)}</select><small>仅并发独立叶子模块；父级汇总和仓库级文档按依赖顺序执行。</small></label></section></div>
  </> : <Empty icon={<FolderGit2 />} title="请选择代码仓" text="从左侧列表选择一个代码仓查看详情。" />}</section></div>;
}

function Collections({ collections, repositories, scope, select, onAdd, notify, refresh }: any) {
  const selected = collections.find((item: any) => scope?.type === "collection" && item.id === scope.id);
  const [detail, setDetail] = useState<any>(null);
  useEffect(() => { if (selected) api.get<any>(`/api/collections/${selected.id}`).then(setDetail).catch((e) => notify(message(e), true)); }, [selected?.id]);
  const toggle = async (repo: any, included: boolean) => { try { if (included) await api.delete(`/api/collections/${selected.id}/repositories/${repo.id}`); else await api.post(`/api/collections/${selected.id}/repositories/${repo.id}`); await refresh(); setDetail(await api.get(`/api/collections/${selected.id}`)); } catch (e) { notify(message(e), true); } };
  const rebuild = async () => { try { const result = await api.post<any>(`/api/collections/${selected.id}/relations/rebuild`); notify(`跨仓关系已更新：${result.edges} 条确定/候选边。`); } catch (e) { notify(message(e), true); } };
  return <div className="collection-grid"><section className="card"><CardTitle title="知识空间" eyebrow="LOGICAL COLLECTIONS" action={<button className="button subtle small" onClick={onAdd}><Plus size={14} />新建</button>} /><div className="space-cards">{collections.map((item: any) => <button className={selected?.id === item.id ? "selected" : ""} key={item.id} onClick={() => select(item)}><span className="space-icon"><Boxes /></span><span><strong>{item.name}</strong><small>{item.description || "跨仓知识空间"}</small></span><em>{item.repositories?.length || 0} 仓</em></button>)}{!collections.length && <Empty icon={<Boxes />} title="还没有知识空间" text="将多个相关仓库组成逻辑集合，用于跨仓搜索和问答。" />}</div></section>{selected && detail && <section className="card"><CardTitle title={selected.name} eyebrow="MEMBER REPOSITORIES" action={<button className="button subtle small" onClick={rebuild}><RefreshCw size={14} />重建跨仓关系</button>} /><p className="section-intro">成员仓仍保持独立，不复制源码。集合只保存关系、集合 Wiki 与检索配置。</p><div className="member-list">{repositories.map((repo: any) => { const included = detail.repositories?.some((item: any) => item.id === repo.id); return <div key={repo.id}><span className="repo-avatar tiny">{repo.name.slice(0, 2)}</span><span><strong>{repo.name}</strong><small>{repo.path}</small></span><button className={`toggle ${included ? "on" : ""}`} onClick={() => toggle(repo, included)}><i /></button></div>; })}</div></section>}</div>;
}

function Wiki({ scope, onManual, notify }: { scope: Scope; onManual: () => void; notify: Function }) {
  const [docs, setDocs] = useState<any[]>([]); const [selected, setSelected] = useState<any>(null); const [filter, setFilter] = useState("");
  useEffect(() => { setSelected(null); if (!scope) return; api.get<any>(`/api/wiki/documents?${query({ scope_type: scope.type, scope_id: scope.id })}`).then((value) => { setDocs(value.documents || []); if (value.documents?.[0]) load(value.documents[0].id); }).catch((e) => notify(message(e), true)); }, [scope?.type, scope?.id]);
  const load = (id: string) => api.get<any>(`/api/wiki/documents/${id}`).then(setSelected).catch((e) => notify(message(e), true));
  const shown = docs.filter((doc) => `${doc.title} ${doc.relative_path}`.toLowerCase().includes(filter.toLowerCase()));
  if (!scope) return <ScopeEmpty />;
  return <div className="wiki-layout"><aside className="document-sidebar"><div className="document-tools"><div className="input-with-icon"><Search size={15} /><input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="筛选 Wiki 页面" /></div><button className="icon-button" onClick={onManual} title="新建人工知识页"><Plus size={16} /></button></div><div className="document-list">{shown.map((doc) => <button key={doc.id} className={selected?.id === doc.id ? "selected" : ""} onClick={() => load(doc.id)}><FileText size={15} /><span><strong>{doc.title}</strong><small>{doc.kind === "manual" ? "人工知识" : doc.relative_path}</small></span>{doc.kind === "manual" && <Tags size={13} />}</button>)}{!shown.length && <Empty icon={<BookOpen />} title="还没有 Wiki" text="生成仓库或集合 Wiki 后将在这里显示。" />}</div></aside><article className="markdown-panel">{selected ? <><div className="document-meta"><div><span className="eyebrow">{selected.kind === "manual" ? "MANUAL KNOWLEDGE" : "GENERATED SNAPSHOT"}</span><h2>{selected.title}</h2></div><div><span className="evidence-badge"><CheckCircle2 size={13} />{selected.kind === "manual" ? "工程师知识" : "编译器证据"}</span></div></div><div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{selected.content || ""}</ReactMarkdown></div></> : <Empty icon={<BookOpen />} title="选择一篇文档" text="文档内容、源码证据与版本信息会显示在这里。" />}</article></div>;
}

function Graph({ scope, notify }: { scope: Scope; notify: Function }) {
  const [level, setLevel] = useState<"repository" | "module" | "file" | "symbol">("module");
  const [certainty, setCertainty] = useState("");
  const [graph, setGraph] = useState<any>({ nodes: [], edges: [] });
  const [selected, setSelected] = useState<any>(null);
  const [selectedEdge, setSelectedEdge] = useState<any>(null);
  const [neighbors, setNeighbors] = useState<any>(null);
  const [neighborhoodMode, setNeighborhoodMode] = useState(false);
  const [neighborLoading, setNeighborLoading] = useState(false);
  const [showLabels, setShowLabels] = useState(true);
  const [showEdgeLabels, setShowEdgeLabels] = useState(true);
  const [showIsolated, setShowIsolated] = useState(false);
  const [compactLargeGraph, setCompactLargeGraph] = useState(true);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!scope) return;
    setLoading(true);
    setNeighborhoodMode(false);
    // File and symbol graphs can contain hundreds of nodes.  Keep the graph
    // readable on first load while leaving both label channels available from
    // the toolbar when a user needs exact names.
    setShowLabels(level === "repository" || level === "module");
    setShowEdgeLabels(level === "repository" || level === "module");
    try {
      setGraph(await api.get(`/api/graph?${query({ scope_type: scope.type, scope_id: scope.id, level, certainty, limit: level === "symbol" ? 650 : 1200 })}`));
      setSelected(null);
      setSelectedEdge(null);
      setNeighbors(null);
    } catch (e) { notify(message(e), true); } finally { setLoading(false); }
  }, [scope?.type, scope?.id, level, certainty]);

  useEffect(() => { load(); }, [load]);

  const loadNeighbors = useCallback(async (nodeId: string) => {
    setNeighborLoading(true);
    try {
      const value = await api.get<any>(`/api/graph/neighbors?${query({ node_id: nodeId, depth: 1, limit: 180, scope_type: scope?.type, scope_id: scope?.id, level })}`);
      setNeighbors(value);
      return value;
    } catch (e) { notify(message(e), true); return null; } finally { setNeighborLoading(false); }
  // The request must follow the active scope and graph level.  Keeping this
  // callback dependent on `notify` alone captured the initial null scope and
  // module level, so later clicks could query the wrong projection (or receive
  // a 404) after switching repositories, collections, files, or symbols.
  }, [notify, scope?.type, scope?.id, level]);

  const chooseNode = useCallback((node: any | null) => {
    setSelected(node);
    setSelectedEdge(null);
    if (node) void loadNeighbors(node.id);
    else setNeighbors(null);
  }, [loadNeighbors]);

  const expandNeighbors = async () => {
    if (!selected) return;
    const value = neighbors || await loadNeighbors(selected.id);
    if (!value) return;
    setGraph({ nodes: value.nodes || [], edges: value.edges || [], truncated: value.truncated, relation_counts: value.relation_counts });
    setNeighborhoodMode(true);
  };

  const graphNodes = useMemo(() => [...(graph.nodes || []), ...((neighbors?.nodes || []).filter((node: any) => !(graph.nodes || []).some((item: any) => item.id === node.id)))], [graph.nodes, neighbors?.nodes]);
  const nodeById = useMemo(() => new Map(graphNodes.map((node: any) => [node.id, node])), [graphNodes]);
  const relatedNodes = (neighbors?.nodes || []).filter((node: any) => node.id !== selected?.id);
  const relationLabel = (edge: any) => edge.relation_label || ({ CONTAINS: "包含", DEPENDS_ON: "依赖", INCLUDES: "包含头文件", CALLS: "调用", POSSIBLE_CALL: "可能调用", REFERENCES: "引用", DEFINES: "定义", DOCUMENTS: "文档对应", RELATED_TO: "相关" } as Record<string, string>)[edge.kind] || edge.kind || "关系";

  const visibleGraph = useMemo(() => {
    if ((level !== "file" && level !== "symbol") || neighborhoodMode) return graph;
    let edges = [...(graph.edges || [])];
    let visibleIds = new Set<string>();
    if (compactLargeGraph) {
      const edgeDegree = new Map<string, number>();
      const ranked = edges.sort((left: any, right: any) =>
        Number(right.count || right.confidence || 0) - Number(left.count || left.confidence || 0));
      const backbone: any[] = [];
      for (const edge of ranked) {
        const sourceDegree = edgeDegree.get(edge.source) || 0;
        const targetDegree = edgeDegree.get(edge.target) || 0;
        const adds = Number(!visibleIds.has(edge.source)) + Number(!visibleIds.has(edge.target));
        if (visibleIds.size + adds > 90) continue;
        if (sourceDegree >= 5 && targetDegree >= 5) continue;
        backbone.push(edge);
        visibleIds.add(edge.source); visibleIds.add(edge.target);
        edgeDegree.set(edge.source, sourceDegree + 1);
        edgeDegree.set(edge.target, targetDegree + 1);
        if (backbone.length >= 125) break;
      }
      edges = backbone;
    } else {
      for (const edge of edges) { visibleIds.add(edge.source); visibleIds.add(edge.target); }
    }
    if (showIsolated) for (const node of graph.nodes || []) visibleIds.add(node.id);
    const relationCounts: Record<string, number> = {};
    for (const edge of edges) relationCounts[edge.kind] = (relationCounts[edge.kind] || 0) + 1;
    return {
      ...graph,
      nodes: (graph.nodes || []).filter((node: any) => visibleIds.has(node.id)),
      edges,
      relation_counts: relationCounts,
    };
  }, [graph, level, showIsolated, compactLargeGraph, neighborhoodMode]);
  const hiddenIsolatedCount = Math.max(0, (graph.nodes?.length || 0) - (visibleGraph.nodes?.length || 0));

  if (!scope) return <ScopeEmpty />;
  const activeItem = selected || selectedEdge;
  return <section className="graph-layout">
    <div className="graph-card">
      <div className="graph-controls">
        <div className="segmented">{["repository", "module", "file", "symbol"].map((item) => <button className={level === item ? "active" : ""} key={item} onClick={() => { setLevel(item as any); setNeighborhoodMode(false); }}>{({ repository: "仓库", module: "模块", file: "文件", symbol: "符号" } as any)[item]}</button>)}</div>
        <select value={certainty} onChange={(e) => setCertainty(e.target.value)}><option value="">全部确定性</option><option value="compiler">编译器确认</option><option value="candidate">候选关系</option><option value="user-confirmed">人工确认</option></select>
        <button className="icon-button" title="刷新图谱" onClick={load}><RefreshCw className={loading ? "spin" : ""} size={16} /></button>
        <button className={`graph-toggle ${showLabels ? "active" : ""}`} onClick={() => setShowLabels((value) => !value)}>节点文字</button>
        <button className={`graph-toggle ${showEdgeLabels ? "active" : ""}`} onClick={() => setShowEdgeLabels((value) => !value)}>关系文字</button>
        {(level === "file" || level === "symbol") && <button className={`graph-toggle ${compactLargeGraph ? "active" : ""}`} onClick={() => setCompactLargeGraph((value) => !value)}>核心关系</button>}
        {(level === "file" || level === "symbol") && <button className={`graph-toggle ${showIsolated ? "active" : ""}`} onClick={() => setShowIsolated((value) => !value)}>孤立节点</button>}
        {neighborhoodMode && <button className="button subtle small" onClick={load}>返回全图</button>}
        <div className="graph-summary"><strong>{visibleGraph.nodes?.length || 0}</strong> 节点 · <strong>{visibleGraph.edges?.length || 0}</strong> 关系{hiddenIsolatedCount > 0 && <span> · 已精简 {hiddenIsolatedCount} 个节点</span>}</div>
      </div>
      <div className="graph-relation-legend">{Object.entries(visibleGraph.relation_counts || {}).map(([kind, count]) => <span key={kind}><i className={`relation-dot ${kind.toLowerCase()}`} />{relationLabel({ kind })} <em>{String(count)}</em></span>)}</div>
      <GraphCanvas graph={visibleGraph} level={level} selectedNodeId={selected?.id} selectedEdgeId={selectedEdge?.id} showLabels={showLabels} showEdgeLabels={showEdgeLabels} onSelect={chooseNode} onSelectEdge={setSelectedEdge} />
    </div>
    <aside className={`inspector ${activeItem ? "open" : ""}`}>
      {selected ? <>
        <div className="inspector-head"><span className={`kind-icon ${selected.kind}`}><Code2 /></span><button className="icon-button" onClick={() => { setSelected(null); setNeighbors(null); }}><X size={15} /></button></div>
        <span className="eyebrow">{selected.kind_label || selected.kind?.toUpperCase()}</span>
        <h3>{selected.display_name || selected.name || selected.label}</h3>
        <p className="mono break">{selected.qualified_name || selected.path || selected.id}</p>
        <DescriptionList rows={[["仓库", selected.repository_id || "—"], ["模块", selected.module_id || "—"], ["证据等级", selected.certainty || "compiler"], ["起始行", selected.line_start || "—"], ["节点 ID", selected.id]]} />
        <button className="button subtle full" onClick={expandNeighbors} disabled={neighborLoading}>{neighborLoading ? <LoaderCircle className="spin" size={15} /> : <Network size={15} />} {neighborhoodMode ? "已展开当前邻居" : "展开一跳邻居"}</button>
        <section className="inspector-relations"><div className="inspector-section-title"><span>关联节点</span><em>{relatedNodes.length}</em></div>{neighborLoading && <p className="inspector-muted">正在加载关系…</p>}{!neighborLoading && relatedNodes.slice(0, 80).map((node: any) => { const edges = (neighbors?.edges || []).filter((edge: any) => edge.source === selected.id && edge.target === node.id || edge.target === selected.id && edge.source === node.id); return <button className="related-node" key={node.id} onClick={() => chooseNode(node)}><span className={`related-kind ${node.kind}`} /><span><strong>{node.display_name || node.name}</strong><small>{edges.map(relationLabel).join("、") || node.kind_label || node.kind}</small></span><ChevronRight size={14} /></button>; })}{!neighborLoading && !relatedNodes.length && <p className="inspector-muted">当前节点没有可展示的一跳关系。</p>}</section>
      </> : selectedEdge ? <>
        <div className="inspector-head"><span className="kind-icon relation"><Network /></span><button className="icon-button" onClick={() => setSelectedEdge(null)}><X size={15} /></button></div>
        <span className="eyebrow">关系</span><h3>{relationLabel(selectedEdge)}</h3>
        <DescriptionList rows={[["起点", nodeById.get(selectedEdge.source)?.display_name || selectedEdge.source], ["终点", nodeById.get(selectedEdge.target)?.display_name || selectedEdge.target], ["确定性", selectedEdge.certainty || "—"], ["置信度", selectedEdge.confidence == null ? "—" : Number(selectedEdge.confidence).toFixed(2)], ["关系 ID", selectedEdge.id]]} />
        <p className="inspector-muted">点击起点或终点节点可查看其关联节点与源码定位。</p>
      </> : <Empty icon={<PanelLeftClose />} title="节点详情" text="点击节点查看关联节点；点击连接线查看关系类型、方向和确定性。" />}
    </aside>
  </section>;
}

function KnowledgeSearch({ scope, notify }: { scope: Scope; notify: Function }) {
  const [term, setTerm] = useState(""); const [result, setResult] = useState<any>(null); const [loading, setLoading] = useState(false);
  const submit = async (event: FormEvent) => { event.preventDefault(); if (!scope || !term.trim()) return; setLoading(true); try { setResult(await api.post("/api/search", { query: term, scope_type: scope.type, scope_id: scope.id, limit: 20 })); } catch (e) { notify(message(e), true); } finally { setLoading(false); } };
  if (!scope) return <ScopeEmpty />;
  return <><section className="search-hero"><span className="eyebrow">HYBRID RETRIEVAL</span><h2>从代码符号到工程知识，一次检索。</h2><form onSubmit={submit}><Search size={20} /><input autoFocus value={term} onChange={(e) => setTerm(e.target.value)} placeholder="例如：PDSCH 编码入口、HARQ 重传路径、dmrs_config…" /><button className="button primary" disabled={loading}>{loading ? <LoaderCircle className="spin" size={16} /> : "检索"}</button></form><div className="retrieval-channels"><span><Braces />符号</span><span><FileText />全文</span><span><Sparkles />向量</span><span><Network />图关系</span></div></section>{result && <section className="results"><div className="results-head"><strong>检索结果</strong><span>{result.results?.length || 0} 条 · {result.warnings?.length ? "向量通道已降级" : "四路融合"}</span></div>{result.warnings?.map((warning: string) => <div className="inline-warning" key={warning}><CircleHelp size={15} />{warning}；符号、全文与图谱检索仍正常工作。</div>)}{result.results?.map((item: any, index: number) => <article key={item.id}><span className="rank">{String(index + 1).padStart(2, "0")}</span><div><div className="result-meta"><span>{kindLabel(item.kind)}</span><code>{item.source_uri}</code></div><h3>{item.title}</h3><p>{excerpt(item.content, term)}</p><div className="channel-tags">{(item.channels || []).map((channel: string) => <span key={channel}>{channelLabel(channel)}</span>)}</div></div><em>{Number(item.score || 0).toFixed(3)}</em></article>)}</section>}</>;
}

function KnowledgeAsk({ scope, notify }: { scope: Scope; notify: Function }) {
  const [conversation, setConversation] = useState<any>(null); const [turns, setTurns] = useState<any[]>([]); const [question, setQuestion] = useState(""); const [loading, setLoading] = useState(false);
  useEffect(() => { setConversation(null); setTurns([]); }, [scope?.type, scope?.id]);
  const send = async (event: FormEvent) => { event.preventDefault(); if (!scope || !question.trim()) return; const text = question.trim(); setQuestion(""); setLoading(true); try { let current = conversation; if (!current) { current = await api.post("/api/conversations", { scope_type: scope.type, scope_id: scope.id, title: text.slice(0, 50) }); setConversation(current); } const turn = await api.post<any>(`/api/conversations/${current.id}/turns`, { question: text, limit: 12 }); setTurns((items) => [...items, turn]); } catch (error) { const detail = message(error); setTurns((items) => [...items, { id: `failed-${Date.now()}`, question: text, answer: "RAG 问答生成失败。", status: "failed", error: detail }]); notify(detail, true); setQuestion(text); } finally { setLoading(false); } };
  if (!scope) return <ScopeEmpty />;
  return <div className="chat-shell"><section className="chat-main"><div className="chat-history">{!turns.length && <div className="chat-welcome"><span><Sparkles /></span><h2>询问当前{scope.type === "repository" ? "代码仓" : "知识空间"}</h2><p>每一轮都会重新执行混合检索，并使用固定引用编号构造证据上下文。</p><div className="prompt-cards">{["从调度到信道编码的关键调用链是什么？", "哪些模块依赖公共接口，证据在哪里？", "如果修改 DMRS 配置，影响范围有哪些？"].map((value) => <button key={value} onClick={() => setQuestion(value)}>{value}<ChevronRight size={14} /></button>)}</div></div>}{turns.map((turn, index) => <div className="turn" key={turn.id || index}><div className="question"><span>你</span><p>{turn.question}</p></div><div className={`answer ${turn.status === "validation_failed" || turn.status === "citation_validation_failed" || turn.status === "failed" ? "failed" : ""}`}><span><Sparkles size={15} /></span><div><ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.answer || ""}</ReactMarkdown>{turn.error && <section className="rag-error"><strong><XCircle size={14} />生成失败原因</strong><pre>{turn.error}</pre><small>请检查 OpenCode CLI、模型标识、认证状态、工作目录和 stderr 日志路径。</small></section>}{turn.citations?.length > 0 && <div className="citations"><strong>本轮证据</strong>{turn.citations.map((citation: any) => <button key={citation.citation_key}><b>[{citation.citation_key}]</b><span>{citation.title}<small>{citation.source_uri}</small></span></button>)}</div>}</div></div></div>)}{loading && <div className="answer loading"><span><LoaderCircle className="spin" size={15} /></span><div><strong>正在检索证据并调用 OpenCode…</strong><p>回答返回后会校验全部引用。</p></div></div>}</div><form className="chat-input" onSubmit={send}><textarea value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="输入一个基于当前代码仓的问题…" rows={2} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} /><button disabled={loading || !question.trim()}><Send size={18} /></button><small>答案仅依据本轮检索证据 · 模型认证由 OpenCode 管理</small></form></section><aside className="evidence-guide"><span className="eyebrow">CITATION CONTRACT</span><h3>引用说明</h3>{[["W", "仓库或集合 Wiki"], ["C", "源码与行号"], ["G", "编译器关系图"], ["M", "人工知识页"]].map(([key, text]) => <div key={key}><b>{key}</b><span>{text}</span></div>)}<p>候选关系不会被描述为确定调用。无法从证据回答时，系统会明确提示。</p></aside></div>;
}

function Jobs({ jobs, notify, refresh }: any) {
  const [selected, setSelected] = useState<any>(null);
  const [timeline, setTimeline] = useState<any[]>([]);
  const loadDetail = async (job: any) => { try { const value = await api.get<any>(`/api/jobs/${job.id}/timeline`); setSelected(value.job); setTimeline(value.events || []); } catch (e) { notify(message(e), true); } };
  useEffect(() => { if (!selected) return; const current = jobs.find((item: any) => item.id === selected.id); if (!current) return; loadDetail(current); }, [jobs]);
  const act = async (job: any, action: "cancel" | "retry") => { try { await api.post(`/api/jobs/${job.id}/${action}`); await refresh(); notify(action === "cancel" ? "已请求取消任务。" : "任务已重新排队。"); } catch (e) { notify(message(e), true); } };
  return <div className="jobs-layout"><section className="card jobs-card"><CardTitle title="全部任务" eyebrow={`${jobs.length} JOBS`} /><div className="jobs-table"><div className="table-head"><span>任务</span><span>范围</span><span>状态</span><span>进度</span><span>操作</span></div>{jobs.map((job: any) => <div className={`job-line ${selected?.id === job.id ? "selected" : ""}`} key={job.id} onClick={() => loadDetail(job)}><span><JobIcon status={job.status} /><span><strong>{jobTitle(job.kind)}</strong><small>{job.message || job.id}</small></span></span><code>{job.scope_id || "系统"}</code><StatusBadge status={job.status} /><span><i className="progress"><b style={{ width: `${job.progress || 0}%` }} /></i><em>{Math.round(job.progress || 0)}%</em></span><span onClick={(event) => event.stopPropagation()}>{["queued", "running"].includes(job.status) ? <button className="mini-button" onClick={() => act(job, "cancel")}>取消</button> : job.status === "failed" ? <button className="mini-button" onClick={() => act(job, "retry")}>重试</button> : "—"}</span></div>)}{!jobs.length && <Empty icon={<Activity />} title="暂无任务记录" text="分析、生成和索引任务会持久化保存在这里。" />}</div></section>{selected && <aside className="card job-detail"><div className="job-detail-head"><div><span className="eyebrow">TASK DETAIL</span><h3>{jobTitle(selected.kind)}</h3><small>{selected.id}</small></div><button className="icon-button" onClick={() => { setSelected(null); setTimeline([]); }}><X size={16} /></button></div><div className="job-summary"><StatusBadge status={selected.status} /><span>{stageLabel(selected.stage)}</span><strong>{Math.round(selected.progress || 0)}%</strong></div><p className="job-message">{selected.message || "等待任务状态更新。"}</p>{selected.error && <section className="job-error"><strong><XCircle size={14} />失败原因</strong><pre>{selected.error}</pre></section>}<section className="job-timeline"><span className="eyebrow">EXECUTION TIMELINE</span>{timeline.filter((event: any) => event.type === "progress" || event.type === "status").map((event: any) => <div key={event.event_id}><i className={event.stage === "failed" ? "failed" : ""} /><span><strong>{stageLabel(event.stage)}</strong><small>{event.message}</small></span><em>{typeof event.progress === "number" ? `${event.progress}%` : ""}</em></div>)}{!timeline.length && <p>暂无阶段记录。</p>}</section></aside>}</div>;
}

function SystemSettings({ status }: any) {
  const profileTitle = (key: string) => key === "bge-m3" ? "BGE-M3（默认）" : key === "balanced" ? "平衡档" : "高质量档";
  return <div className="settings-grid"><section className="card"><CardTitle title="本地运行环境" eyebrow="RUNTIME" /><div className="health-list"><Health name="ClangWiki 服务" ok={Boolean(status)} detail={status ? `v${status.version}` : "未连接"} /><Health name="OpenCode CLI" ok={Boolean(status?.opencode)} detail={status?.opencode || "未在 PATH 中发现"} /><Health name="BGE-M3 / ONNX Runtime" ok={Boolean(status?.vector_runtime?.onnxruntime?.available)} detail={status?.vector_runtime?.onnxruntime?.available ? status.vector_runtime.onnxruntime.version : "BGE-M3 运行库未安装"} /><Health name="USearch" ok={Boolean(status?.vector_runtime?.usearch?.available)} detail={status?.vector_runtime?.usearch?.available ? status.vector_runtime.usearch.version : "可选组件，当前使用降级检索"} /></div></section><section className="card"><CardTitle title="数据与安全边界" eyebrow="LOCAL ONLY" /><DescriptionList rows={[["数据根目录", status?.data_root || "—"], ["监听范围", "127.0.0.1（仅本机）"], ["模型调用", "opencode run"], ["API Key", "不接收、不保存、不读取"], ["源码权限", "只读；删除注册不会删除源码"], ["前端资源", "随 Python 包离线分发"]]} /></section><section className="card full-span"><CardTitle title="离线 Embedding 配置" eyebrow="OPTIONAL VECTOR CHANNEL" /><div className="profile-grid">{Object.entries(status?.embedding_profiles || {}).map(([key, value]: [string, any]) => <div key={key}><span className="profile-icon"><Database /></span><div><strong>{profileTitle(key)}</strong><code>{value.model}</code><p>{value.dimension} 维 · {key === "bge-m3" ? "ONNX 本地 CPU 推理" : "CPU ONNX 本地推理"}</p></div>{key === "bge-m3" && <span className="recommended">默认</span>}</div>)}</div></section></div>;
}

function RepositoryModal({ close, done, modelOptions, defaultModel }: any) {
  const [form, setForm] = useState({ path: "", name: "", model: defaultModel || "", customModel: "", channels: "", concurrency: "2" }); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const useCustomModel = form.model === "__custom__";
  const resolvedModel = useCustomModel ? form.customModel.trim() : form.model;
  const submit = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(""); try { const concurrency = Number(form.concurrency); if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 4) throw new Error("模块生成并发数必须是 1 到 4 的整数。"); const config: any = { module_generation_concurrency: concurrency }; if (resolvedModel) config.model = resolvedModel; if (form.channels) config.channel_module_paths = form.channels.split(",").map((v) => v.trim()).filter(Boolean); done(await api.post("/api/repositories", { path: form.path, name: form.name || null, config })); } catch (e) { setError(message(e)); } finally { setBusy(false); } };
  return <Modal title="注册本地代码仓" subtitle="ClangWiki 只保存路径和分析产物，不复制或修改源码。" close={close}><form onSubmit={submit} className="form"><label><span>仓库绝对路径</span><input required autoFocus value={form.path} onChange={(e) => setForm({ ...form, path: e.target.value })} placeholder="D:\projects\pdsch-channel" /></label><label><span>显示名称（可选）</span><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="PDSCH 信道仓" /></label><label><span>OpenCode 模型标识</span><select value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })}><option value="">使用系统默认模型{defaultModel ? `（${defaultModel}）` : ""}</option>{modelOptions.map((model: string) => <option key={model} value={model}>{model}</option>)}<option value="__custom__">手动输入其他模型标识…</option></select><small>从下拉列表选择 OpenCode 模型；这里只保存模型 ID，不接受 API Key。</small></label>{useCustomModel && <label><span>自定义模型标识</span><input required value={form.customModel} onChange={(e) => setForm({ ...form, customModel: e.target.value })} placeholder="企业 OpenCode 中的 provider/glm-5.1" /></label>}<label><span>模块生成并发数</span><input type="number" min="1" max="4" step="1" value={form.concurrency} onChange={(e) => setForm({ ...form, concurrency: e.target.value })} /><small>默认 2。仅同层叶子模块并发调用 OpenCode；父级汇总、系统架构和首页仍按依赖顺序生成。</small></label><label><span>信道根（逗号分隔，可选）</span><input value={form.channels} onChange={(e) => setForm({ ...form, channels: e.target.value })} placeholder="src/phy/pdsch, src/phy/pusch" /><small>仓库顶层目录就是信道根时请留空；系统将把顶层下一层源码目录作为最小叶子文档单元。仅在大仓库中需限定某个信道时再填写。</small></label>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><button type="button" className="button ghost" onClick={close}>取消</button><button className="button primary" disabled={busy}>{busy && <LoaderCircle className="spin" size={15} />}注册仓库</button></div></form></Modal>;
}

function CollectionModal({ repositories, close, done }: any) {
  const [name, setName] = useState(""); const [description, setDescription] = useState(""); const [selected, setSelected] = useState<string[]>([]); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { done(await api.post("/api/collections", { name, description, repository_ids: selected, config: {} })); } catch (e) { setError(message(e)); } };
  return <Modal title="新建逻辑知识空间" subtitle="成员仓保持独立，知识空间负责跨仓检索、关系与 Wiki。" close={close}><form className="form" onSubmit={submit}><label><span>知识空间名称</span><input required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="基带知识空间" /></label><label><span>用途说明</span><textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} placeholder="包含 PHY、MAC、公共接口和驱动仓…" /></label><fieldset><legend>初始成员仓</legend>{repositories.map((repo: any) => <label className="check-row" key={repo.id}><input type="checkbox" checked={selected.includes(repo.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, repo.id] : selected.filter((id) => id !== repo.id))} /><span>{repo.name}<small>{repo.path}</small></span></label>)}</fieldset>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><button type="button" className="button ghost" onClick={close}>取消</button><button className="button primary">创建知识空间</button></div></form></Modal>;
}

function ManualModal({ scope, close, done }: any) {
  const [title, setTitle] = useState(""); const [content, setContent] = useState(""); const [tags, setTags] = useState(""); const [error, setError] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); if (!scope) return; try { await api.post("/api/wiki/pages", { title, content, repository_id: scope.type === "repository" ? scope.id : null, collection_id: scope.type === "collection" ? scope.id : null, tags: tags.split(",").map((v) => v.trim()).filter(Boolean) }); done(); } catch (e) { setError(message(e)); } };
  return <Modal title="新建人工知识页" subtitle="人工知识独立于机器生成快照，可修订、回滚并参与检索。" close={close} wide><form className="form" onSubmit={submit}><label><span>标题</span><input required autoFocus value={title} onChange={(e) => setTitle(e.target.value)} /></label><label><span>Markdown 内容</span><textarea required className="editor" value={content} onChange={(e) => setContent(e.target.value)} rows={14} placeholder="# 设计说明\n\n记录工程约束、Session 经验和故障定位方法…" /></label><label><span>标签（逗号分隔）</span><input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="PDSCH, HARQ, 调试" /></label>{error && <div className="form-error">{error}</div>}<div className="modal-actions"><button type="button" className="button ghost" onClick={close}>取消</button><button className="button primary">保存知识页</button></div></form></Modal>;
}

function Modal({ title, subtitle, close, children, wide = false }: { title: string; subtitle: string; close: () => void; children: ReactNode; wide?: boolean }) { return <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}><section className={`modal ${wide ? "wide" : ""}`}><header><div><h2>{title}</h2><p>{subtitle}</p></div><button className="icon-button" onClick={close}><X size={17} /></button></header>{children}</section></div>; }
function Metric({ icon, label, value, detail }: any) { return <div className="metric-card"><span className="metric-icon">{icon}</span><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>; }
function CardTitle({ title, eyebrow, action }: any) { return <div className="card-title"><div><span className="eyebrow">{eyebrow}</span><h3>{title}</h3></div>{action}</div>; }
function Empty({ icon, title, text }: any) { return <div className="empty"><span>{icon}</span><strong>{title}</strong><p>{text}</p></div>; }
function ScopeEmpty() { return <Empty icon={<Layers3 />} title="请先选择工作范围" text="从左侧选择一个代码仓或逻辑知识空间。" />; }
function StatusDot({ status }: { status: string }) { return <i className={`status-dot ${status}`} />; }
function StatusBadge({ status }: { status: string }) { return <span className={`status-badge ${status}`}>{statusLabel(status)}</span>; }
function JobIcon({ status }: { status: string }) { return <span className={`job-icon ${status}`}>{status === "completed" ? <CheckCircle2 /> : status === "failed" || status === "cancelled" ? <XCircle /> : status === "running" ? <LoaderCircle className="spin" /> : <Clock3 />}</span>; }
function Health({ name, ok, detail }: any) { return <div><span className={`health-icon ${ok ? "ok" : "warn"}`}>{ok ? <CheckCircle2 /> : <CircleHelp />}</span><span><strong>{name}</strong><small>{detail}</small></span><em>{ok ? "可用" : "可选/缺失"}</em></div>; }
function DescriptionList({ rows }: { rows: Array<[string, any]> }) { return <dl className="description-list">{rows.map(([key, value]) => <div key={key}><dt>{key}</dt><dd className={String(value).length > 28 ? "mono break" : ""}>{String(value)}</dd></div>)}</dl>; }

function ModuleTree({ tree }: any) { const [open, setOpen] = useState<Set<string>>(new Set(tree.roots || [])); useEffect(() => setOpen(new Set(tree.roots || [])), [tree]); const render = (id: string, depth = 0): ReactNode => { const node = tree.nodes?.[id]; if (!node) return null; const children = node.child_ids || []; const expanded = open.has(id); return <div key={id}><button className="module-row" style={{ paddingLeft: 8 + depth * 13 }} onClick={() => { const next = new Set(open); expanded ? next.delete(id) : next.add(id); setOpen(next); }}>{children.length ? expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} /> : <span className="leaf-dot" />}<span>{node.display_name || node.source_path || id}</span>{node.is_leaf && <em>叶</em>}</button>{expanded && children.map((child: string) => render(child, depth + 1))}</div>; }; return <div className="module-tree">{(tree.roots || []).map((id: string) => render(id))}{!tree.roots?.length && <div className="sidebar-empty">生成后显示模块树</div>}</div>; }
function FileTree({ nodes, depth = 0 }: { nodes: any[]; depth?: number }) { const [open, setOpen] = useState<Set<string>>(new Set()); return <div className="file-tree">{nodes.slice(0, 350).map((node) => <div key={node.path}><button style={{ paddingLeft: 4 + depth * 15 }} onClick={() => { if (node.kind !== "directory") return; const next = new Set(open); open.has(node.path) ? next.delete(node.path) : next.add(node.path); setOpen(next); }}>{node.kind === "directory" ? open.has(node.path) ? <ChevronDown /> : <ChevronRight /> : <span className="tree-indent" />}{node.kind === "directory" ? <Folder /> : <FileCode2 />}<span>{node.name}</span>{node.size != null && <em>{formatBytes(node.size)}</em>}</button>{node.kind === "directory" && open.has(node.path) && <FileTree nodes={node.children || []} depth={depth + 1} />}</div>)}</div>; }

function message(error: unknown) { return error instanceof Error ? error.message : String(error); }
function statusLabel(status: string) { return ({ registered: "待生成", generating: "生成中", ready: "已就绪", failed: "失败", queued: "排队中", running: "执行中", completed: "已完成", cancelled: "已取消", interrupted: "已中断" } as Record<string, string>)[status] || status || "未知"; }
function activeJobCount(jobs: any[]) { return jobs.filter((item) => ["queued", "running"].includes(item.status)).length; }
function jobTitle(kind: string) { return ({ generate: "仓库 Wiki 生成", index: "知识索引", collection_generate: "集合 Wiki 生成", analysis: "代码分析", ask: "知识问答" } as Record<string, string>)[kind] || kind; }
function stageLabel(stage: string) { return ({ queued: "排队等待", start: "启动任务", prepare: "校验配置", cmake: "CMake 编译数据库", "cmake-fallback": "CMake 后备模式（部分分析）", clang: "Clang 静态分析", modules: "模块层级构建", plan: "文档任务规划", parallel: "叶子模块并发生成", context: "整理文档上下文", opencode: "OpenCode 文档生成", validate: "Markdown 校验", document: "写入模块文档", documents: "模块文档完成", graph: "关系图入库", wiki: "Wiki 快照登记", index: "构建混合索引", completed: "任务完成", failed: "任务失败", cancelled: "已取消", interrupted: "服务中断" } as Record<string, string>)[stage] || stage || "处理中"; }
function kindLabel(kind: string) { return ({ document: "Wiki 文档", manual: "人工知识", symbol: "代码符号", code: "源码", relation: "图关系", annotation: "批注" } as Record<string, string>)[kind] || kind; }
function channelLabel(channel: string) { return ({ symbol: "符号命中", keyword: "全文召回", vector: "向量召回", graph: "图关系扩展" } as Record<string, string>)[channel] || channel; }
function excerpt(content: string, term: string) { const clean = (content || "").replace(/[#`*|>]/g, " ").replace(/\s+/g, " ").trim(); const index = clean.toLowerCase().indexOf(term.toLowerCase()); const start = Math.max(0, index > 0 ? index - 90 : 0); return `${start > 0 ? "…" : ""}${clean.slice(start, start + 290)}${clean.length > start + 290 ? "…" : ""}`; }
function formatBytes(size: number) { if (size < 1024) return `${size} B`; if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`; return `${(size / 1024 ** 2).toFixed(1)} MB`; }

export default App;
