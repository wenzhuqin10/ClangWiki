from pathlib import Path

import pytest

from cppwiki.analyzer import RepositoryAnalyzer
from cppwiki.database import Database
from cppwiki.embedding import HashingEmbedder
from cppwiki.generator import FakeGeneratorGateway
from cppwiki.models import WikiPagePlan
from cppwiki.retrieval import HybridRetriever
from cppwiki.service import RepositoryService


FIXTURE = Path(__file__).parent / "fixtures" / "cpp-sample"


@pytest.fixture
def service(tmp_path):
    database = Database(tmp_path / "test.db")
    embedder = HashingEmbedder()
    return RepositoryService(
        database,
        RepositoryAnalyzer(tmp_path / "missing-analyzer"),
        HybridRetriever(database, embedder),
        FakeGeneratorGateway(),
    )


@pytest.mark.asyncio
async def test_analyze_search_plan_and_page(service):
    summary = await service.analyze(str(FIXTURE))
    assert summary.symbol_count >= 6
    assert summary.chunk_count >= 6

    hits = await service.retriever.search(
        summary.repository_id, "Processor execute callback", 10, True
    )
    assert hits
    assert any("Processor::execute" in (hit.get("symbol") or "") for hit in hits)

    plan = await service.plan_wiki(summary.repository_id, "zh-CN", 4)
    assert plan.pages

    page = await service.generate_page(
        summary.repository_id,
        WikiPagePlan(id="flow", title="执行流程", description="处理流程", query="execute transform"),
    )
    assert page.startswith("# 测试文档")


@pytest.mark.asyncio
async def test_reanalysis_does_not_duplicate_fts_rows(service):
    first = await service.analyze(str(FIXTURE))
    second = await service.analyze(str(FIXTURE))
    assert first.repository_id == second.repository_id
    hits = service.database.fts_search(first.repository_id, "Processor", 100)
    assert len(hits) == len(set(hits))

