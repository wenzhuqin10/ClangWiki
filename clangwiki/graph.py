from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from .database import Database, json_dumps, json_loads
from .graph_analytics import GraphAnalytics
from .graph_domain import enrich_baseband_graph
from .io import read_json
from .registry import Registry


GRAPH_KINDS = {
    "CONTAINS", "BUILDS", "COMPILES", "DECLARES", "DEFINES", "DECLARATION_OF",
    "MEMBER_OF", "HAS_PARAMETER", "HAS_FIELD", "HAS_VALUE", "DEPENDS_ON", "INCLUDES",
    "CALLS", "POSSIBLE_CALL", "REFERENCES", "READS", "WRITES", "USES_TYPE", "PASSES_TO",
    "RETURNS_TYPE", "REGISTER_CALLBACK", "INVOKES_CALLBACK", "INHERITS", "GUARDED_BY",
    "IMPLEMENTS_CHANNEL", "PARTICIPATES_IN", "PRECEDES", "TRIGGERS", "SENDS", "RECEIVES",
    "PRODUCES", "CONSUMES", "CONFIGURES", "TRANSITIONS_TO", "RUNS_IN", "LOGS", "ASSERTS",
    "SPECIFIED_BY", "TESTS", "VALIDATES", "DOCUMENTS", "MENTIONS", "EXPLAINS",
    "EVIDENCE_FOR", "RELATED_TO", "PROVIDES_INTERFACE", "CONSUMES_INTERFACE",
    "MATCHES_DECLARATION", "CROSS_REPO_CALL",
}

GRAPH_RELATION_LABELS = {
    "CONTAINS": "包含",
    "BUILDS": "构建",
    "COMPILES": "编译",
    "DECLARES": "声明",
    "DEPENDS_ON": "依赖",
    "INCLUDES": "包含头文件",
    "CALLS": "调用",
    "POSSIBLE_CALL": "可能调用",
    "REFERENCES": "引用",
    "READS": "读取",
    "WRITES": "写入",
    "USES_TYPE": "使用类型",
    "PASSES_TO": "参数传递",
    "RETURNS_TYPE": "返回类型",
    "REGISTER_CALLBACK": "注册回调",
    "INVOKES_CALLBACK": "触发回调",
    "INHERITS": "继承",
    "IMPLEMENTS_CHANNEL": "实现信道",
    "PARTICIPATES_IN": "参与流程",
    "CONFIGURES": "配置",
    "RUNS_IN": "运行于",
    "SPECIFIED_BY": "协议依据",
    "TESTS": "测试",
    "DEFINES": "定义",
    "DOCUMENTS": "文档对应",
    "RELATED_TO": "相关",
    "SURPRISING_CONNECTION": "惊喜链接",
}

GRAPH_NODE_LABELS = {
    "repository": "仓库",
    "module": "模块",
    "file": "文件",
    "symbol": "符号",
    "external": "外部符号",
    "domain": "基带领域",
    "document": "文档",
    "community": "耦合群",
}


