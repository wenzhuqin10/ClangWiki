from __future__ import annotations

import asyncio
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .database import Database, json_dumps, json_loads
from .errors import ClangWikiError
from .graph import GRAPH_KINDS, GraphService
from .indexing import EMBEDDING_PROFILES, IndexService
from .jobs import PersistentJobManager
from .platform import CollectionGenerationService, PlatformGenerationService
from .rag import RagService
from .registry import Registry
from .wiki import WikiService


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepositoryCreate(StrictModel):
    path: str
    name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class RepositoryUpdate(StrictModel):
    name: str | None = None
    config: dict[str, Any] | None = None


class CollectionCreate(StrictModel):
    name: str
    description: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    repository_ids: list[str] = Field(default_factory=list)


class CollectionUpdate(StrictModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None


class JobRequest(StrictModel):
    overrides: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(StrictModel):
    query: str
    scope_type: Literal["repository", "collection"]
    scope_id: str
    limit: int = 12
    kinds: list[str] | None = None
    module_id: str | None = None


class ManualPageCreate(StrictModel):
    title: str
    content: str
    repository_id: str | None = None
    collection_id: str | None = None
    module_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class ManualPageUpdate(StrictModel):
    title: str | None = None
    content: str
    tags: list[str] | None = None


class AnnotationCreate(StrictModel):
    content: str
    document_id: str | None = None
    node_id: str | None = None
    anchor: str | None = None


class ConversationCreate(StrictModel):
    scope_type: Literal["repository", "collection"]
    scope_id: str
    title: str = "新建知识问答"


class TurnCreate(StrictModel):
    question: str
    limit: int = 12


class SettingsUpdate(StrictModel):
    values: dict[str, Any]


@dataclass
class PlatformServices:
    database: Database
    registry: Registry
    graph: GraphService
    wiki: WikiService
    indexer: IndexService
    generation: PlatformGenerationService
    collection_generation: CollectionGenerationService
    rag: RagService
    jobs: PersistentJobManager


def build_services(data_root: Path) -> PlatformServices:
    database = Database(data_root)
    registry = Registry(database)
    graph = GraphService(database, registry)
    wiki = WikiService(database, registry)
    indexer = IndexService(database, registry)
    generation = PlatformGenerationService(database, registry, graph, wiki, indexer)
    collection_generation = CollectionGenerationService(database, registry, graph, wiki, indexer)
    rag = RagService(database, registry, indexer)
    jobs = PersistentJobManager(database)
    jobs.register("generate", lambda scope, payload, emit, cancel: generation.generate_repository(scope, payload.get("overrides", payload), emit, cancel))
    jobs.register("index", lambda scope, payload, emit, cancel: _index_job(indexer, scope, payload, emit, cancel))
    jobs.register("collection_generate", lambda scope, payload, emit, cancel: collection_generation.generate(scope, payload.get("overrides", payload), emit, cancel))
    return PlatformServices(database, registry, graph, wiki, indexer, generation, collection_generation, rag, jobs)


def create_app(data_root: Path, web_root: Path | None = None) -> FastAPI:
    services = build_services(data_root)
    app = FastAPI(
        title="ClangWiki Local Knowledge Platform",
        version=__version__,
        description="本机多仓 C/C++ 代码知识、Wiki、图谱与有引用 RAG 服务。",
    )
    app.state.services = services

    @app.exception_handler(KeyError)
    async def key_error_handler(_, exc: KeyError):
        return _json_error(404, str(exc).strip("'"))

    @app.exception_handler(ValueError)
    async def value_error_handler(_, exc: ValueError):
        return _json_error(400, str(exc))

    @app.exception_handler(ClangWikiError)
    async def clangwiki_error_handler(_, exc: ClangWikiError):
        return _json_error(400, str(exc))

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        repositories = services.registry.list_repositories()
        collections = services.registry.list_collections()
        active_jobs = [item for item in services.jobs.list() if item["status"] in {"queued", "running"}]
        default_model_row = services.database.one(
            "SELECT value_json FROM settings WHERE key = ?", ("default_model",)
        )
        default_model = json_loads(default_model_row["value_json"], "") if default_model_row else ""
        model_options = [default_model] if default_model else []
        model_options.extend(
            item.get("config", {}).get("model", "") for item in repositories
        )
        model_options.extend([
            "zai/glm-5.1",
            "deepseek/deepseek-v4-flash",
            "opencode/deepseek-v4-flash-free",
        ])
        return {
            "version": __version__, "data_root": str(services.database.data_root),
            "repositories": len(repositories), "collections": len(collections),
            "active_jobs": len(active_jobs), "opencode": shutil.which("opencode"),
            "vector_runtime": _vector_runtime_status(), "embedding_profiles": EMBEDDING_PROFILES,
            "default_model": default_model,
            "model_options": list(dict.fromkeys(item for item in model_options if item)),
        }

    @app.get("/api/repositories")
    def repositories() -> dict[str, Any]:
        return {"repositories": services.registry.list_repositories()}

    @app.post("/api/repositories", status_code=201)
    def add_repository(body: RepositoryCreate) -> dict[str, Any]:
        _reject_secrets(body.config)
        return services.registry.add_repository(Path(body.path), body.name, body.config)

    @app.get("/api/repositories/{repository_id}")
    def repository(repository_id: str) -> dict[str, Any]:
        value = services.registry.get_repository(repository_id)
        value["runs"] = services.generation.list_runs(repository_id)[:20]
        value["index"] = services.indexer.status("repository", repository_id)
        value["stats"] = _repository_stats(services, value)
        return value

    @app.patch("/api/repositories/{repository_id}")
    def update_repository(repository_id: str, body: RepositoryUpdate) -> dict[str, Any]:
        values = body.model_dump(exclude_none=True)
        _reject_secrets(values.get("config") or {})
        return services.registry.update_repository(repository_id, values)

    @app.delete("/api/repositories/{repository_id}", status_code=204)
    def remove_repository(repository_id: str, purge_artifacts: bool = False) -> None:
        services.registry.remove_repository(repository_id, purge_artifacts)

    @app.get("/api/repositories/{repository_id}/tree")
    def repository_tree(repository_id: str, kind: Literal["source", "module"] = "module") -> dict[str, Any]:
        repository = services.registry.get_repository(repository_id)
        if kind == "source":
            return {"tree": _source_tree(Path(repository["path"]))}
        run = repository.get("active_run")
        if not run:
            return {"tree": {"roots": [], "nodes": {}}, "modules": []}
        root = Path(run["artifact_path"]) / "knowledge"
        return {
            "tree": _read_json(root / "module_tree.json", {"roots": [], "nodes": {}}),
            "modules": _read_json(root / "modules.json", []),
        }

    @app.get("/api/repositories/{repository_id}/source")
    def source(
        repository_id: str, path: str = Query(...), line_start: int = 1, line_end: int = 200,
    ) -> dict[str, Any]:
        return services.wiki.source_snippet(repository_id, path, line_start, line_end)

    @app.post("/api/repositories/{repository_id}/generate", status_code=202)
    def generate_repository(repository_id: str, body: JobRequest) -> dict[str, Any]:
        _reject_secrets(body.overrides)
        services.registry.get_repository(repository_id)
        return services.jobs.start("generate", "repository", repository_id, {"overrides": body.overrides})

    @app.post("/api/repositories/{repository_id}/index", status_code=202)
    def index_repository(repository_id: str, body: JobRequest) -> dict[str, Any]:
        services.registry.get_repository(repository_id)
        return services.jobs.start("index", "repository", repository_id, body.overrides)

    @app.get("/api/repositories/{repository_id}/runs")
    def runs(repository_id: str) -> dict[str, Any]:
        return {"runs": services.generation.list_runs(repository_id)}

    @app.post("/api/repositories/{repository_id}/runs/{run_id}/activate")
    def activate_run(repository_id: str, run_id: str) -> dict[str, Any]:
        return services.generation.activate_run(repository_id, run_id)

    @app.get("/api/collections")
    def collections() -> dict[str, Any]:
        return {"collections": services.registry.list_collections()}

    @app.post("/api/collections", status_code=201)
    def add_collection(body: CollectionCreate) -> dict[str, Any]:
        _reject_secrets(body.config)
        collection = services.registry.create_collection(body.name, body.description, body.config)
        for repository_id in body.repository_ids:
            services.registry.add_collection_repository(collection["id"], repository_id)
        return services.registry.get_collection(collection["id"])

    @app.get("/api/collections/{collection_id}")
    def collection(collection_id: str) -> dict[str, Any]:
        value = services.registry.get_collection(collection_id)
        value["index"] = services.indexer.status("collection", collection_id)
        value["documents"] = services.wiki.list_documents("collection", collection_id)
        return value

    @app.patch("/api/collections/{collection_id}")
    def update_collection(collection_id: str, body: CollectionUpdate) -> dict[str, Any]:
        values = body.model_dump(exclude_none=True)
        _reject_secrets(values.get("config") or {})
        return services.registry.update_collection(collection_id, values)

    @app.delete("/api/collections/{collection_id}", status_code=204)
    def remove_collection(collection_id: str) -> None:
        services.registry.remove_collection(collection_id)

    @app.post("/api/collections/{collection_id}/repositories/{repository_id}")
    def add_collection_repository(collection_id: str, repository_id: str) -> dict[str, Any]:
        return services.registry.add_collection_repository(collection_id, repository_id)

    @app.delete("/api/collections/{collection_id}/repositories/{repository_id}")
    def remove_collection_repository(collection_id: str, repository_id: str) -> dict[str, Any]:
        return services.registry.remove_collection_repository(collection_id, repository_id)

    @app.post("/api/collections/{collection_id}/generate", status_code=202)
    def generate_collection(collection_id: str, body: JobRequest) -> dict[str, Any]:
        _reject_secrets(body.overrides)
        services.registry.get_collection(collection_id)
        return services.jobs.start("collection_generate", "collection", collection_id, {"overrides": body.overrides})

    @app.post("/api/collections/{collection_id}/relations/rebuild")
    def rebuild_collection_relations(collection_id: str) -> dict[str, int]:
        return services.graph.rebuild_collection(collection_id)

    @app.get("/api/graph")
    def graph(
        scope_type: Literal["repository", "collection"], scope_id: str,
        level: Literal["repository", "module", "file", "symbol"] = "module",
        kinds: list[str] | None = Query(default=None), certainty: str | None = None,
        limit: int = 2500,
    ) -> dict[str, Any]:
        return services.graph.graph(scope_type, scope_id, level, kinds, certainty, limit)

    @app.get("/api/graph/neighbors")
    def graph_neighbors(node_id: str, depth: int = 1, kinds: list[str] | None = Query(default=None)) -> dict[str, Any]:
        return services.graph.neighbors(node_id, depth, kinds)

    @app.get("/api/graph/path")
    def graph_path(source_id: str, target_id: str, max_depth: int = 8) -> dict[str, Any]:
        return services.graph.shortest_path(source_id, target_id, max_depth)

    @app.patch("/api/graph/edges/{edge_id}")
    def confirm_edge(edge_id: str, confirmed: bool) -> dict[str, Any]:
        return services.graph.set_edge_confirmation(edge_id, confirmed)

    @app.get("/api/wiki/documents")
    def documents(
        scope_type: Literal["repository", "collection"] | None = None,
        scope_id: str | None = None,
        include_history: bool = False,
    ) -> dict[str, Any]:
        return {"documents": services.wiki.list_documents(scope_type, scope_id, include_history)}

    @app.get("/api/wiki/documents/{document_id}")
    def document(document_id: str) -> dict[str, Any]:
        return services.wiki.get_document(document_id)

    @app.post("/api/wiki/pages", status_code=201)
    def create_manual_page(body: ManualPageCreate) -> dict[str, Any]:
        return services.wiki.create_manual_page(
            body.title, body.content, body.repository_id, body.collection_id, body.module_id, body.tags,
        )

    @app.patch("/api/wiki/pages/{document_id}")
    def update_manual_page(document_id: str, body: ManualPageUpdate) -> dict[str, Any]:
        return services.wiki.update_manual_page(document_id, body.content, body.title, body.tags)

    @app.get("/api/wiki/pages/{document_id}/revisions")
    def document_revisions(document_id: str) -> dict[str, Any]:
        return {"revisions": services.wiki.revisions(document_id)}

    @app.post("/api/wiki/pages/{document_id}/revisions/{revision}/restore")
    def restore_document_revision(document_id: str, revision: int) -> dict[str, Any]:
        return services.wiki.restore_revision(document_id, revision)

    @app.post("/api/wiki/annotations", status_code=201)
    def create_annotation(body: AnnotationCreate) -> dict[str, Any]:
        return services.wiki.add_annotation(body.content, body.document_id, body.node_id, body.anchor)

    @app.post("/api/search")
    def search(body: SearchRequest) -> dict[str, Any]:
        return services.indexer.search(body.query, body.scope_type, body.scope_id, body.limit, body.kinds, body.module_id)

    @app.get("/api/conversations")
    def conversations() -> dict[str, Any]:
        return {"conversations": services.rag.list_conversations()}

    @app.post("/api/conversations", status_code=201)
    def create_conversation(body: ConversationCreate) -> dict[str, Any]:
        return services.rag.create_conversation(body.scope_type, body.scope_id, body.title)

    @app.get("/api/conversations/{conversation_id}")
    def conversation(conversation_id: str) -> dict[str, Any]:
        return services.rag.get_conversation(conversation_id)

    @app.post("/api/conversations/{conversation_id}/turns")
    def ask(conversation_id: str, body: TurnCreate) -> dict[str, Any]:
        return services.rag.ask(conversation_id, body.question, body.limit)

    @app.get("/api/jobs")
    def jobs() -> dict[str, Any]:
        return {"jobs": services.jobs.list()}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        return services.jobs.get(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        return services.jobs.cancel(job_id)

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str) -> dict[str, Any]:
        return services.jobs.retry(job_id)

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, after: int = 0) -> StreamingResponse:
        services.jobs.get(job_id)

        async def stream():
            cursor = after
            while True:
                events = services.jobs.events(job_id, cursor)
                for event in events:
                    cursor = max(cursor, int(event.get("event_id") or 0))
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                current = services.jobs.get(job_id)
                if current["status"] not in {"queued", "running"}:
                    yield "data: " + json.dumps({"type": "complete", **current}, ensure_ascii=False) + "\n\n"
                    break
                await asyncio.sleep(0.75)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/settings")
    def settings() -> dict[str, Any]:
        return {row["key"]: json_loads(row["value_json"], None) for row in services.database.all("SELECT * FROM settings")}

    @app.patch("/api/settings")
    def update_settings(body: SettingsUpdate) -> dict[str, Any]:
        _reject_secrets(body.values)
        now = time.time()
        for key, value in body.values.items():
            services.database.execute(
                "INSERT INTO settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                (key, json_dumps(value), now),
            )
        return settings()

    static_root = (web_root or Path(__file__).resolve().parent / "web").resolve()
    if static_root.is_dir():
        app.mount("/", StaticFiles(directory=static_root, html=True), name="web")
    return app


