const state = {
  status: null,
  tree: null,
  relations: [],
  documents: [],
  jobs: [],
  selectedDocument: null,
  activeJob: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
}

function showToast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  window.setTimeout(() => node.classList.remove("show"), 3200);
}

function syncThemeToggle() {
  const button = $("#theme-toggle");
  if (!button) return;
  const isDark = document.body.classList.contains("dark");
  button.textContent = isDark ? "☀" : "☾";
  button.title = isDark ? "切换到浅色模式" : "切换到深色模式";
  button.setAttribute("aria-label", button.title);
}

function toggleTheme() {
  document.body.classList.toggle("dark");
  syncThemeToggle();
}

function setView(view) {
  $$(".view").forEach((node) => node.classList.toggle("active", node.id === `${view}-view`));
  $$(".nav-tab").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  const titles = {
    overview: "代码仓总览", documents: "生成的文档", relations: "代码关系图", jobs: "生成任务",
  };
  $("#page-title").textContent = titles[view] || titles.overview;
}

function prettyPath(path) {
  return path.split("/").filter(Boolean).join(" / ");
}

function refreshOverview() {
  const status = state.status || {};
  const repo = status.repo || "代码仓";
  $("#repo-name").textContent = repo.split(/[\\/]/).filter(Boolean).pop() || repo;
  $("#repo-path").textContent = repo;
  $("#repo-path").title = repo;
  $("#version").textContent = status.version ? `v${status.version}` : "";
  $("#analysis-mode").textContent = `分析模式：${status.analysis_mode || "尚未运行"}`;
  $("#model-name").textContent = `模型：${status.model || "—"}`;

  const modules = state.tree?.modules || [];
  $("#metric-modules").textContent = modules.length;
  $("#metric-leaves").textContent = modules.filter((item) => item.is_leaf).length;
  $("#metric-relations").textContent = state.relations.length;
  $("#metric-documents").textContent = state.documents.length;
  $("#tree-badge").textContent = `${modules.length} 个节点`;
  $("#status-dot").classList.add("ready");
  $("#server-status").textContent = "本地服务已连接";
  renderTree();
  renderPreview();
}

function moduleDocumentPath(node) {
  return node.source_path ? `Modules/${node.source_path}/index.md` : "";
}

function renderTree() {
  const nodes = state.tree?.tree?.nodes || {};
  const roots = state.tree?.tree?.roots || [];
  const modules = Object.fromEntries((state.tree?.modules || []).map((item) => [item.module_id, item]));
  if (!roots.length) {
    $("#module-tree").innerHTML = '<div class="empty">尚未发现分析产物。</div>';
    return;
  }
  const build = (id) => {
    const node = nodes[id] || modules[id] || {};
    const children = node.child_ids || [];
    const type = node.is_leaf ? "叶子" : node.is_channel_root ? "信道" : "汇总";
    return `<div class="tree-node"><div class="tree-row"><button class="tree-toggle">${children.length ? "▾" : "·"}</button><span class="tree-label" data-doc="${escapeHtml(moduleDocumentPath(node))}">${escapeHtml(node.display_name || id)}</span><span class="tree-type">${type}</span></div>${children.map(build).join("")}</div>`;
  };
  $("#module-tree").innerHTML = roots.map(build).join("");
  $$('[data-doc]').forEach((node) => node.addEventListener("click", () => openDocument(node.dataset.doc)));
}

function documentLink(document) {
  return `<div class="doc-link" data-document="${escapeHtml(document.path)}"><div><strong>${escapeHtml(document.title)}</strong><small>${escapeHtml(prettyPath(document.path))}</small></div><span class="muted">›</span></div>`;
}

function renderPreview() {
  const documents = state.documents.slice(0, 8);
  $("#document-preview").innerHTML = documents.length
    ? documents.map(documentLink).join("")
    : '<div class="empty">生成 Wiki 后，文档会显示在这里。</div>';
  $$('[data-document]').forEach((node) => node.addEventListener("click", () => openDocument(node.dataset.document)));
}

function renderDocuments() {
  const query = ($("#document-filter")?.value || "").toLowerCase();
  const documents = state.documents.filter((item) => `${item.title} ${item.path}`.toLowerCase().includes(query));
  $("#document-list").innerHTML = documents.length
    ? documents.map(documentLink).join("")
    : '<div class="empty">没有匹配的文档。</div>';
  $$('[data-document]').forEach((node) => node.addEventListener("click", () => openDocument(node.dataset.document)));
  if (state.selectedDocument) {
    $$('[data-document]').forEach((node) => node.classList.toggle("selected", node.dataset.document === state.selectedDocument));
  }
}

async function openDocument(path) {
  if (!path) return;
  try {
    const document = await api(`/api/document?path=${encodeURIComponent(path)}`);
    state.selectedDocument = document.path;
    $("#document-content").innerHTML = renderMarkdown(document.content);
    setView("documents");
    renderDocuments();
  } catch (error) {
    showToast(`读取文档失败：${error.message}`);
  }
}

