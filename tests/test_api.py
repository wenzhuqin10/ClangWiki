from pathlib import Path

from fastapi.testclient import TestClient

import cppwiki.api as api_module
from cppwiki.analyzer import RepositoryAnalyzer
from cppwiki.database import Database
from cppwiki.embedding import HashingEmbedder
from cppwiki.generator import FakeGeneratorGateway
from cppwiki.retrieval import HybridRetriever
from cppwiki.service import RepositoryService


FIXTURE = Path(__file__).parent / "fixtures" / "cpp-sample"


def test_api_contract(monkeypatch, tmp_path):
    database = Database(tmp_path / "api.db")
    service = RepositoryService(
        database,
        RepositoryAnalyzer(tmp_path / "missing"),
        HybridRetriever(database, HashingEmbedder()),
        FakeGeneratorGateway(),
    )
    monkeypatch.setattr(api_module, "get_service", lambda: service)
    fixture = str((tmp_path.parent.parent / "missing").resolve())

    with TestClient(api_module.app) as client:
        assert client.get("/").status_code == 200
        invalid = client.post("/repositories/analyze", json={"path": fixture})
        assert invalid.status_code == 400
        assert client.get("/repositories/not-found/analysis").status_code == 404

        analyzed = client.post("/repositories/analyze", json={"path": str(FIXTURE)})
        assert analyzed.status_code == 200
        repository_id = analyzed.json()["repository_id"]
        searched = client.post(
            "/repositories/%s/search" % repository_id,
            json={"query": "Processor execute", "top_k": 10, "expand_graph": True},
        )
        assert searched.status_code == 200
        assert searched.json()
        planned = client.post(
            "/repositories/%s/wiki/plan" % repository_id,
            json={"language": "zh-CN", "page_count": 4},
        )
        assert planned.status_code == 200
        assert planned.json()["pages"]
        assert client.get("/repositories/%s/health" % repository_id).status_code == 200
