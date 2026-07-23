import json
import sqlite3
import struct
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS repositories (
  id TEXT PRIMARY KEY,
  root_path TEXT NOT NULL UNIQUE,
  mode TEXT NOT NULL,
  confidence REAL NOT NULL,
  errors_json TEXT NOT NULL DEFAULT '[]',
  analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS symbols (
  id TEXT PRIMARY KEY,
  repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  file_path TEXT NOT NULL,
  line_start INTEGER NOT NULL,
  line_end INTEGER NOT NULL,
  signature TEXT NOT NULL DEFAULT '',
  UNIQUE(repository_id, qualified_name, file_path, line_start)
);
CREATE INDEX IF NOT EXISTS idx_symbols_repo_name ON symbols(repository_id, name);
CREATE TABLE IF NOT EXISTS relations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  target TEXT NOT NULL,
  kind TEXT NOT NULL,
  file_path TEXT NOT NULL DEFAULT '',
  line INTEGER NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 1.0,
  UNIQUE(repository_id, source, target, kind, file_path, line)
);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(repository_id, source);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(repository_id, target);
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  symbol_id TEXT,
  symbol TEXT,
  kind TEXT NOT NULL,
  file_path TEXT NOT NULL,
  line_start INTEGER NOT NULL,
  line_end INTEGER NOT NULL,
  content TEXT NOT NULL,
  embedding BLOB,
  embedding_dim INTEGER
);
CREATE INDEX IF NOT EXISTS idx_chunks_repo_symbol ON chunks(repository_id, symbol);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  chunk_id UNINDEXED, repository_id UNINDEXED, symbol, file_path, content,
  tokenize='unicode61'
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def replace_repository(
        self,
        repository_id: str,
        root_path: str,
        mode: str,
        confidence: float,
        errors: Sequence[str],
    ) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM chunks_fts WHERE repository_id = ?", (repository_id,))
            connection.execute("DELETE FROM repositories WHERE id = ?", (repository_id,))
            connection.execute(
                "INSERT INTO repositories(id, root_path, mode, confidence, errors_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (repository_id, root_path, mode, confidence, json.dumps(list(errors))),
            )

    def insert_symbols(self, rows: Iterable[Dict[str, Any]]) -> None:
        values = [
            (
                row["id"], row["repository_id"], row["kind"], row["name"],
                row.get("qualified_name", row["name"]), row["file_path"],
                row["line_start"], row["line_end"], row.get("signature", ""),
            )
            for row in rows
        ]
        with self.connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values
            )

    def insert_relations(self, rows: Iterable[Dict[str, Any]]) -> None:
        values = [
            (
                row["repository_id"], row["source"], row["target"], row["kind"],
                row.get("file_path", ""), row.get("line", 0), row.get("confidence", 1.0),
            )
            for row in rows
        ]
        with self.connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO relations(repository_id, source, target, kind, file_path, line, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", values
            )

    def insert_chunks(self, rows: Iterable[Dict[str, Any]]) -> None:
        rows = list(rows)
        with self.connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO chunks(id, repository_id, symbol_id, symbol, kind, file_path, "
                "line_start, line_end, content) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(
                    row["id"], row["repository_id"], row.get("symbol_id"), row.get("symbol"),
                    row["kind"], row["file_path"], row["line_start"], row["line_end"], row["content"],
                ) for row in rows],
            )
            connection.executemany(
                "INSERT INTO chunks_fts(chunk_id, repository_id, symbol, file_path, content) VALUES (?, ?, ?, ?, ?)",
                [(
                    row["id"], row["repository_id"], row.get("symbol") or "",
                    row["file_path"], row["content"],
                ) for row in rows],
            )

    def update_embeddings(self, pairs: Iterable[tuple]) -> None:
        values = []
        for chunk_id, vector in pairs:
            blob = struct.pack("<%sf" % len(vector), *vector)
            values.append((blob, len(vector), chunk_id))
        with self.connect() as connection:
            connection.executemany(
                "UPDATE chunks SET embedding = ?, embedding_dim = ? WHERE id = ?", values
            )

    @staticmethod
    def decode_vector(blob: Optional[bytes], dimension: Optional[int]) -> List[float]:
        if not blob or not dimension:
            return []
        return list(struct.unpack("<%sf" % dimension, blob))

    def repository(self, repository_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM repositories WHERE id = ?", (repository_id,)
            ).fetchone()
            return dict(row) if row else None

    def counts(self, repository_id: str) -> Dict[str, int]:
        with self.connect() as connection:
            return {
                table: connection.execute(
                    "SELECT count(*) FROM %s WHERE repository_id = ?" % table,
                    (repository_id,),
                ).fetchone()[0]
                for table in ("symbols", "relations", "chunks")
            }

    def chunks(self, repository_id: str, embedded_only: bool = False) -> List[Dict[str, Any]]:
        suffix = " AND embedding IS NOT NULL" if embedded_only else ""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks WHERE repository_id = ?" + suffix, (repository_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def fts_search(self, repository_id: str, query: str, limit: int) -> List[str]:
        terms = [part.replace('"', "") for part in query.split() if part.strip()]
        if not terms:
            return []
        expression = " OR ".join('"%s"' % term for term in terms[:12])
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT chunk_id FROM chunks_fts WHERE repository_id = ? "
                "AND chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
                (repository_id, expression, limit),
            ).fetchall()
            return [row[0] for row in rows]

    def symbol_search(self, repository_id: str, query: str, limit: int) -> List[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT c.id FROM chunks c JOIN symbols s ON c.symbol_id = s.id "
                "WHERE c.repository_id = ? AND (s.name = ? OR s.qualified_name LIKE ?) LIMIT ?",
                (repository_id, query, "%" + query + "%", limit),
            ).fetchall()
            return [row[0] for row in rows]

    def graph_neighbors(self, repository_id: str, symbol: str) -> List[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT source, target FROM relations WHERE repository_id = ? "
                "AND (source = ? OR target = ?)",
                (repository_id, symbol, symbol),
            ).fetchall()
            result = []
            for row in rows:
                result.append(row["target"] if row["source"] == symbol else row["source"])
            return result

    def chunks_for_symbols(self, repository_id: str, symbols: Sequence[str]) -> List[str]:
        if not symbols:
            return []
        placeholders = ",".join("?" for _ in symbols)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM chunks WHERE repository_id = ? AND symbol IN (%s)" % placeholders,
                [repository_id] + list(symbols),
            ).fetchall()
            return [row[0] for row in rows]
