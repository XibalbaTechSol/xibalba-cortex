from __future__ import annotations

import os
import hashlib
import json
import mimetypes
import re
import shutil
import sqlite3
import threading
import uuid
from pathlib import Path

import sqlite_vec

_SCHEMA_VERSION = 1

# Generous default cap on a single attachment -- not a policy decision, just a guard against
# accidentally ingesting something absurd (e.g. a whole video library) into the blob store.
_DEFAULT_MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024

# Pinned per the Phase 0 embedding-model spike (docs/architecture/advanced-memory.md addendum):
# BAAI/bge-small-en-v1.5, 384-dim. The dimension is baked into the vec0 virtual table at create
# time (sqlite-vec's own constraint), so changing models requires a new table, not a config flag.
# Vectors are never computed in-process here -- see EMBEDDING_MODEL_ID docstring below.
EMBEDDING_MODEL_ID = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

_VALID_STATUSES = {
    "candidate",
    "active",
    "confirmed",
    "disputed",
    "quarantined",
    "superseded",
    "forgotten",
}
_EVENT_SCHEMA = "xibalba.memory.event.v1"
_TRUSTED_SOURCE_KINDS = {"direct_user", "explicit_memory"}
_EVIDENCE_CLASSES = {
    "declared_intent",
    "observed_event",
    "extracted_proposition",
    "inference",
    "summary",
    "policy",
}
_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?previous\s+instructions\b", re.IGNORECASE),
    re.compile(r"\b(system|developer)\s+(note|message|instruction)\s*:", re.IGNORECASE),
    re.compile(r"\b(run|call|invoke|execute)\s+(?:the\s+)?(?:requested\s+)?tool\b", re.IGNORECASE),
    re.compile(r"</?(?:memory-context|system|tool_call)\b", re.IGNORECASE),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    locator TEXT,
    role TEXT,
    session_id TEXT,
    message_id TEXT,
    tool_name TEXT,
    observed_at TEXT,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'candidate', 'active', 'confirmed', 'disputed',
        'quarantined', 'superseded', 'forgotten'
    )),
    valid_from TEXT,
    valid_to TEXT,
    supersedes_id TEXT REFERENCES memories(id),
    derivation_family TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    memory_id UNINDEXED,
    content,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'unknown',
    normalization_version TEXT NOT NULL DEFAULT 'v1',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(normalized_name, entity_type)
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    evidence_memory_id TEXT REFERENCES memories(id),
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
    UNIQUE(entity_id, normalized_alias)
);

CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    evidence_quote TEXT NOT NULL,
    PRIMARY KEY(memory_id, entity_id)
);

CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    subject_entity_id TEXT NOT NULL REFERENCES entities(id),
    predicate TEXT NOT NULL,
    object_entity_id TEXT REFERENCES entities(id),
    object_literal TEXT,
    evidence_memory_id TEXT NOT NULL REFERENCES memories(id),
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN (
        'candidate', 'active', 'confirmed', 'disputed', 'superseded', 'forgotten'
    )),
    valid_from TEXT,
    valid_to TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((object_entity_id IS NOT NULL) != (object_literal IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS memory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL REFERENCES memories(id),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'create', 'confirm', 'contradict', 'supersede',
        'quarantine', 'forget', 'restore', 'attach_media'
    )),
    detail_json TEXT NOT NULL DEFAULT '{}',
    node_id TEXT NOT NULL,
    parent_event_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memory_events_node_id ON memory_events(node_id);

CREATE TABLE IF NOT EXISTS contradictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id_a TEXT NOT NULL REFERENCES memories(id),
    memory_id_b TEXT NOT NULL REFERENCES memories(id),
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    media_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    storage_locator TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_attachments_memory_id ON attachments(memory_id);

