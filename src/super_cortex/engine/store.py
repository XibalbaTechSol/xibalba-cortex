"""SQLite storage for the SuperCortex engine: documents, chunks, keyword index, vectors.

One database file holds everything, and every mutation of a document (its row, its chunks,
their keyword index and their vectors) happens in a single transaction. That is the property
the two-system Supermemory setup lacks: there, forgetting a memory updated the ledger and the
search index in separate systems, so they could disagree.

Vectors are stored as float32 blobs beside their chunk, tagged with the embedding model that
produced them. Nearest-neighbour search is exact (brute force): through sqlite-vec's C
distance function when the extension loads, otherwise in Python. Exact search is the right
call at our size (thousands of chunks); an ANN index is a later optimisation, not a feature.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .chunking import chunk_text
from .embedder import Embedder

_STOPWORDS = frozenset(
    "a an and are as at be by did do does for from has have how i in is it its of on or that the "
    "their there this to was were what when where which who why will with you your we our".split()
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def fts_query(query: str) -> str | None:
    """OR of the query's content words, each quoted.

    The old Cortex store ANDed every token. That is precise for keyword lookups but returns
    nothing for a natural-language question whose words don't all occur in one memory, which
    is the common case for agent recall. BM25 already rewards documents matching more terms.
    """
    tokens = [t for t in re.findall(r"[\w-]+", query.lower()) if t not in _STOPWORDS and len(t) > 1]
    if not tokens:
        return None
    return " OR ".join('"' + t.replace('"', "") + '"' for t in dict.fromkeys(tokens))


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: str
    doc_id: str
    namespace: str
    content: str
    ordinal: int


class EngineStore:
    def __init__(self, path: str | Path, embedder: Embedder, max_chunk_chars: int = 800) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.max_chunk_chars = max_chunk_chars
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self.vector_backend = self._load_sqlite_vec()
        self._migrate()

    # -- setup -------------------------------------------------------------------------------

    def _load_sqlite_vec(self) -> str:
        try:
            import sqlite_vec

            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            return "sqlite-vec"
        except Exception:  # extension loading unsupported on this Python build, or not installed
            return "python"

    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    namespace TEXT NOT NULL,
                    id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, id)
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    model_key TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    FOREIGN KEY (namespace, doc_id) REFERENCES documents(namespace, id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS chunks_ns_model ON chunks(namespace, model_key);
                CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(namespace, doc_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    content, chunk_id UNINDEXED, namespace UNINDEXED, tokenize = 'porter unicode61'
                );
                """
            )

    # -- documents ---------------------------------------------------------------------------

    def upsert_document(
        self,
        namespace: str,
        content: str,
        doc_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        content = content.strip()
        if not content:
            raise ValueError("content must not be empty")
        doc_id = doc_id or uuid.uuid4().hex
        digest = content_hash(content)
        meta_json = json.dumps(metadata or {}, sort_keys=True)
        with self._lock:
            existing = self._conn.execute(
                "SELECT content_hash, metadata_json FROM documents WHERE namespace = ? AND id = ?",
                (namespace, doc_id),
            ).fetchone()
            if existing and existing["content_hash"] == digest and existing["metadata_json"] == meta_json:
                return {"id": doc_id, "status": "unchanged"}
            if existing and existing["content_hash"] == digest:
                with self._conn:
                    self._conn.execute(
                        "UPDATE documents SET metadata_json = ?, updated_at = ? WHERE namespace = ? AND id = ?",
                        (meta_json, _now(), namespace, doc_id),
                    )
                return {"id": doc_id, "status": "updated"}
            chunks = chunk_text(content, self.max_chunk_chars)
            # Embed before opening the write transaction: a slow or failing model call must not
            # hold the database lock or leave a half-written document behind.
            vectors = self.embedder.embed(chunks)
            now = _now()
            with self._conn:
                self._delete_chunks(namespace, [doc_id])
                self._conn.execute(
                    """INSERT INTO documents(namespace, id, content, metadata_json, content_hash, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(namespace, id) DO UPDATE SET content = excluded.content,
                         metadata_json = excluded.metadata_json, content_hash = excluded.content_hash,
                         updated_at = excluded.updated_at""",
                    (namespace, doc_id, content, meta_json, digest, now, now),
                )
                for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors)):
                    chunk_id = f"{doc_id}#{ordinal}"
                    self._conn.execute(
                        "INSERT INTO chunks(id, namespace, doc_id, ordinal, content, model_key, embedding) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (chunk_id, namespace, doc_id, ordinal, chunk, self.embedder.model_key, _pack(vector)),
                    )
                    self._conn.execute(
                        "INSERT INTO chunks_fts(content, chunk_id, namespace) VALUES (?, ?, ?)",
                        (chunk, chunk_id, namespace),
                    )
        return {"id": doc_id, "status": "updated" if existing else "created", "chunks": len(chunks)}

    def _delete_chunks(self, namespace: str, doc_ids: list[str]) -> None:
        marks = ",".join("?" for _ in doc_ids)
        rows = self._conn.execute(
            f"SELECT id FROM chunks WHERE namespace = ? AND doc_id IN ({marks})", (namespace, *doc_ids)
        ).fetchall()
        for row in rows:
            self._conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (row["id"],))
        self._conn.execute(f"DELETE FROM chunks WHERE namespace = ? AND doc_id IN ({marks})", (namespace, *doc_ids))

    def get_document(self, namespace: str, doc_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE namespace = ? AND id = ?", (namespace, doc_id)
            ).fetchone()
        return self._doc_row(row) if row else None

    def delete_documents(self, namespace: str, doc_ids: list[str]) -> int:
        if not doc_ids:
            return 0
        marks = ",".join("?" for _ in doc_ids)
        with self._lock, self._conn:
            self._delete_chunks(namespace, doc_ids)
            cur = self._conn.execute(
                f"DELETE FROM documents WHERE namespace = ? AND id IN ({marks})", (namespace, *doc_ids)
            )
        return cur.rowcount

    def list_namespaces(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT DISTINCT namespace FROM documents ORDER BY namespace").fetchall()
        return [r["namespace"] for r in rows]

    def list_documents(self, namespace: str, page: int = 1, limit: int = 10) -> dict[str, Any]:
        page, limit = max(1, page), max(1, min(limit, 100))
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM documents WHERE namespace = ?", (namespace,)).fetchone()[0]
            rows = self._conn.execute(
                "SELECT * FROM documents WHERE namespace = ? ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
                (namespace, limit, (page - 1) * limit),
            ).fetchall()
        return {
            "documents": [self._doc_row(r) for r in rows],
            "pagination": {"currentPage": page, "limit": limit, "totalItems": total,
                           "totalPages": max(1, -(-total // limit))},
        }

    @staticmethod
    def _doc_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "namespace": row["namespace"],
            "content": row["content"],
            "metadata": json.loads(row["metadata_json"]),
            "contentHash": row["content_hash"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    # -- retrieval channels ------------------------------------------------------------------

    def lexical_ranked(self, namespace: str, query: str, k: int) -> list[str]:
        match = fts_query(query)
        if match is None:
            return []
        with self._lock:
            rows = self._conn.execute(
                """SELECT chunk_id FROM chunks_fts
                   WHERE chunks_fts MATCH ? AND namespace = ?
                   ORDER BY bm25(chunks_fts) LIMIT ?""",
                (match, namespace, k),
            ).fetchall()
        return [r["chunk_id"] for r in rows]

    def vector_ranked(self, namespace: str, query_vector: list[float], k: int) -> list[tuple[str, float]]:
        model_key = self.embedder.model_key
        with self._lock:
            if self.vector_backend == "sqlite-vec":
                rows = self._conn.execute(
                    """SELECT id, 1.0 - vec_distance_cosine(embedding, ?) AS sim FROM chunks
                       WHERE namespace = ? AND model_key = ? ORDER BY sim DESC LIMIT ?""",
                    (_pack(query_vector), namespace, model_key, k),
                ).fetchall()
                return [(r["id"], float(r["sim"])) for r in rows]
            rows = self._conn.execute(
                "SELECT id, embedding FROM chunks WHERE namespace = ? AND model_key = ?", (namespace, model_key)
            ).fetchall()
        scored = [(r["id"], sum(a * b for a, b in zip(query_vector, _unpack(r["embedding"])))) for r in rows]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:k]

    def similarities(self, chunk_ids: list[str], query_vector: list[float]) -> dict[str, float]:
        """Cosine similarity for specific chunks -- used to give keyword-only hits a real score."""
        if not chunk_ids:
            return {}
        marks = ",".join("?" for _ in chunk_ids)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, embedding, model_key FROM chunks WHERE id IN ({marks})", chunk_ids
            ).fetchall()
        return {
            r["id"]: sum(a * b for a, b in zip(query_vector, _unpack(r["embedding"])))
            for r in rows
            if r["model_key"] == self.embedder.model_key
        }

    def chunks(self, chunk_ids: list[str]) -> dict[str, ChunkHit]:
        if not chunk_ids:
            return {}
        marks = ",".join("?" for _ in chunk_ids)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, doc_id, namespace, content, ordinal FROM chunks WHERE id IN ({marks})", chunk_ids
            ).fetchall()
        return {r["id"]: ChunkHit(r["id"], r["doc_id"], r["namespace"], r["content"], r["ordinal"]) for r in rows}

    def stale_vector_count(self) -> int:
        """Chunks embedded by a different model than the active one (need re-embedding)."""
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE model_key != ?", (self.embedder.model_key,)
            ).fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
