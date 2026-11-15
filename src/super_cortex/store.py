from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .models import (
    AgentRecord,
    EntityRecord,
    EventRecord,
    ExchangeRecord,
    LifecycleStatus,
    MemoryRecord,
    RelationRecord,
    ScopeRecord,
    ScopeType,
    utc_now_iso,
)

GENESIS_HASH = "0" * 64


def canonical_json(data: Any) -> str:
    """Deterministic canonical JSON encoding for cryptographic hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def compute_merkle_root(leaf_hashes: list[str]) -> str:
    """Compute binary Merkle root from a list of hexadecimal hashes."""
    if not leaf_hashes:
        return GENESIS_HASH

    current_level = leaf_hashes
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if i + 1 < len(current_level) else left
            combined = sha256_hex(left + right)
            next_level.append(combined)
        current_level = next_level

    return current_level[0]


def compute_merkle_proof(leaf_hashes: list[str], target_index: int) -> list[dict[str, str]]:
    """Compute audit proof path (siblings) for a specific leaf index."""
    if not leaf_hashes or target_index < 0 or target_index >= len(leaf_hashes):
        return []

    proof = []
    current_level = leaf_hashes[:]
    idx = target_index

    while len(current_level) > 1:
        sibling_idx = idx + 1 if idx % 2 == 0 else idx - 1
        if sibling_idx < len(current_level):
            sibling_hash = current_level[sibling_idx]
            position = "right" if idx % 2 == 0 else "left"
            proof.append({"position": position, "hash": sibling_hash})
        else:
            proof.append({"position": "right", "hash": current_level[idx]})

        next_level = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if i + 1 < len(current_level) else left
            next_level.append(sha256_hex(left + right))

        current_level = next_level
        idx = idx // 2

    return proof


def verify_merkle_proof(leaf_hash: str, proof: list[dict[str, str]], expected_root: str) -> bool:
    """Recompute root from leaf hash using audit proof path and check against expected root."""
    curr = leaf_hash
    for step in proof:
        if step["position"] == "right":
            curr = sha256_hex(curr + step["hash"])
        else:
            curr = sha256_hex(step["hash"] + curr)
    return curr == expected_root


class ProvenanceStore:
    """Cryptographic provenance ledger and entity graph backed by SQLite."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    prior_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    transition TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    source_id TEXT,
                    text TEXT NOT NULL,
                    epistemic_class TEXT NOT NULL,
                    lifecycle_status TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    label TEXT UNIQUE NOT NULL,
                    aliases_json TEXT NOT NULL,
                    evidence_links_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS relations (
                    relation_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_links_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS exchanges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange_id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    response_text TEXT NOT NULL,
                    response_hash TEXT NOT NULL,
                    tool_calls_json TEXT NOT NULL,
                    context_hashes_json TEXT NOT NULL,
                    turn_hash TEXT NOT NULL,
                    parent_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace);
                CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(lifecycle_status);
                CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject);
                CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object);
                CREATE INDEX IF NOT EXISTS idx_exchanges_session ON exchanges(session_id);

                CREATE TABLE IF NOT EXISTS scopes (
                    scope_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    agent_id TEXT,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    default_scope_id TEXT NOT NULL,
                    client_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_active_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_scopes_type ON scopes(scope_type);
                CREATE INDEX IF NOT EXISTS idx_scopes_agent ON scopes(agent_id);
                """
            )
            # Seed default scopes if none exist
            cursor = conn.execute("SELECT COUNT(*) as count FROM scopes")
            if cursor.fetchone()["count"] == 0:
                now = utc_now_iso()
                default_scopes = [
                    ("shared", "Shared Memory Fabric", ScopeType.SHARED.value, None, "Collective operational knowledge accessible across all authorized agent scopes", now),
                    ("agent:xibalba", "Xibalba Executive Scope", ScopeType.SINGLE_AGENT.value, "xibalba", "Isolated operational memory enclave for Xibalba orchestrator", now),
                    ("agent:hermes", "Hermes Agent Scope", ScopeType.SINGLE_AGENT.value, "hermes", "Private operational memory for Hermes agent", now),
                    ("agent:claude", "Claude Code Scope", ScopeType.SINGLE_AGENT.value, "claude", "Private operational memory for Claude Code CLI sessions", now),
                    ("agent:shield", "Xibalba Shield Scope", ScopeType.SINGLE_AGENT.value, "shield", "Private operational memory for Xibalba Shield defensive monitoring", now),
                ]
                conn.executemany(
                    "INSERT INTO scopes (scope_id, name, scope_type, agent_id, description, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    default_scopes,
                )

            # Seed default agents if none exist
            cursor = conn.execute("SELECT COUNT(*) as count FROM agents")
            if cursor.fetchone()["count"] == 0:
                now = utc_now_iso()
                default_agents = [
                    ("xibalba", "Xibalba Orchestrator", "shared", "antigravity", "active", now, now),
                    ("hermes", "Hermes Core Agent", "agent:hermes", "hermes", "active", now, now),
                    ("claude", "Claude Code CLI", "agent:claude", "claude_code", "active", now, now),
                    ("shield", "Xibalba Shield", "agent:shield", "shield", "active", now, now),
                ]
                conn.executemany(
                    "INSERT INTO agents (agent_id, name, default_scope_id, client_type, status, last_active_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    default_agents,
                )
            conn.commit()

    def append_event(self, actor: str, transition: str, payload: dict[str, Any]) -> EventRecord:
        """Append an event to the append-only cryptographic hash chain."""
        timestamp = utc_now_iso()
        event_id = f"evt_{uuid.uuid4().hex}"
        payload_str = canonical_json(payload)

        with self._get_conn() as conn:
            cursor = conn.execute("SELECT event_hash FROM events ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            prior_hash = row["event_hash"] if row else GENESIS_HASH

            raw_to_hash = f"{prior_hash}:{timestamp}:{actor}:{transition}:{payload_str}"
            event_hash = sha256_hex(raw_to_hash)

            conn.execute(
                """
                INSERT INTO events (event_id, prior_hash, event_hash, actor, transition, timestamp, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, prior_hash, event_hash, actor, transition, timestamp, payload_str),
            )
            conn.commit()

        return EventRecord(
            event_id=event_id,
            prior_hash=prior_hash,
            event_hash=event_hash,
            actor=actor,
            transition=transition,
            timestamp=timestamp,
            payload=payload,
        )

    def verify_chain(self) -> dict[str, Any]:
        """Verify the integrity of the event hash chain."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT event_id, prior_hash, event_hash, actor, transition, timestamp, payload_json FROM events ORDER BY id ASC"
            )
            rows = cursor.fetchall()

        if not rows:
            return {"valid": True, "event_count": 0, "head_hash": GENESIS_HASH}

        expected_prior = GENESIS_HASH
        for idx, row in enumerate(rows):
            if row["prior_hash"] != expected_prior:
                return {
                    "valid": False,
                    "error": f"Prior hash mismatch at index {idx}",
                    "event_id": row["event_id"],
                    "expected_prior": expected_prior,
                    "found_prior": row["prior_hash"],
                }

            raw_to_hash = f"{row['prior_hash']}:{row['timestamp']}:{row['actor']}:{row['transition']}:{row['payload_json']}"
            computed_hash = sha256_hex(raw_to_hash)
            if computed_hash != row["event_hash"]:
                return {
                    "valid": False,
                    "error": f"Event hash corruption at index {idx}",
                    "event_id": row["event_id"],
                    "expected_hash": computed_hash,
                    "found_hash": row["event_hash"],
                }

            expected_prior = row["event_hash"]

        return {"valid": True, "event_count": len(rows), "head_hash": expected_prior}

    def save_memory(self, memory: MemoryRecord) -> None:
        """Store or update a memory in the ledger."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO memories (id, source_id, text, epistemic_class, lifecycle_status, content_hash, namespace, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    text = excluded.text,
                    epistemic_class = excluded.epistemic_class,
                    lifecycle_status = excluded.lifecycle_status,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    memory.id,
                    memory.source_id,
                    memory.text,
                    memory.epistemic_class,
                    memory.lifecycle_status,
                    memory.content_hash,
                    memory.namespace,
                    canonical_json(memory.metadata),
                    memory.created_at,
                    memory.updated_at,
                ),
            )
            conn.commit()

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        """Fetch a memory record by ID."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT id, source_id, text, epistemic_class, lifecycle_status, content_hash, namespace, metadata_json, created_at, updated_at FROM memories WHERE id = ?",
                (memory_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return MemoryRecord(
                id=row["id"],
                source_id=row["source_id"],
                text=row["text"],
                epistemic_class=row["epistemic_class"],
                lifecycle_status=row["lifecycle_status"],
                content_hash=row["content_hash"],
                namespace=row["namespace"],
                metadata=json.loads(row["metadata_json"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def update_memory_status(self, memory_id: str, status: LifecycleStatus) -> bool:
        """Update lifecycle status of a memory."""
        now = utc_now_iso()
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE memories SET lifecycle_status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, memory_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def add_entity(self, label: str, aliases: list[str] | None = None, evidence_links: list[str] | None = None) -> EntityRecord:
        """Insert or retrieve an entity node."""
        aliases = aliases or []
        evidence_links = evidence_links or []
        now = utc_now_iso()

        with self._get_conn() as conn:
            cursor = conn.execute("SELECT entity_id, label, aliases_json, evidence_links_json, created_at FROM entities WHERE label = ?", (label,))
            row = cursor.fetchone()
            if row:
                existing_aliases = set(json.loads(row["aliases_json"]))
                existing_aliases.update(aliases)
                existing_evidence = set(json.loads(row["evidence_links_json"]))
                existing_evidence.update(evidence_links)

                conn.execute(
                    "UPDATE entities SET aliases_json = ?, evidence_links_json = ? WHERE entity_id = ?",
                    (canonical_json(sorted(existing_aliases)), canonical_json(sorted(existing_evidence)), row["entity_id"]),
                )
                conn.commit()
                return EntityRecord(
                    entity_id=row["entity_id"],
                    label=row["label"],
                    aliases=sorted(existing_aliases),
                    evidence_links=sorted(existing_evidence),
                    created_at=row["created_at"],
                )

            entity_id = f"ent_{uuid.uuid4().hex[:16]}"
            conn.execute(
                "INSERT INTO entities (entity_id, label, aliases_json, evidence_links_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (entity_id, label, canonical_json(aliases), canonical_json(evidence_links), now),
            )
            conn.commit()

        return EntityRecord(
            entity_id=entity_id,
            label=label,
            aliases=aliases,
            evidence_links=evidence_links,
            created_at=now,
        )

    def add_relation(
        self,
        subject: str,
        predicate: str,
        object: str,
        confidence: float = 1.0,
        evidence_links: list[str] | None = None,
    ) -> RelationRecord:
        """Add a directed relation edge between subject and object."""
        evidence_links = evidence_links or []
        relation_id = f"rel_{uuid.uuid4().hex[:16]}"
        now = utc_now_iso()

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO relations (relation_id, subject, predicate, object, confidence, evidence_links_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (relation_id, subject, predicate, object, confidence, canonical_json(evidence_links), now),
            )
            conn.commit()

        return RelationRecord(
            relation_id=relation_id,
            subject=subject,
            predicate=predicate,
            object=object,
            confidence=confidence,
            evidence_links=evidence_links,
            created_at=now,
        )

    def get_neighbors(self, node: str, max_depth: int = 1) -> list[dict[str, Any]]:
        """Get neighboring relations where node is subject or object."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT relation_id, subject, predicate, object, confidence, evidence_links_json, created_at
                FROM relations
                WHERE subject = ? OR object = ?
                """,
                (node, node),
            )
            rows = cursor.fetchall()

        results = []
        for r in rows:
            results.append({
                "relation_id": r["relation_id"],
                "subject": r["subject"],
                "predicate": r["predicate"],
                "object": r["object"],
                "confidence": r["confidence"],
                "evidence_links": json.loads(r["evidence_links_json"]),
                "created_at": r["created_at"],
            })
        return results

    def save_exchange(
        self,
        session_id: str,
        prompt_text: str,
        response_text: str,
        tool_calls: list[dict[str, Any]] | None = None,
        context_hashes: list[str] | None = None,
    ) -> ExchangeRecord:
        """Capture a model exchange turn with cryptographic hash link."""
        tool_calls = tool_calls or []
        context_hashes = context_hashes or []
        exchange_id = f"exch_{uuid.uuid4().hex[:16]}"
        now = utc_now_iso()

        prompt_hash = sha256_hex(prompt_text)
        response_hash = sha256_hex(response_text)
        tools_str = canonical_json(tool_calls)
        context_str = canonical_json(context_hashes)

        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT turn_hash FROM exchanges WHERE session_id = ? ORDER BY rowid DESC LIMIT 1",
                (session_id,),
            )
            row = cursor.fetchone()
            parent_hash = row["turn_hash"] if row else GENESIS_HASH

            turn_raw = f"{parent_hash}:{session_id}:{prompt_hash}:{response_hash}:{tools_str}:{context_str}:{now}"
            turn_hash = sha256_hex(turn_raw)

            conn.execute(
                """
                INSERT INTO exchanges (exchange_id, session_id, prompt_text, prompt_hash, response_text, response_hash, tool_calls_json, context_hashes_json, turn_hash, parent_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exchange_id,
                    session_id,
                    prompt_text,
                    prompt_hash,
                    response_text,
                    response_hash,
                    tools_str,
                    context_str,
                    turn_hash,
                    parent_hash,
                    now,
                ),
            )
            conn.commit()

        return ExchangeRecord(
            exchange_id=exchange_id,
            session_id=session_id,
            prompt_text=prompt_text,
            prompt_hash=prompt_hash,
            response_text=response_text,
            response_hash=response_hash,
            tool_calls=tool_calls,
            context_hashes=context_hashes,
            turn_hash=turn_hash,
            parent_hash=parent_hash,
            created_at=now,
        )

    def session_merkle_root(self, session_id: str) -> str:
        """Compute the domain-separated Merkle root for all exchanges in a session."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT turn_hash FROM exchanges WHERE session_id = ? ORDER BY rowid ASC",
                (session_id,),
            )
            rows = cursor.fetchall()

        if not rows:
            return GENESIS_HASH

        leaf_hashes = [r["turn_hash"] for r in rows]
        return compute_merkle_root(leaf_hashes)

    def get_session_merkle_proof(self, session_id: str, turn_index: int = 0) -> dict[str, Any]:
        """Generate a complete cryptographic inclusion proof for a specific exchange turn in a session."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT turn_hash, exchange_id FROM exchanges WHERE session_id = ? ORDER BY rowid ASC",
                (session_id,),
            )
            rows = cursor.fetchall()

        if not rows or turn_index >= len(rows):
            return {"verified": False, "error": "Invalid turn index or empty session"}

        leaf_hashes = [r["turn_hash"] for r in rows]
        target_leaf = leaf_hashes[turn_index]
        root = compute_merkle_root(leaf_hashes)
        proof = compute_merkle_proof(leaf_hashes, turn_index)
        valid = verify_merkle_proof(target_leaf, proof, root)

        return {
            "session_id": session_id,
            "turn_index": turn_index,
            "exchange_id": rows[turn_index]["exchange_id"],
            "target_turn_hash": target_leaf,
            "merkle_root": root,
            "proof_depth": len(proof),
            "proof_path": proof,
            "verified": valid,
        }

    def get_session_distribution(self) -> list[dict[str, Any]]:
        """Retrieve temporal distribution of all agent interaction sessions."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT
                    session_id,
                    MIN(created_at) as start_time,
                    MAX(created_at) as end_time,
                    COUNT(*) as turn_count,
                    GROUP_CONCAT(tool_calls_json) as all_tools
                FROM exchanges
                GROUP BY session_id
                ORDER BY start_time DESC
                """
            )
            rows = cursor.fetchall()

        sessions = []
        for r in rows:
            sid = r["session_id"]
            root = self.session_merkle_root(sid)
            # Count total tool executions
            tool_count = 0
            if r["all_tools"]:
                for chunk in r["all_tools"].split("],["):
                    tool_count += chunk.count('"name"')

            sessions.append({
                "session_id": sid,
                "start_time": r["start_time"],
                "end_time": r["end_time"],
                "turn_count": r["turn_count"],
                "tool_execution_count": tool_count,
                "merkle_root": root,
            })
        return sessions

    def get_session_turns(self, session_id: str) -> list[dict[str, Any]]:
        """Get chronological turns for a specific session."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT exchange_id, session_id, prompt_text, prompt_hash, response_text, response_hash,
                       tool_calls_json, context_hashes_json, turn_hash, parent_hash, created_at
                FROM exchanges
                WHERE session_id = ?
                ORDER BY rowid ASC
                """,
                (session_id,),
            )
            rows = cursor.fetchall()

        return [
            {
                "exchange_id": r["exchange_id"],
                "session_id": r["session_id"],
                "prompt_text": r["prompt_text"],
                "response_text": r["response_text"],
                "tool_calls": json.loads(r["tool_calls_json"]),
                "turn_hash": r["turn_hash"],
                "parent_hash": r["parent_hash"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def save_scope(self, scope: ScopeRecord) -> None:
        """Store or update a memory scope."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO scopes (scope_id, name, scope_type, agent_id, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_id) DO UPDATE SET
                    name = excluded.name,
                    scope_type = excluded.scope_type,
                    agent_id = excluded.agent_id,
                    description = excluded.description
                """,
                (
                    scope.scope_id,
                    scope.name,
                    scope.scope_type,
                    scope.agent_id,
                    scope.description,
                    scope.created_at,
                ),
            )
            conn.commit()

    def list_scopes(self) -> list[ScopeRecord]:
        """List all registered scopes."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT scope_id, name, scope_type, agent_id, description, created_at FROM scopes ORDER BY created_at ASC"
            )
            rows = cursor.fetchall()

        return [
            ScopeRecord(
                scope_id=r["scope_id"],
                name=r["name"],
                scope_type=r["scope_type"],
                agent_id=r["agent_id"],
                description=r["description"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_scope(self, scope_id: str) -> ScopeRecord | None:
        """Get a single scope by id."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT scope_id, name, scope_type, agent_id, description, created_at FROM scopes WHERE scope_id = ?",
                (scope_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            return ScopeRecord(
                scope_id=r["scope_id"],
                name=r["name"],
                scope_type=r["scope_type"],
                agent_id=r["agent_id"],
                description=r["description"],
                created_at=r["created_at"],
            )

    def save_agent(self, agent: AgentRecord) -> None:
        """Store or update an AI agent registration."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO agents (agent_id, name, default_scope_id, client_type, status, last_active_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    name = excluded.name,
                    default_scope_id = excluded.default_scope_id,
                    client_type = excluded.client_type,
                    status = excluded.status,
                    last_active_at = excluded.last_active_at
                """,
                (
                    agent.agent_id,
                    agent.name,
                    agent.default_scope_id,
                    agent.client_type,
                    agent.status,
                    agent.last_active_at,
                    agent.created_at,
                ),
            )
            conn.commit()

    def list_agents(self) -> list[AgentRecord]:
        """List all registered agents."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT agent_id, name, default_scope_id, client_type, status, last_active_at, created_at FROM agents ORDER BY created_at ASC"
            )
            rows = cursor.fetchall()

        return [
            AgentRecord(
                agent_id=r["agent_id"],
                name=r["name"],
                default_scope_id=r["default_scope_id"],
                client_type=r["client_type"],
                status=r["status"],
                last_active_at=r["last_active_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        """Get an agent by id."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT agent_id, name, default_scope_id, client_type, status, last_active_at, created_at FROM agents WHERE agent_id = ?",
                (agent_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            return AgentRecord(
                agent_id=r["agent_id"],
                name=r["name"],
                default_scope_id=r["default_scope_id"],
                client_type=r["client_type"],
                status=r["status"],
                last_active_at=r["last_active_at"],
                created_at=r["created_at"],
            )

    def touch_agent_active(self, agent_id: str) -> None:
        """Update last active timestamp of an agent."""
        now = utc_now_iso()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE agents SET last_active_at = ? WHERE agent_id = ?",
                (now, agent_id),
            )
            conn.commit()

    def count_memories_by_scope(self) -> dict[str, int]:
        """Count memories grouped by scope (parsed from metadata_json or namespace)."""
        counts: dict[str, int] = {}
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT metadata_json, namespace FROM memories")
            for row in cursor.fetchall():
                try:
                    meta = json.loads(row["metadata_json"])
                    scope = meta.get("scope") or row["namespace"] or "shared"
                except Exception:
                    scope = row["namespace"] or "shared"
                counts[scope] = counts.get(scope, 0) + 1
        return counts

    def list_memories(
        self,
        scope: str | None = None,
        epistemic_class: str | None = None,
        search_query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List stored memories with filtering support."""
        with self._get_conn() as conn:
            query = "SELECT * FROM memories WHERE lifecycle_status != 'archived'"
            params: list[Any] = []
            if epistemic_class and epistemic_class != "all":
                query += " AND epistemic_class = ?"
                params.append(epistemic_class)
            if search_query:
                query += " AND text LIKE ?"
                params.append(f"%{search_query}%")
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            results = []
            for r in rows:
                meta = {}
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    pass
                m_scope = meta.get("scope", "shared")
                if scope and scope != "all" and m_scope != scope:
                    continue
                valid_time = meta.get("valid_time") or {
                    "valid_from": r["created_at"],
                    "valid_until": None,
                    "is_currently_valid": r["lifecycle_status"] == "active",
                }
                results.append({
                    "id": r["id"],
                    "source_id": r["source_id"],
                    "text": r["text"],
                    "epistemic_class": r["epistemic_class"],
                    "lifecycle_status": r["lifecycle_status"],
                    "content_hash": r["content_hash"],
                    "namespace": r["namespace"],
                    "scope": m_scope,
                    "agent_id": meta.get("agent_id"),
                    "para": meta.get("para", {}),
                    "triples": meta.get("triples", []),
                    "valid_time": valid_time,
                    "tags": meta.get("tags", []),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                })
            return results

    def delete_memory(self, memory_id: str) -> bool:
        """Mark memory archived and remove from active index."""
        return self.update_memory_status(memory_id, LifecycleStatus.ARCHIVED)
