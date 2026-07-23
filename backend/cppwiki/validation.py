import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

from .analyzer import RepositoryAnalyzer
from .config import get_settings
from .database import Database
from .embedding import OllamaEmbedder
from .generator import OpenCodeServerGateway
from .retrieval import HybridRetriever
from .service import RepositoryService


QUERIES = [
    ("Processor::execute 的实现在哪里", "Processor::execute"),
    ("回调函数如何注册", "register_callback"),
    ("处理计数在哪里读取", "processed_count"),
]


async def validate(repo: Path, live: bool, generate: bool = False) -> int:
    settings = get_settings()
    database = Database(settings.database_path)
    embedder = OllamaEmbedder(
        settings.embed_url, settings.embed_model, settings.embed_num_gpu,
        settings.embed_batch_size, settings.request_timeout_seconds,
    )
    generator = OpenCodeServerGateway(
        settings.opencode_url, settings.opencode_provider, settings.opencode_model,
        settings.opencode_username, settings.opencode_password,
        settings.request_timeout_seconds,
    )
    service = RepositoryService(
        database, RepositoryAnalyzer(settings.analyzer_path),
        HybridRetriever(database, embedder), generator, settings.max_context_chars,
    )

    report = {
        "profile": settings.profile,
        "python": sys.version.split()[0],
        "clang": shutil.which("clang"),
        "analyzer": str(settings.analyzer_path),
    }
    if live:
        report["embedding_health"] = await embedder.health()
        report["generator_health"] = await generator.health()
        started = time.perf_counter()
        summary = await service.analyze(str(repo))
        report["analysis"] = summary.model_dump()
        report["analysis_seconds"] = round(time.perf_counter() - started, 3)
        successes = 0
        results = []
        for query, expected in QUERIES:
            started = time.perf_counter()
            hits = await service.retriever.search(summary.repository_id, query, 10, True)
            found = any(expected in (hit.get("symbol") or "") for hit in hits)
            successes += int(found)
            results.append({
                "query": query, "expected": expected, "found": found,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            })
        report["retrieval"] = results
        report["recall_at_10"] = successes / len(QUERIES)
        if generate:
            plan = await service.plan_wiki(summary.repository_id, "zh-CN", 2)
            page = await service.generate_page(summary.repository_id, plan.pages[0], "zh-CN")
            report["generation"] = {
                "plan_pages": len(plan.pages),
                "first_page_title": plan.pages[0].title,
                "first_page_chars": len(page),
                "passed": len(page.strip()) >= 100,
            }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    healthy = report.get("embedding_health", {}).get("healthy", True)
    healthy = healthy and report.get("generator_health", {}).get("healthy", True)
    healthy = healthy and report.get("recall_at_10", 1.0) >= 0.9
    healthy = healthy and report.get("generation", {}).get("passed", True)
    return 0 if healthy else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(validate(args.repo.resolve(), args.live, args.generate)))


if __name__ == "__main__":
    main()