def _index_job(indexer: IndexService, repository_id: str, payload: dict[str, Any], emit, cancel) -> dict[str, Any]:
    if cancel.is_set():
        return {"cancelled": True}
    emit({"stage": "chunk", "message": "正在切分文档、源码与图关系", "progress": 15})
    result = indexer.index_repository(repository_id, payload.get("embedding_profile"))
    emit({"stage": "index", "message": "知识索引构建完成", "progress": 100})
    return result


def _repository_stats(services: PlatformServices, repository: dict[str, Any]) -> dict[str, int]:
    repository_id = repository["id"]
    run_id = repository.get("active_run_id")
    node_rows = services.database.all(
        "SELECT kind,COUNT(*) AS value FROM knowledge_nodes WHERE repository_id=? AND run_id=? GROUP BY kind",
        (repository_id, run_id),
    ) if run_id else []
    edge_rows = services.database.one(
        "SELECT COUNT(*) AS value FROM knowledge_edges WHERE repository_id=? AND run_id=?", (repository_id, run_id)
    ) if run_id else None
    values = {row["kind"]: int(row["value"]) for row in node_rows}
    return {
        "modules": values.get("module", 0), "files": values.get("file", 0),
        "symbols": values.get("symbol", 0), "relations": int((edge_rows or {}).get("value") or 0),
    }


