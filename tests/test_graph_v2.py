from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from clangwiki.database import Database
from clangwiki.graph import GraphService
from clangwiki.indexing import IndexService
from clangwiki.rag import RagService
from clangwiki.registry import Registry


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_v1_database_migrates_to_evidence_graph(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    connection = sqlite3.connect(data_root / "clangwiki.db")
    Database._migrate_v1(connection)
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()

    database = Database(data_root)
    assert database.one("SELECT name FROM sqlite_master WHERE type='table' AND name='graph_evidence'")
    assert database.one("SELECT name FROM sqlite_master WHERE type='table' AND name='graph_node_snapshots'")
    assert database.one("SELECT name FROM sqlite_master WHERE type='table' AND name='graph_edge_snapshots'")
    assert database.one("SELECT name FROM sqlite_master WHERE type='table' AND name='graph_insights'")
    node_columns = {row["name"] for row in database.all("PRAGMA table_info(knowledge_nodes)")}
    edge_columns = {row["name"] for row in database.all("PRAGMA table_info(knowledge_edges)")}
    metric_columns = {row["name"] for row in database.all("PRAGMA table_info(graph_metrics)")}
    layout_columns = {row["name"] for row in database.all("PRAGMA table_info(graph_layouts)")}
    assert {"layer", "subtype", "stable_key", "community_id"} <= node_columns
    assert {"status", "origin", "weight", "evidence_count"} <= edge_columns
    assert {"god_score", "god_type", "community_span", "fan_in", "fan_out"} <= metric_columns
    assert {"dimension", "z"} <= layout_columns


def test_v3_database_receives_god_node_migration(tmp_path: Path) -> None:
    data_root = tmp_path / "data-v3"
    data_root.mkdir()
    connection = sqlite3.connect(data_root / "clangwiki.db")
    Database._migrate_v1(connection)
    Database._migrate_v2(connection)
    Database._migrate_v3(connection)
    connection.execute("PRAGMA user_version = 3")
    connection.commit()
    connection.close()

    database = Database(data_root)
    assert database.connection().execute("PRAGMA user_version").fetchone()[0] == 5
    metric_columns = {row["name"] for row in database.all("PRAGMA table_info(graph_metrics)")}
    assert "god_score" in metric_columns
    assert database.one("SELECT name FROM sqlite_master WHERE type='table' AND name='graph_insights'")


def test_graph_v2_keeps_candidates_out_of_confirmed_paths(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    repo = tmp_path / "repo"
    (repo / "PDSCH" / "encoder").mkdir(parents=True)
    (repo / "PHY" / "ldpc").mkdir(parents=True)
    (repo / "CMakeLists.txt").write_text("add_library(pdsch PDSCH/encoder/pdsch.c)", encoding="utf-8")
    (repo / "PDSCH" / "encoder" / "pdsch.c").write_text("void pdsch_encode(void) {}", encoding="utf-8")
    database = Database(data_root)
    registry = Registry(database)
    repository = registry.add_repository(repo, "PDSCH", {"model": "test/model"})
    run_id = "run-v2"
    knowledge = data_root / "repositories" / repository["id"] / "runs" / run_id / "knowledge"
    _write(knowledge / "modules.json", [
        {"module_id": "PDSCH", "display_name": "PDSCH", "source_path": "PDSCH", "parent_id": None, "direct_files": []},
        {"module_id": "PDSCH_encoder", "display_name": "encoder", "source_path": "PDSCH/encoder", "parent_id": "PDSCH", "direct_files": ["PDSCH/encoder/pdsch.c"]},
        {"module_id": "PHY_ldpc", "display_name": "ldpc", "source_path": "PHY/ldpc", "parent_id": None, "direct_files": ["PHY/ldpc/ldpc.c"]},
    ])
    _write(knowledge / "symbols.json", [
        {"kind": "function", "name": "pdsch_encode", "qualified_name": "pdsch_encode", "usr": "c:@F@pdsch_encode", "file_path": "PDSCH/encoder/pdsch.c", "line_start": 1, "line_end": 1, "signature": "void (void)", "certainty": "compiler"},
        {"kind": "function", "name": "ldpc_encode", "qualified_name": "ldpc_encode", "usr": "c:@F@ldpc_encode", "file_path": "PHY/ldpc/ldpc.c", "line_start": 2, "line_end": 2, "signature": "void (void)", "certainty": "compiler"},
        {"kind": "function", "name": "unknown_stage", "qualified_name": "unknown_stage", "file_path": "PDSCH/encoder/pdsch.c", "line_start": 3, "line_end": 3, "signature": "void (void)", "certainty": "lexical"},
    ])
    _write(knowledge / "relations.json", [
        {"kind": "CALLS", "source": "pdsch_encode", "target": "ldpc_encode", "file_path": "PDSCH/encoder/pdsch.c", "line": 10, "certainty": "compiler", "confidence": 1.0},
        {"kind": "POSSIBLE_CALL", "source": "pdsch_encode", "target": "unknown_stage", "file_path": "PDSCH/encoder/pdsch.c", "line": 11, "certainty": "lexical", "confidence": 0.5},
        {"kind": "POSSIBLE_CALL", "source": "ldpc_encode", "target": "pdsch_encode", "file_path": "PHY/ldpc/ldpc.c", "line": 12, "certainty": "lexical", "confidence": 0.5},
    ])
    _write(knowledge / "repository.json", {"analysis_mode": "full", "diagnostics": []})
    _write(knowledge / "source_coverage.json", {"source_count": 1, "covered_source_count": 1, "coverage": 1.0})
    _write(knowledge.parent / "build" / "compile_commands.json", [{
        "directory": str(repo),
        "file": str(repo / "PDSCH" / "encoder" / "pdsch.c"),
        "command": "clang -c PDSCH/encoder/pdsch.c -o CMakeFiles/pdsch.dir/pdsch.c.obj",
        "output": "CMakeFiles/pdsch.dir/pdsch.c.obj",
    }])

    graph = GraphService(database, registry)
    result = graph.ingest_repository(repository["id"], run_id, knowledge.parent)
    assert result["diagnostics"]["confirmed_calls"] == 1
    assert database.one(
        "SELECT id FROM knowledge_nodes WHERE repository_id=? AND kind='build_target' AND name='pdsch'",
        (repository["id"],),
    )
    assert database.one(
        "SELECT id FROM knowledge_nodes WHERE repository_id=? AND kind='translation_unit'",
        (repository["id"],),
    )
    encoder_module = database.one(
        "SELECT id FROM knowledge_nodes WHERE repository_id=? AND kind='module' AND module_id=?",
        (repository["id"], "PDSCH_encoder"),
    )
    ldpc_module = database.one(
        "SELECT id FROM knowledge_nodes WHERE repository_id=? AND kind='module' AND module_id=?",
        (repository["id"], "PHY_ldpc"),
    )
    assert encoder_module and ldpc_module
    outgoing = graph.neighbors(
        encoder_module["id"], scope_type="repository", scope_id=repository["id"],
        level="module", direction="outgoing",
    )
    assert any(edge["source"] == encoder_module["id"] and edge["target"] == ldpc_module["id"] for edge in outgoing["edges"])
    incoming_without_candidates = graph.neighbors(
        encoder_module["id"], scope_type="repository", scope_id=repository["id"],
        level="module", direction="incoming",
    )
    assert all(edge["kind"] != "POSSIBLE_CALL" for edge in incoming_without_candidates["edges"])
    incoming_with_candidates = graph.neighbors(
        encoder_module["id"], scope_type="repository", scope_id=repository["id"],
        level="module", direction="incoming", include_candidates=True,
    )
    assert any(edge["kind"] == "POSSIBLE_CALL" and edge["source"] == ldpc_module["id"] for edge in incoming_with_candidates["edges"])
    default_module_graph = graph.graph("repository", repository["id"], "module", limit=20)
    assert any(edge["source"] == encoder_module["id"] and edge["target"] == ldpc_module["id"] for edge in default_module_graph["edges"])
    hierarchy_graph = graph.graph("repository", repository["id"], "module", view="hierarchy", limit=20)
    assert any(edge["kind"] == "CONTAINS" for edge in hierarchy_graph["edges"])
    default_graph = graph.graph("repository", repository["id"], "symbol", limit=200)
    assert "CALLS" in {edge["kind"] for edge in default_graph["edges"]}
    assert "POSSIBLE_CALL" not in {edge["kind"] for edge in default_graph["edges"]}
    complete_graph = graph.graph(
        "repository", repository["id"], "symbol", limit=200,
        statuses=["confirmed", "candidate"], layers=["code", "domain"],
    )
    assert "POSSIBLE_CALL" in {edge["kind"] for edge in complete_graph["edges"]}
    call = next(edge for edge in complete_graph["edges"] if edge["kind"] == "CALLS")
    core_graph = graph.graph("repository", repository["id"], "symbol", limit=200, view="coremap")
    assert core_graph["focus"] == "god_nodes"
    assert any(node["id"] == call["source"] for node in core_graph["nodes"])
    surprise_graph = graph.graph("repository", repository["id"], "symbol", limit=200, view="surprises")
    assert surprise_graph["focus"] == "surprising_connections"
    assert all(edge["kind"] == "SURPRISING_CONNECTION" for edge in surprise_graph["edges"])
    assert graph.insights(repository["id"], "surprising_connection")
    symbol_results = graph.symbol_search("repository", repository["id"], "pdsch_encode", limit=5)
    assert symbol_results["total"] >= 1
    assert any(item["name"] == "pdsch_encode" for item in symbol_results["results"])
    core_functions = graph.core_functions(repository["id"], limit=2)
    assert core_functions["nodes"]
    assert len(core_functions["nodes"]) <= 2
    impact = graph.impact("repository", repository["id"], call["source"], "implementation", depth=2)
    assert impact["anchor"]["id"] == call["source"]
    assert call["target"] in impact["impact_tiers"]["must_review"]
    assert call["origin"] == "compiler" and call["evidence_count"] == 1
    detail = graph.node_detail(call["source"])
    assert any(edge["evidence"] for edge in detail["edges"] if edge["kind"] == "CALLS")
    edge_detail = graph.edge_detail(call["id"])
    assert edge_detail["source_node"]["id"] == call["source"]
    assert edge_detail["target_node"]["id"] == call["target"]
    assert edge_detail["evidence"][0]["line_start"] == 10
    path = graph.shortest_path(call["source"], call["target"], directed=True)
    assert path["found"] is True
    reverse = graph.shortest_path(call["target"], call["source"], directed=True)
    assert reverse["found"] is False
    assert graph.communities(repository["id"])
    assert "<graphml" in graph.export_graphml("repository", repository["id"], "symbol")

    database.execute(
        "UPDATE repositories SET active_run_id=?,status='ready' WHERE id=?",
        (run_id, repository["id"]),
    )
    graph_chunks = [
        chunk for chunk in IndexService(database, registry)._repository_chunks(
            registry.get_repository(repository["id"])
        )
        if chunk.kind == "graph"
    ]
    call_chunks = [item for item in graph_chunks if item.metadata["relation_type"] == "CALLS"]
    assert len(call_chunks) == 1
    assert "CALLS" in call_chunks[0].content
    assert all("POSSIBLE_CALL" not in item.content for item in graph_chunks)
    assert all(item.metadata["status"] == "confirmed" for item in graph_chunks)
    monkeypatch.setattr(
        "clangwiki.indexing.LocalVectorIndex.update",
        lambda self, all_chunks, changed, removed: {"available": False, "warning": "test"},
    )
    indexer = IndexService(database, registry)
    indexer.index_repository(repository["id"], profile="balanced")
    search = indexer.search("pdsch_encode ldpc_encode", "repository", repository["id"], limit=20)
    assert any(item["kind"] == "graph" for item in search["results"])
    evidence = RagService(database, registry, indexer)._evidence(search["results"])
    assert any(key.startswith("G") for key in evidence)

    _write(knowledge / "relations.json", [
        {"kind": "CALLS", "source": "pdsch_encode", "target": "ldpc_encode", "file_path": "PDSCH/encoder/pdsch.c", "line": 10, "certainty": "compiler", "confidence": 1.0},
        {"kind": "READS", "source": "ldpc_encode", "target": "pdsch_encode", "file_path": "PDSCH/encoder/pdsch.c", "line": 12, "certainty": "compiler", "confidence": 1.0},
    ])
    graph.ingest_repository(repository["id"], "run-v3", knowledge.parent)
    graph_diff = graph.diff(repository["id"], run_id, "run-v3")
    assert graph_diff["summary"]["edges_added"] >= 1
    assert graph_diff["summary"]["edges_removed"] >= 1