function inlineMarkdown(value) {
  return value.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderMarkdown(source) {
  const lines = escapeHtml(source).split("\n");
  let html = "";
  let inCode = false;
  let code = [];
  for (const line of lines) {
    if (line.startsWith("```")) {
      if (inCode) {
        html += `<pre><code>${code.join("\n")}</code></pre>`;
        code = [];
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      code.push(line);
    } else if (line.startsWith("# ")) {
      html += `<h1>${inlineMarkdown(line.slice(2))}</h1>`;
    } else if (line.startsWith("## ")) {
      html += `<h2>${inlineMarkdown(line.slice(3))}</h2>`;
    } else if (line.startsWith("### ")) {
      html += `<h3>${inlineMarkdown(line.slice(4))}</h3>`;
    } else if (/^[-*] /.test(line)) {
      html += `<li>${inlineMarkdown(line.slice(2))}</li>`;
    } else if (line.startsWith("> ")) {
      html += `<blockquote>${inlineMarkdown(line.slice(2))}</blockquote>`;
    } else if (line.trim()) {
      html += `<p>${inlineMarkdown(line)}</p>`;
    }
  }
  if (inCode) html += `<pre><code>${code.join("\n")}</code></pre>`;
  return html || '<div class="empty">文档内容为空。</div>';
}

function renderGraph() {
  const svg = $("#relation-graph");
  const empty = $("#relation-empty");
  const edges = state.relations.filter((item) => item.source && item.target).slice(0, 80);
  if (!edges.length) {
    svg.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";
  const names = [...new Set(edges.flatMap((item) => [item.source, item.target]))].slice(0, 28);
  const points = names.map((name, index) => ({ name, x: 80 + (index % 4) * 225, y: 60 + Math.floor(index / 4) * 77 }));
  const byName = Object.fromEntries(points.map((point) => [point.name, point]));
  const defs = '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#59637a"/></marker></defs>';
  const lines = edges.filter((edge) => byName[edge.source] && byName[edge.target]).map((edge) => {
    const start = byName[edge.source];
    const end = byName[edge.target];
    const possible = edge.certainty === "lexical" || edge.kind === "POSSIBLE_CALL";
    return `<line class="graph-edge ${possible ? "possible" : ""}" x1="${start.x + 95}" y1="${start.y + 18}" x2="${end.x}" y2="${end.y + 18}" marker-end="url(#arrow)"/>`;
  }).join("");
  const nodes = points.map((point) => `<g class="graph-node"><rect x="${point.x}" y="${point.y}" width="190" height="38" rx="7"/><text x="${point.x + 10}" y="${point.y + 24}">${escapeHtml(point.name).slice(0, 25)}</text></g>`).join("");
  svg.innerHTML = defs + lines + nodes;
}

function renderJobs() {
  const jobs = state.jobs || [];
  $("#job-list").innerHTML = jobs.length
    ? jobs.slice().reverse().map((job) => `<div class="job-row"><div><div class="job-status ${escapeHtml(job.status)}">${escapeHtml(job.status)}</div><small class="muted mono">${escapeHtml(job.job_id)}</small></div><div><div class="job-progress"><i style="width:${job.progress || 0}%"></i></div><small class="muted">${escapeHtml(job.message || "—")}</small></div><div class="muted">${job.progress || 0}%</div></div>`).join("")
    : '<div class="empty">还没有生成任务。</div>';
}

function updateProgress(job) {
  if (!job) return;
  const progress = job.progress || 0;
  $("#progress-value").textContent = job.status === "completed" ? "✓" : `${progress}%`;
  $("#progress-message").textContent = job.message || job.status;
  $("#progress-ring").style.background = `conic-gradient(var(--accent) ${progress * 3.6}deg, var(--surface-3) 0deg)`;
  state.activeJob = job;
}

async function loadAll() {
  try {
    const [status, tree, relations, documents, jobs] = await Promise.all([
      api("/api/status"), api("/api/tree"), api("/api/relations"), api("/api/documents"), api("/api/jobs"),
    ]);
    state.status = status;
    state.tree = tree;
    state.relations = relations.relations || [];
    state.documents = documents.documents || [];
    state.jobs = jobs.jobs || [];
    refreshOverview();
    renderDocuments();
    renderGraph();
    renderJobs();
    const active = state.jobs.find((job) => job.status === "running" || job.status === "queued");
    if (active) subscribe(active.job_id);
    else if (state.jobs.length) updateProgress(state.jobs[state.jobs.length - 1]);
  } catch (error) {
    $("#server-status").textContent = "服务不可用";
    showToast(`无法连接本地服务：${error.message}`);
  }
}

function subscribe(jobId) {
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  source.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "complete") {
      source.close();
      state.jobs = state.jobs.filter((job) => job.job_id !== jobId).concat(data);
      updateProgress(data);
      loadAll();
    } else {
      updateProgress({ ...state.activeJob, ...data, status: "running" });
      renderJobs();
    }
  };
  source.onerror = () => source.close();
}

async function startGeneration() {
  try {
    const job = await api("/api/generate", { method: "POST", body: JSON.stringify({}) });
    state.jobs = (state.jobs || []).concat(job);
    updateProgress(job);
    setView("jobs");
    renderJobs();
    subscribe(job.job_id);
    showToast("生成任务已启动");
  } catch (error) {
    showToast(`启动失败：${error.message}`);
  }
}

$$('.nav-tab,[data-view]').forEach((node) => node.addEventListener("click", () => setView(node.dataset.view)));
$("#refresh-btn").addEventListener("click", loadAll);
$("#generate-btn").addEventListener("click", startGeneration);
$("#generate-btn-secondary").addEventListener("click", startGeneration);
$("#document-filter").addEventListener("input", renderDocuments);
$("#theme-toggle").addEventListener("click", toggleTheme);
syncThemeToggle();
loadAll();
