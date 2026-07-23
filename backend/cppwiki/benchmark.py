import argparse
import asyncio
import json
import math
import time
from pathlib import Path
from typing import List

from .analyzer import source_files
from .config import get_settings
from .embedding import OllamaEmbedder


def similarity(left: List[float], right: List[float]) -> float:
    return sum(a * b for a, b in zip(left, right)) / (
        (math.sqrt(sum(a * a for a in left)) or 1.0)
        * (math.sqrt(sum(b * b for b in right)) or 1.0)
    )


async def run(repo: Path) -> int:
    settings = get_settings()
    documents = [
        path.read_text(encoding="utf-8", errors="replace")
        for path in source_files(repo)
    ][:16]
    if not documents:
        raise RuntimeError("No C/C++ files found")

    async def measure(num_gpu: int):
        embedder = OllamaEmbedder(
            settings.embed_url, settings.embed_model, num_gpu,
            settings.embed_batch_size, settings.request_timeout_seconds,
        )
        started = time.perf_counter()
        vectors = await embedder.embed(documents)
        return vectors, time.perf_counter() - started

    gpu_vectors, gpu_seconds = await measure(999)
    cpu_vectors, cpu_seconds = await measure(0)
    pairwise = [similarity(gpu, cpu) for gpu, cpu in zip(gpu_vectors, cpu_vectors)]
    report = {
        "model": settings.embed_model,
        "documents": len(documents),
        "dimension_gpu": len(gpu_vectors[0]),
        "dimension_cpu": len(cpu_vectors[0]),
        "gpu_seconds": round(gpu_seconds, 3),
        "cpu_seconds": round(cpu_seconds, 3),
        "mean_same_input_cosine": round(sum(pairwise) / len(pairwise), 8),
        "compatible": len(gpu_vectors[0]) == len(cpu_vectors[0]) and min(pairwise) > 0.999,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["compatible"] else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.repo.resolve())))


if __name__ == "__main__":
    main()

