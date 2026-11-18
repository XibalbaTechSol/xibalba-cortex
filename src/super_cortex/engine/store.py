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


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


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
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,            -- latest | superseded | candidate | forgotten
                    is_inference INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL,
                    supersedes_id TEXT,
                    extractor TEXT NOT NULL,         -- model that proposed it
                    model_key TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS memories_ns_status ON memories(namespace, status);
                CREATE TABLE IF NOT EXISTS memory_sources (
                    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    namespace TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    chunk_id TEXT,
                    quote TEXT NOT NULL,
                    PRIMARY KEY (memory_id, doc_id)
                );
                CREATE INDEX IF NOT EXISTS memory_sources_doc ON memory_sources(namespace, doc_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    content, memory_id UNINDEXED, namespace UNINDEXED, tokenize = 'porter unicode61'
                );
                CREATE TABLE IF NOT EXISTS llm_usage (
                    day TEXT NOT NULL,
                    model TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (day, model)
                );
                """
            )
            columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(documents)")}
            for column, ddl in (
                ("task_type", "TEXT NOT NULL DEFAULT 'memory'"),
                ("dreaming", "TEXT NOT NULL DEFAULT 'dynamic'"),
                ("dream_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("dream_attempts", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if column not in columns:
                    self._conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {ddl}")
            self._conn.execute("CREATE INDEX IF NOT EXISTS documents_dream ON documents(dream_status, namespace, created_at)")

    # -- documents ---------------------------------------------------------------------------

    def upsert_document(
        self,
        namespace: str,
        content: str,
        doc_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        task_type: str = "memory",
        dreaming: str = "dynamic",
    ) -> dict[str, Any]:
        if task_type not in ("memory", "superrag"):
            raise ValueError("taskType must be memory or superrag")
        if dreaming not in ("dynamic", "instant"):
            raise ValueError("dreaming must be dynamic or instant")
        dream_status = "pending" if task_type == "memory" else "skipped"
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
                    """INSERT INTO documents(namespace, id, content, metadata_json, content_hash, created_at, updated_at,
                                            task_type, dreaming, dream_status, dream_attempts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                       ON CONFLICT(namespace, id) DO UPDATE SET content = excluded.content,
                         metadata_json = excluded.metadata_json, content_hash = excluded.content_hash,
                         updated_at = excluded.updated_at, task_type = excluded.task_type,
                         dreaming = excluded.dreaming, dream_status = excluded.dream_status, dream_attempts = 0""",
                    (namespace, doc_id, content, meta_json, digest, now, now, task_type, dreaming, dream_status),
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
            affected = [r["memory_id"] for r in self._conn.execute(
                f"SELECT DISTINCT memory_id FROM memory_sources WHERE namespace = ? AND doc_id IN ({marks})",
                (namespace, *doc_ids),
            )]
            self._conn.execute(
                f"DELETE FROM memory_sources WHERE namespace = ? AND doc_id IN ({marks})", (namespace, *doc_ids)
            )
            # A learned memory with no remaining evidence is forgotten in the same transaction,
            # so search can never return a memory whose source was deleted.
            for memory_id in affected:
                left = self._conn.execute("SELECT 1 FROM memory_sources WHERE memory_id = ? LIMIT 1", (memory_id,)).fetchone()
                if left is None:
                    self._set_memory_status(memory_id, "forgotten")
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

    # -- dreaming queue ------------------------------------------------------------------------

    def pending_documents(self, limit: int = 200, max_attempts: int = 3) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT namespace, id, content, metadata_json, created_at, dreaming, dream_attempts FROM documents
                   WHERE dream_status = 'pending' AND dream_attempts < ?
                   ORDER BY namespace, created_at, id LIMIT ?""",
                (max_attempts, limit),
            ).fetchall()
        return [{"namespace": r["namespace"], "id": r["id"], "content": r["content"],
                 "metadata": json.loads(r["metadata_json"]), "created_at": r["created_at"],
                 "dreaming": r["dreaming"], "attempts": r["dream_attempts"]} for r in rows]

    def mark_dreamed(self, namespace: str, doc_ids: list[str], status: str = "done") -> None:
        marks = ",".join("?" for _ in doc_ids)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE documents SET dream_status = ? WHERE namespace = ? AND id IN ({marks})",
                (status, namespace, *doc_ids),
            )

    def record_dream_failure(self, namespace: str, doc_ids: list[str], max_attempts: int = 3) -> None:
        marks = ",".join("?" for _ in doc_ids)
        with self._lock, self._conn:
            self._conn.execute(
                f"""UPDATE documents SET dream_attempts = dream_attempts + 1,
                      dream_status = CASE WHEN dream_attempts + 1 >= ? THEN 'failed' ELSE dream_status END
                    WHERE namespace = ? AND id IN ({marks})""",
                (max_attempts, namespace, *doc_ids),
            )

    def dream_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT dream_status, COUNT(*) n FROM documents GROUP BY dream_status").fetchall()
        return {r["dream_status"]: r["n"] for r in rows}

    def chunk_for_quote(self, namespace: str, doc_id: str, quote: str) -> str | None:
        """The chunk of `doc_id` containing `quote` (whitespace- and case-insensitive), if any."""
        needle = _normalise(quote)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, content FROM chunks WHERE namespace = ? AND doc_id = ? ORDER BY ordinal", (namespace, doc_id)
            ).fetchall()
        for row in rows:
            if needle and needle in _normalise(row["content"]):
                return row["id"]
        return None

    # -- learned memories ---------------------------------------------------------------------

    def insert_memory(
        self,
        namespace: str,
        content: str,
        sources: list[tuple[str, str | None, str]],
        *,
        confidence: float,
        status: str,
        extractor: str,
        is_inference: bool = False,
        supersedes_id: str | None = None,
        vector: list[float] | None = None,
    ) -> str:
        """Insert a memory with its evidence; superseding `supersedes_id` in the same transaction."""
        if not sources:
            raise ValueError("a memory needs at least one source")
        vector = vector if vector is not None else self.embedder.embed([content])[0]
        memory_id = "m_" + uuid.uuid4().hex[:20]
        now = _now()
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO memories(id, namespace, content, status, is_inference, confidence, supersedes_id,
                                       extractor, model_key, embedding, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (memory_id, namespace, content, status, int(is_inference), confidence, supersedes_id,
                 extractor, self.embedder.model_key, _pack(vector), now, now),
            )
            self._conn.execute("INSERT INTO memories_fts(content, memory_id, namespace) VALUES (?, ?, ?)",
                               (content, memory_id, namespace))
            for doc_id, chunk_id, quote in sources:
                self._conn.execute(
                    "INSERT OR IGNORE INTO memory_sources(memory_id, namespace, doc_id, chunk_id, quote) VALUES (?, ?, ?, ?, ?)",
                    (memory_id, namespace, doc_id, chunk_id, quote),
                )
            if supersedes_id and status == "latest":
                self._set_memory_status(supersedes_id, "superseded")
        return memory_id

    def add_memory_source(self, memory_id: str, namespace: str, doc_id: str, chunk_id: str | None, quote: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO memory_sources(memory_id, namespace, doc_id, chunk_id, quote) VALUES (?, ?, ?, ?, ?)",
                (memory_id, namespace, doc_id, chunk_id, quote),
            )

    def _set_memory_status(self, memory_id: str, status: str) -> None:
        self._conn.execute("UPDATE memories SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), memory_id))

    def get_memories(self, memory_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not memory_ids:
            return {}
        marks = ",".join("?" for _ in memory_ids)
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM memories WHERE id IN ({marks})", memory_ids).fetchall()
            srcs = self._conn.execute(
                f"SELECT memory_id, doc_id, chunk_id, quote FROM memory_sources WHERE memory_id IN ({marks}) ORDER BY rowid",
                memory_ids,
            ).fetchall()
        sources: dict[str, list[dict[str, Any]]] = {}
        for r in srcs:
            sources.setdefault(r["memory_id"], []).append({"documentId": r["doc_id"], "chunkId": r["chunk_id"], "quote": r["quote"]})
        return {
            r["id"]: {
                "id": r["id"], "namespace": r["namespace"], "memory": r["content"], "status": r["status"],
                "isLatest": r["status"] == "latest", "isInference": bool(r["is_inference"]),
                "confidence": r["confidence"], "supersedes": r["supersedes_id"], "extractor": r["extractor"],
                "createdAt": r["created_at"], "updatedAt": r["updated_at"], "sources": sources.get(r["id"], []),
            }
            for r in rows
        }

    def list_memories(self, namespace: str, status: str | None = "latest", page: int = 1, limit: int = 10) -> dict[str, Any]:
        page, limit = max(1, page), max(1, min(limit, 100))
        where, args = "namespace = ?", [namespace]
        if status:
            where, args = where + " AND status = ?", args + [status]
        with self._lock:
            total = self._conn.execute(f"SELECT COUNT(*) FROM memories WHERE {where}", args).fetchone()[0]
            ids = [r["id"] for r in self._conn.execute(
                f"SELECT id FROM memories WHERE {where} ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
                (*args, limit, (page - 1) * limit),
            )]
        found = self.get_memories(ids)
        return {"memories": [found[i] for i in ids if i in found],
                "pagination": {"currentPage": page, "limit": limit, "totalItems": total,
                               "totalPages": max(1, -(-total // limit))}}

    def memory_lexical_ranked(self, namespace: str, query: str, k: int, statuses: tuple[str, ...] = ("latest",)) -> list[str]:
        match = fts_query(query)
        if match is None:
            return []
        marks = ",".join("?" for _ in statuses)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT f.memory_id FROM memories_fts f JOIN memories m ON m.id = f.memory_id
                    WHERE memories_fts MATCH ? AND f.namespace = ? AND m.status IN ({marks})
                    ORDER BY bm25(memories_fts) LIMIT ?""",
                (match, namespace, *statuses, k),
            ).fetchall()
        return [r["memory_id"] for r in rows]

    def memory_vector_ranked(self, namespace: str, query_vector: list[float], k: int,
                             statuses: tuple[str, ...] = ("latest",)) -> list[tuple[str, float]]:
        marks = ",".join("?" for _ in statuses)
        with self._lock:
            if self.vector_backend == "sqlite-vec":
                rows = self._conn.execute(
                    f"""SELECT id, 1.0 - vec_distance_cosine(embedding, ?) AS sim FROM memories
                        WHERE namespace = ? AND model_key = ? AND status IN ({marks}) ORDER BY sim DESC LIMIT ?""",
                    (_pack(query_vector), namespace, self.embedder.model_key, *statuses, k),
                ).fetchall()
                return [(r["id"], float(r["sim"])) for r in rows]
            rows = self._conn.execute(
                f"SELECT id, embedding FROM memories WHERE namespace = ? AND model_key = ? AND status IN ({marks})",
                (namespace, self.embedder.model_key, *statuses),
            ).fetchall()
        scored = [(r["id"], sum(a * b for a, b in zip(query_vector, _unpack(r["embedding"])))) for r in rows]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:k]

    def memory_similarities(self, memory_ids: list[str], query_vector: list[float]) -> dict[str, float]:
        if not memory_ids:
            return {}
        marks = ",".join("?" for _ in memory_ids)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, embedding, model_key FROM memories WHERE id IN ({marks})", memory_ids
            ).fetchall()
        return {r["id"]: sum(a * b for a, b in zip(query_vector, _unpack(r["embedding"])))
                for r in rows if r["model_key"] == self.embedder.model_key}

    # -- LLM budget ---------------------------------------------------------------------------

    def llm_requests_today(self, model: str) -> int:
        day = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            row = self._conn.execute("SELECT requests FROM llm_usage WHERE day = ? AND model = ?", (day, model)).fetchone()
        return row["requests"] if row else 0

    def record_llm_request(self, model: str) -> None:
        day = datetime.now(timezone.utc).date().isoformat()
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO llm_usage(day, model, requests) VALUES (?, ?, 1)
                   ON CONFLICT(day, model) DO UPDATE SET requests = requests + 1""",
                (day, model),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
