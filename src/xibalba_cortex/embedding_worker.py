"""External embedding sidecar for the canonical xibalba-cortex store.

The worker loads the embedding model in this process, never in the always-on MCP server.
It only projects active and confirmed memory content into the versioned sqlite-vec index.
"""
from __future__ import annotations

import argparse
import logging
import math
from collections.abc import Iterable
from typing import Any

from .store import EMBEDDING_DIM, EMBEDDING_MODEL_ID, GraphStore

logger = logging.getLogger("xibalba_cortex.embedding_worker")


def eligible_memories(store: GraphStore) -> list[dict[str, Any]]:
    """Return active/confirmed memories missing or stale for the pinned model."""
    with store._lock:  # one connection is already serialized by GraphStore's lock
        rows = store._connection.execute(
            """
            SELECT m.id, m.content, m.content_hash
            FROM memories m
            LEFT JOIN embeddings_meta e ON e.memory_id = m.id
            WHERE m.status IN ('active', 'confirmed')
              AND (e.memory_id IS NULL
                   OR e.model_id != ?
                   OR e.dim != ?
                   OR e.generated_from_hash != m.content_hash)
            ORDER BY m.created_at, m.id
            """,
            (EMBEDDING_MODEL_ID, EMBEDDING_DIM),
        ).fetchall()
    return [dict(row) for row in rows]


def embed_memories(
    store: GraphStore,
    model: Any,
    *,
    batch_size: int = 16,
    max_items: int | None = None,
) -> dict[str, int]:
    """Embed eligible memories in bounded batches, isolating individual write failures."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    rows = eligible_memories(store)
    if max_items is not None:
        if max_items < 0:
            raise ValueError("max_items must be non-negative")
        rows = rows[:max_items]

    processed = embedded = failed = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [row["content"] for row in batch]
        try:
            vectors = model.encode(texts, batch_size=len(batch), normalize_embeddings=True)
            vectors = vectors.tolist() if hasattr(vectors, "tolist") else vectors
        except Exception:
            logger.exception("embedding batch failed at offset %d", start)
            failed += len(batch)
            processed += len(batch)
            continue

        if len(vectors) != len(batch):
            logger.error("model returned %d vectors for %d memories", len(vectors), len(batch))
            failed += len(batch)
            processed += len(batch)
            continue

        for row, vector in zip(batch, vectors, strict=True):
            processed += 1
            try:
                if len(vector) != EMBEDDING_DIM:
                    raise ValueError(f"expected {EMBEDDING_DIM} dimensions, got {len(vector)}")
                numeric_vector = [float(value) for value in vector]
                if any(not math.isfinite(value) for value in numeric_vector):
                    raise ValueError("embedding values must be finite")
                if not any(value != 0.0 for value in numeric_vector):
                    raise ValueError("embedding vector must have non-zero norm")
                store.store_embedding(row["id"], numeric_vector, expected_content_hash=row["content_hash"])
                embedded += 1
            except Exception:
                logger.exception("failed to store embedding for memory %s", row["id"])
                failed += 1

    return {
        "processed": processed,
        "embedded": embedded,
        "failed": failed,
        "remaining": len(eligible_memories(store)),
    }


def build_model(model_id: str = EMBEDDING_MODEL_ID) -> Any:
    """Load the model in the short-lived worker process, not in xibalba-cortex."""
    if model_id != EMBEDDING_MODEL_ID:
        raise ValueError(f"only {EMBEDDING_MODEL_ID} is supported by the v1 store")
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_id)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill xibalba-cortex memory embeddings")
    parser.add_argument("--home", default=None, help="xibalba-cortex home directory")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    store = GraphStore(args.home or __import__("pathlib").Path.home() / ".hermes" / "xibalba-cortex")
    candidates = eligible_memories(store)
    logger.info("eligible memories: %d", len(candidates))
    if args.dry_run:
        return 0
    result = embed_memories(store, build_model(), batch_size=args.batch_size, max_items=args.max_items)
    logger.info("embedding result: %s", result)
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