class GraphService:
    def __init__(self, database: Database, registry: Registry) -> None:
        self.db = database
        self.registry = registry
        self.analytics = GraphAnalytics(database)

    def ingest_repository(self, repository_id: str, run_id: str, run_root: Path) -> dict[str, int]:
        repository = self.registry.get_repository(repository_id)
        knowledge = run_root / "knowledge"
        modules = _read_list(knowledge / "modules.json")
        symbols = _read_list(knowledge / "symbols.json")
        relations = _read_list(knowledge / "relations.json")
        repository_info = _read_object(knowledge / "repository.json")
        coverage = _read_object(knowledge / "source_coverage.json")
        git_commit = str(repository.get("git_commit") or "") or None

        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        repo_node = f"repo:{repository_id}"
        nodes[repo_node] = self._node(
            repo_node, repository_id, run_id, "repository", repository["name"], path=repository["path"],
            layer="code", subtype="repository", origin="source",
            metadata={"analysis_mode": repository_info.get("analysis_mode", "unknown"), "coverage": coverage},
        )

        module_by_source: dict[str, str] = {}
        file_to_module: dict[str, str] = {}
        for module in modules:
            module_id = str(module.get("module_id", ""))
            node_id = f"module:{repository_id}:{module_id}"
            source_path = str(module.get("source_path", ""))
            module_by_source[source_path] = node_id
            nodes[node_id] = self._node(
                node_id, repository_id, run_id, "module", str(module.get("display_name") or source_path or "root"),
                path=source_path, module_id=module_id, metadata=module,
            )
            parent_id = module.get("parent_id")
            parent_node = f"module:{repository_id}:{parent_id}" if parent_id else repo_node
            edge = self._edge(repository_id, run_id, parent_node, node_id, "CONTAINS", "compiler", 1.0)
            edges[edge["id"]] = edge
            for file_path in module.get("direct_files") or []:
                file_to_module[str(file_path)] = module_id

        for module in modules:
            module_id = str(module.get("module_id", ""))
            module_node = f"module:{repository_id}:{module_id}"
            for file_path in module.get("direct_files") or []:
                relative = _normalise(str(file_path))
                file_node = f"file:{repository_id}:{relative}"
                nodes[file_node] = self._node(
                    file_node, repository_id, run_id, "file", Path(relative).name,
                    path=relative, module_id=module_id,
                )
                edge = self._edge(repository_id, run_id, module_node, file_node, "CONTAINS", "compiler", 1.0)
                edges[edge["id"]] = edge

        # Compilation database facts form the build layer of the graph.  They
        # remain useful even when a translation unit later fails libclang
        # parsing, because the user can still see target membership and exact
        # compile settings in diagnostics.
        compilation_database = _read_list(run_root / "build" / "compile_commands.json")
        for command in compilation_database:
            source_path = _repository_relative(str(command.get("file") or ""), Path(repository["path"]))
            if not source_path:
                continue
            target_name = _cmake_target_name(command) or "unclassified"
            target_id = f"target:{repository_id}:{_digest(target_name)}"
            if target_id not in nodes:
                nodes[target_id] = self._node(
                    target_id, repository_id, run_id, "build_target", target_name,
                    layer="code", subtype="cmake_target", certainty="build", origin="build",
                    metadata={"target": target_name},
                )
                edge = self._edge(
                    repository_id, run_id, repo_node, target_id, "BUILDS", "build", 1.0,
                    status="confirmed", origin="build", confirmed=True,
                )
                edges[edge["id"]] = edge
            translation_unit_id = f"tu:{repository_id}:{_digest(source_path)}"
            nodes[translation_unit_id] = self._node(
                translation_unit_id, repository_id, run_id, "translation_unit", Path(source_path).name,
                path=source_path, module_id=file_to_module.get(source_path) or _closest_module(source_path, modules),
                layer="code", subtype="translation_unit", certainty="build", origin="build",
                metadata={
                    "directory": command.get("directory"), "output": command.get("output"),
                    "command": str(command.get("command") or "")[:8000],
                    "arguments": list(command.get("arguments") or [])[:256],
                },
            )
            edge = self._edge(
                repository_id, run_id, target_id, translation_unit_id, "COMPILES", "build", 1.0,
                status="confirmed", origin="build", confirmed=True,
            )
            edges[edge["id"]] = edge
            file_node = f"file:{repository_id}:{source_path}"
            if file_node not in nodes:
                module_id = file_to_module.get(source_path) or _closest_module(source_path, modules)
                nodes[file_node] = self._node(
                    file_node, repository_id, run_id, "file", Path(source_path).name,
                    path=source_path, module_id=module_id,
                )
            edge = self._edge(
                repository_id, run_id, translation_unit_id, file_node, "CONTAINS", "build", 1.0,
                status="confirmed", origin="build", confirmed=True,
            )
            edges[edge["id"]] = edge

        symbols_by_name: dict[str, list[str]] = defaultdict(list)
        symbol_file: dict[str, str] = {}
        for symbol in symbols:
            name = str(symbol.get("qualified_name") or symbol.get("name") or "")
            if not name:
                continue
            path = _normalise(str(symbol.get("file_path") or ""))
            line = int(symbol.get("line_start") or 0)
            stable_key = str(symbol.get("usr") or "").strip() or f"{name}|{path}|{symbol.get('signature') or ''}"
            node_id = f"symbol:{repository_id}:{_digest(stable_key)}"
            module_id = file_to_module.get(path) or _closest_module(path, modules)
            certainty = str(symbol.get("certainty") or "compiler")
            symbol_kind = str(symbol.get("kind") or "symbol").lower()
            nodes[node_id] = self._node(
                node_id, repository_id, run_id, "symbol", str(symbol.get("name") or name),
                qualified_name=name, path=path, line_start=line,
                line_end=int(symbol.get("line_end") or line), module_id=module_id,
                certainty=certainty, metadata=symbol, layer="code", subtype=symbol_kind,
                stable_key=stable_key, origin="compiler" if certainty == "compiler" else "source",
            )
            symbols_by_name[name].append(node_id)
            symbol_file[node_id] = path
            file_node = f"file:{repository_id}:{path}"
            if file_node not in nodes:
                nodes[file_node] = self._node(file_node, repository_id, run_id, "file", Path(path).name, path=path, module_id=module_id)
                parent = f"module:{repository_id}:{module_id}" if module_id else repo_node
                edge = self._edge(repository_id, run_id, parent, file_node, "CONTAINS", certainty, 1.0)
                edges[edge["id"]] = edge
            edge = self._edge(repository_id, run_id, file_node, node_id, "DEFINES", certainty, 1.0)
            edges[edge["id"]] = edge

        for relation in relations:
            kind = str(relation.get("kind") or "RELATED_TO").upper()
            if kind not in GRAPH_KINDS:
                kind = "RELATED_TO"
            file_path = _normalise(str(relation.get("file_path") or ""))
            source_name = str(relation.get("source") or "")
            target_name = str(relation.get("target") or "")
            source_id = _best_symbol(symbols_by_name.get(source_name, []), symbol_file, file_path)
            if source_id is None and source_name == file_path:
                source_id = f"file:{repository_id}:{file_path}"
            if source_id is None:
                source_id = self._external_node(nodes, repository_id, run_id, source_name or file_path)

            if kind == "INCLUDES":
                target_id = self._resolve_include(nodes, repository_id, run_id, target_name, file_to_module)
            else:
                target_id = _best_symbol(symbols_by_name.get(target_name, []), symbol_file, file_path)
                if target_id is None:
                    target_id = self._external_node(nodes, repository_id, run_id, target_name)
            certainty = str(relation.get("certainty") or ("lexical" if kind == "POSSIBLE_CALL" else "compiler"))
            confidence = float(relation.get("confidence") or 0.5)
            origin = "compiler" if certainty == "compiler" else "source"
            status = "candidate" if kind == "POSSIBLE_CALL" or certainty in {"lexical", "candidate"} else "confirmed"
            metadata = {
                "file_path": file_path,
                "line": relation.get("line"),
                "raw_source": source_name,
                "raw_target": target_name,
            }
            edge = self._edge(
                repository_id, run_id, source_id, target_id, kind, certainty, confidence, metadata,
                status=status, origin=origin, confirmed=status == "confirmed",
                evidence={"git_commit": git_commit, "source_uri": file_path, "line_start": relation.get("line"),
                          "line_end": relation.get("line"), "extractor": "libclang" if origin == "compiler" else "lexical",
                          "reason": f"{kind} extracted from {file_path}"},
            )
            _merge_edge(edges, edge)

        enrich_baseband_graph(
            repository_id, run_id, nodes, edges,
            edge_factory=self._edge, node_factory=self._node,
        )
        self._replace_repository_graph(repository_id, run_id, nodes.values(), edges.values())
        analysis = self.analytics.analyze(repository_id, run_id)
        diagnostics = self.diagnostics(repository_id)
        return {"nodes": len(nodes), "edges": len(edges), "analysis": analysis, "diagnostics": diagnostics}

    def rebuild_collection(self, collection_id: str) -> dict[str, int]:
        repository_ids = self.registry.collection_repository_ids(collection_id)
        placeholders = ",".join("?" for _ in repository_ids)
        if not repository_ids:
            self.db.execute("DELETE FROM knowledge_edges WHERE collection_id=?", (collection_id,))
            return {"edges": 0, "candidates": 0}
        nodes = self.db.all(
            f"SELECT * FROM knowledge_nodes WHERE repository_id IN ({placeholders}) AND kind='symbol'",
            tuple(repository_ids),
        )
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            groups[str(node.get("qualified_name") or node["name"])].append(node)

        values: list[dict[str, Any]] = []
        confirmed = candidates = 0
        for name, members in groups.items():
            repositories = {member["repository_id"] for member in members}
            if len(repositories) < 2:
                continue
            for left_index, left in enumerate(members):
                for right in members[left_index + 1:]:
                    if left["repository_id"] == right["repository_id"]:
                        continue
                    left_meta = json_loads(left.get("metadata_json"), {})
                    right_meta = json_loads(right.get("metadata_json"), {})
                    signature_left = str(left_meta.get("signature") or "").strip()
                    signature_right = str(right_meta.get("signature") or "").strip()
                    exact = bool(signature_left and signature_left == signature_right)
                    certainty = "compiler" if exact else "candidate"
                    confidence = 1.0 if exact else 0.55
                    edge = self._edge(
                        None, None, left["id"], right["id"], "MATCHES_DECLARATION", certainty,
                        confidence, {"symbol": name, "match": "signature" if exact else "name"},
                        collection_id=collection_id, confirmed=exact,
                        status="confirmed" if exact else "candidate",
                        origin="compiler" if exact else "rule",
                    )
                    values.append(edge)
                    confirmed += int(exact)
                    candidates += int(not exact)
                    if len(values) >= 20000:
                        break
                if len(values) >= 20000:
                    break
            if len(values) >= 20000:
                break
        with self.db.transaction() as connection:
            connection.execute("DELETE FROM knowledge_edges WHERE collection_id=?", (collection_id,))
            connection.executemany(
                "INSERT INTO knowledge_edges(id,repository_id,collection_id,run_id,source_id,target_id,kind,certainty,confidence,confirmed,metadata_json,status,origin,weight,evidence_count) "
                "VALUES(:id,:repository_id,:collection_id,:run_id,:source_id,:target_id,:kind,:certainty,:confidence,:confirmed,:metadata_json,:status,:origin,:weight,:evidence_count)",
                values,
            )
        return {"edges": len(values), "confirmed": confirmed, "candidates": candidates}

    def set_edge_confirmation(self, edge_id: str, confirmed: bool) -> dict[str, Any]:
        edge = self.db.one("SELECT * FROM knowledge_edges WHERE id=?", (edge_id,))
        if not edge:
            raise KeyError("关系不存在")
        certainty = "user-confirmed" if confirmed else "rejected"
        status = "confirmed" if confirmed else "rejected"
        self.db.execute(
            "UPDATE knowledge_edges SET confirmed=?, certainty=?, status=?, origin='user' WHERE id=?",
            (1 if confirmed else 0, certainty, status, edge_id),
        )
        return self.db.one("SELECT * FROM knowledge_edges WHERE id=?", (edge_id,)) or {}

    def graph(
        self,
        scope_type: str,
        scope_id: str,
        level: str = "module",
        kinds: Iterable[str] | None = None,
        certainty: str | None = None,
        limit: int = 2500,
        *,
        view: str | None = None,
        layers: Iterable[str] | None = None,
        statuses: Iterable[str] | None = None,
        community_id: str | None = None,
        min_degree: int = 0,
    ) -> dict[str, Any]:
        repository_ids = self._scope_repositories(scope_type, scope_id)
        if not repository_ids:
            return {"nodes": [], "edges": [], "truncated": False, "relation_counts": {}}
        placeholders = ",".join("?" for _ in repository_ids)
        node_conditions = [f"n.repository_id IN ({placeholders})"]
        node_parameters: list[Any] = list(repository_ids)
        requested_layers = [item for item in (layers or []) if item in {"code", "domain", "knowledge", "candidate"}]
        if requested_layers:
            normal_layers = [item for item in requested_layers if item != "candidate"]
            if normal_layers:
                node_conditions.append("n.layer IN (" + ",".join("?" for _ in normal_layers) + ")")
                node_parameters.extend(normal_layers)
        if community_id:
            node_conditions.append("n.community_id=?")
            node_parameters.append(community_id)
        nodes = self.db.all(
            "SELECT n.*,m.degree,m.in_degree,m.out_degree,m.betweenness,m.pagerank,m.is_hub,m.is_bridge,m.is_orphan,"
            "m.god_score,m.god_type,m.community_span,m.fan_in,m.fan_out "
            "FROM knowledge_nodes n LEFT JOIN graph_metrics m ON m.node_id=n.id AND (m.run_id=n.run_id OR m.run_id IS NULL) WHERE "
            + " AND ".join(node_conditions),
            tuple(node_parameters),
        )
        node_map = {node["id"]: self._public_node(node) for node in nodes}
        conditions = [f"(repository_id IN ({placeholders})"]
        parameters: list[Any] = list(repository_ids)
        if scope_type == "collection":
            conditions[0] += " OR collection_id=?)"
            parameters.append(scope_id)
        else:
            conditions[0] += ")"
        requested_kinds = [item.upper() for item in (kinds or []) if item.upper() in GRAPH_KINDS]
        if requested_kinds:
            conditions.append("kind IN (" + ",".join("?" for _ in requested_kinds) + ")")
            parameters.extend(requested_kinds)
        if certainty:
            conditions.append("certainty=?")
            parameters.append(certainty)
        requested_statuses = [item for item in (statuses or ["confirmed"]) if item in {"confirmed", "candidate", "rejected"}]
        if requested_statuses:
            conditions.append("status IN (" + ",".join("?" for _ in requested_statuses) + ")")
            parameters.extend(requested_statuses)
        if level in {"repository", "module", "file"}:
            # Structural containment/definition edges collapse to self-edges at
            # aggregate levels and can consume the SQL limit before any actual
            # dependency or call edge is read.
            conditions.append("kind NOT IN ('CONTAINS','DEFINES','DOCUMENTS')")
        edges = self.db.all(
            "SELECT * FROM knowledge_edges WHERE " + " AND ".join(conditions) + " LIMIT ?",
            tuple(parameters + [max(limit * 5, limit)]),
        )
        if view == "community":
            return self._community_graph(repository_ids, node_map, edges, limit)
        if view == "coremap":
            result = self._coremap_graph(repository_ids, node_map, edges, limit)
            result["diagnostics"] = self.diagnostics(repository_ids[0]) if len(repository_ids) == 1 else {}
            return result
        if view == "surprises":
            result = self._surprise_graph(repository_ids, node_map, limit)
            result["diagnostics"] = self.diagnostics(repository_ids[0]) if len(repository_ids) == 1 else {}
            return result
        if level == "symbol":
            public_edges = [self._public_edge(edge) for edge in edges if edge["source_id"] in node_map and edge["target_id"] in node_map]
            used = {item[key] for item in public_edges for key in ("source", "target")}
            public_nodes = [node_map[item] for item in used if float(node_map[item].get("metrics", {}).get("degree") or 0) >= min_degree][:limit]
            allowed = {node["id"] for node in public_nodes}
            public_edges = [edge for edge in public_edges if edge["source"] in allowed and edge["target"] in allowed]
            return {
                "nodes": public_nodes,
                "edges": public_edges[:limit],
                "truncated": len(public_edges) > limit,
                "relation_counts": _relation_counts(public_edges),
                "diagnostics": self.diagnostics(repository_ids[0]) if len(repository_ids) == 1 else {},
            }
        result = self._aggregate(level, node_map, edges, limit)
        result["diagnostics"] = self.diagnostics(repository_ids[0]) if len(repository_ids) == 1 else {}
        return result

    def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        kinds: Iterable[str] | None = None,
        limit: int = 500,
        *,
        scope_type: str | None = None,
        scope_id: str | None = None,
        level: str = "symbol",
        direction: str = "both",
        include_candidates: bool = False,
    ) -> dict[str, Any]:
        # Aggregate graph levels (repository/module/file) use derived edges,
        # therefore query the same graph projection used by the canvas.  A raw
        # SQL traversal would otherwise return module-to-file containment edges
        # while the user is looking at module-to-module dependencies.
        if scope_type and scope_id and level != "symbol":
            projected = self.graph(scope_type, scope_id, level, kinds, None, max(limit * 4, limit))
            projected_nodes = {node["id"]: node for node in projected.get("nodes", [])}
            if node_id not in projected_nodes:
                raise KeyError("图谱节点不存在")
            projected_edges = list(projected.get("edges", []))
            return _projected_neighbors(node_id, projected_nodes, projected_edges, depth, limit)
        center_row = self.db.one("SELECT * FROM knowledge_nodes WHERE id=?", (node_id,))
        if not center_row:
            raise KeyError("图谱节点不存在")
        depth = max(1, min(3, depth))
        requested = {item.upper() for item in (kinds or [])}
        seen = {node_id}
        frontier = {node_id}
        edge_rows: dict[str, dict[str, Any]] = {}
        for _ in range(depth):
            if not frontier or len(seen) >= limit:
                break
            placeholders = ",".join("?" for _ in frontier)
            status_sql = "" if include_candidates else " AND status='confirmed'"
            if direction == "outgoing":
                rows = self.db.all(
                    f"SELECT * FROM knowledge_edges WHERE source_id IN ({placeholders}){status_sql} LIMIT ?",
                    tuple(frontier) + (limit * 4,),
                )
            elif direction == "incoming":
                rows = self.db.all(
                    f"SELECT * FROM knowledge_edges WHERE target_id IN ({placeholders}){status_sql} LIMIT ?",
                    tuple(frontier) + (limit * 4,),
                )
            else:
                rows = self.db.all(
                    f"SELECT * FROM knowledge_edges WHERE (source_id IN ({placeholders}) OR target_id IN ({placeholders})){status_sql} LIMIT ?",
                    tuple(frontier) + tuple(frontier) + (limit * 4,),
                )
            next_frontier: set[str] = set()
            for row in rows:
                if requested and row["kind"] not in requested:
                    continue
                edge_rows[row["id"]] = row
                for key in ("source_id", "target_id"):
                    if row[key] not in seen:
                        next_frontier.add(row[key])
            seen.update(next_frontier)
            frontier = next_frontier
        placeholders = ",".join("?" for _ in seen)
        nodes = self.db.all(f"SELECT * FROM knowledge_nodes WHERE id IN ({placeholders})", tuple(seen)) if seen else []
        public_nodes = [self._public_node(node) for node in nodes]
        public_edges = [self._public_edge(edge) for edge in edge_rows.values()]
        public_center = self._public_node(center_row)
        return {
            "center": public_center,
            "nodes": public_nodes,
            "edges": public_edges,
            "depth": depth,
            "relation_counts": _relation_counts(public_edges),
            "truncated": len(seen) >= limit,
        }

    def shortest_path(
        self, source_id: str, target_id: str, max_depth: int = 8, *, directed: bool = True,
        kinds: Iterable[str] | None = None, include_candidates: bool = False,
    ) -> dict[str, Any]:
        requested = {kind.upper() for kind in (kinds or []) if kind.upper() in GRAPH_KINDS}
        queue: deque[tuple[str, list[str], list[str]]] = deque([(source_id, [source_id], [])])
        seen = {source_id}
        while queue:
            current, nodes, edges = queue.popleft()
            if len(edges) >= max_depth:
                continue
            status_sql = "" if include_candidates else " AND status='confirmed'"
            if directed:
                rows = self.db.all(
                    f"SELECT * FROM knowledge_edges WHERE source_id=?{status_sql} LIMIT 2000", (current,),
                )
            else:
                rows = self.db.all(
                    f"SELECT * FROM knowledge_edges WHERE (source_id=? OR target_id=?){status_sql} LIMIT 2000", (current, current),
                )
            for row in rows:
                if requested and row["kind"] not in requested:
                    continue
                neighbour = row["target_id"] if row["source_id"] == current else row["source_id"]
                if neighbour == target_id:
                    node_rows = self._nodes_by_ids(nodes + [neighbour])
                    edge_rows = [self.db.one("SELECT * FROM knowledge_edges WHERE id=?", (item,)) for item in edges + [row["id"]]]
                    return {
                        "nodes": [self._public_node(item) for item in node_rows],
                        "edges": [self._public_edge(item) for item in edge_rows if item],
                        "found": True,
                    }
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append((neighbour, nodes + [neighbour], edges + [row["id"]]))
        return {"nodes": [], "edges": [], "found": False}

    def _replace_repository_graph(
        self,
        repository_id: str,
        run_id: str,
        nodes: Iterable[dict[str, Any]],
        edges: Iterable[dict[str, Any]],
    ) -> None:
        node_values = list(nodes)
        edge_values = list(edges)
        nodes_by_id = {item["id"]: item for item in node_values}
        node_ids = {item["id"] for item in node_values}
        edge_ids = {item["id"] for item in edge_values}
        evidence_values: list[dict[str, Any]] = []
        for edge in edge_values:
            raw_evidence = list(edge.pop("_evidence", []))
            if not raw_evidence:
                source = nodes_by_id.get(edge["source_id"], {})
                raw_evidence = [{
                    "origin": edge.get("origin") or "source",
                    "confidence": edge.get("confidence") or 0.0,
                    "source_uri": source.get("path"),
                    "line_start": source.get("line_start"),
                    "line_end": source.get("line_end"),
                    "extractor": "clangwiki-graph",
                    "reason": f"{edge.get('kind')} relation extracted from {edge.get('origin') or 'source'} facts",
                }]
            edge["evidence_count"] = len(raw_evidence)
            for index, item in enumerate(raw_evidence):
                evidence_key = f"{edge['id']}|{index}|{item.get('source_uri')}|{item.get('line_start')}"
                evidence_values.append({
                    "id": f"evidence:{_digest(evidence_key)}",
                    "edge_id": edge["id"], "repository_id": repository_id, "run_id": run_id,
                    "git_commit": item.get("git_commit"), "origin": item.get("origin") or edge["origin"],
                    "confidence": float(item.get("confidence") or edge["confidence"]),
                    "source_uri": item.get("source_uri"), "line_start": item.get("line_start"),
                    "line_end": item.get("line_end"), "extractor": item.get("extractor"),
                    "extractor_version": item.get("extractor_version"), "reason": item.get("reason") or "",
                    "metadata_json": json_dumps(item.get("metadata") or {}),
                })
        with self.db.transaction() as connection:
            connection.execute(
                "DELETE FROM graph_node_snapshots WHERE repository_id=? AND run_id=?",
                (repository_id, run_id),
            )
            connection.execute(
                "DELETE FROM graph_edge_snapshots WHERE repository_id=? AND run_id=?",
                (repository_id, run_id),
            )
            connection.executemany(
                "INSERT INTO graph_node_snapshots(repository_id,run_id,node_id,payload_json) VALUES(?,?,?,?)",
                [(repository_id, run_id, item["id"], json_dumps(item)) for item in node_values],
            )
            connection.executemany(
                "INSERT INTO graph_edge_snapshots(repository_id,run_id,edge_id,payload_json) VALUES(?,?,?,?)",
                [(repository_id, run_id, item["id"], json_dumps(item)) for item in edge_values],
            )
            connection.executemany(
                "INSERT INTO knowledge_nodes(id,repository_id,collection_id,run_id,kind,name,qualified_name,path,line_start,line_end,module_id,certainty,metadata_json,layer,subtype,stable_key,community_id,properties_json,first_seen_run_id,last_seen_run_id) "
                "VALUES(:id,:repository_id,:collection_id,:run_id,:kind,:name,:qualified_name,:path,:line_start,:line_end,:module_id,:certainty,:metadata_json,:layer,:subtype,:stable_key,:community_id,:properties_json,:first_seen_run_id,:last_seen_run_id) "
                "ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id,kind=excluded.kind,name=excluded.name,qualified_name=excluded.qualified_name,"
                "path=excluded.path,line_start=excluded.line_start,line_end=excluded.line_end,module_id=excluded.module_id,certainty=excluded.certainty,"
                "metadata_json=excluded.metadata_json,layer=excluded.layer,subtype=excluded.subtype,stable_key=excluded.stable_key,"
                "properties_json=excluded.properties_json,last_seen_run_id=excluded.last_seen_run_id",
                node_values,
            )
            connection.executemany(
                "INSERT INTO knowledge_edges(id,repository_id,collection_id,run_id,source_id,target_id,kind,certainty,confidence,confirmed,metadata_json,status,origin,weight,evidence_count) "
                "VALUES(:id,:repository_id,:collection_id,:run_id,:source_id,:target_id,:kind,:certainty,:confidence,:confirmed,:metadata_json,:status,:origin,:weight,:evidence_count) "
                "ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id,kind=excluded.kind,certainty=excluded.certainty,confidence=excluded.confidence,"
                "metadata_json=excluded.metadata_json,status=excluded.status,origin=excluded.origin,weight=excluded.weight,evidence_count=excluded.evidence_count",
                edge_values,
            )
            existing_nodes = [row[0] for row in connection.execute("SELECT id FROM knowledge_nodes WHERE repository_id=?", (repository_id,))]
            existing_edges = [row[0] for row in connection.execute("SELECT id FROM knowledge_edges WHERE repository_id=?", (repository_id,))]
            connection.executemany("DELETE FROM knowledge_nodes WHERE id=?", [(item,) for item in existing_nodes if item not in node_ids])
            connection.executemany("DELETE FROM knowledge_edges WHERE id=?", [(item,) for item in existing_edges if item not in edge_ids])
            connection.execute("DELETE FROM graph_evidence WHERE repository_id=?", (repository_id,))
            if evidence_values:
                connection.executemany(
                    "INSERT INTO graph_evidence(id,edge_id,repository_id,run_id,git_commit,origin,confidence,source_uri,line_start,line_end,extractor,extractor_version,reason,metadata_json) "
                    "VALUES(:id,:edge_id,:repository_id,:run_id,:git_commit,:origin,:confidence,:source_uri,:line_start,:line_end,:extractor,:extractor_version,:reason,:metadata_json)",
                    evidence_values,
                )

    def diff(self, repository_id: str, from_run_id: str, to_run_id: str) -> dict[str, Any]:
        """Compare two immutable graph snapshots by stable node and edge IDs."""
        self.registry.get_repository(repository_id)
        before_nodes = self._snapshot_map("graph_node_snapshots", "node_id", repository_id, from_run_id)
        after_nodes = self._snapshot_map("graph_node_snapshots", "node_id", repository_id, to_run_id)
        before_edges = self._snapshot_map("graph_edge_snapshots", "edge_id", repository_id, from_run_id)
        after_edges = self._snapshot_map("graph_edge_snapshots", "edge_id", repository_id, to_run_id)
        if not before_nodes and not before_edges:
            raise KeyError(f"图谱运行快照不存在：{from_run_id}")
        if not after_nodes and not after_edges:
            raise KeyError(f"图谱运行快照不存在：{to_run_id}")
        node_diff = _snapshot_diff(before_nodes, after_nodes)
        edge_diff = _snapshot_diff(before_edges, after_edges)
        return {
            "repository_id": repository_id,
            "from_run_id": from_run_id,
            "to_run_id": to_run_id,
            "nodes": node_diff,
            "edges": edge_diff,
            "summary": {
                "nodes_added": len(node_diff["added"]),
                "nodes_removed": len(node_diff["removed"]),
                "nodes_changed": len(node_diff["changed"]),
                "edges_added": len(edge_diff["added"]),
                "edges_removed": len(edge_diff["removed"]),
                "edges_changed": len(edge_diff["changed"]),
            },
        }

    def _snapshot_map(
        self, table: str, id_column: str, repository_id: str, run_id: str,
    ) -> dict[str, dict[str, Any]]:
        rows = self.db.all(
            f"SELECT {id_column} AS id,payload_json FROM {table} WHERE repository_id=? AND run_id=?",
            (repository_id, run_id),
        )
        return {row["id"]: json_loads(row["payload_json"], {}) for row in rows}

    @staticmethod
    def _node(
        node_id: str, repository_id: str | None, run_id: str | None, kind: str, name: str,
        *, qualified_name: str | None = None, path: str | None = None,
        line_start: int | None = None, line_end: int | None = None,
        module_id: str | None = None, certainty: str = "compiler",
        metadata: dict[str, Any] | None = None, collection_id: str | None = None,
        layer: str = "code", subtype: str | None = None, stable_key: str | None = None,
        community_id: str | None = None, origin: str = "source",
    ) -> dict[str, Any]:
        properties = {"origin": origin}
        return {
            "id": node_id, "repository_id": repository_id, "collection_id": collection_id,
            "run_id": run_id, "kind": kind, "name": name, "qualified_name": qualified_name,
            "path": path, "line_start": line_start, "line_end": line_end,
            "module_id": module_id, "certainty": certainty, "metadata_json": json_dumps(metadata or {}),
            "layer": layer, "subtype": subtype, "stable_key": stable_key or node_id,
            "community_id": community_id, "properties_json": json_dumps(properties),
            "first_seen_run_id": run_id, "last_seen_run_id": run_id,
        }

    @staticmethod
    def _edge(
        repository_id: str | None, run_id: str | None, source_id: str, target_id: str,
        kind: str, certainty: str, confidence: float, metadata: dict[str, Any] | None = None,
        *, collection_id: str | None = None, confirmed: bool = False,
        status: str | None = None, origin: str | None = None, weight: float = 1.0,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        edge_id = f"edge:{_digest(f'{collection_id}|{repository_id}|{source_id}|{target_id}|{kind}')}"
        resolved_status = status or ("confirmed" if confirmed or certainty not in {"candidate", "lexical", "rejected"} else ("rejected" if certainty == "rejected" else "candidate"))
        resolved_origin = origin or ("compiler" if certainty == "compiler" else "source")
        value = {
            "id": edge_id, "repository_id": repository_id, "collection_id": collection_id,
            "run_id": run_id, "source_id": source_id, "target_id": target_id,
            "kind": kind, "certainty": certainty, "confidence": confidence,
            "confirmed": 1 if resolved_status == "confirmed" else 0, "metadata_json": json_dumps(metadata or {}),
            "status": resolved_status, "origin": resolved_origin, "weight": weight,
            "evidence_count": 1 if evidence else 0,
        }
        value["_evidence"] = [{"origin": resolved_origin, "confidence": confidence, **(evidence or {})}] if evidence else []
        return value

    def _external_node(self, nodes: dict[str, dict[str, Any]], repository_id: str, run_id: str, name: str) -> str:
        node_id = f"external:{repository_id}:{_digest(name)}"
        if node_id not in nodes:
            nodes[node_id] = self._node(node_id, repository_id, run_id, "external", name or "unresolved", certainty="candidate")
        return node_id

    def _resolve_include(
        self, nodes: dict[str, dict[str, Any]], repository_id: str, run_id: str,
        target: str, file_to_module: dict[str, str],
    ) -> str:
        normalised = _normalise(target)
        matches = [path for path in file_to_module if path == normalised or path.endswith("/" + normalised)]
        if matches:
            path = sorted(matches, key=len)[0]
            node_id = f"file:{repository_id}:{path}"
            if node_id not in nodes:
                nodes[node_id] = self._node(
                    node_id, repository_id, run_id, "file", Path(path).name,
                    path=path, module_id=file_to_module.get(path),
                )
            return node_id
        return self._external_node(nodes, repository_id, run_id, target)

    def _scope_repositories(self, scope_type: str, scope_id: str) -> list[str]:
        if scope_type == "repository":
            self.registry.get_repository(scope_id)
            return [scope_id]
        if scope_type == "collection":
            return self.registry.collection_repository_ids(scope_id)
        raise ValueError("scope_type 必须是 repository 或 collection")

    @staticmethod
    def _public_node(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"], "repository_id": row.get("repository_id"), "collection_id": row.get("collection_id"),
            "kind": row["kind"], "name": row["name"], "qualified_name": row.get("qualified_name"),
            "path": row.get("path"), "line_start": row.get("line_start"), "line_end": row.get("line_end"),
            "module_id": row.get("module_id"), "certainty": row.get("certainty"),
            "layer": row.get("layer") or "code", "subtype": row.get("subtype"),
            "stable_key": row.get("stable_key"), "community_id": row.get("community_id"),
            "kind_label": GRAPH_NODE_LABELS.get(str(row.get("kind") or ""), str(row.get("kind") or "未知")),
            "display_name": row.get("name") or row.get("qualified_name") or row["id"],
            "metadata": json_loads(row.get("metadata_json"), {}),
            "properties": json_loads(row.get("properties_json"), {}),
            "metrics": {
                "degree": row.get("degree") or 0, "in_degree": row.get("in_degree") or 0,
                "out_degree": row.get("out_degree") or 0, "betweenness": row.get("betweenness") or 0,
                "pagerank": row.get("pagerank") or 0, "is_hub": bool(row.get("is_hub")),
                "is_bridge": bool(row.get("is_bridge")), "is_orphan": bool(row.get("is_orphan")),
                "god_score": row.get("god_score") or 0, "god_type": row.get("god_type"),
                "community_span": row.get("community_span") or 0,
                "fan_in": row.get("fan_in") or row.get("in_degree") or 0,
                "fan_out": row.get("fan_out") or row.get("out_degree") or 0,
            },
        }

    @staticmethod
    def _public_edge(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"], "source": row["source_id"], "target": row["target_id"],
            "kind": row["kind"], "certainty": row["certainty"], "confidence": row["confidence"],
            "status": row.get("status") or ("confirmed" if row.get("confirmed") else "candidate"),
            "origin": row.get("origin") or "source", "weight": row.get("weight") or 1.0,
            "evidence_count": row.get("evidence_count") or 0,
            "relation_label": GRAPH_RELATION_LABELS.get(str(row.get("kind") or ""), str(row.get("kind") or "相关")),
            "confirmed": bool(row["confirmed"]), "metadata": json_loads(row.get("metadata_json"), {}),
        }

    def _aggregate(self, level: str, node_map: dict[str, dict[str, Any]], edges: list[dict[str, Any]], limit: int) -> dict[str, Any]:
        if level not in {"repository", "module", "file"}:
            raise ValueError("level 必须是 repository、module、file 或 symbol")

        def owner(node: dict[str, Any]) -> str | None:
            repository_id = node.get("repository_id")
            if level == "repository":
                return f"repo:{repository_id}" if repository_id else None
            if level == "module":
                module_id = node.get("module_id")
                if node["kind"] == "module":
                    return node["id"]
                return f"module:{repository_id}:{module_id}" if repository_id and module_id else None
            if node["kind"] == "file":
                return node["id"]
            path = node.get("path")
            return f"file:{repository_id}:{path}" if repository_id and path else None

        aggregate_edges: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        used: set[str] = set()
        for edge in edges:
            source_node = node_map.get(edge["source_id"])
            target_node = node_map.get(edge["target_id"])
            if not source_node or not target_node:
                continue
            source = owner(source_node)
            target = owner(target_node)
            if not source or not target or source == target:
                continue
            key = (source, target, edge["kind"], edge["certainty"])
            if key not in aggregate_edges:
                aggregate_edges[key] = {
                    "id": f"aggregate:{_digest('|'.join(key))}", "source": source, "target": target,
                    "kind": edge["kind"], "relation_label": GRAPH_RELATION_LABELS.get(edge["kind"], edge["kind"]),
                    "certainty": edge["certainty"], "confidence": edge["confidence"],
                    "confirmed": bool(edge["confirmed"]), "count": 0, "metadata": {},
                }
            aggregate_edges[key]["count"] += 1
            used.update((source, target))
        # An overview graph must also contain isolated owners. Otherwise a
        # repository with six modules but only three cross-module relations is
        # rendered as if the other modules did not exist.
        if level == "repository":
            available = {
                f"repo:{node['repository_id']}"
                for node in node_map.values()
                if node.get("repository_id")
            }
        elif level == "module":
            available = {
                node["id"]
                for node in node_map.values()
                if node.get("kind") == "module"
            }
        else:
            available = {
                node["id"]
                for node in node_map.values()
                if node.get("kind") == "file"
            }
        ordered_node_ids = sorted(used) + sorted(available - used)
        public_nodes: list[dict[str, Any]] = []
        for node_id in ordered_node_ids:
            node = node_map.get(node_id)
            if node is None and node_id.startswith("module:"):
                # Aggregated IDs intentionally refer to the corresponding module
                # node, whose stable ID has the same shape. Keep the fallback for
                # historical runs that used a different node ID digest.
                parts = node_id.split(":", 2)
                if len(parts) == 3:
                    node = next(
                        (
                            item for item in node_map.values()
                            if item.get("repository_id") == parts[1]
                            and item.get("kind") == "module"
                            and item.get("module_id") == parts[2]
                        ),
                        None,
                    )
            if node:
                public_nodes.append(node)
            elif node_id.startswith("repo:"):
                repository_id = node_id.split(":", 1)[1]
                repository = self.registry.get_repository(repository_id)
                public_nodes.append({"id": node_id, "repository_id": repository_id, "kind": "repository", "name": repository["name"], "path": repository["path"]})
        edge_values = list(aggregate_edges.values())
        return {
            "nodes": public_nodes[:limit],
            "edges": edge_values[:limit],
            "truncated": len(edge_values) > limit or len(public_nodes) > limit,
            "relation_counts": _relation_counts(edge_values),
        }

    def _community_graph(
        self, repository_ids: list[str], node_map: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]], limit: int,
    ) -> dict[str, Any]:
        communities = self.db.all(
            "SELECT * FROM graph_communities WHERE repository_id IN (" + ",".join("?" for _ in repository_ids) + ")",
            tuple(repository_ids),
        )
        community_map = {row["id"]: row for row in communities}
        aggregate: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for edge in edges:
            source_node = node_map.get(edge["source_id"])
            target_node = node_map.get(edge["target_id"])
            if not source_node or not target_node:
                continue
            source = source_node.get("community_id")
            target = target_node.get("community_id")
            if not source or not target or source == target:
                continue
            key = (source, target, edge["kind"], edge.get("status") or "confirmed")
            item = aggregate.setdefault(key, {
                "id": f"community-edge:{_digest('|'.join(key))}", "source": source, "target": target,
                "kind": edge["kind"], "relation_label": GRAPH_RELATION_LABELS.get(edge["kind"], edge["kind"]),
                "certainty": edge["certainty"], "status": edge.get("status") or "confirmed",
                "origin": edge.get("origin") or "source", "confidence": edge["confidence"],
                "confirmed": (edge.get("status") or "confirmed") == "confirmed", "count": 0, "metadata": {},
            })
            item["count"] += 1
        public_nodes = [{
            "id": row["id"], "repository_id": row["repository_id"], "kind": "community",
            "layer": "code", "subtype": "community", "name": row["name"], "display_name": row["name"],
            "community_id": row["id"], "color": row["color"], "member_count": row["member_count"],
            "cohesion": row["cohesion"], "metadata": json_loads(row.get("metadata_json"), {}),
            "metrics": {"degree": 0, "is_hub": False, "is_bridge": False, "is_orphan": False},
        } for row in community_map.values()]
        edge_values = list(aggregate.values())
        return {
            "nodes": public_nodes[:limit], "edges": edge_values[:limit],
            "truncated": len(public_nodes) > limit or len(edge_values) > limit,
            "relation_counts": _relation_counts(edge_values),
            "diagnostics": self.diagnostics(repository_ids[0]) if len(repository_ids) == 1 else {},
        }

    def _coremap_graph(
        self, repository_ids: list[str], node_map: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]], limit: int,
    ) -> dict[str, Any]:
        """Return a bounded radial-style projection around God Nodes.

        The database remains the source of truth; this projection only limits
        the first render to the most connected, cross-community symbols and
        their confirmed one-hop relationships.
        """
        hub_nodes = [
            node for node in node_map.values()
            if node.get("kind") in {"symbol", "external"}
            and node.get("metrics", {}).get("is_hub")
        ]
        hub_nodes.sort(
            key=lambda node: (
                -float(node.get("metrics", {}).get("god_score") or 0),
                -float(node.get("metrics", {}).get("degree") or 0),
                str(node.get("display_name") or node.get("id")),
            )
        )
        # A sparse or partially analysed repository may have no node above the
        # strict threshold.  Showing the strongest confirmed symbols still
        # gives the user a useful, honest focus view.
        if not hub_nodes:
            hub_nodes = sorted(
                [
                    node for node in node_map.values()
                    if node.get("kind") in {"symbol", "external"}
                    and float(node.get("metrics", {}).get("degree") or 0) > 0
                ],
                key=lambda node: -float(node.get("metrics", {}).get("degree") or 0),
            )[:8]
        hub_nodes = hub_nodes[: min(8, max(1, limit // 10))]
        selected_order = [node["id"] for node in hub_nodes]
        selected = set(selected_order)
        confirmed_edges = [edge for edge in edges if (edge.get("status") or "confirmed") == "confirmed"]
        by_hub: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in confirmed_edges:
            if edge["source_id"] in selected or edge["target_id"] in selected:
                hub_id = edge["source_id"] if edge["source_id"] in selected else edge["target_id"]
                by_hub[hub_id].append(edge)
        for hub_id, related in by_hub.items():
            related.sort(key=lambda edge: (-float(edge.get("weight") or 1), str(edge.get("id"))))
            for edge in related[:18]:
                for node_id in (edge["source_id"], edge["target_id"]):
                    if node_id not in selected:
                        selected.add(node_id)
                        selected_order.append(node_id)
        selected = set(selected_order[:limit])
        public_edges = [
            self._public_edge(edge) for edge in confirmed_edges
            if edge["source_id"] in selected and edge["target_id"] in selected
        ]
        public_edges.sort(key=lambda edge: (-float(edge.get("weight") or 1), edge["id"]))
        public_nodes = [node_map[node_id] for node_id in selected if node_id in node_map]
        public_nodes.sort(
            key=lambda node: (
                not bool(node.get("metrics", {}).get("is_hub")),
                -float(node.get("metrics", {}).get("god_score") or 0),
                str(node.get("display_name") or node.get("id")),
            )
        )
        return {
            "nodes": public_nodes[:limit],
            "edges": public_edges[: max(limit * 3, limit)],
            "truncated": len(selected) > limit or len(public_edges) > max(limit * 3, limit),
            "relation_counts": _relation_counts(public_edges),
            "focus": "god_nodes", "available": bool(public_edges),
            "message": None if public_edges else "当前没有编译器确认的代码关系，无法生成核心星图。",
        }

    def _surprise_graph(
        self, repository_ids: list[str], node_map: dict[str, dict[str, Any]], limit: int,
    ) -> dict[str, Any]:
        """Project persisted surprising-connection insights as graph edges."""
        rows: list[dict[str, Any]] = []
        for repository_id in repository_ids:
            rows.extend(self.insights(repository_id, "surprising_connection", min(limit, 200)))
        rows.sort(key=lambda row: (-float(row.get("score") or 0), str(row.get("id"))))
        rows = rows[:limit]
        selected: set[str] = set()
        public_edges: list[dict[str, Any]] = []
        for row in rows:
            source_id, target_id = row.get("source_id"), row.get("target_id")
            if not source_id or not target_id:
                continue
            source = row.get("source") or node_map.get(source_id)
            target = row.get("target") or node_map.get(target_id)
            if not source or not target:
                continue
            node_map.setdefault(source_id, source)
            node_map.setdefault(target_id, target)
            selected.update((source_id, target_id))
            public_edges.append({
                "id": row["id"], "source": source_id, "target": target_id,
                "kind": "SURPRISING_CONNECTION", "relation_label": "惊喜链接",
                "certainty": "analytics", "confidence": float(row.get("score") or 0),
                "status": "confirmed", "origin": "analytics", "weight": row.get("score") or 0,
                "evidence_count": len(row.get("evidence") or []), "confirmed": True,
                "metadata": {"insight": row.get("reason") or {}, "path": row.get("path") or [], "evidence": row.get("evidence") or []},
                "insight_kind": row.get("kind"), "score": row.get("score") or 0,
            })
        public_nodes = [node_map[node_id] for node_id in selected if node_id in node_map]
        return {
            "nodes": public_nodes, "edges": public_edges, "truncated": len(public_edges) >= limit,
            "relation_counts": _relation_counts(public_edges), "focus": "surprising_connections",
        }

    def analyze_repository(self, repository_id: str) -> dict[str, Any]:
        repository = self.registry.get_repository(repository_id)
        return self.analytics.analyze(repository_id, repository.get("active_run_id"))

    def communities(self, repository_id: str) -> list[dict[str, Any]]:
        self.registry.get_repository(repository_id)
        return [
            {**row, "metadata": json_loads(row.get("metadata_json"), {})}
            for row in self.analytics.communities(repository_id)
        ]

    def ranked_nodes(self, repository_id: str, category: str, limit: int = 30) -> list[dict[str, Any]]:
        self.registry.get_repository(repository_id)
        return [self._public_node(row) for row in self.analytics.ranked_nodes(repository_id, category, limit)]

    def node_detail(self, node_id: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT n.*,m.degree,m.in_degree,m.out_degree,m.betweenness,m.pagerank,m.is_hub,m.is_bridge,m.is_orphan,"
            "m.god_score,m.god_type,m.community_span,m.fan_in,m.fan_out "
            "FROM knowledge_nodes n LEFT JOIN graph_metrics m ON m.node_id=n.id AND (m.run_id=n.run_id OR m.run_id IS NULL) WHERE n.id=?",
            (node_id,),
        )
        if not row:
            raise KeyError("图谱节点不存在")
        edge_rows = self.db.all(
            "SELECT * FROM knowledge_edges WHERE source_id=? OR target_id=? ORDER BY status,kind LIMIT 300",
            (node_id, node_id),
        )
        edge_ids = [edge["id"] for edge in edge_rows]
        evidence: list[dict[str, Any]] = []
        if edge_ids:
            placeholders = ",".join("?" for _ in edge_ids)
            evidence = self.db.all(
                f"SELECT * FROM graph_evidence WHERE edge_id IN ({placeholders}) ORDER BY source_uri,line_start",
                tuple(edge_ids),
            )
        by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in evidence:
            item["metadata"] = json_loads(item.pop("metadata_json", None), {})
            by_edge[item["edge_id"]].append(item)
        public_edges = []
        for edge in edge_rows:
            value = self._public_edge(edge)
            value["evidence"] = by_edge.get(edge["id"], [])
            public_edges.append(value)
        return {"node": self._public_node(row), "edges": public_edges}

    def edge_detail(self, edge_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM knowledge_edges WHERE id=?", (edge_id,))
        if not row:
            raise KeyError("图谱关系不存在")
        evidence = self.db.all(
            "SELECT * FROM graph_evidence WHERE edge_id=? ORDER BY source_uri,line_start,line_end",
            (edge_id,),
        )
        for item in evidence:
            item["metadata"] = json_loads(item.pop("metadata_json", None), {})
        nodes = self._nodes_by_ids([row["source_id"], row["target_id"]])
        node_map = {item["id"]: self._public_node(item) for item in nodes}
        return {
            "edge": self._public_edge(row),
            "source_node": node_map.get(row["source_id"]),
            "target_node": node_map.get(row["target_id"]),
            "evidence": evidence,
        }

    def snapshot_runs(self, repository_id: str) -> list[dict[str, Any]]:
        self.registry.get_repository(repository_id)
        return self.db.all(
            "SELECT r.id,r.created_at,r.git_commit,"
            "(SELECT COUNT(*) FROM graph_node_snapshots ns WHERE ns.run_id=r.id) AS node_count,"
            "(SELECT COUNT(*) FROM graph_edge_snapshots es WHERE es.run_id=r.id) AS edge_count "
            "FROM runs r WHERE r.repository_id=? AND ("
            "EXISTS(SELECT 1 FROM graph_node_snapshots ns WHERE ns.run_id=r.id) OR "
            "EXISTS(SELECT 1 FROM graph_edge_snapshots es WHERE es.run_id=r.id)) "
            "ORDER BY r.created_at DESC",
            (repository_id,),
        )

    def diagnostics(self, repository_id: str) -> dict[str, Any]:
        repository = self.registry.get_repository(repository_id)
        run_id = repository.get("active_run_id")
        repo_node = self.db.one("SELECT * FROM knowledge_nodes WHERE id=?", (f"repo:{repository_id}",))
        metadata = json_loads(repo_node.get("metadata_json") if repo_node else None, {})
        counts = self.db.all(
            "SELECT status,origin,kind,COUNT(*) AS count FROM knowledge_edges WHERE repository_id=? GROUP BY status,origin,kind",
            (repository_id,),
        )
        confirmed_calls = sum(int(row["count"]) for row in counts if row["kind"] == "CALLS" and row["status"] == "confirmed")
        candidate_calls = sum(int(row["count"]) for row in counts if row["kind"] == "POSSIBLE_CALL" or row["status"] == "candidate")
        mode = str(metadata.get("analysis_mode") or "unknown")
        warnings: list[str] = []
        if mode != "full":
            warnings.append("当前为部分分析：词法候选关系不能作为确定调用链。")
        if confirmed_calls == 0:
            warnings.append("没有编译器确认的 CALLS，请检查分析器和编译数据库覆盖。")
        coverage = metadata.get("coverage") if isinstance(metadata.get("coverage"), dict) else {}
        return {
            "repository_id": repository_id, "run_id": run_id, "analysis_mode": mode,
            "coverage": coverage, "confirmed_calls": confirmed_calls, "candidate_relations": candidate_calls,
            "relation_breakdown": counts, "warnings": warnings,
            "compiler_grade": mode == "full" and confirmed_calls > 0,
        }

    def cycles(self, repository_id: str, limit: int = 30) -> list[dict[str, Any]]:
        import networkx as nx
        rows = self.db.all(
            "SELECT source_id,target_id,kind FROM knowledge_edges WHERE repository_id=? AND status='confirmed' "
            "AND kind IN ('CALLS','DEPENDS_ON','INCLUDES','REGISTER_CALLBACK','INVOKES_CALLBACK')",
            (repository_id,),
        )
        graph = nx.DiGraph((row["source_id"], row["target_id"]) for row in rows)
        result = []
        for group in nx.strongly_connected_components(graph):
            if len(group) <= 1:
                continue
            nodes = self._nodes_by_ids(sorted(group))
            result.append({"size": len(group), "nodes": [self._public_node(node) for node in nodes]})
            if len(result) >= limit:
                break
        return sorted(result, key=lambda item: -item["size"])

    def insights(self, repository_id: str, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self.registry.get_repository(repository_id)
        rows = self.analytics.insights(repository_id, kind=kind, limit=limit)
        node_ids = [item for row in rows for item in (row.get("source_id"), row.get("target_id")) if item]
        nodes = {node["id"]: self._public_node(node) for node in self._nodes_by_ids(list(dict.fromkeys(node_ids)))}
        for row in rows:
            row["source"] = nodes.get(row.get("source_id"))
            row["target"] = nodes.get(row.get("target_id"))
        return rows

    def export_graphml(self, scope_type: str, scope_id: str, level: str = "symbol") -> str:
        from xml.sax.saxutils import escape
        payload = self.graph(scope_type, scope_id, level, limit=100000, statuses=["confirmed", "candidate"])
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
            '<key id="label" for="all" attr.name="label" attr.type="string"/>',
            '<key id="kind" for="all" attr.name="kind" attr.type="string"/>',
            '<key id="status" for="edge" attr.name="status" attr.type="string"/>',
            '<graph id="ClangWiki" edgedefault="directed">',
        ]
        for node in payload["nodes"]:
            lines.append(f'<node id="{escape(str(node["id"]))}"><data key="label">{escape(str(node.get("display_name") or node["id"]))}</data><data key="kind">{escape(str(node.get("subtype") or node.get("kind")))}</data></node>')
        for edge in payload["edges"]:
            lines.append(f'<edge id="{escape(str(edge["id"]))}" source="{escape(str(edge["source"]))}" target="{escape(str(edge["target"]))}"><data key="kind">{escape(str(edge["kind"]))}</data><data key="status">{escape(str(edge.get("status") or "confirmed"))}</data></edge>')
        lines.extend(["</graph>", "</graphml>"])
        return "\n".join(lines)

    def _nodes_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in ids)
        rows = self.db.all(f"SELECT * FROM knowledge_nodes WHERE id IN ({placeholders})", tuple(ids))
        by_id = {row["id"]: row for row in rows}
        return [by_id[item] for item in ids if item in by_id]


def _read_list(path: Path) -> list[dict[str, Any]]:
    try:
        value = read_json(path)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = read_json(path)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _merge_edge(edges: dict[str, dict[str, Any]], edge: dict[str, Any]) -> None:
    existing = edges.get(edge["id"])
    if existing is None:
        edges[edge["id"]] = edge
        return
    existing.setdefault("_evidence", []).extend(edge.get("_evidence", []))
    existing["evidence_count"] = len(existing["_evidence"])
    existing["weight"] = float(existing.get("weight") or 1.0) + float(edge.get("weight") or 1.0)
    existing["confidence"] = max(float(existing.get("confidence") or 0), float(edge.get("confidence") or 0))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _snapshot_diff(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]],
) -> dict[str, list[Any]]:
    before_ids = set(before)
    after_ids = set(after)
    changed = []
    for item_id in sorted(before_ids & after_ids):
        left = {key: value for key, value in before[item_id].items() if key not in {"run_id", "last_seen_run_id"}}
        right = {key: value for key, value in after[item_id].items() if key not in {"run_id", "last_seen_run_id"}}
        if left != right:
            changed.append({"id": item_id, "before": before[item_id], "after": after[item_id]})
    return {
        "added": [after[item_id] for item_id in sorted(after_ids - before_ids)],
        "removed": [before[item_id] for item_id in sorted(before_ids - after_ids)],
        "changed": changed,
    }


def _normalise(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")


def _repository_relative(value: str, repository_root: Path) -> str:
    if not value:
        return ""
    candidate = Path(value)
    try:
        if candidate.is_absolute():
            return _normalise(str(candidate.resolve().relative_to(repository_root.resolve())))
    except (OSError, ValueError):
        return ""
    return _normalise(value)


def _cmake_target_name(command: dict[str, Any]) -> str | None:
    text = " ".join(str(item) for item in command.get("arguments") or [])
    text += " " + str(command.get("command") or "")
    text += " " + str(command.get("output") or "")
    match = re.search(r"CMakeFiles[/\\]([^/\\]+?)\.dir(?:[/\\]|\s|$)", text)
    return match.group(1) if match else None


def _closest_module(path: str, modules: list[dict[str, Any]]) -> str | None:
    candidates = []
    for module in modules:
        source = _normalise(str(module.get("source_path") or ""))
        if source and (path == source or path.startswith(source + "/")):
            candidates.append((len(source), str(module.get("module_id"))))
    return max(candidates, default=(0, None))[1]


def _best_symbol(candidates: list[str], symbol_file: dict[str, str], file_path: str) -> str | None:
    if not candidates:
        return None
    for candidate in candidates:
        if symbol_file.get(candidate) == file_path:
            return candidate
    return candidates[0]


def _relation_counts(edges: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for edge in edges:
        kind = str(edge.get("kind") or "RELATED_TO")
        counts[kind] += 1
    return dict(sorted(counts.items()))


def _projected_neighbors(
    node_id: str,
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    depth: int,
    limit: int,
) -> dict[str, Any]:
    depth = max(1, min(3, depth))
    seen = {node_id}
    frontier = {node_id}
    selected_edges: dict[str, dict[str, Any]] = {}
    for _ in range(depth):
        if not frontier or len(seen) >= limit:
            break
        next_frontier: set[str] = set()
        for edge in edges:
            if edge["source"] not in frontier and edge["target"] not in frontier:
                continue
            selected_edges[edge["id"]] = edge
            for endpoint in (edge["source"], edge["target"]):
                if endpoint not in seen:
                    next_frontier.add(endpoint)
        seen.update(next_frontier)
        frontier = next_frontier
    public_edges = list(selected_edges.values())
    return {
        "center": nodes[node_id],
        "nodes": [nodes[item] for item in seen if item in nodes],
        "edges": public_edges,
        "depth": depth,
        "relation_counts": _relation_counts(public_edges),
        "truncated": len(seen) >= limit,
    }
