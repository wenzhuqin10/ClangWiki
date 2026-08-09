from __future__ import annotations

import hashlib
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .database import Database, json_dumps, json_loads
from .io import read_json
from .registry import Registry


HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+\.md(?:#[^)]+)?)\)")


class WikiService:
    def __init__(self, database: Database, registry: Registry) -> None:
        self.db = database
        self.registry = registry

    def ingest_generated(self, repository_id: str, run_id: str, run_root: Path) -> list[dict[str, Any]]:
        output_root = run_root / "output"
        modules = _safe_json(run_root / "knowledge" / "modules.json", [])
        module_by_document = {
            f"Modules/{str(item.get('source_path') or 'root')}/index.md": str(item.get("module_id"))
            for item in modules if isinstance(item, dict)
        }
        now = time.time()
        inserted: list[dict[str, Any]] = []
        for path in sorted(output_root.rglob("*.md")) if output_root.is_dir() else []:
            relative = path.relative_to(output_root).as_posix()
            content = path.read_text(encoding="utf-8", errors="replace")
            title = _title(content, relative)
            document_id = f"doc:{repository_id}:{run_id}:{_digest(relative)}"
            module_id = module_by_document.get(relative)
            metadata = {
                "doc_id": document_id,
                "repo_id": repository_id,
                "run_id": run_id,
                "module_id": module_id,
                "source_paths": self._module_sources(modules, module_id),
                "tags": [],
                "evidence_level": "compiler",
                "backlinks": [item for item in LINK_RE.findall(content)],
            }
            enriched = _with_frontmatter(content, metadata)
            path.write_text(enriched.rstrip() + "\n", encoding="utf-8")
            self.db.execute(
                "INSERT OR REPLACE INTO documents(id,repository_id,collection_id,run_id,kind,title,relative_path,content,module_id,evidence_level,immutable,metadata_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    document_id, repository_id, None, run_id, "generated", title, relative,
                    enriched, module_id, "compiler", 1, json_dumps(metadata), now, now,
                ),
            )
            self._upsert_document_node(document_id, repository_id, None, run_id, title, relative, module_id)
            inserted.append(self.get_document(document_id))
        return inserted

    def ingest_collection_document(
        self, collection_id: str, name: str, content: str, relative_path: str,
    ) -> dict[str, Any]:
        now = time.time()
        document_id = f"collection-doc:{collection_id}:{_digest(relative_path)}"
        metadata = {"doc_id": document_id, "collection_id": collection_id, "tags": ["跨仓汇总"]}
        enriched = _with_frontmatter(content, metadata)
        output = self.registry.collection_root(collection_id) / "output" / relative_path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(enriched.rstrip() + "\n", encoding="utf-8")
        self.db.execute(
            "INSERT OR REPLACE INTO documents(id,repository_id,collection_id,run_id,kind,title,relative_path,content,module_id,evidence_level,immutable,metadata_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (document_id, None, collection_id, None, "collection", name, relative_path, enriched, None, "mixed", 1, json_dumps(metadata), now, now),
        )
        self._upsert_document_node(document_id, None, collection_id, None, name, relative_path, None)
        return self.get_document(document_id)

    def list_documents(
        self,
        scope_type: str | None = None,
        scope_id: str | None = None,
        include_history: bool = False,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if scope_type == "repository" and scope_id:
            repository = self.registry.get_repository(scope_id)
            if include_history:
                conditions.append("repository_id=?")
                parameters.append(scope_id)
            else:
                conditions.append("repository_id=? AND (run_id=? OR kind IN ('manual','annotation'))")
                parameters.extend((scope_id, repository.get("active_run_id")))
        elif scope_type == "collection" and scope_id:
            repository_ids = self.registry.collection_repository_ids(scope_id)
            clauses = ["collection_id=?"]
            parameters.append(scope_id)
            for repository_id in repository_ids:
                repository = self.registry.get_repository(repository_id)
                clauses.append("(repository_id=? AND run_id=?)")
                parameters.extend((repository_id, repository.get("active_run_id")))
            conditions.append("(" + " OR ".join(clauses) + ")")
        sql = "SELECT * FROM documents"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY kind, title"
        return [self._public_document(row, include_content=False) for row in self.db.all(sql, tuple(parameters))]

    def get_document(self, document_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM documents WHERE id=?", (document_id,))
        if not row:
            raise KeyError("文档不存在")
        document = self._public_document(row, include_content=True)
        document["tags"] = [
            item["name"] for item in self.db.all(
                "SELECT t.name FROM tags t JOIN document_tags dt ON dt.tag_id=t.id WHERE dt.document_id=? ORDER BY t.name",
                (document_id,),
            )
        ]
        document["annotations"] = [self._public_annotation(item) for item in self.db.all(
            "SELECT * FROM annotations WHERE document_id=? ORDER BY created_at", (document_id,)
        )]
        document["related"] = self.related_documents(document_id)
        return document

    def create_manual_page(
        self,
        title: str,
        content: str,
        repository_id: str | None = None,
        collection_id: str | None = None,
        module_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        if bool(repository_id) == bool(collection_id):
            raise ValueError("人工知识页必须且只能归属一个仓库或知识空间。")
        if repository_id:
            self.registry.get_repository(repository_id)
        if collection_id:
            self.registry.get_collection(collection_id)
        now = time.time()
        document_id = f"manual:{uuid.uuid4().hex}"
        body = content.strip()
        if not HEADING_RE.search(body):
            body = f"# {title.strip()}\n\n{body}"
        metadata = {"tags": tags or [], "manual": True}
        self.db.execute(
            "INSERT INTO documents(id,repository_id,collection_id,run_id,kind,title,relative_path,content,module_id,evidence_level,immutable,metadata_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (document_id, repository_id, collection_id, None, "manual", title.strip(), None, body, module_id, "human", 0, json_dumps(metadata), now, now),
        )
        self.db.execute(
            "INSERT INTO document_revisions(id,document_id,revision,content,created_at) VALUES(?,?,?,?,?)",
            (f"rev:{uuid.uuid4().hex}", document_id, 1, body, now),
        )
        self._upsert_document_node(document_id, repository_id, collection_id, None, title, None, module_id, certainty="human")
        self.set_tags(document_id, tags or [])
        return self.get_document(document_id)

    def update_manual_page(self, document_id: str, content: str, title: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
        current = self.get_document(document_id)
        if current["immutable"]:
            raise ValueError("机器生成文档快照不可直接编辑，请创建批注或人工知识页。")
        revision = self.db.one("SELECT COALESCE(MAX(revision),0) AS value FROM document_revisions WHERE document_id=?", (document_id,))
        next_revision = int((revision or {}).get("value") or 0) + 1
        now = time.time()
        self.db.execute(
            "UPDATE documents SET title=?,content=?,updated_at=? WHERE id=?",
            (title or current["title"], content, now, document_id),
        )
        self.db.execute(
            "INSERT INTO document_revisions(id,document_id,revision,content,created_at) VALUES(?,?,?,?,?)",
            (f"rev:{uuid.uuid4().hex}", document_id, next_revision, content, now),
        )
        if tags is not None:
            self.set_tags(document_id, tags)
        return self.get_document(document_id)

    def revisions(self, document_id: str) -> list[dict[str, Any]]:
        self.get_document(document_id)
        return self.db.all(
            "SELECT id,revision,content,created_at FROM document_revisions WHERE document_id=? ORDER BY revision DESC",
            (document_id,),
        )

    def restore_revision(self, document_id: str, revision: int) -> dict[str, Any]:
        row = self.db.one(
            "SELECT content FROM document_revisions WHERE document_id=? AND revision=?",
            (document_id, revision),
        )
        if not row:
            raise KeyError("修订版本不存在")
        return self.update_manual_page(document_id, row["content"])

    def add_annotation(
        self,
        content: str,
        document_id: str | None = None,
        node_id: str | None = None,
        anchor: str | None = None,
    ) -> dict[str, Any]:
        if not document_id and not node_id:
            raise ValueError("批注必须关联文档或代码节点。")
        if document_id:
            self.get_document(document_id)
        if node_id and not self.db.one("SELECT id FROM knowledge_nodes WHERE id=?", (node_id,)):
            raise KeyError("代码节点不存在")
        annotation_id = f"annotation:{uuid.uuid4().hex}"
        now = time.time()
        self.db.execute(
            "INSERT INTO annotations(id,document_id,node_id,anchor,content,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (annotation_id, document_id, node_id, anchor, content.strip(), now, now),
        )
        return self._public_annotation(self.db.one("SELECT * FROM annotations WHERE id=?", (annotation_id,)) or {})

    def set_tags(self, document_id: str, tags: list[str]) -> None:
        self.get_document(document_id)
        clean = sorted({item.strip() for item in tags if item.strip()})
        with self.db.transaction() as connection:
            connection.execute("DELETE FROM document_tags WHERE document_id=?", (document_id,))
            for tag in clean:
                tag_id = f"tag:{_digest(tag.casefold())}"
                connection.execute("INSERT OR IGNORE INTO tags(id,name) VALUES(?,?)", (tag_id, tag))
                connection.execute("INSERT INTO document_tags(document_id,tag_id) VALUES(?,?)", (document_id, tag_id))

    def related_documents(self, document_id: str, limit: int = 8) -> list[dict[str, Any]]:
        current = self.db.one("SELECT * FROM documents WHERE id=?", (document_id,))
        if not current:
            return []
        rows = self.db.all(
            "SELECT DISTINCT d.id,d.title,d.kind,d.repository_id,d.collection_id,d.module_id "
            "FROM documents d LEFT JOIN document_tags dt ON dt.document_id=d.id "
            "WHERE d.id<>? AND ((d.module_id IS NOT NULL AND d.module_id=?) OR dt.tag_id IN "
            "(SELECT tag_id FROM document_tags WHERE document_id=?)) LIMIT ?",
            (document_id, current.get("module_id"), document_id, limit),
        )
        return rows

    def source_snippet(self, repository_id: str, relative_path: str, line_start: int = 1, line_end: int = 200) -> dict[str, Any]:
        repository = self.registry.get_repository(repository_id)
        root = Path(repository["path"]).resolve()
        target = (root / relative_path).resolve()
        if root not in target.parents or not target.is_file():
            raise FileNotFoundError("源码文件不存在或超出已注册仓库范围。")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, line_start)
        end = min(len(lines), max(start, line_end), start + 499)
        return {
            "repository_id": repository_id,
            "path": target.relative_to(root).as_posix(),
            "line_start": start,
            "line_end": end,
            "content": "\n".join(lines[start - 1:end]),
        }

    def _upsert_document_node(
        self,
        document_id: str,
        repository_id: str | None,
        collection_id: str | None,
        run_id: str | None,
        title: str,
        relative_path: str | None,
        module_id: str | None,
        certainty: str = "compiler",
    ) -> None:
        node_id = f"document-node:{document_id}"
        self.db.execute(
            "INSERT INTO knowledge_nodes(id,repository_id,collection_id,run_id,kind,name,qualified_name,path,line_start,line_end,module_id,certainty,metadata_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id,name=excluded.name,path=excluded.path,module_id=excluded.module_id",
            (node_id, repository_id, collection_id, run_id, "document", title, None, relative_path, None, None, module_id, certainty, json_dumps({"document_id": document_id})),
        )
        if repository_id and module_id:
            source = f"module:{repository_id}:{module_id}"
            if self.db.one("SELECT id FROM knowledge_nodes WHERE id=?", (source,)):
                edge_id = f"edge:{_digest(source + '|' + node_id + '|DOCUMENTS')}"
                self.db.execute(
                    "INSERT OR REPLACE INTO knowledge_edges(id,repository_id,collection_id,run_id,source_id,target_id,kind,certainty,confidence,confirmed,metadata_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (edge_id, repository_id, None, run_id, source, node_id, "DOCUMENTS", certainty, 1.0, 1, "{}"),
                )

    @staticmethod
    def _module_sources(modules: list[Any], module_id: str | None) -> list[str]:
        for item in modules:
            if isinstance(item, dict) and str(item.get("module_id")) == str(module_id):
                return [str(path) for path in item.get("direct_files") or []]
        return []

    @staticmethod
    def _public_document(row: dict[str, Any], include_content: bool) -> dict[str, Any]:
        result = {
            "id": row["id"], "repository_id": row.get("repository_id"), "collection_id": row.get("collection_id"),
            "run_id": row.get("run_id"), "kind": row["kind"], "title": row["title"],
            "relative_path": row.get("relative_path"), "module_id": row.get("module_id"),
            "evidence_level": row.get("evidence_level"), "immutable": bool(row.get("immutable")),
            "metadata": json_loads(row.get("metadata_json"), {}), "created_at": row["created_at"], "updated_at": row["updated_at"],
        }
        if include_content:
            result["content"] = row.get("content") or ""
        return result

    @staticmethod
    def _public_annotation(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"), "document_id": row.get("document_id"), "node_id": row.get("node_id"),
            "anchor": row.get("anchor"), "content": row.get("content"),
            "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
        }


def _with_frontmatter(content: str, metadata: dict[str, Any]) -> str:
    if content.startswith("---\n"):
        return content
    lines = ["---"]
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    lines.extend(["---", "", content.lstrip()])
    return "\n".join(lines)


def _title(content: str, fallback: str) -> str:
    match = HEADING_RE.search(content)
    return match.group(1).strip() if match else fallback


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _safe_json(path: Path, fallback: Any) -> Any:
    try:
        return read_json(path)
    except (OSError, ValueError):
        return fallback
