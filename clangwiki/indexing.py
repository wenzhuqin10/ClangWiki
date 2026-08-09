from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .database import Database, json_dumps, json_loads
from .registry import Registry


EMBEDDING_PROFILES = {
    "balanced": {
        "model": "intfloat/multilingual-e5-small",
        "dimension": 384,
        "max_length": 512,
        "description": "平衡档：中英文语义检索，适合普通 CPU。",
    },
    "quality": {
        "model": "intfloat/multilingual-e5-large",
        "dimension": 1024,
        "max_length": 512,
        "description": "高质量档：更高召回质量与资源占用。",
    },
}

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
IDENTIFIER_RE = re.compile(r"[A-Za-z_]\w*(?:::\w+)*")


@dataclass(frozen=True)
class ChunkRecord:
    id: str
    repository_id: str | None
    collection_id: str | None
    document_id: str | None
    node_id: str | None
    kind: str
    title: str
    content: str
    source_uri: str
    content_hash: str
    vector_key: int
    metadata: dict[str, Any]

    def db_values(self, now: float) -> tuple[Any, ...]:
        return (
            self.id, self.repository_id, self.collection_id, self.document_id, self.node_id,
            self.kind, self.title, self.content, self.source_uri, self.content_hash,
            self.vector_key, json_dumps(self.metadata), now,
        )


