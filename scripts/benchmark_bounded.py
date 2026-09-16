"""Bounded local Cortex benchmark; never targets the configured live home."""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from xibalba_cortex.store import GraphStore


MAX_MEMORIES = 1_000
MAX_ITERATIONS = 100


def _summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return {
        "count": len(samples),
        "p50_ms": round(statistics.median(samples) * 1000, 3),
        "p95_ms": round(ordered[p95_index] * 1000, 3),
        "max_ms": round(max(samples) * 1000, 3),
    }


def _timed(function, iterations: int) -> dict[str, float]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        function()
        samples.append(time.perf_counter() - started)
    return _summary(samples)


def run(*, memories: int, iterations: int) -> dict[str, object]:
    if not 1 <= memories <= MAX_MEMORIES:
        raise ValueError(f"memories must be between 1 and {MAX_MEMORIES}")
    if not 1 <= iterations <= MAX_ITERATIONS:
        raise ValueError(f"iterations must be between 1 and {MAX_ITERATIONS}")

    with tempfile.TemporaryDirectory(prefix="xibalba-cortex-bench-") as directory:
        home = Path(directory) / "graph"
        store = GraphStore(home)
        try:
            started = time.perf_counter()
            for index in range(memories):
                store.store_memory(
                    f"bounded benchmark memory {index} integrity cortex",
                    source={"kind": "benchmark", "locator": f"bench://{index}"},
                    status="confirmed",
                )
            ingest_seconds = time.perf_counter() - started
            result = {
                "fixture": {"memories": memories, "iterations": iterations},
                "ingest": {"count": memories, "total_ms": round(ingest_seconds * 1000, 3)},
                "search": _timed(lambda: store.search("benchmark integrity", limit=10), iterations),
                "status_fast": _timed(lambda: store.status(fast=True), iterations),
            }
            return result
        finally:
            store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memories", type=int, default=100)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(run(memories=args.memories, iterations=args.iterations), sort_keys=True))


if __name__ == "__main__":
    main()
