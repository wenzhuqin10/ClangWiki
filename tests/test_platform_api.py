from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clangwiki.api import create_app
from clangwiki.errors import ClangWikiError
from clangwiki.graph import GraphService
from clangwiki.platform import (
    DOCUMENT_SCHEMA_VERSION,
    PlatformGenerationService,
    _hash_json,
    _module_generation_concurrency,
    repository_file_hashes,
)


def _repository(path: Path, name: str = "demo") -> Path:
    root = path / name
    (root / "src").mkdir(parents=True)
    (root / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\nproject(demo C)\n", encoding="utf-8")
    (root / "src" / "demo.c").write_text("int pdsch_encode(void) { return 0; }\n", encoding="utf-8")
    return root


def test_local_platform_registers_repositories_without_secrets(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    repository_root = _repository(tmp_path)

    response = client.post("/api/repositories", json={"path": str(repository_root), "name": "PDSCH", "config": {"model": "corp/glm-5.1"}})
    assert response.status_code == 201
    repository = response.json()
    assert repository["name"] == "PDSCH"
    assert repository["path"] == str(repository_root.resolve())

    blocked = client.post("/api/repositories", json={"path": str(repository_root), "config": {"api_key": "must-not-store"}})
    assert blocked.status_code == 400
    assert "凭据" in blocked.json()["detail"]

    static = client.get("/")
    assert static.status_code == 200
    assert "root" in static.text


def test_manual_knowledge_is_searchable_before_first_generation(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    repository_root = _repository(tmp_path)
    repository = client.post("/api/repositories", json={"path": str(repository_root)}).json()

    page = client.post("/api/wiki/pages", json={
        "title": "PDSCH 调试笔记", "content": "# PDSCH 调试\n\n检查 `pdsch_encode` 与 HARQ 上下文。",
        "repository_id": repository["id"], "tags": ["PDSCH", "调试"],
    })
    assert page.status_code == 201
    services = app.state.services
    indexed = services.indexer.index_repository(repository["id"])
    assert indexed["chunks"] >= 1

    search = client.post("/api/search", json={
        "query": "pdsch_encode", "scope_type": "repository", "scope_id": repository["id"],
    })
    assert search.status_code == 200
    assert search.json()["results"]
    assert search.json()["results"][0]["kind"] == "manual"


def test_generated_documents_are_stored_in_module_knowledge_folders(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    repository_root = _repository(tmp_path)
    repository = client.post("/api/repositories", json={"path": str(repository_root)}).json()
    services = app.state.services
    run_id = "run-module-documents"
    run_root = services.registry.run_root(repository["id"], run_id)
    output = run_root / "output"
    module_output = output / "Modules" / "src" / "phy" / "pdsch" / "encoder"
    module_output.mkdir(parents=True)
    (module_output / "index.md").write_text(
        "# PDSCH Encoder\n\n## 模块概述\n这是一个用于测试的模块文档，包含源码职责、输入输出和可追溯证据。\n",
        encoding="utf-8",
    )
    channel_output = output / "Modules" / "src" / "phy" / "pdsch"
    channel_output.mkdir(parents=True, exist_ok=True)
    (channel_output / "index.md").write_text("# PDSCH\n\n信道任务导航。\n", encoding="utf-8")
    subsystem_output = output / "Modules" / "src" / "phy"
    (subsystem_output / "index.md").write_text("# PHY\n\n子系统导航。\n", encoding="utf-8")
    output.mkdir(exist_ok=True)
    (output / "Architecture.md").write_text("# 系统架构\n\n## 系统目标与边界\n仓库级文档。\n", encoding="utf-8")
    knowledge = run_root / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "modules.json").write_text(json.dumps([
        {
            "module_id": "src--phy",
            "display_name": "phy",
            "source_path": "src/phy",
            "child_ids": ["src--phy--pdsch"],
            "direct_files": [],
            "is_leaf": False,
            "is_channel_root": False,
        },
        {
            "module_id": "src--phy--pdsch",
            "display_name": "pdsch",
            "source_path": "src/phy/pdsch",
            "child_ids": ["src--phy--pdsch--encoder"],
            "direct_files": [],
            "is_leaf": False,
            "is_channel_root": True,
        },
        {
            "module_id": "src--phy--pdsch--encoder",
            "display_name": "encoder",
            "source_path": "src/phy/pdsch/encoder",
            "direct_files": ["src/phy/pdsch/encoder/encode.c"],
            "is_leaf": True,
        },
    ]), encoding="utf-8")
    services.database.execute(
        "INSERT INTO runs(id,repository_id,status,config_hash,schema_version,artifact_path,manifest_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (run_id, repository["id"], "completed", "test", "test", str(run_root), "{}", time.time()),
    )
    services.database.execute(
        "UPDATE repositories SET active_run_id=?,status='ready' WHERE id=?",
        (run_id, repository["id"]),
    )

    documents = services.wiki.ingest_generated(repository["id"], run_id, run_root)
    module_document = next(
        item
        for item in documents
        if item["module_id"] == "src--phy--pdsch--encoder"
    )
    expected = run_root / "knowledge" / "documents" / "modules" / "src--phy--pdsch--encoder" / "index.md"
    assert expected.is_file()
    assert module_document["storage_path"] == expected.relative_to(run_root).as_posix()
    assert module_document["module_folder"] == expected.parent.relative_to(run_root).as_posix()
    assert module_document["document_role"] == "leaf-engineering"

    channel_document = next(item for item in documents if item["module_id"] == "src--phy--pdsch")
    assert channel_document["document_role"] == "channel-playbook"
    assert "/channels/" in f"/{channel_document['storage_path']}"
    subsystem_document = next(item for item in documents if item["module_id"] == "src--phy")
    assert subsystem_document["document_role"] == "subsystem-guide"
    assert "/subsystems/" in f"/{subsystem_document['storage_path']}"

    services.indexer.index_repository(repository["id"], profile="balanced")
    chunk = services.database.one(
        "SELECT metadata_json FROM chunks WHERE document_id=? LIMIT 1",
        (module_document["id"],),
    )
    metadata = json.loads(chunk["metadata_json"])
    assert metadata["module_folder"] == module_document["module_folder"]
    assert metadata["storage_path"] == module_document["storage_path"]

    exported = client.get(f"/api/wiki/documents/{module_document['id']}/export")
    assert exported.status_code == 200
    assert "PDSCH Encoder" in exported.text
    exported_all = client.get(f"/api/repositories/{repository['id']}/documents/export")
    assert exported_all.status_code == 200
    assert exported_all.headers["content-type"] == "application/zip"
    assert exported_all.content.startswith(b"PK")

    published = client.post(f"/api/repositories/{repository['id']}/documents/publish")
    assert published.status_code == 200
    assert published.json()["run_id"] == run_id
    assert published.json()["files"] == len(list(output.rglob("*.md")))
    repository_wiki = repository_root / "docs" / "clangwiki"
    assert (repository_wiki / "Architecture.md").is_file()
    assert (repository_wiki / "Modules" / "src" / "phy" / "pdsch" / "encoder" / "index.md").is_file()
    export_manifest = json.loads((repository_wiki / ".clangwiki-export.json").read_text(encoding="utf-8"))
    assert export_manifest["run_id"] == run_id

    # A subsequent synchronisation must preserve unknown engineer-authored files.
    manual_note = repository_wiki / "engineering-note.md"
    manual_note.write_text("keep me\n", encoding="utf-8")
    assert client.post(f"/api/repositories/{repository['id']}/documents/publish").status_code == 200
    assert manual_note.read_text(encoding="utf-8") == "keep me\n"


def test_graph_and_logical_collection_keep_repositories_isolated(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    first = client.post("/api/repositories", json={"path": str(_repository(tmp_path, "common"))}).json()
    second = client.post("/api/repositories", json={"path": str(_repository(tmp_path, "pdsch"))}).json()
    collection = client.post("/api/collections", json={
        "name": "基带知识空间", "repository_ids": [first["id"], second["id"]],
    }).json()
    assert len(collection["repositories"]) == 2

    services = app.state.services
    run_id = "run-test"
    run_root = services.registry.run_root(first["id"], run_id)
    knowledge = run_root / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "modules.json").write_text(json.dumps([
        {"module_id": "pdsch", "display_name": "PDSCH", "source_path": "src", "parent_id": None, "direct_files": ["src/demo.c"]}
    ]), encoding="utf-8")
    (knowledge / "symbols.json").write_text(json.dumps([
        {"name": "pdsch_encode", "qualified_name": "pdsch_encode", "file_path": "src/demo.c", "line_start": 1, "line_end": 1, "kind": "function", "signature": "int pdsch_encode(void)", "certainty": "compiler"}
    ]), encoding="utf-8")
    (knowledge / "relations.json").write_text(json.dumps([
        {"source": "pdsch_encode", "target": "ldpc_encode", "kind": "CALLS", "file_path": "src/demo.c", "line": 1, "certainty": "compiler", "confidence": 1.0}
    ]), encoding="utf-8")
    services.database.execute(
        "INSERT INTO runs(id,repository_id,status,config_hash,schema_version,artifact_path,manifest_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (run_id, first["id"], "completed", "test", "test", str(run_root), "{}", time.time()),
    )
    services.database.execute("UPDATE repositories SET active_run_id=?,status='ready' WHERE id=?", (run_id, first["id"]))
    result = GraphService(services.database, services.registry).ingest_repository(first["id"], run_id, run_root)
    assert result["nodes"] >= 4

    graph = client.get(f"/api/graph?scope_type=repository&scope_id={first['id']}&level=symbol")
    assert graph.status_code == 200
    assert any(node["name"] == "pdsch_encode" for node in graph.json()["nodes"])
    assert graph.json()["relation_counts"]["CALLS"] == 1
    assert next(edge for edge in graph.json()["edges"] if edge["kind"] == "CALLS")["relation_label"] == "调用"
    pdsch_node = next(node for node in graph.json()["nodes"] if node["name"] == "pdsch_encode")
    neighbors = client.get(f"/api/graph/neighbors?node_id={pdsch_node['id']}&depth=1")
    assert neighbors.status_code == 200
    assert neighbors.json()["center"]["id"] == pdsch_node["id"]
    assert neighbors.json()["relation_counts"]["CALLS"] == 1
    assert any(edge["relation_label"] == "调用" for edge in neighbors.json()["edges"])
    missing_neighbors = client.get("/api/graph/neighbors?node_id=missing-node")
    assert missing_neighbors.status_code == 404
    collection_graph = client.post(f"/api/collections/{collection['id']}/relations/rebuild")
    assert collection_graph.status_code == 200
    # The collection only stores logical links; it never gains a source-tree copy.
    assert not (services.registry.collection_root(collection["id"]) / "source").exists()


def test_module_graph_keeps_isolated_modules(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    repository = client.post(
        "/api/repositories", json={"path": str(_repository(tmp_path))},
    ).json()
    services = app.state.services
    run_id = "run-isolated-modules"
    run_root = services.registry.run_root(repository["id"], run_id)
    knowledge = run_root / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "modules.json").write_text(json.dumps([
        {"module_id": "pdsch", "display_name": "PDSCH", "source_path": "src", "parent_id": None, "direct_files": ["src/demo.c"]},
        {"module_id": "dmrs", "display_name": "DMRS", "source_path": "dmrs", "parent_id": None, "direct_files": []},
    ]), encoding="utf-8")
    (knowledge / "symbols.json").write_text("[]", encoding="utf-8")
    (knowledge / "relations.json").write_text("[]", encoding="utf-8")
    services.database.execute(
        "INSERT INTO runs(id,repository_id,status,config_hash,schema_version,artifact_path,manifest_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (run_id, repository["id"], "completed", "test", "test", str(run_root), "{}", time.time()),
    )
    services.database.execute(
        "UPDATE repositories SET active_run_id=?,status='ready' WHERE id=?",
        (run_id, repository["id"]),
    )
    GraphService(services.database, services.registry).ingest_repository(
        repository["id"], run_id, run_root,
    )

    graph = client.get(
        f"/api/graph?scope_type=repository&scope_id={repository['id']}&level=module",
    )
    assert graph.status_code == 200
    assert {node["module_id"] for node in graph.json()["nodes"]} == {"pdsch", "dmrs"}
    assert graph.json()["edges"] == []


def test_generation_config_hash_is_stable_across_cli_and_api_defaults() -> None:
    repository_config = {
        "model": "deepseek/deepseek-v4-flash",
        "agent": "",
        "language": "简体中文",
        "max_source_chars_per_task": 18000,
        "channel_module_paths": [],
        "leaf_module_paths": [],
    }
    cli_config = {
        **repository_config,
        "force": False,
        "skip_cmake": False,
        "skip_analysis": False,
    }
    api_config = {**repository_config}

    canonical_cli = PlatformGenerationService._generation_config(cli_config)
    canonical_api = PlatformGenerationService._generation_config(api_config)
    assert canonical_cli == canonical_api
    assert _hash_json(canonical_cli) == _hash_json(canonical_api)
    assert canonical_api["only"] is None
    assert canonical_api["skip_cmake"] is False
    assert canonical_api["skip_analysis"] is False
    # Concurrency changes execution speed, not generated content, so it is
    # intentionally outside the snapshot hash.
    assert "module_generation_concurrency" not in canonical_api
    assert _module_generation_concurrency(repository_config.get("module_generation_concurrency")) == 2


def test_module_generation_concurrency_is_bounded() -> None:
    assert _module_generation_concurrency(None) == 2
    assert _module_generation_concurrency(1) == 1
    assert _module_generation_concurrency("4") == 4
    for value in (0, 5, "fast", True):
        try:
            _module_generation_concurrency(value)
        except Exception:
            pass
        else:
            raise AssertionError(f"expected invalid concurrency for {value!r}")


def test_repository_persists_module_generation_concurrency(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    repository = client.post("/api/repositories", json={
        "path": str(_repository(tmp_path)),
        "config": {"module_generation_concurrency": 3},
    })
    assert repository.status_code == 201
    assert repository.json()["config"]["module_generation_concurrency"] == 3

    invalid = client.patch(
        f"/api/repositories/{repository.json()['id']}",
        json={"config": {"module_generation_concurrency": 5}},
    )
    assert invalid.status_code == 400
    assert "1 到 4" in invalid.json()["detail"]

    # Generation overrides are validated when the job is submitted.  The
    # caller should never receive a queued job that is guaranteed to fail
    # later in a worker thread.
    invalid_job = client.post(
        f"/api/repositories/{repository.json()['id']}/generate",
        json={"overrides": {"module_generation_concurrency": 0}},
    )
    assert invalid_job.status_code == 400
    assert "1 到 4" in invalid_job.json()["detail"]


def test_concurrency_normalizes_string_and_rejects_fractional_values(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    repository_root = _repository(tmp_path)

    repository = client.post(
        "/api/repositories",
        json={"path": str(repository_root), "config": {"module_generation_concurrency": "3"}},
    )
    assert repository.status_code == 201
    assert repository.json()["config"]["module_generation_concurrency"] == 3

    fractional = client.patch(
        f"/api/repositories/{repository.json()['id']}",
        json={"config": {"module_generation_concurrency": 2.5}},
    )
    assert fractional.status_code == 400
    assert "1 到 4" in fractional.json()["detail"]


def test_unchanged_generation_reuses_snapshot_and_restores_ready_status(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    repository_root = _repository(tmp_path)
    repository = client.post("/api/repositories", json={
        "path": str(repository_root),
        "config": {"model": "deepseek/deepseek-v4-flash"},
    }).json()
    services = app.state.services
    run_id = "run-reusable"
    run_root = services.registry.run_root(repository["id"], run_id)
    run_root.mkdir(parents=True)
    canonical = PlatformGenerationService._generation_config(repository["config"])
    config_hash = _hash_json(canonical)
    manifest = {
        "config_hash": config_hash,
        "file_hashes": repository_file_hashes(repository_root),
    }
    services.database.execute(
        "INSERT INTO runs(id,repository_id,status,config_hash,schema_version,artifact_path,manifest_json,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            run_id,
            repository["id"],
            "completed",
            config_hash,
            DOCUMENT_SCHEMA_VERSION,
            str(run_root),
            json.dumps(manifest),
            time.time(),
        ),
    )
    services.database.execute(
        "UPDATE repositories SET active_run_id=?,status='failed' WHERE id=?",
        (run_id, repository["id"]),
    )

    result = services.generation.generate_repository(repository["id"])

    assert result["reused"] is True
    assert result["run"]["id"] == run_id
    assert services.registry.get_repository(repository["id"])["status"] == "ready"


def test_failed_document_run_exposes_safe_resume_checkpoint(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    repository_root = _repository(tmp_path)
    repository = client.post("/api/repositories", json={
        "path": str(repository_root), "config": {"model": "test/model"},
    }).json()
    services = app.state.services
    run_id = "run-resumable"
    run_root = services.registry.run_root(repository["id"], run_id)
    for relative in (
        "build/compile_commands.json", "analysis/diagnostics.json", "analysis/files.json",
        "analysis/symbols.json", "analysis/relations.json", "tasks/tasks.json",
    ):
        target = run_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[]" if target.name != "diagnostics.json" else "{}", encoding="utf-8")
    (run_root / "checkpoint.json").write_text(json.dumps({
        "completed_task_ids": ["leaf-a"], "completed": 1, "total": 3,
    }), encoding="utf-8")
    canonical = PlatformGenerationService._generation_config(repository["config"])
    config_hash = _hash_json(canonical)
    manifest = {"file_hashes": repository_file_hashes(repository_root), "request_overrides": {}}
    services.database.execute(
        "INSERT INTO runs(id,repository_id,status,config_hash,schema_version,artifact_path,manifest_json,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (run_id, repository["id"], "interrupted", config_hash, DOCUMENT_SCHEMA_VERSION, str(run_root), json.dumps(manifest), time.time()),
    )

    run = services.generation.list_runs(repository["id"])[0]
    assert run["resumable"] is True
    assert run["checkpoint"]["completed"] == 1
    assert services.generation._validate_resume_source(
        repository["id"], run_id, repository_file_hashes(repository_root), config_hash,
    )["id"] == run_id

    (repository_root / "src" / "demo.c").write_text("int changed(void) { return 1; }\n", encoding="utf-8")
    with pytest.raises(ClangWikiError, match="代码仓内容"):
        services.generation._validate_resume_source(
            repository["id"], run_id, repository_file_hashes(repository_root), config_hash,
        )

    # A later successful continuation supersedes the old checkpoint.  The
    # history remains visible, but neither the API nor the UI should offer the
    # stale run as another “continue” action.
    newer_run_id = "run-resumed"
    newer_root = services.registry.run_root(repository["id"], newer_run_id)
    newer_root.mkdir(parents=True, exist_ok=True)
    services.database.execute(
        "INSERT INTO runs(id,repository_id,status,config_hash,schema_version,artifact_path,manifest_json,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            newer_run_id, repository["id"], "completed", config_hash, DOCUMENT_SCHEMA_VERSION,
            str(newer_root), json.dumps({"resume_from_run_id": run_id}), time.time() + 1,
        ),
    )
    runs = services.generation.list_runs(repository["id"])
    assert runs[0]["id"] == newer_run_id
    assert next(item for item in runs if item["id"] == run_id)["resumable"] is False
