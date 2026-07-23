from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from .analyzer import RepositoryAnalyzer
from .config import get_settings
from .database import Database
from .embedding import OllamaEmbedder
from .generator import OpenCodeServerGateway
from .models import (
    AnalysisSummary,
    AnalyzeRequest,
    HealthReport,
    SearchHit,
    SearchRequest,
    WikiPagePlan,
    WikiPlan,
    WikiPlanRequest,
)
from .retrieval import HybridRetriever
from .service import RepositoryService


@lru_cache(maxsize=1)
def get_service() -> RepositoryService:
    settings = get_settings()
    database = Database(settings.database_path)
    analyzer = RepositoryAnalyzer(settings.analyzer_path)
    embedder = OllamaEmbedder(
        settings.embed_url,
        settings.embed_model,
        settings.embed_num_gpu,
        settings.embed_batch_size,
        settings.request_timeout_seconds,
    )
    generator = OpenCodeServerGateway(
        settings.opencode_url,
        settings.opencode_provider,
        settings.opencode_model,
        settings.opencode_username,
        settings.opencode_password,
        settings.request_timeout_seconds,
    )
    return RepositoryService(
        database,
        analyzer,
        HybridRetriever(database, embedder),
        generator,
        settings.max_context_chars,
    )


app = FastAPI(
    title="C++ DeepWiki Service",
    version="0.1.0",
    description="Compiler-assisted RAG and OpenCode documentation backend",
)


@app.get("/")
async def root():
    return {"name": "cpp-deepwiki", "docs": "/docs", "health": "/health"}


@app.get("/health")
async def global_health():
    service = get_service()
    return {
        "database": {"healthy": service.database.path.exists()},
        "embedding": await service.retriever.embedder.health(),
        "generator": await service.generator.health(),
        "analyzer": {"configured_path": str(service.analyzer.analyzer_path)},
    }


@app.post("/repositories/analyze", response_model=AnalysisSummary)
async def analyze(request: AnalyzeRequest):
    try:
        return await get_service().analyze(request.path, request.compile_database)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/repositories/{repository_id}/analysis", response_model=AnalysisSummary)
async def analysis(repository_id: str):
    try:
        return get_service().summary(repository_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Repository not found") from exc


@app.post("/repositories/{repository_id}/search", response_model=list[SearchHit])
async def search(repository_id: str, request: SearchRequest):
    if not get_service().database.repository(repository_id):
        raise HTTPException(status_code=404, detail="Repository not found")
    return await get_service().retriever.search(
        repository_id, request.query, request.top_k, request.expand_graph
    )


@app.post("/repositories/{repository_id}/wiki/plan", response_model=WikiPlan)
async def wiki_plan(repository_id: str, request: WikiPlanRequest):
    try:
        return await get_service().plan_wiki(
            repository_id, request.language, request.page_count
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Repository not found") from exc


@app.websocket("/repositories/{repository_id}/wiki/pages/{page_id}")
async def wiki_page(websocket: WebSocket, repository_id: str, page_id: str):
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        page = WikiPagePlan(
            id=page_id,
            title=payload["title"],
            description=payload.get("description", ""),
            query=payload.get("query", payload["title"]),
        )
        text = await get_service().generate_page(
            repository_id, page, payload.get("language", "zh-CN")
        )
        await websocket.send_json({"type": "content", "content": text})
        await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "error": str(exc)})
    finally:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()


@app.get("/repositories/{repository_id}/health", response_model=HealthReport)
async def repository_health(repository_id: str):
    service = get_service()
    repository = service.database.repository(repository_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    return HealthReport(
        repository_id=repository_id,
        analyzer={
            "healthy": True,
            "mode": repository["mode"],
            "confidence": repository["confidence"],
            "configured_path": str(service.analyzer.analyzer_path),
        },
        embedding=await service.retriever.embedder.health(),
        generator=await service.generator.health(),
        database={"healthy": service.database.path.exists(), **service.database.counts(repository_id)},
    )
