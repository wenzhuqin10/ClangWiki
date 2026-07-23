import math
import re
from collections import defaultdict
from typing import Any, Dict, List, Sequence, Tuple

from .database import Database
from .embedding import Embedder

try:
    import faiss  # type: ignore
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover - exercised on lightweight developer installs
    faiss = None
    np = None


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return -1.0
    return sum(a * b for a, b in zip(left, right)) / (
        (math.sqrt(sum(a * a for a in left)) or 1.0)
        * (math.sqrt(sum(b * b for b in right)) or 1.0)
    )


class HybridRetriever:
    def __init__(self, database: Database, embedder: Embedder):
        self.database = database
        self.embedder = embedder

    async def index(self, repository_id: str) -> int:
        chunks = self.database.chunks(repository_id)
        missing = [row for row in chunks if row.get("embedding") is None]
        if not missing:
            return 0
        vectors = await self.embedder.embed([row["content"] for row in missing])
        self.database.update_embeddings(zip([row["id"] for row in missing], vectors))
        return len(missing)

    async def search(
        self, repository_id: str, query: str, top_k: int = 10, expand_graph: bool = True
    ) -> List[Dict[str, Any]]:
        chunks = self.database.chunks(repository_id, embedded_only=True)
        by_id = {row["id"]: row for row in chunks}
        if not by_id:
            return []

        query_vector = (await self.embedder.embed([query]))[0]
        vector_limit = max(top_k * 3, 20)
        vector_rank = self._vector_rank(by_id, query_vector, vector_limit)
        fts_rank = self.database.fts_search(repository_id, query, max(top_k * 3, 20))

        identifiers = re.findall(r"[A-Za-z_]\w*(?:::\w+)*", query)
        symbol_rank: List[str] = []
        for identifier in identifiers:
            symbol_rank.extend(self.database.symbol_search(repository_id, identifier, top_k))
        symbol_rank = list(dict.fromkeys(symbol_rank))

        rankings: List[Tuple[str, List[str], float]] = [
            ("symbol", symbol_rank, 1.4),
            ("fts", fts_rank, 1.0),
            ("vector", vector_rank, 1.0),
        ]
        scores: Dict[str, float] = defaultdict(float)
        signals: Dict[str, List[str]] = defaultdict(list)
        for signal, ranking, weight in rankings:
            for position, chunk_id in enumerate(ranking):
                if chunk_id in by_id:
                    scores[chunk_id] += weight / (60.0 + position + 1)
                    signals[chunk_id].append(signal)

        if expand_graph:
            seeds = sorted(scores, key=scores.get, reverse=True)[:5]
            for seed in seeds:
                symbol = by_id[seed].get("symbol")
                if not symbol:
                    continue
                neighbors = self.database.graph_neighbors(repository_id, symbol)
                for neighbor_id in self.database.chunks_for_symbols(repository_id, neighbors):
                    if neighbor_id in by_id:
                        scores[neighbor_id] += 0.7 / 61.0
                        signals[neighbor_id].append("graph")

        ordered = sorted(scores, key=scores.get, reverse=True)[:top_k]
        result = []
        for chunk_id in ordered:
            row = by_id[chunk_id]
            result.append({
                "chunk_id": chunk_id,
                "file_path": row["file_path"],
                "symbol": row.get("symbol"),
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "content": row["content"],
                "score": scores[chunk_id],
                "signals": sorted(set(signals[chunk_id])),
            })
        return result

    def _vector_rank(
        self, by_id: Dict[str, Dict[str, Any]], query_vector: Sequence[float], limit: int
    ) -> List[str]:
        chunk_ids = list(by_id)
        vectors = [
            self.database.decode_vector(row["embedding"], row["embedding_dim"])
            for row in by_id.values()
        ]
        if faiss is not None and np is not None and vectors:
            matrix = np.asarray(vectors, dtype="float32")
            query = np.asarray([query_vector], dtype="float32")
            index = faiss.IndexFlatIP(matrix.shape[1])
            index.add(matrix)
            _, positions = index.search(query, min(limit, len(chunk_ids)))
            return [chunk_ids[position] for position in positions[0] if position >= 0]
        return sorted(
            chunk_ids,
            key=lambda chunk_id: cosine(
                query_vector,
                self.database.decode_vector(
                    by_id[chunk_id]["embedding"], by_id[chunk_id]["embedding_dim"]
                ),
            ),
            reverse=True,
        )[:limit]
