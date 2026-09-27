"""External embedding sidecar for the canonical xibalba-cortex store.

The worker loads the embedding model in this process, never in the always-on MCP server.
It only projects active and confirmed memory content into the versioned sqlite-vec index.
"""
from __future__ import annotations

import argparse
import logging
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections.abc import Iterable
from typing import Any

from .store import EMBEDDING_MODEL_ID, GraphStore

logger = logging.getLogger("xibalba_cortex.embedding_worker")


def eligible_memories(store: GraphStore) -> list[dict[str, Any]]:
    """Return active/confirmed memories missing or stale for the currently active registered
    embedding model (not a bare hardcoded constant -- see store.get_active_embedding_model)."""
    active_model = store.get_active_embedding_model()
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
            (active_model["model_id"], active_model["dimension"]),
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
        except Exception as exc:
            logger.exception("embedding batch failed at offset %d", start)
            for row in batch:
                store.record_embedding_failure(row["id"], str(exc))
            failed += len(batch)
            processed += len(batch)
            continue

        if len(vectors) != len(batch):
            logger.error("model returned %d vectors for %d memories", len(vectors), len(batch))
            for row in batch:
                store.record_embedding_failure(row["id"], f"model returned {len(vectors)} vectors for batch of {len(batch)}")
            failed += len(batch)
            processed += len(batch)
            continue

        for row, vector in zip(batch, vectors, strict=True):
            processed += 1
            try:
                # store_embedding is the authoritative validator (dimension/finite/zero-norm,
                # against the active registered model) -- no need to duplicate those checks here.
                numeric_vector = [float(value) for value in vector]
                store.store_embedding(row["id"], numeric_vector, expected_content_hash=row["content_hash"])
                embedded += 1
            except Exception as exc:
                logger.exception("failed to store embedding for memory %s", row["id"])
                store.record_embedding_failure(row["id"], str(exc))
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
    parser.add_argument("--additional-home", action="append", default=[], help="additional isolated profile store to index")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--serve", action="store_true", help="serve query embeddings and continuously backfill")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--port", type=int, default=8421)
    args = parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    homes = [args.home or __import__("pathlib").Path.home() / ".hermes" / "xibalba-cortex", *args.additional_home]
    stores = [GraphStore(home) for home in homes]
    candidates = sum(len(eligible_memories(store)) for store in stores)
    logger.info("eligible memories across %d isolated stores: %d", len(stores), candidates)
    if args.dry_run:
        return 0
    model = build_model()
    if args.serve:
        if not 1 <= args.port <= 65535 or args.interval_seconds < 5:
            parser.error("port must be valid and interval-seconds at least 5")
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.path != "/embed":
                    self.send_error(404); return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if size <= 0 or size > 32_768:
                        self.send_error(413); return
                    payload = json.loads(self.rfile.read(size))
                    text = payload.get("text") if isinstance(payload, dict) else None
                    if not isinstance(text, str) or not text or len(text) > 20_000:
                        self.send_error(400); return
                    vector = model.encode([text], normalize_embeddings=True)[0]
                    vector = vector.tolist() if hasattr(vector, "tolist") else vector
                    body = json.dumps({"vector": [float(v) for v in vector]}).encode()
                    self.send_response(200); self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
                except Exception:
                    logger.exception("query embedding failed")
                    self.send_error(503)
            def log_message(self, fmt: str, *args: object) -> None:
                logger.info("embedding http: " + fmt, *args)
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        import threading
        def backfill() -> None:
            while True:
                try:
                    for profile_store in stores:
                        result = embed_memories(profile_store, model, batch_size=args.batch_size, max_items=args.max_items)
                        logger.info("embedding backfill home=%s result=%s", profile_store.home, result)
                except Exception:
                    logger.exception("embedding backfill cycle failed")
                time.sleep(args.interval_seconds)
        threading.Thread(target=backfill, daemon=True, name="embedding-backfill").start()
        logger.info("embedding sidecar listening on 127.0.0.1:%d", args.port)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.shutdown()
        return 0
    results = [embed_memories(profile_store, model, batch_size=args.batch_size, max_items=args.max_items) for profile_store in stores]
    logger.info("embedding results: %s", results)
    return 0 if all(result["failed"] == 0 for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