class IndexService:
    def __init__(self, database: Database, registry: Registry) -> None:
        self.db = database
        self.registry = registry

    def index_repository(self, repository_id: str, profile: str | None = None) -> dict[str, Any]:
        repository = self.registry.get_repository(repository_id)
        profile_name = profile or str(repository["config"].get("embedding_profile") or "balanced")
        if profile_name not in EMBEDDING_PROFILES:
            raise ValueError(f"未知 Embedding 配置档：{profile_name}")
        chunks = list(self._repository_chunks(repository))
        return self._store_and_embed("repository", repository_id, chunks, profile_name)

    def index_collection(self, collection_id: str, profile: str = "balanced") -> dict[str, Any]:
        self.registry.get_collection(collection_id)
        chunks = list(self._collection_chunks(collection_id))
        return self._store_and_embed("collection", collection_id, chunks, profile)

    def search(
        self,
        query: str,
        scope_type: str,
        scope_id: str,
        limit: int = 12,
        kinds: list[str] | None = None,
        module_id: str | None = None,
    ) -> dict[str, Any]:
        value = query.strip()
        if not value:
            raise ValueError("查询内容不能为空。")
        limit = max(1, min(100, limit))
        repository_ids, collection_ids = self._scope_ids(scope_type, scope_id)
        channel_hits: dict[str, list[str]] = {
            "symbol": self._symbol_search(value, repository_ids, limit * 3),
            "keyword": self._fts_search(value, repository_ids, collection_ids, limit * 3),
            "vector": [],
            "graph": [],
        }
        warnings: list[str] = []
        vector_hits, vector_warning = self._vector_search(value, scope_type, scope_id, repository_ids, limit * 3)
        channel_hits["vector"] = vector_hits
        if vector_warning:
            warnings.append(vector_warning)
        channel_hits["graph"] = self._graph_expand(channel_hits["symbol"] + channel_hits["keyword"][:5], limit * 3)

        scores: dict[str, float] = {}
        matched_channels: dict[str, list[str]] = {}
        for channel, ids in channel_hits.items():
            for rank, chunk_id in enumerate(ids, start=1):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (60 + rank)
                matched_channels.setdefault(chunk_id, []).append(channel)
        rows = self._chunks_by_ids(list(scores))
        exact_identifiers = {item.casefold() for item in IDENTIFIER_RE.findall(value)}
        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            if kinds and row["kind"] not in kinds:
                continue
            metadata = json_loads(row.get("metadata_json"), {})
            if module_id and metadata.get("module_id") != module_id:
                continue
            score = scores.get(row["id"], 0.0)
            searchable = f"{row['title']} {row['content']}".casefold()
            if exact_identifiers and any(item in searchable for item in exact_identifiers):
                score += 0.025
            if metadata.get("certainty") == "compiler":
                score += 0.01
            if row["kind"] in {"manual", "annotation"}:
                score += 0.005
            public = self._public_chunk(row)
            public["score"] = round(score, 8)
            public["channels"] = sorted(set(matched_channels.get(row["id"], [])))
            ranked.append((score, public))
        ranked.sort(key=lambda item: (-item[0], item[1]["title"]))
        return {
            "query": value,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "results": [item[1] for item in ranked[:limit]],
            "warnings": warnings,
            "channels": {key: len(value) for key, value in channel_hits.items()},
        }

    def status(self, scope_type: str, scope_id: str) -> dict[str, Any]:
        if scope_type == "repository":
            manifest = self.registry.repository_root(scope_id) / "index" / "index-manifest.json"
            count = self.db.one("SELECT COUNT(*) AS value FROM chunks WHERE repository_id=?", (scope_id,))
        else:
            manifest = self.registry.collection_root(scope_id) / "index" / "index-manifest.json"
            count = self.db.one("SELECT COUNT(*) AS value FROM chunks WHERE collection_id=?", (scope_id,))
        return {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "chunks": int((count or {}).get("value") or 0),
            "manifest": _safe_json(manifest, {}),
        }

    def _repository_chunks(self, repository: dict[str, Any]) -> Iterator[ChunkRecord]:
        repository_id = repository["id"]
        active_run_id = repository.get("active_run_id")
        if active_run_id:
            documents = self.db.all(
                "SELECT * FROM documents WHERE repository_id=? AND (run_id=? OR kind='manual')",
                (repository_id, active_run_id),
            )
        else:
            # Manual pages remain useful before the first generated snapshot.
            documents = self.db.all(
                "SELECT * FROM documents WHERE repository_id=? AND kind='manual'",
                (repository_id,),
            )
        for document in documents:
            yield from _document_chunks(document)
        for annotation in self.db.all(
            "SELECT a.*,d.repository_id,d.collection_id FROM annotations a LEFT JOIN documents d ON d.id=a.document_id "
            "WHERE d.repository_id=? OR a.node_id IN (SELECT id FROM knowledge_nodes WHERE repository_id=?)",
            (repository_id, repository_id),
        ):
            yield _annotation_chunk(annotation, repository_id, None)

        if not active_run_id:
            return
        root = Path(repository["path"])
        nodes = self.db.all(
            "SELECT * FROM knowledge_nodes WHERE repository_id=? AND run_id=? AND kind='symbol'",
            (repository_id, active_run_id),
        )
        for node in nodes:
            yield self._symbol_chunk(node, root)
        for edge in self.db.all(
            "SELECT e.*,s.name AS source_name,t.name AS target_name FROM knowledge_edges e "
            "LEFT JOIN knowledge_nodes s ON s.id=e.source_id LEFT JOIN knowledge_nodes t ON t.id=e.target_id "
            "WHERE e.repository_id=? AND e.run_id=? AND e.kind IN ('CALLS','POSSIBLE_CALL','REFERENCES','INCLUDES')",
            (repository_id, active_run_id),
        ):
            yield _edge_chunk(edge, repository_id, None)

    def _collection_chunks(self, collection_id: str) -> Iterator[ChunkRecord]:
        for document in self.db.all("SELECT * FROM documents WHERE collection_id=?", (collection_id,)):
            yield from _document_chunks(document)
        for annotation in self.db.all(
            "SELECT a.*,d.repository_id,d.collection_id FROM annotations a JOIN documents d ON d.id=a.document_id WHERE d.collection_id=?",
            (collection_id,),
        ):
            yield _annotation_chunk(annotation, None, collection_id)
        for edge in self.db.all(
            "SELECT e.*,s.name AS source_name,t.name AS target_name FROM knowledge_edges e "
            "LEFT JOIN knowledge_nodes s ON s.id=e.source_id LEFT JOIN knowledge_nodes t ON t.id=e.target_id "
            "WHERE e.collection_id=? AND e.certainty<>'rejected'",
            (collection_id,),
        ):
            yield _edge_chunk(edge, None, collection_id)

    def _symbol_chunk(self, node: dict[str, Any], root: Path) -> ChunkRecord:
        metadata = json_loads(node.get("metadata_json"), {})
        relative = str(node.get("path") or "")
        source = ""
        target = (root / relative).resolve()
        if root.resolve() in target.parents and target.is_file():
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(1, int(node.get("line_start") or 1))
            end = min(len(lines), int(node.get("line_end") or start), start + 399)
            source = "\n".join(lines[start - 1:end])
        calls = self.db.all(
            "SELECT t.name,e.kind FROM knowledge_edges e JOIN knowledge_nodes t ON t.id=e.target_id WHERE e.source_id=? LIMIT 100",
            (node["id"],),
        )
        called = ", ".join(f"{item['name']} ({item['kind']})" for item in calls)
        name = str(node.get("qualified_name") or node["name"])
        content = (
            f"Symbol: {name}\nKind: {metadata.get('kind', 'symbol')}\nModule: {node.get('module_id') or 'unknown'}\n"
            f"Defined at: {relative}:{node.get('line_start') or 1}\nCertainty: {node.get('certainty')}\n"
            f"Calls/relations: {called or 'none'}\nSignature: {metadata.get('signature') or ''}\nSource:\n{source}"
        )
        source_uri = f"code://{node['repository_id']}/{relative}:{node.get('line_start') or 1}"
        return _chunk(node["repository_id"], None, None, node["id"], "code", name, content, source_uri, {
            "module_id": node.get("module_id"), "path": relative, "line_start": node.get("line_start"),
            "line_end": node.get("line_end"), "certainty": node.get("certainty"),
        })

    def _store_and_embed(
        self, scope_type: str, scope_id: str, chunks: list[ChunkRecord], profile: str,
    ) -> dict[str, Any]:
        now = time.time()
        field = "repository_id" if scope_type == "repository" else "collection_id"
        existing = {row["id"]: row for row in self.db.all(f"SELECT * FROM chunks WHERE {field}=?", (scope_id,))}
        incoming = {item.id: item for item in chunks}
        removed = [row for chunk_id, row in existing.items() if chunk_id not in incoming]
        changed = [item for chunk_id, item in incoming.items() if chunk_id not in existing or existing[chunk_id]["content_hash"] != item.content_hash]
        unchanged = len(incoming) - len(changed)
        with self.db.transaction() as connection:
            for row in removed:
                connection.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (row["id"],))
                connection.execute("DELETE FROM chunks WHERE id=?", (row["id"],))
            for item in changed:
                connection.execute("DELETE FROM chunks_fts WHERE chunk_id=?", (item.id,))
                connection.execute(
                    "INSERT INTO chunks(id,repository_id,collection_id,document_id,node_id,kind,title,content,source_uri,content_hash,vector_key,metadata_json,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,content=excluded.content,source_uri=excluded.source_uri,"
                    "content_hash=excluded.content_hash,vector_key=excluded.vector_key,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at",
                    item.db_values(now),
                )
                connection.execute("INSERT INTO chunks_fts(chunk_id,title,content) VALUES(?,?,?)", (item.id, item.title, item.content))

        root = self.registry.repository_root(scope_id) if scope_type == "repository" else self.registry.collection_root(scope_id)
        index_root = root / "index"
        index_root.mkdir(parents=True, exist_ok=True)
        vector = LocalVectorIndex(index_root, self.db.data_root / "models", profile)
        vector_result = vector.update(
            all_chunks=list(incoming.values()), changed=changed, removed=removed,
        )
        manifest = {
            "scope_type": scope_type, "scope_id": scope_id, "profile": profile,
            "model": EMBEDDING_PROFILES[profile]["model"], "chunks": len(incoming),
            "changed": len(changed), "unchanged": unchanged, "removed": len(removed),
            "vector": vector_result, "updated_at": now,
        }
        (index_root / "index-manifest.json").write_text(json_dumps(manifest) + "\n", encoding="utf-8")
        return manifest

    def _symbol_search(self, query: str, repository_ids: list[str], limit: int) -> list[str]:
        if not repository_ids:
            return []
        placeholders = ",".join("?" for _ in repository_ids)
        terms = IDENTIFIER_RE.findall(query) or [query]
        node_ids: list[str] = []
        for term in terms[:8]:
            rows = self.db.all(
                f"SELECT id,name,qualified_name FROM knowledge_nodes WHERE repository_id IN ({placeholders}) AND kind='symbol' "
                "AND (lower(name)=lower(?) OR lower(qualified_name)=lower(?) OR name LIKE ? OR qualified_name LIKE ?) LIMIT ?",
                tuple(repository_ids) + (term, term, f"%{term}%", f"%{term}%", limit),
            )
            node_ids.extend(row["id"] for row in rows)
        if not node_ids:
            return []
        placeholders = ",".join("?" for _ in node_ids)
        rows = self.db.all(f"SELECT id,node_id FROM chunks WHERE node_id IN ({placeholders})", tuple(node_ids))
        by_node = {row["node_id"]: row["id"] for row in rows}
        return _unique([by_node[item] for item in node_ids if item in by_node])[:limit]

    def _fts_search(
        self, query: str, repository_ids: list[str], collection_ids: list[str], limit: int,
    ) -> list[str]:
        terms = [item for item in re.split(r"\s+", query.strip()) if item]
        expression = " OR ".join('"' + item.replace('"', '""') + '"' for item in terms[:12])
        try:
            rows = self.db.all(
                "SELECT chunk_id,bm25(chunks_fts) AS rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (expression, limit * 5),
            )
        except Exception:
            rows = []
        allowed = set(repository_ids)
        allowed_collections = set(collection_ids)
        result: list[str] = []
        for row in rows:
            chunk = self.db.one("SELECT repository_id,collection_id FROM chunks WHERE id=?", (row["chunk_id"],))
            if chunk and (chunk.get("repository_id") in allowed or chunk.get("collection_id") in allowed_collections):
                result.append(row["chunk_id"])
        return result[:limit]

    def _vector_search(
        self, query: str, scope_type: str, scope_id: str, repository_ids: list[str], limit: int,
    ) -> tuple[list[str], str | None]:
        targets: list[tuple[str, str, Path]] = []
        if scope_type == "repository":
            targets.append(("repository", scope_id, self.registry.repository_root(scope_id)))
        else:
            targets.append(("collection", scope_id, self.registry.collection_root(scope_id)))
            targets.extend(("repository", item, self.registry.repository_root(item)) for item in repository_ids)
        found: list[tuple[float, str]] = []
        warning: str | None = None
        for _, target_id, root in targets:
            manifest = _safe_json(root / "index" / "index-manifest.json", {})
            profile = str(manifest.get("profile") or "balanced")
            vector = LocalVectorIndex(root / "index", self.db.data_root / "models", profile)
            values, problem = vector.search(query, limit)
            if problem:
                warning = problem
                continue
            key_map = {int(row["vector_key"]): row["id"] for row in self.db.all(
                "SELECT id,vector_key FROM chunks WHERE (repository_id=? OR collection_id=?) AND vector_key IS NOT NULL",
                (target_id, target_id),
            )}
            found.extend((distance, key_map[key]) for key, distance in values if key in key_map)
        found.sort(key=lambda item: item[0])
        return _unique([chunk_id for _, chunk_id in found])[:limit], warning

    def _graph_expand(self, chunk_ids: list[str], limit: int) -> list[str]:
        rows = self._chunks_by_ids(chunk_ids[:20])
        node_ids = [row["node_id"] for row in rows if row.get("node_id")]
        if not node_ids:
            return []
        placeholders = ",".join("?" for _ in node_ids)
        edges = self.db.all(
            f"SELECT source_id,target_id FROM knowledge_edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders}) LIMIT ?",
            tuple(node_ids) + tuple(node_ids) + (limit * 3,),
        )
        related = _unique([edge[key] for edge in edges for key in ("source_id", "target_id") if edge[key] not in node_ids])
        if not related:
            return []
        placeholders = ",".join("?" for _ in related)
        chunks = self.db.all(f"SELECT id,node_id FROM chunks WHERE node_id IN ({placeholders})", tuple(related))
        by_node = {row["node_id"]: row["id"] for row in chunks}
        return [by_node[item] for item in related if item in by_node][:limit]

    def _scope_ids(self, scope_type: str, scope_id: str) -> tuple[list[str], list[str]]:
        if scope_type == "repository":
            self.registry.get_repository(scope_id)
            return [scope_id], []
        if scope_type == "collection":
            return self.registry.collection_repository_ids(scope_id), [scope_id]
        raise ValueError("scope_type 必须是 repository 或 collection")

    def _chunks_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self.db.all(f"SELECT * FROM chunks WHERE id IN ({placeholders})", tuple(ids))
        by_id = {row["id"]: row for row in rows}
        return [by_id[item] for item in ids if item in by_id]

    @staticmethod
    def _public_chunk(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"], "repository_id": row.get("repository_id"), "collection_id": row.get("collection_id"),
            "document_id": row.get("document_id"), "node_id": row.get("node_id"), "kind": row["kind"],
            "title": row["title"], "content": row["content"], "source_uri": row["source_uri"],
            "metadata": json_loads(row.get("metadata_json"), {}),
        }