CREATE TABLE IF NOT EXISTS embeddings_meta (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    dim INTEGER NOT NULL,
    generated_from_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS integrity_links (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    node_id TEXT,
    verification_state TEXT NOT NULL CHECK (verification_state IN (
        'unlinked', 'hash_match_local', 'ancestry_verified',
        'anchored_to_configured_root', 'verification_failed', 'content_unavailable'
    )),
    expected_content_hash TEXT,
    failure_reason TEXT,
    verified_at TEXT
);
"""


class GraphStore:
    """Profile-local SQLite authority for Xibalba graph memory."""

    def __init__(self, home: str | Path):
        self.home = Path(home).expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.home, 0o700)
        self.db_path = self.home / "graph-memory.sqlite3"
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.db_path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        os.chmod(self.db_path, 0o600)
        self._connection.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    def _configure(self) -> None:
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.enable_load_extension(True)
        sqlite_vec.load(self._connection)
        self._connection.enable_load_extension(False)

    def _migrate(self) -> None:
        with self._lock:
            self._connection.executescript(_SCHEMA)
            self._connection.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors USING vec0(
                    memory_id TEXT PRIMARY KEY,
                    embedding FLOAT[{EMBEDDING_DIM}]
                )
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                (_SCHEMA_VERSION,),
            )

    def status(self) -> dict[str, object]:
        with self._lock:
            schema_version = self._connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
            journal_mode = self._connection.execute("PRAGMA journal_mode").fetchone()[0]
            foreign_keys = bool(self._connection.execute("PRAGMA foreign_keys").fetchone()[0])
            integrity_check = self._connection.execute("PRAGMA integrity_check").fetchone()[0]
            fts5 = bool(
                self._connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'memory_fts'"
                ).fetchone()
            )
        return {
            "schema_version": schema_version,
            "journal_mode": str(journal_mode).lower(),
            "foreign_keys": foreign_keys,
            "fts5": fts5,
            "integrity_check": integrity_check,
        }

    def backup(self, destination: str | Path) -> dict[str, object]:
        """Online backup via SQLite's own backup API -- safe under WAL with concurrent readers,
        unlike copying the file directly. Verifies the copy before returning, not just that the
        API call succeeded.
        """
        destination = Path(destination).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._lock:
            backup_connection = sqlite3.connect(destination)
            try:
                self._connection.backup(backup_connection)
            finally:
                backup_connection.close()
        os.chmod(destination, 0o600)

        verify_connection = sqlite3.connect(destination)
        try:
            integrity_check = verify_connection.execute("PRAGMA integrity_check").fetchone()[0]
            schema_version = verify_connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        finally:
            verify_connection.close()
        return {
            "destination": str(destination),
            "integrity_check": integrity_check,
            "schema_version": schema_version,
        }

    def restore(self, source: str | Path) -> dict[str, object]:
        """Replace this store's live database with a backup, refusing corrupt input.

        Verifies the source's integrity_check BEFORE touching the live database -- a restore
        that installs a corrupt backup over a healthy database is strictly worse than refusing.
        """
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)

        source_connection = sqlite3.connect(source)
        try:
            try:
                integrity_check = source_connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
            except sqlite3.DatabaseError as exc:
                integrity_check = f"not a valid SQLite database: {exc}"
        finally:
            source_connection.close()
        if integrity_check != "ok":
            raise ValueError(
                f"refusing to restore from a backup that fails integrity_check: {integrity_check}"
            )

        with self._lock:
            self._connection.close()
            for suffix in ("", "-wal", "-shm"):
                sidecar = Path(str(self.db_path) + suffix)
                if sidecar.exists():
                    sidecar.unlink()

            source_connection = sqlite3.connect(source)
            dest_connection = sqlite3.connect(self.db_path)
            try:
                source_connection.backup(dest_connection)
            finally:
                source_connection.close()
                dest_connection.close()
            os.chmod(self.db_path, 0o600)

            self._connection = sqlite3.connect(
                self.db_path, timeout=5.0, isolation_level=None, check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._configure()
            self._migrate()
        return self.status()

    @staticmethod
    def _sha256(text: str) -> str:
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @staticmethod
    def _quarantine_reasons(content: str, source_kind: str) -> list[str]:
        if source_kind in _TRUSTED_SOURCE_KINDS:
            return []
        if any(pattern.search(content) for pattern in _INJECTION_PATTERNS):
            return ["instruction_injection"]
        return []

    def _head_node_id(self, memory_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT node_id FROM memory_events WHERE memory_id = ? ORDER BY id DESC LIMIT 1",
            (memory_id,),
        ).fetchone()
        return row["node_id"] if row else None

    def _append_event(
        self, memory_id: str, event_type: str, detail: dict[str, object]
    ) -> str:
        """Append an immutable, hash-linked event node. Must run inside an open transaction.

        Each node's id commits to its own content and its parent's id, so the chain is
        tamper-evident: recomputing node_id at every step and checking parent_event_id
        resolves is enough to verify history without trusting the database file itself.
        """
        parent_event_id = self._head_node_id(memory_id)
        node = {
            "schema": _EVENT_SCHEMA,
            "memory_id": memory_id,
            "event_type": event_type,
            "detail": detail,
            "parent_event_id": parent_event_id,
        }
        node_id = self._sha256(self._canonical_json(node))
        self._connection.execute(
            "INSERT INTO memory_events(memory_id, event_type, detail_json, node_id, parent_event_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (memory_id, event_type, self._canonical_json(detail), node_id, parent_event_id),
        )
        return node_id

    def verify_chain(self, memory_id: str) -> dict[str, object]:
        """Recompute every event's node_id and check parent linkage — pure local computation,
        no external dependency. This is chain integrity, not Integrity DAG anchoring: it proves
        this memory's own history is internally consistent, not that it's anchored on-chain.
        """
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, event_type, detail_json, node_id, parent_event_id FROM memory_events "
                "WHERE memory_id = ? ORDER BY id",
                (memory_id,),
            ).fetchall()
        expected_parent = None
        for row in rows:
            node = {
                "schema": _EVENT_SCHEMA,
                "memory_id": memory_id,
                "event_type": row["event_type"],
                "detail": json.loads(row["detail_json"]),
                "parent_event_id": expected_parent,
            }
            recomputed = self._sha256(self._canonical_json(node))
            if row["parent_event_id"] != expected_parent or recomputed != row["node_id"]:
                return {
                    "valid": False,
                    "length": len(rows),
                    "broken_at_event_id": row["id"],
                    "head_node_id": rows[-1]["node_id"] if rows else None,
                }
            expected_parent = row["node_id"]
        return {
            "valid": True,
            "length": len(rows),
            "broken_at_event_id": None,
            "head_node_id": rows[-1]["node_id"] if rows else None,
        }

    def store_memory(
        self,
        content: str,
        *,
        source: dict[str, object],
        status: str = "candidate",
        idempotency_key: str | None = None,
        evidence_class: str = "observed_event",
    ) -> dict[str, object]:
        content = content.strip()
        if not content:
            raise ValueError("content must not be empty")
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid memory status: {status}")
        if evidence_class not in _EVIDENCE_CLASSES:
            raise ValueError(f"invalid evidence_class: {evidence_class}")
        source_kind = str(source.get("kind") or "").strip()
        if not source_kind:
            raise ValueError("source.kind is required")

        reasons = self._quarantine_reasons(content, source_kind)
        effective_status = "quarantined" if reasons else status
        content_digest = self._sha256(content)
        source_payload = dict(source)
        source_payload["content_hash"] = content_digest
        source_id = self._sha256(self._canonical_json(source_payload))
        memory_id = str(uuid.uuid4())
        known_source_fields = {
            "kind", "locator", "role", "session_id", "message_id", "tool_name", "observed_at"
        }
        source_metadata = {
            key: value for key, value in source.items() if key not in known_source_fields
        }
        event_type = "quarantine" if effective_status == "quarantined" else "create"

        with self._lock:
            if idempotency_key:
                existing = self._connection.execute(
                    "SELECT id FROM memories WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    return self.get_memory(existing["id"])

            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO sources(
                        id, kind, locator, role, session_id, message_id, tool_name,
                        observed_at, content_hash, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        source_kind,
                        source.get("locator"),
                        source.get("role"),
                        source.get("session_id"),
                        source.get("message_id"),
                        source.get("tool_name"),
                        source.get("observed_at"),
                        content_digest,
                        self._canonical_json(source_metadata),
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO memories(
                        id, source_id, content, content_hash, status,
                        derivation_family, idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        source_id,
                        content,
                        content_digest,
                        effective_status,
                        evidence_class,
                        idempotency_key,
                    ),
                )
                self._connection.execute(
                    "INSERT INTO memory_fts(memory_id, content) VALUES (?, ?)",
                    (memory_id, content),
                )
                self._append_event(memory_id, event_type, {"quarantine_reasons": reasons})
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return self.get_memory(memory_id)

    def get_memory(self, memory_id: str) -> dict[str, object]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT m.*, s.kind AS source_kind, s.locator, s.role, s.session_id,
                       s.message_id, s.tool_name, s.observed_at, s.metadata_json
                FROM memories m JOIN sources s ON s.id = m.source_id
                WHERE m.id = ?
                """,
                (memory_id,),
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            event = self._connection.execute(
                "SELECT detail_json FROM memory_events WHERE memory_id = ? ORDER BY id LIMIT 1",
                (memory_id,),
            ).fetchone()
        source = {
            "id": row["source_id"],
            "kind": row["source_kind"],
            "locator": row["locator"],
            "role": row["role"],
            "session_id": row["session_id"],
            "message_id": row["message_id"],
            "tool_name": row["tool_name"],
            "observed_at": row["observed_at"],
            "metadata": json.loads(row["metadata_json"]),
        }
        details = json.loads(event["detail_json"]) if event else {}
        return {
            "id": row["id"],
            "content": row["content"],
            "content_hash": row["content_hash"],
            "status": row["status"],
            "source": source,
            "quarantine_reasons": details.get("quarantine_reasons", []),
            "supersedes_id": row["supersedes_id"],
            "evidence_class": row["derivation_family"],
        }

    def memory_events(self, memory_id: str) -> list[dict[str, object]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, event_type, detail_json, node_id, parent_event_id, created_at "
                "FROM memory_events WHERE memory_id = ? ORDER BY id",
                (memory_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "detail": json.loads(row["detail_json"]),
                "node_id": row["node_id"],
                "parent_event_id": row["parent_event_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _lexical_ranked_ids(self, query: str, limit: int) -> list[str]:
        tokens = re.findall(r"[\w-]+", query, flags=re.UNICODE)
        if not tokens:
            return []
        fts_query = " AND ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT m.id
                FROM memory_fts f
                JOIN memories m ON m.id = f.memory_id
                WHERE memory_fts MATCH ?
                  AND m.status IN ('active', 'confirmed')
                ORDER BY bm25(memory_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        return [row["id"] for row in rows]

    def _vector_ranked_ids(self, query_vector: list[float], limit: int) -> list[str]:
        if len(query_vector) != EMBEDDING_DIM:
            raise ValueError(
                f"query_vector must have dimension {EMBEDDING_DIM} (model {EMBEDDING_MODEL_ID}), "
                f"got {len(query_vector)}"
            )
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT v.memory_id
                FROM memory_vectors v
                JOIN memories m ON m.id = v.memory_id
                WHERE v.embedding MATCH ? AND k = ?
                  AND m.status IN ('active', 'confirmed')
                ORDER BY distance
                """,
                (sqlite_vec.serialize_float32(query_vector), limit),
            ).fetchall()
        return [row["memory_id"] for row in rows]

    def search(
        self,
        query: str,
        *,
        query_vector: list[float] | None = None,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        """Recall active/confirmed memories.

        Lexical-only (FTS5/BM25) when query_vector is omitted -- unchanged v1 behavior. When
        query_vector is supplied (caller-computed; this store never runs an embedding model
        in-process, see EMBEDDING_MODEL_ID), fuses lexical and vector channels with Reciprocal
        Rank Fusion (k=60) rather than trusting either ranking alone.
        """
        bounded_limit = max(1, min(int(limit), 100))
        if query_vector is None:
            return [self.get_memory(memory_id) for memory_id in self._lexical_ranked_ids(query, bounded_limit)]

        candidate_pool = max(bounded_limit * 4, 20)
        lexical_ids = self._lexical_ranked_ids(query, candidate_pool)
        vector_ids = self._vector_ranked_ids(query_vector, candidate_pool)

        rrf_k = 60
        scores: dict[str, float] = {}
        for rank, memory_id in enumerate(lexical_ids, start=1):
            scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (rrf_k + rank)
        for rank, memory_id in enumerate(vector_ids, start=1):
            scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (rrf_k + rank)

        ranked = sorted(scores, key=lambda memory_id: scores[memory_id], reverse=True)
        return [self.get_memory(memory_id) for memory_id in ranked[:bounded_limit]]

    def store_embedding(
        self,
        memory_id: str,
        vector: list[float],
        *,
        model_id: str = EMBEDDING_MODEL_ID,
    ) -> dict[str, object]:
        """Attach a caller-computed embedding to a memory.

        This store never computes embeddings itself -- a local CPU model was benchmarked
        (BAAI/bge-small-en-v1.5: 77 embeds/sec, but ~270MB resident once loaded) and found too
        heavy to keep always-loaded inside this always-on server process on this machine's
        actual free RAM. The model_id/dim stay pinned so a mismatched vector is rejected rather
        than silently mixed with incompatible ones.
        """
        if model_id != EMBEDDING_MODEL_ID:
            raise ValueError(
                f"unsupported embedding model_id: {model_id!r} (this store only accepts "
                f"{EMBEDDING_MODEL_ID!r} vectors in v1)"
            )
        if len(vector) != EMBEDDING_DIM:
            raise ValueError(f"vector must have dimension {EMBEDDING_DIM}, got {len(vector)}")
        memory = self.get_memory(memory_id)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "DELETE FROM memory_vectors WHERE memory_id = ?", (memory_id,)
                )
                self._connection.execute(
                    "INSERT INTO memory_vectors(memory_id, embedding) VALUES (?, ?)",
                    (memory_id, sqlite_vec.serialize_float32(vector)),
                )
                self._connection.execute(
                    "INSERT OR REPLACE INTO embeddings_meta("
                    "memory_id, model_id, dim, generated_from_hash) VALUES (?, ?, ?, ?)",
                    (memory_id, model_id, EMBEDDING_DIM, memory["content_hash"]),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return {"memory_id": memory_id, "model_id": model_id, "dim": EMBEDDING_DIM}

    def attach_media(
        self,
        memory_id: str,
        file_path: str | Path,
        *,
        media_type: str | None = None,
        max_bytes: int = _DEFAULT_MAX_ATTACHMENT_BYTES,
    ) -> dict[str, object]:
        """Attach a screenshot, recording, or other binary artifact to a memory.

        Stored content-addressed on disk (`<home>/blobs/sha256/<hash>`), never as a SQLite BLOB
        -- keeps the canonical DB file small and fast, and reuses the same content-addressing
        convention as content_hash/node_id/leaf_hash elsewhere in this system. Identical bytes
        dedupe for free. The memory's own `content` stays text (a caption/description/transcript
        the calling agent supplies) -- raw pixels/audio are not searchable in v1, same
        agent-side-extraction principle already applied to embeddings.
        """
        self.get_memory(memory_id)  # raises KeyError if missing
        source_path = Path(file_path).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)

        byte_size = source_path.stat().st_size
        if byte_size > max_bytes:
            raise ValueError(
                f"attachment is {byte_size} bytes, exceeds max_bytes={max_bytes}"
            )

        digest = hashlib.sha256()
        with source_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        content_hash = "sha256:" + digest.hexdigest()

        if media_type is None:
            guessed, _ = mimetypes.guess_type(str(source_path))
            media_type = guessed or "application/octet-stream"

        blob_dir = self.home / "blobs" / "sha256" / digest.hexdigest()[:2]
        blob_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        blob_path = blob_dir / digest.hexdigest()
        if not blob_path.exists():
            shutil.copyfile(source_path, blob_path)
            os.chmod(blob_path, 0o600)

        attachment_id = str(uuid.uuid4())
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """
                    INSERT INTO attachments(
                        id, memory_id, media_type, content_hash, byte_size, storage_locator
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (attachment_id, memory_id, media_type, content_hash, byte_size, str(blob_path)),
                )
                self._append_event(
                    memory_id,
                    "attach_media",
                    {
                        "attachment_id": attachment_id,
                        "media_type": media_type,
                        "content_hash": content_hash,
                        "byte_size": byte_size,
                    },
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return self.get_attachment(attachment_id)

    def get_attachment(self, attachment_id: str) -> dict[str, object]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
            ).fetchone()
        if row is None:
            raise KeyError(attachment_id)
        return {
            "id": row["id"],
            "memory_id": row["memory_id"],
            "media_type": row["media_type"],
            "content_hash": row["content_hash"],
            "byte_size": row["byte_size"],
            "storage_locator": row["storage_locator"],
            "created_at": row["created_at"],
        }

    def list_attachments(self, memory_id: str) -> list[dict[str, object]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id FROM attachments WHERE memory_id = ? ORDER BY created_at, id",
                (memory_id,),
            ).fetchall()
        return [self.get_attachment(row["id"]) for row in rows]

    def supersede_memory(
        self,
        old_id: str,
        new_content: str,
        *,
        source: dict[str, object],
        status: str = "confirmed",
        idempotency_key: str | None = None,
        evidence_class: str = "observed_event",
    ) -> dict[str, object]:
        self.get_memory(old_id)  # raises KeyError if missing
        new = self.store_memory(
            new_content,
            source=source,
            status=status,
            idempotency_key=idempotency_key,
            evidence_class=evidence_class,
        )
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "UPDATE memories SET status = 'superseded' WHERE id = ?", (old_id,)
                )
                self._connection.execute(
                    "UPDATE memories SET supersedes_id = ? WHERE id = ?", (old_id, new["id"])
                )
                self._append_event(old_id, "supersede", {"superseded_by": new["id"]})
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return self.get_memory(new["id"])

    def mark_contradiction(
        self, memory_id_a: str, memory_id_b: str, reason: str
    ) -> dict[str, object]:
        self.get_memory(memory_id_a)
        self.get_memory(memory_id_b)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    "INSERT INTO contradictions(memory_id_a, memory_id_b, reason) VALUES (?, ?, ?)",
                    (memory_id_a, memory_id_b, reason),
                )
                for memory_id, other_id in ((memory_id_a, memory_id_b), (memory_id_b, memory_id_a)):
                    self._append_event(
                        memory_id, "contradict", {"contradicts": other_id, "reason": reason}
                    )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return {"status": "recorded", "memory_id_a": memory_id_a, "memory_id_b": memory_id_b}

    def contradictions(self, memory_id: str) -> list[dict[str, object]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT memory_id_a, memory_id_b, reason FROM contradictions "
                "WHERE memory_id_a = ? OR memory_id_b = ?",
                (memory_id, memory_id),
            ).fetchall()
        others = []
        for row in rows:
            other_id = row["memory_id_b"] if row["memory_id_a"] == memory_id else row["memory_id_a"]
            others.append(self.get_memory(other_id))
        return others

    def forget_memory(self, memory_id: str) -> dict[str, object]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = self._connection.execute(
                    "UPDATE memories SET status = 'forgotten' WHERE id = ?", (memory_id,)
                )
                if cursor.rowcount == 0:
                    raise KeyError(memory_id)
                self._append_event(memory_id, "forget", {})
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        record = self.get_memory(memory_id)
        record["content_hash_retained"] = True
        return record

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.strip().lower().split())

    def _find_entity(self, name: str) -> sqlite3.Row | None:
        normalized = self._normalize_name(name)
        return self._connection.execute(
            "SELECT * FROM entities WHERE normalized_name = ? LIMIT 1", (normalized,)
        ).fetchone()

    def _get_or_create_entity(self, name: str, entity_type: str = "unknown") -> sqlite3.Row:
        normalized = self._normalize_name(name)
        row = self._connection.execute(
            "SELECT * FROM entities WHERE normalized_name = ? AND entity_type = ?",
            (normalized, entity_type),
        ).fetchone()
        if row is not None:
            return row
        entity_id = str(uuid.uuid4())
        self._connection.execute(
            "INSERT INTO entities(id, canonical_name, normalized_name, entity_type) VALUES (?, ?, ?, ?)",
            (entity_id, name.strip(), normalized, entity_type),
        )
        return self._connection.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()

    def link_entities(
        self,
        subject_name: str,
        predicate: str,
        object_name: str,
        *,
        evidence_memory_id: str,
        confidence: float = 1.0,
    ) -> dict[str, object]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                subject = self._get_or_create_entity(subject_name)
                obj = self._get_or_create_entity(object_name)
                relation_id = str(uuid.uuid4())
                self._connection.execute(
                    """
                    INSERT INTO relations(
                        id, subject_entity_id, predicate, object_entity_id,
                        evidence_memory_id, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (relation_id, subject["id"], predicate, obj["id"], evidence_memory_id, confidence),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return {
            "id": relation_id,
            "subject": subject_name,
            "predicate": predicate,
            "object": object_name,
            "evidence_memory_id": evidence_memory_id,
        }

    def neighbors(
        self, subject_name: str, *, max_depth: int = 1, node_limit: int = 50, edge_limit: int = 200
    ) -> dict[str, object]:
        if not isinstance(max_depth, int) or not (1 <= max_depth <= 3):
            raise ValueError("max_depth must be an integer between 1 and 3")
        with self._lock:
            entity = self._find_entity(subject_name)
            if entity is None:
                return {"truncated": False, "edges": []}
            visited = {entity["id"]}
            frontier = [entity["id"]]
            edges: list[dict[str, object]] = []
            truncated = False
            for _ in range(max_depth):
                if not frontier:
                    break
                next_frontier: list[str] = []
                placeholders = ",".join("?" * len(frontier))
                rows = self._connection.execute(
                    f"""
                    SELECT r.predicate, r.object_entity_id, r.object_literal, r.evidence_memory_id,
                           oe.canonical_name AS object_name
                    FROM relations r
                    LEFT JOIN entities oe ON oe.id = r.object_entity_id
                    WHERE r.subject_entity_id IN ({placeholders}) AND r.status = 'active'
                    ORDER BY r.created_at, r.id
                    """,
                    frontier,
                ).fetchall()
                for row in rows:
                    if len(edges) >= edge_limit:
                        truncated = True
                        break
                    edges.append(
                        {
                            "predicate": row["predicate"],
                            "object": row["object_name"] or row["object_literal"],
                            "evidence_memory_id": row["evidence_memory_id"],
                        }
                    )
                    target_id = row["object_entity_id"]
                    if target_id and target_id not in visited:
                        if len(visited) >= node_limit:
                            truncated = True
                        else:
                            visited.add(target_id)
                            next_frontier.append(target_id)
                frontier = next_frontier
        return {"truncated": truncated, "edges": edges}

    def find_path(
        self, from_name: str, to_name: str, *, max_depth: int = 3
    ) -> dict[str, object]:
        if not isinstance(max_depth, int) or not (1 <= max_depth <= 5):
            raise ValueError("max_depth must be an integer between 1 and 5")
        with self._lock:
            start = self._find_entity(from_name)
            goal = self._find_entity(to_name)
            if start is None or goal is None or start["id"] == goal["id"]:
                return {"edges": []}
            visited = {start["id"]}
            queue: list[tuple[str, list[dict[str, object]]]] = [(start["id"], [])]
            while queue:
                current_id, path = queue.pop(0)
                if len(path) >= max_depth:
                    continue
                rows = self._connection.execute(
                    """
                    SELECT r.predicate, r.object_entity_id, r.object_literal,
                           oe.canonical_name AS object_name
                    FROM relations r
                    LEFT JOIN entities oe ON oe.id = r.object_entity_id
                    WHERE r.subject_entity_id = ? AND r.status = 'active'
                    ORDER BY r.created_at, r.id
                    """,
                    (current_id,),
                ).fetchall()
                for row in rows:
                    edge = {
                        "predicate": row["predicate"],
                        "object": row["object_name"] or row["object_literal"],
                    }
                    new_path = path + [edge]
                    target_id = row["object_entity_id"]
                    if target_id == goal["id"]:
                        return {"edges": new_path}
                    if target_id and target_id not in visited:
                        visited.add(target_id)
                        queue.append((target_id, new_path))
        return {"edges": []}

    def close(self) -> None:
        with self._lock:
            self._connection.close()