def _source_tree(root: Path, limit: int = 10000) -> list[dict[str, Any]]:
    excluded = {".git", "build", "dist", "node_modules", ".clangwiki"}
    result: list[dict[str, Any]] = []
    count = 0

    def visit(directory: Path) -> list[dict[str, Any]]:
        nonlocal count
        values: list[dict[str, Any]] = []
        try:
            children = sorted(directory.iterdir(), key=lambda path: (path.is_file(), path.name.casefold()))
        except OSError:
            return values
        for child in children:
            if count >= limit or child.name in excluded:
                continue
            relative = child.relative_to(root).as_posix()
            count += 1
            if child.is_dir():
                values.append({"name": child.name, "path": relative, "kind": "directory", "children": visit(child)})
            elif child.suffix.lower() in {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".cmake", ".txt", ".md"} or child.name == "CMakeLists.txt":
                values.append({"name": child.name, "path": relative, "kind": "file", "size": child.stat().st_size})
        return values

    result.extend(visit(root))
    return result


def _vector_runtime_status() -> dict[str, Any]:
    values = {}
    for package in ("onnxruntime", "FlagEmbedding", "fastembed", "usearch"):
        try:
            module = __import__(package)
            values[package] = {"available": True, "version": getattr(module, "__version__", "unknown")}
        except ImportError:
            values[package] = {"available": False}
    return values


def _reject_secrets(value: Any, path: str = "config") -> None:
    forbidden = ("api_key", "apikey", "token", "secret", "password", "credential")
    if isinstance(value, dict):
        for key, item in value.items():
            if any(word in str(key).casefold() for word in forbidden):
                raise ValueError(f"{path}.{key} 不允许保存凭据；模型认证必须由 OpenCode 管理。")
            _reject_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{path}[{index}]")


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _json_error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status_code, content={"detail": detail})
