import hashlib
import math
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Sequence

import httpx


def normalize(vector: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [float(value) / norm for value in vector]


class Embedder(ABC):
    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> Dict[str, Any]:
        raise NotImplementedError


class OllamaEmbedder(Embedder):
    def __init__(
        self,
        base_url: str,
        model: str,
        num_gpu: int = 999,
        batch_size: int = 16,
        timeout: float = 900.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_gpu = num_gpu
        self.batch_size = batch_size
        self.timeout = timeout

    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for offset in range(0, len(texts), self.batch_size):
                batch = list(texts[offset:offset + self.batch_size])
                response = await client.post(
                    self.base_url + "/api/embed",
                    json={
                        "model": self.model,
                        "input": batch,
                        "options": {"num_gpu": self.num_gpu},
                        "truncate": True,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                returned = payload.get("embeddings", [])
                if len(returned) != len(batch):
                    raise RuntimeError("Ollama returned an unexpected embedding count")
                vectors.extend(normalize(vector) for vector in returned)
        return vectors

    async def health(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                version = (await client.get(self.base_url + "/api/version")).json()
                tags = (await client.get(self.base_url + "/api/tags")).json()
            names = [item.get("name") for item in tags.get("models", [])]
            return {
                "healthy": self.model in names or any(
                    name and name.startswith(self.model + ":") for name in names
                ),
                "model": self.model,
                "num_gpu": self.num_gpu,
                "version": version.get("version"),
                "available_models": names,
            }
        except Exception as exc:
            return {"healthy": False, "model": self.model, "error": str(exc)}


class HashingEmbedder(Embedder):
    """Deterministic offline embedder for tests; never used as the production default."""

    def __init__(self, dimension: int = 128):
        self.dimension = dimension

    async def embed(self, texts: Sequence[str]) -> List[List[float]]:
        result = []
        for text in texts:
            vector = [0.0] * self.dimension
            terms = [term.lower() for term in text.replace("::", " ").split()]
            for term in terms:
                digest = hashlib.sha256(term.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "little") % self.dimension
                vector[index] += -1.0 if digest[4] & 1 else 1.0
            result.append(normalize(vector))
        return result

    async def health(self) -> Dict[str, Any]:
        return {"healthy": True, "model": "hashing-test-only", "dimension": self.dimension}