class LocalVectorIndex:
    """Optional FastEmbed + USearch adapter. Absence never disables lexical search."""

    def __init__(self, index_root: Path, model_cache: Path, profile: str) -> None:
        self.index_root = index_root
        self.model_cache = model_cache
        self.profile = profile if profile in EMBEDDING_PROFILES else "balanced"
        self.model_info = EMBEDDING_PROFILES[self.profile]
        self.index_path = index_root / "chunks.usearch"
        self.vector_manifest = index_root / "vector-manifest.json"

    def available(self) -> tuple[bool, str | None]:
        try:
            import fastembed  # noqa: F401
            import usearch  # noqa: F401
        except ImportError:
            return False, "本地向量组件未安装；当前使用符号、全文和图谱检索。生产环境请安装 clangwiki[rag]。"
        return True, None

    def update(
        self,
        all_chunks: list[ChunkRecord],
        changed: list[ChunkRecord],
        removed: list[dict[str, Any]],
    ) -> dict[str, Any]:
        available, warning = self.available()
        if not available:
            return {"available": False, "warning": warning}
        try:
            from usearch.index import Index

            model = self._embedding_model()
            metadata = _safe_json(self.vector_manifest, {})
            compatible = (
                self.index_path.is_file()
                and metadata.get("model") == self.model_info["model"]
                and int(metadata.get("dimension") or 0) == int(self.model_info["dimension"])
            )
            index = Index.restore(str(self.index_path), view=False) if compatible else Index(
                ndim=int(self.model_info["dimension"]), metric="cos", dtype="f16",
                connectivity=16, expansion_add=128, expansion_search=64,
            )
            if compatible:
                for row in removed:
                    key = row.get("vector_key")
                    if key is not None and int(key) in index:
                        index.remove(int(key))
                values = changed
            else:
                values = all_chunks
            if values:
                vectors = list(model.embed([_embedding_passage(item.content) for item in values], batch_size=32))
                for item, vector in zip(values, vectors):
                    if item.vector_key in index:
                        index.remove(item.vector_key)
                    index.add(item.vector_key, vector)
            index.save(str(self.index_path))
            self.vector_manifest.write_text(json_dumps({
                "model": self.model_info["model"], "dimension": self.model_info["dimension"],
                "count": len(all_chunks), "updated_at": time.time(),
            }) + "\n", encoding="utf-8")
            return {"available": True, "model": self.model_info["model"], "count": len(all_chunks), "incremental": compatible}
        except Exception as exc:
            return {"available": False, "warning": f"向量索引构建失败，已保留其他检索通道：{exc}"}

    def search(self, query: str, limit: int) -> tuple[list[tuple[int, float]], str | None]:
        available, warning = self.available()
        if not available:
            return [], warning
        if not self.index_path.is_file():
            return [], "尚未构建向量索引；当前结果来自其他检索通道。"
        try:
            from usearch.index import Index

            model = self._embedding_model()
            vector = next(iter(model.query_embed(_embedding_query(query))))
            index = Index.restore(str(self.index_path), view=True)
            matches = index.search(vector, limit)
            return [(int(key), float(distance)) for key, distance in zip(matches.keys, matches.distances)], None
        except Exception as exc:
            return [], f"向量查询失败，已退化到其他检索通道：{exc}"

    def _embedding_model(self):
        from fastembed import TextEmbedding

        self.model_cache.mkdir(parents=True, exist_ok=True)
        model_name = str(self.model_info["model"])
        try:
            return TextEmbedding(model_name=model_name, cache_dir=str(self.model_cache), lazy_load=True)
        except ValueError:
            if model_name != "intfloat/multilingual-e5-small":
                raise
            from fastembed.common.model_description import ModelSource, PoolingType

            TextEmbedding.add_custom_model(
                model=model_name,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(hf=model_name),
                dim=384,
                model_file="onnx/model.onnx",
            )
            return TextEmbedding(model_name=model_name, cache_dir=str(self.model_cache), lazy_load=True)


