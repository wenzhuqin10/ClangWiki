from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence


SCHEMA_VERSION = 1


class Database:
    """Thread-safe SQLite storage for the local single-user knowledge platform."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root.expanduser().resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        for name in ("repositories", "collections", "models", "backups", "tmp"):
            (self.data_root / name).mkdir(parents=True, exist_ok=True)
        self.path = self.data_root / "clangwiki.db"
        self._local = threading.local()
        self._migration_lock = threading.Lock()
        self.migrate()

    def connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            self._local.connection = connection
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Cursor:
        connection = self.connection()
        cursor = connection.execute(sql, parameters)
        connection.commit()
        return cursor

    def executemany(self, sql: str, values: Sequence[Sequence[Any]]) -> None:
        connection = self.connection()
        connection.executemany(sql, values)
        connection.commit()

    def one(self, sql: str, parameters: Sequence[Any] = ()) -> dict[str, Any] | None:
        row = self.connection().execute(sql, parameters).fetchone()
        return dict(row) if row is not None else None

    def all(self, sql: str, parameters: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection().execute(sql, parameters).fetchall()]

    def migrate(self) -> None:
        with self._migration_lock:
            connection = self.connection()
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库版本 {version} 高于当前程序支持的 {SCHEMA_VERSION}，请升级 ClangWiki。"
                )
            if version < 1:
                self._migrate_v1(connection)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()

    @staticmethod
    def _migrate_v1(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS repositories (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                config_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'registered',
                active_run_id TEXT,
                git_branch TEXT,
                git_commit TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS collections (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                config_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS collection_repositories (
                collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
                added_at REAL NOT NULL,
                PRIMARY KEY (collection_id, repository_id)
            );

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                git_commit TEXT,
                config_hash TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                embedding_model TEXT,
                artifact_path TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                finished_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_runs_repository ON runs(repository_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                scope_type TEXT NOT NULL,
                scope_id TEXT,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);

            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                event_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_job_events ON job_events(job_id, id);

            CREATE TABLE IF NOT EXISTS knowledge_nodes (
                id TEXT PRIMARY KEY,
                repository_id TEXT REFERENCES repositories(id) ON DELETE CASCADE,
                collection_id TEXT REFERENCES collections(id) ON DELETE CASCADE,
                run_id TEXT,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                qualified_name TEXT,
                path TEXT,
                line_start INTEGER,
                line_end INTEGER,
                module_id TEXT,
                certainty TEXT NOT NULL DEFAULT 'compiler',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_repo_kind ON knowledge_nodes(repository_id, kind);
            CREATE INDEX IF NOT EXISTS idx_nodes_name ON knowledge_nodes(name);
            CREATE INDEX IF NOT EXISTS idx_nodes_qualified ON knowledge_nodes(qualified_name);

            CREATE TABLE IF NOT EXISTS knowledge_edges (
                id TEXT PRIMARY KEY,
                repository_id TEXT REFERENCES repositories(id) ON DELETE CASCADE,
                collection_id TEXT REFERENCES collections(id) ON DELETE CASCADE,
                run_id TEXT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                certainty TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                confirmed INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_edges_source ON knowledge_edges(source_id, kind);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON knowledge_edges(target_id, kind);
            CREATE INDEX IF NOT EXISTS idx_edges_repo ON knowledge_edges(repository_id, kind);

            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                repository_id TEXT REFERENCES repositories(id) ON DELETE CASCADE,
                collection_id TEXT REFERENCES collections(id) ON DELETE CASCADE,
                run_id TEXT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                relative_path TEXT,
                content TEXT,
                module_id TEXT,
                evidence_level TEXT NOT NULL DEFAULT 'mixed',
                immutable INTEGER NOT NULL DEFAULT 1,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_documents_repo ON documents(repository_id, run_id);
            CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection_id);

            CREATE TABLE IF NOT EXISTS document_revisions (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(document_id, revision)
            );

            CREATE TABLE IF NOT EXISTS annotations (
                id TEXT PRIMARY KEY,
                document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                node_id TEXT REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                anchor TEXT,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tags (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS document_tags (
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY(document_id, tag_id)
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                repository_id TEXT REFERENCES repositories(id) ON DELETE CASCADE,
                collection_id TEXT REFERENCES collections(id) ON DELETE CASCADE,
                document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
                node_id TEXT REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                vector_key INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_repo ON chunks(repository_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_collection ON chunks(collection_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash);

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turns (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                status TEXT NOT NULL,
                retrieval_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS citations (
                id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
                citation_key TEXT NOT NULL,
                chunk_id TEXT REFERENCES chunks(id) ON DELETE SET NULL,
                source_uri TEXT NOT NULL,
                title TEXT NOT NULL
            );
            """
        )
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                "chunk_id UNINDEXED, title, content, tokenize='trigram')"
            )
        except sqlite3.OperationalError:
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                "chunk_id UNINDEXED, title, content, tokenize='unicode61')"
            )


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback
