from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from .database import Database, json_dumps, json_loads
from .io import read_json
from .registry import Registry


GRAPH_KINDS = {
    "CONTAINS", "DEPENDS_ON", "INCLUDES", "CALLS", "POSSIBLE_CALL",
    "REFERENCES", "DEFINES", "DOCUMENTS", "RELATED_TO",
}

GRAPH_RELATION_LABELS = {
    "CONTAINS": "包含",
    "DEPENDS_ON": "依赖",
    "INCLUDES": "包含头文件",
    "CALLS": "调用",
    "POSSIBLE_CALL": "可能调用",
    "REFERENCES": "引用",
    "DEFINES": "定义",
    "DOCUMENTS": "文档对应",
    "RELATED_TO": "相关",
}

GRAPH_NODE_LABELS = {
    "repository": "仓库",
    "module": "模块",
    "file": "文件",
    "symbol": "符号",
    "external": "外部符号",
}


class GraphService:
    def __init__(self, database: Database, registry: Registry) -> None:
        self.db = database
        self.registry = registry

    def ingest_repository(self, repository_id: str, run_id: str, run_root: Path) -> dict[str, int]:
        repository = self.registry.get_repository(repository_id)
        knowledge = run_root / "knowledge"
        modules = _read_list(knowledge / "modules.json")
        symbols = _read_list(knowledge / "symbols.json")
        relations = _read_list(knowledge / "relations.json")

        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        repo_node = f"repo:{repository_id}"
        nodes[repo_node] = self._node(repo_node, repository_id, run_id, "repository", repository["name"], path=repository["path"])

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

        symbols_by_name: dict[str, list[str]] = defaultdict(list)
        symbol_file: dict[str, str] = {}
        for symbol in symbols:
            name = str(symbol.get("qualified_name") or symbol.get("name") or "")
            if not name:
                continue
            path = _normalise(str(symbol.get("file_path") or ""))
            line = int(symbol.get("line_start") or 0)
            node_id = f"symbol:{repository_id}:{_digest(f'{name}|{path}|{line}')}"
            module_id = file_to_module.get(path) or _closest_module(path, modules)
            certainty = str(symbol.get("certainty") or "compiler")
            nodes[node_id] = self._node(
                node_id, repository_id, run_id, "symbol", str(symbol.get("name") or name),
                qualified_name=name, path=path, line_start=line,
                line_end=int(symbol.get("line_end") or line), module_id=module_id,
                certainty=certainty, metadata=symbol,
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
            metadata = {
                "file_path": file_path,
                "line": relation.get("line"),
                "raw_source": source_name,
                "raw_target": target_name,
            }
            edge = self._edge(repository_id, run_id, source_id, target_id, kind, certainty, confidence, metadata)
            edges[edge["id"]] = edge

        self._replace_repository_graph(repository_id, run_id, nodes.values(), edges.values())
        return {"nodes": len(nodes), "edges": len(edges)}

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
                        None, None, left["id"], right["id"], "RELATED_TO", certainty,
                        confidence, {"symbol": name, "match": "signature" if exact else "name"},
                        collection_id=collection_id, confirmed=exact,
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
                "INSERT INTO knowledge_edges(id,repository_id,collection_id,run_id,source_id,target_id,kind,certainty,confidence,confirmed,metadata_json) "
                "VALUES(:id,:repository_id,:collection_id,:run_id,:source_id,:target_id,:kind,:certainty,:confidence,:confirmed,:metadata_json)",
                values,
            )
        return {"edges": len(values), "confirmed": confirmed, "candidates": candidates}

    def set_edge_confirmation(self, edge_id: str, confirmed: bool) -> dict[str, Any]:
        edge = self.db.one("SELECT * FROM knowledge_edges WHERE id=?", (edge_id,))
        if not edge:
            raise KeyError("关系不存在")
        certainty = "user-confirmed" if confirmed else "rejected"
        self.db.execute(
            "UPDATE knowledge_edges SET confirmed=?, certainty=? WHERE id=?",
            (1 if confirmed else 0, certainty, edge_id),
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
    ) -> dict[str, Any]:
        repository_ids = self._scope_repositories(scope_type, scope_id)
        if not repository_ids:
            return {"nodes": [], "edges": [], "truncated": False, "relation_counts": {}}
        placeholders = ",".join("?" for _ in repository_ids)
        nodes = self.db.all(
            f"SELECT * FROM knowledge_nodes WHERE repository_id IN ({placeholders})",
            tuple(repository_ids),
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
        if level in {"repository", "module", "file"}:
            # Structural containment/definition edges collapse to self-edges at
            # aggregate levels and can consume the SQL limit before any actual
            # dependency or call edge is read.
            conditions.append("kind NOT IN ('CONTAINS','DEFINES','DOCUMENTS')")
        edges = self.db.all(
            "SELECT * FROM knowledge_edges WHERE " + " AND ".join(conditions) + " LIMIT ?",
            tuple(parameters + [max(limit * 5, limit)]),
        )
        if level == "symbol":
            public_edges = [self._public_edge(edge) for edge in edges if edge["source_id"] in node_map and edge["target_id"] in node_map]
            used = {item[key] for item in public_edges for key in ("source", "target")}
            public_nodes = [node_map[item] for item in used][:limit]
            return {
                "nodes": public_nodes,
                "edges": public_edges[:limit],
                "truncated": len(public_edges) > limit,
                "relation_counts": _relation_counts(public_edges),
            }
        return self._aggregate(level, node_map, edges, limit)

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
            rows = self.db.all(
                f"SELECT * FROM knowledge_edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders}) LIMIT ?",
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

    def shortest_path(self, source_id: str, target_id: str, max_depth: int = 8) -> dict[str, Any]:
        queue: deque[tuple[str, list[str], list[str]]] = deque([(source_id, [source_id], [])])
        seen = {source_id}
        while queue:
            current, nodes, edges = queue.popleft()
            if len(edges) >= max_depth:
                continue
            rows = self.db.all(
                "SELECT * FROM knowledge_edges WHERE source_id=? OR target_id=? LIMIT 2000",
                (current, current),
            )
            for row in rows:
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
        node_ids = {item["id"] for item in node_values}
        edge_ids = {item["id"] for item in edge_values}
        with self.db.transaction() as connection:
            connection.executemany(
                "INSERT INTO knowledge_nodes(id,repository_id,collection_id,run_id,kind,name,qualified_name,path,line_start,line_end,module_id,certainty,metadata_json) "
                "VALUES(:id,:repository_id,:collection_id,:run_id,:kind,:name,:qualified_name,:path,:line_start,:line_end,:module_id,:certainty,:metadata_json) "
                "ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id,kind=excluded.kind,name=excluded.name,qualified_name=excluded.qualified_name,"
                "path=excluded.path,line_start=excluded.line_start,line_end=excluded.line_end,module_id=excluded.module_id,certainty=excluded.certainty,metadata_json=excluded.metadata_json",
                node_values,
            )
            connection.executemany(
                "INSERT INTO knowledge_edges(id,repository_id,collection_id,run_id,source_id,target_id,kind,certainty,confidence,confirmed,metadata_json) "
                "VALUES(:id,:repository_id,:collection_id,:run_id,:source_id,:target_id,:kind,:certainty,:confidence,:confirmed,:metadata_json) "
                "ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id,kind=excluded.kind,certainty=excluded.certainty,confidence=excluded.confidence,metadata_json=excluded.metadata_json",
                edge_values,
            )
            existing_nodes = [row[0] for row in connection.execute("SELECT id FROM knowledge_nodes WHERE repository_id=?", (repository_id,))]
            existing_edges = [row[0] for row in connection.execute("SELECT id FROM knowledge_edges WHERE repository_id=?", (repository_id,))]
            connection.executemany("DELETE FROM knowledge_nodes WHERE id=?", [(item,) for item in existing_nodes if item not in node_ids])
            connection.executemany("DELETE FROM knowledge_edges WHERE id=?", [(item,) for item in existing_edges if item not in edge_ids])

    @staticmethod
    def _node(
        node_id: str, repository_id: str | None, run_id: str | None, kind: str, name: str,
        *, qualified_name: str | None = None, path: str | None = None,
        line_start: int | None = None, line_end: int | None = None,
        module_id: str | None = None, certainty: str = "compiler",
        metadata: dict[str, Any] | None = None, collection_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": node_id, "repository_id": repository_id, "collection_id": collection_id,
            "run_id": run_id, "kind": kind, "name": name, "qualified_name": qualified_name,
            "path": path, "line_start": line_start, "line_end": line_end,
            "module_id": module_id, "certainty": certainty, "metadata_json": json_dumps(metadata or {}),
        }

    @staticmethod
    def _edge(
        repository_id: str | None, run_id: str | None, source_id: str, target_id: str,
        kind: str, certainty: str, confidence: float, metadata: dict[str, Any] | None = None,
        *, collection_id: str | None = None, confirmed: bool = False,
    ) -> dict[str, Any]:
        edge_id = f"edge:{_digest(f'{collection_id}|{repository_id}|{source_id}|{target_id}|{kind}')}"
        return {
            "id": edge_id, "repository_id": repository_id, "collection_id": collection_id,
            "run_id": run_id, "source_id": source_id, "target_id": target_id,
            "kind": kind, "certainty": certainty, "confidence": confidence,
            "confirmed": 1 if confirmed else 0, "metadata_json": json_dumps(metadata or {}),
        }

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
            "kind_label": GRAPH_NODE_LABELS.get(str(row.get("kind") or ""), str(row.get("kind") or "未知")),
            "display_name": row.get("name") or row.get("qualified_name") or row["id"],
            "metadata": json_loads(row.get("metadata_json"), {}),
        }

    @staticmethod
    def _public_edge(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"], "source": row["source_id"], "target": row["target_id"],
            "kind": row["kind"], "certainty": row["certainty"], "confidence": row["confidence"],
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


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _normalise(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")


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