def _document_chunks(document: dict[str, Any]) -> Iterator[ChunkRecord]:
    content = str(document.get("content") or "")
    matches = list(HEADING_RE.finditer(content))
    if not matches:
        yield _chunk(
            document.get("repository_id"), document.get("collection_id"), document["id"], None,
            "manual" if document["kind"] == "manual" else "wiki", document["title"], content,
            _document_uri(document, None), {"module_id": document.get("module_id"), "heading": None},
        )
        return
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        section = content[start:end].strip()
        if len(section) < 30:
            continue
        heading = match.group(2).strip()
        title = f"{document['title']} · {heading}" if heading != document["title"] else document["title"]
        yield _chunk(
            document.get("repository_id"), document.get("collection_id"), document["id"], None,
            "manual" if document["kind"] == "manual" else "wiki", title, section,
            _document_uri(document, heading), {"module_id": document.get("module_id"), "heading": heading, "evidence_level": document.get("evidence_level")},
        )


def _annotation_chunk(annotation: dict[str, Any], repository_id: str | None, collection_id: str | None) -> ChunkRecord:
    title = f"工程师批注 · {annotation.get('anchor') or annotation.get('id')}"
    source_uri = f"annotation://{annotation.get('id')}"
    return _chunk(repository_id, collection_id, annotation.get("document_id"), annotation.get("node_id"), "annotation", title, str(annotation.get("content") or ""), source_uri, {"certainty": "human"})


def _edge_chunk(edge: dict[str, Any], repository_id: str | None, collection_id: str | None) -> ChunkRecord:
    source = str(edge.get("source_name") or edge.get("source_id"))
    target = str(edge.get("target_name") or edge.get("target_id"))
    kind = str(edge.get("kind") or "RELATED_TO")
    content = f"关系：{source} --{kind}--> {target}\n确定性：{edge.get('certainty')}\n置信度：{edge.get('confidence')}"
    source_uri = f"graph://{edge.get('id')}"
    return _chunk(repository_id, collection_id, None, None, "graph", f"{source} → {target}", content, source_uri, {"certainty": edge.get("certainty"), "edge_id": edge.get("id")})


def _chunk(
    repository_id: str | None,
    collection_id: str | None,
    document_id: str | None,
    node_id: str | None,
    kind: str,
    title: str,
    content: str,
    source_uri: str,
    metadata: dict[str, Any],
) -> ChunkRecord:
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    chunk_id = "chunk:" + hashlib.sha256(f"{source_uri}|{content_hash}".encode("utf-8")).hexdigest()[:24]
    vector_key = int(hashlib.sha256(chunk_id.encode("utf-8")).hexdigest()[:16], 16) & 0x7FFFFFFFFFFFFFFF
    return ChunkRecord(chunk_id, repository_id, collection_id, document_id, node_id, kind, title, content, source_uri, content_hash, vector_key, metadata)


def _document_uri(document: dict[str, Any], heading: str | None) -> str:
    scope = document.get("repository_id") or document.get("collection_id") or "local"
    scheme = "manual" if document.get("kind") == "manual" else "wiki"
    suffix = "#" + _anchor(heading) if heading else ""
    return f"{scheme}://{scope}/{document.get('relative_path') or document['id']}{suffix}"


def _anchor(value: str | None) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (value or "").strip().casefold()).strip("-")


def _embedding_query(value: str) -> str:
    return value if value.startswith("query: ") else "query: " + value


def _embedding_passage(value: str) -> str:
    return value if value.startswith("passage: ") else "passage: " + value


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _safe_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
