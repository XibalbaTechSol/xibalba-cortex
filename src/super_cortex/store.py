from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    AgentRecord,
    EntityRecord,
    EventRecord,
    ExchangeRecord,
    LifecycleStatus,
    MemoryRecord,
    ProviderRecord,
    ProviderType,
    RelationRecord,
    ScopeRecord,
    ScopeType,
    TenantKeyRecord,
    TenantPlan,
    TenantRecord,
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
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
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
                    thinking_text TEXT DEFAULT '',
                    tool_calls_json TEXT NOT NULL,
                    context_hashes_json TEXT NOT NULL,
                    turn_hash TEXT NOT NULL,
                    parent_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    scope_id TEXT,
                    agent_id TEXT
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

                CREATE TABLE IF NOT EXISTS providers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider_type TEXT NOT NULL,
                    api_key TEXT,
                    base_url TEXT,
                    default_model TEXT,
                    is_active INTEGER DEFAULT 0,
                    settings_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    plan TEXT NOT NULL DEFAULT 'starter',
                    rate_limit_rpm INTEGER DEFAULT 60,
                    daily_quota_requests INTEGER DEFAULT 10000,
                    is_active INTEGER DEFAULT 1,
                    metadata_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tenant_keys (
                    key_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    key_hash TEXT NOT NULL UNIQUE,
                    key_prefix TEXT NOT NULL,
                    label TEXT NOT NULL,
                    scopes_json TEXT NOT NULL DEFAULT '["read:graph","read:memory","write:memory","exec:deterministic"]',
                    rate_limit_rpm INTEGER DEFAULT 60,
                    requests_count INTEGER DEFAULT 0,
                    zero_inference_tokens_saved INTEGER DEFAULT 0,
                    last_used_at TEXT,
                    expires_at TEXT,
                    is_revoked INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_scopes_type ON scopes(scope_type);
                CREATE INDEX IF NOT EXISTS idx_scopes_agent ON scopes(agent_id);
                CREATE INDEX IF NOT EXISTS idx_providers_active ON providers(is_active);
                CREATE INDEX IF NOT EXISTS idx_tenant_keys_hash ON tenant_keys(key_hash);
                CREATE INDEX IF NOT EXISTS idx_tenant_keys_tenant ON tenant_keys(tenant_id);
                """
            )
            # Automatic column migration for existing databases
            try:
                conn.execute("ALTER TABLE exchanges ADD COLUMN thinking_text TEXT DEFAULT ''")
            except Exception:
                pass

            # Seed default scopes if none exist
            cursor = conn.execute("SELECT COUNT(*) as count FROM scopes")
            if cursor.fetchone()["count"] == 0:
                now = utc_now_iso()
                default_scopes = [
                    ("shared", "Xibalba Solutions", ScopeType.SHARED.value, None, "Company-wide memory shared by every Xibalba Solutions agent", now),
                    ("agent:xibalba", "Xibalba Executive Scope", ScopeType.SINGLE_AGENT.value, "xibalba", "Isolated operational memory enclave for Xibalba orchestrator", now),
                    ("agent:hermes", "Hermes Agent Scope", ScopeType.SINGLE_AGENT.value, "hermes", "Private operational memory for Hermes agent", now),
                    ("agent:agy", "Antigravity Agent Scope", ScopeType.SINGLE_AGENT.value, "agy", "Autonomous workspace orchestration and swarm execution memory", now),
                    ("agent:claude", "Claude Code Scope", ScopeType.SINGLE_AGENT.value, "claude", "Private operational memory for Claude Code CLI sessions", now),
                    ("agent:cortex", "Xibalba Cortex Scope", ScopeType.SINGLE_AGENT.value, "cortex", "Graph Laplacian & Epistemic verification memory engine", now),
                    ("agent:cursor", "Cursor IDE Scope", ScopeType.SINGLE_AGENT.value, "cursor", "Composer agent code synthesis and editor workspace memory", now),
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
                    ("hermes", "Hermes Prime", "agent:hermes", "hermes", "active", now, now),
                    ("agy", "Antigravity Controller", "agent:agy", "antigravity", "active", now, now),
                    ("claude", "Claude Code CLI", "agent:claude", "claude_code", "active", now, now),
                    ("cortex", "Xibalba Cortex", "agent:cortex", "cortex", "active", now, now),
                    ("cursor", "Cursor IDE Composer", "agent:cursor", "cursor", "active", now, now),
                    ("shield", "Xibalba Shield", "agent:shield", "shield", "active", now, now),
                ]
                conn.executemany(
                    "INSERT INTO agents (agent_id, name, default_scope_id, client_type, status, last_active_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    default_agents,
                )

            # Seed default providers if none exist
            cursor = conn.execute("SELECT COUNT(*) as count FROM providers")
            if cursor.fetchone()["count"] == 0:
                import os
                now = utc_now_iso()
                gemini_env = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
                anthropic_env = os.getenv("ANTHROPIC_API_KEY") or ""
                openai_env = os.getenv("OPENAI_API_KEY") or ""
                groq_env = os.getenv("GROQ_API_KEY") or ""

                has_gemini = bool(gemini_env)
                default_providers = [
                    (
                        "gemini",
                        "Google Gemini",
                        ProviderType.GEMINI.value,
                        gemini_env,
                        "https://generativelanguage.googleapis.com/v1beta",
                        "gemini-2.5-flash",
                        1 if has_gemini else 0,
                        json.dumps({"description": "Google Gemini 2.5 Flash / Pro Multimodal Engine", "rpm_limit": 60}),
                        now,
                        now,
                    ),
                    (
                        "anthropic",
                        "Anthropic Claude",
                        ProviderType.ANTHROPIC.value,
                        anthropic_env,
                        "https://api.anthropic.com/v1",
                        "claude-3-7-sonnet-20250219",
                        1 if (not has_gemini and anthropic_env) else 0,
                        json.dumps({"description": "Anthropic Claude 3.7 / 3.5 Sonnet Deep Reasoning", "max_tokens": 1500}),
                        now,
                        now,
                    ),
                    (
                        "openai",
                        "OpenAI",
                        ProviderType.OPENAI.value,
                        openai_env,
                        "https://api.openai.com/v1",
                        "gpt-4o",
                        0,
                        json.dumps({"description": "OpenAI GPT-4o / GPT-4o-mini", "max_tokens": 1500}),
                        now,
                        now,
                    ),
                    (
                        "groq",
                        "Groq LPU",
                        ProviderType.GROQ.value,
                        groq_env,
                        "https://api.groq.com/openai/v1",
                        "llama-3.3-70b-versatile",
                        0,
                        json.dumps({"description": "Groq Ultra-Fast LPU Inference"}),
                        now,
                        now,
                    ),
                    (
                        "ollama",
                        "Ollama Local",
                        ProviderType.OLLAMA.value,
                        "",
                        "http://localhost:11434/v1",
                        "llama3.2",
                        0,
                        json.dumps({"description": "Local Offline Ollama Endpoint"}),
                        now,
                        now,
                    ),
                ]
                conn.executemany(
                    """
                    INSERT INTO providers (id, name, provider_type, api_key, base_url, default_model, is_active, settings_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    default_providers,
                )

            # Seed default tenants if none exist
            cursor = conn.execute("SELECT COUNT(*) as count FROM tenants")
            if cursor.fetchone()["count"] == 0:
                now = utc_now_iso()
                default_tenants = [
                    (
                        "tenant_xibalba_core",
                        "Xibalba Enterprise Cluster",
                        TenantPlan.ENTERPRISE.value,
                        1200,
                        100000,
                        1,
                        json.dumps({"company": "Xibalba Solutions LLC", "tier": "Enterprise Multi-Agent Orchestration", "contact": "engineering@xibalba.io"}),
                        now,
                        now,
                    ),
                    (
                        "tenant_agent_collective",
                        "Autonomous Agent Swarm Network",
                        TenantPlan.SCALE.value,
                        300,
                        25000,
                        1,
                        json.dumps({"description": "Distributed Agent Swarms & Consensus Engine"}),
                        now,
                        now,
                    ),
                    (
                        "tenant_dev_sandbox",
                        "Developer Pro Sandbox",
                        TenantPlan.PRO.value,
                        120,
                        10000,
                        1,
                        json.dumps({"description": "Individual Developer & Researcher Tier"}),
                        now,
                        now,
                    ),
                ]
                conn.executemany(
                    """
                    INSERT INTO tenants (id, name, plan, rate_limit_rpm, daily_quota_requests, is_active, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    default_tenants,
                )

                # Seed master API key for Xibalba Enterprise
                raw_master_key = f"sc_live_{secrets.token_urlsafe(24)}"
                prefix = f"{raw_master_key[:8]}...{raw_master_key[-4:]}"
                h_val = hashlib.sha256(raw_master_key.encode("utf-8")).hexdigest()
                conn.execute(
                    """
                    INSERT INTO tenant_keys (key_id, tenant_id, key_hash, key_prefix, label, scopes_json, rate_limit_rpm, requests_count, zero_inference_tokens_saved, last_used_at, is_revoked, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"key_{uuid.uuid4().hex[:12]}",
                        "tenant_xibalba_core",
                        h_val,
                        prefix,
                        "Production Orchestrator Key",
                        json.dumps(["read:graph", "read:memory", "write:memory", "exec:deterministic", "exec:inference", "admin:tenants"]),
                        1200,
                        42,
                        184500,
                        now,
                        0,
                        now,
                    ),
                )
            conn.commit()

    def append_event(self, actor: str, transition: str, payload: dict[str, Any], timestamp: str | None = None) -> EventRecord:
        """Append an event to the append-only cryptographic hash chain."""
        timestamp = timestamp or utc_now_iso()
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

    def record_access(self, memory_id: str) -> dict[str, Any] | None:
        """Record access/citation for Ebbinghaus memory decay reinforcement and compute temporal retention score."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT id, epistemic_class, metadata_json, created_at FROM memories WHERE id = ?",
                (memory_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            access_cnt = int(meta.get("access_count", 0)) + 1
            now = utc_now_iso()
            meta["access_count"] = access_cnt
            meta["last_accessed_at"] = now
            conn.execute(
                "UPDATE memories SET metadata_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(meta), now, memory_id),
            )
            conn.commit()

        from .deterministic import compute_temporal_retention

        return compute_temporal_retention(
            created_at_iso=row["created_at"],
            epistemic_class=row["epistemic_class"],
            access_count=access_cnt,
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

    def delete_relation(self, relation_id: str) -> bool:
        """Delete a directed relation edge by ID."""
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM relations WHERE relation_id = ?", (relation_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_relations(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        """List relations matching optional subject, predicate, or object filters."""
        query = "SELECT relation_id, subject, predicate, object, confidence, evidence_links_json, created_at FROM relations WHERE 1=1"
        params: list[Any] = []
        if subject:
            query += " AND subject = ?"
            params.append(subject)
        if predicate:
            query += " AND predicate = ?"
            params.append(predicate)
        if object:
            query += " AND object = ?"
            params.append(object)
        query += " ORDER BY rowid DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()

        results = []
        for r in rows:
            ev = []
            try:
                ev = json.loads(r["evidence_links_json"] or "[]")
            except Exception:
                pass
            results.append({
                "relation_id": r["relation_id"],
                "subject": r["subject"],
                "predicate": r["predicate"],
                "object": r["object"],
                "confidence": r["confidence"],
                "evidence_links": ev,
                "created_at": r["created_at"],
            })
        return results

    def update_memory_content(
        self,
        memory_id: str,
        *,
        text: str | None = None,
        epistemic_class: str | None = None,
        status: str | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Update memory fields and merge configurable metadata properties."""
        mem = self.get_memory(memory_id)
        if not mem:
            return None

        now = utc_now_iso()
        new_text = text if text is not None else mem.text
        new_ep = epistemic_class if epistemic_class is not None else mem.epistemic_class
        curr_status = mem.lifecycle_status.value if hasattr(mem.lifecycle_status, "value") else str(mem.lifecycle_status)
        new_status = status if status is not None else curr_status

        meta = dict(mem.metadata)
        if metadata_patch:
            meta.update(metadata_patch)

        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE memories
                SET text = ?, epistemic_class = ?, lifecycle_status = ?, metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_text, new_ep, new_status, canonical_json(meta), now, memory_id),
            )
            conn.commit()

        updated = self.get_memory(memory_id)
        return updated.model_dump() if updated else None

    def save_exchange(
        self,
        session_id: str,
        prompt_text: str,
        response_text: str,
        thinking_text: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        context_hashes: list[str] | None = None,
        created_at: str | None = None,
        scope_id: str | None = None,
        agent_id: str | None = None,
    ) -> ExchangeRecord:
        """Capture a model exchange turn with cryptographic hash link and agent scoping."""
        tool_calls = tool_calls or []
        context_hashes = context_hashes or []
        exchange_id = f"exch_{uuid.uuid4().hex[:16]}"
        now = created_at or utc_now_iso()

        if not agent_id:
            for cand in ("hermes", "agy", "claude", "codex", "cortex", "cursor", "shield", "deepseek", "chrome", "quant", "xibalba"):
                if cand in session_id.lower():
                    agent_id = cand
                    break
            agent_id = agent_id or "xibalba"

        if not scope_id:
            scope_id = f"agent:{agent_id}" if agent_id != "shared" else "shared"

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

            turn_raw = f"{parent_hash}:{session_id}:{prompt_hash}:{response_hash}:{thinking_text}:{tools_str}:{context_str}:{now}"
            turn_hash = sha256_hex(turn_raw)

            conn.execute(
                """
                INSERT INTO exchanges (exchange_id, session_id, prompt_text, prompt_hash, response_text, response_hash, thinking_text, tool_calls_json, context_hashes_json, turn_hash, parent_hash, created_at, scope_id, agent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exchange_id,
                    session_id,
                    prompt_text,
                    prompt_hash,
                    response_text,
                    response_hash,
                    thinking_text,
                    tools_str,
                    context_str,
                    turn_hash,
                    parent_hash,
                    now,
                    scope_id,
                    agent_id,
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
            thinking_text=thinking_text,
            tool_calls=tool_calls,
            context_hashes=context_hashes,
            turn_hash=turn_hash,
            parent_hash=parent_hash,
            created_at=now,
            scope_id=scope_id,
            agent_id=agent_id,
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
        """Retrieve temporal distribution of all agent interaction sessions with scope attribution."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT
                    session_id,
                    MIN(created_at) as start_time,
                    MAX(created_at) as end_time,
                    COUNT(*) as turn_count,
                    GROUP_CONCAT(tool_calls_json) as all_tools,
                    SUM(CASE WHEN thinking_text IS NOT NULL AND trim(thinking_text) != '' THEN 1 ELSE 0 END) as thought_count,
                    MAX(scope_id) as scope_id,
                    MAX(agent_id) as agent_id
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

            agent_id = r["agent_id"]
            if not agent_id or agent_id == "unknown":
                for cand in ("hermes", "agy", "claude", "cortex", "cursor", "shield", "deepseek", "chrome", "quant", "xibalba"):
                    if cand in sid.lower():
                        agent_id = cand
                        break
                agent_id = agent_id or "xibalba"

            scope_id = r["scope_id"] or (f"agent:{agent_id}" if agent_id != "shared" else "shared")

            sessions.append({
                "session_id": sid,
                "agent_id": agent_id,
                "scope_id": scope_id,
                "start_time": r["start_time"],
                "end_time": r["end_time"],
                "turn_count": r["turn_count"],
                "tool_execution_count": tool_count,
                "thought_count": int(r["thought_count"] or 0),
                "merkle_root": root,
            })
        return sessions

    def get_session_turns(self, session_id: str) -> list[dict[str, Any]]:
        """Get chronological turns for a specific session."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT exchange_id, session_id, prompt_text, prompt_hash, response_text, response_hash,
                       thinking_text, tool_calls_json, context_hashes_json, turn_hash, parent_hash, created_at, scope_id, agent_id
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
                "thinking_text": r["thinking_text"] if ("thinking_text" in r.keys() and r["thinking_text"]) else "",
                "tool_calls": json.loads(r["tool_calls_json"]) if r["tool_calls_json"] else [],
                "turn_hash": r["turn_hash"],
                "parent_hash": r["parent_hash"],
                "created_at": r["created_at"],
                "scope_id": r["scope_id"],
                "agent_id": r["agent_id"],
            }
            for r in rows
        ]

    def get_chronological_actions(
        self, session_id: str | None = None, scope_id: str | None = None, limit: int = 300
    ) -> list[dict[str, Any]]:
        """Retrieve flattened chronological sequence of all atomic agent actions."""
        with self._get_conn() as conn:
            query = """
                SELECT exchange_id, session_id, prompt_text, prompt_hash, response_text, response_hash,
                       thinking_text, tool_calls_json, turn_hash, parent_hash, created_at, scope_id, agent_id
                FROM exchanges
            """
            conditions = []
            params: list[Any] = []
            if session_id:
                conditions.append("session_id = ?")
                params.append(session_id)
            if scope_id and scope_id != "all":
                target = scope_id.replace("agent:", "").lower()
                conditions.append("(lower(agent_id) = ? OR lower(scope_id) = ?)")
                params.extend([target, scope_id.lower()])

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY created_at ASC, rowid ASC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()

        actions = []
        for r in rows:
            # 1. Prompt / Intent Action
            actions.append({
                "action_id": f"act_p_{r['exchange_id']}",
                "type": "prompt",
                "category": "intent",
                "agent_id": r["agent_id"] or "agent",
                "scope_id": r["scope_id"] or "shared",
                "session_id": r["session_id"],
                "exchange_id": r["exchange_id"],
                "created_at": r["created_at"],
                "title": (r["prompt_text"] or "Prompt instruction").strip()[:80],
                "payload": {"prompt_text": r["prompt_text"], "prompt_hash": r["prompt_hash"]},
                "icon": "person",
                "color": "#f59e0b",
                "hash": r["turn_hash"],
            })

            # 1b. Reasoning / Internal Chain-of-Thought Action
            th_text = (r["thinking_text"] or "").strip() if "thinking_text" in r.keys() else ""
            if th_text:
                actions.append({
                    "action_id": f"act_th_{r['exchange_id']}",
                    "type": "thought",
                    "category": "reasoning",
                    "agent_id": r["agent_id"] or "agent",
                    "scope_id": r["scope_id"] or "shared",
                    "session_id": r["session_id"],
                    "exchange_id": r["exchange_id"],
                    "created_at": r["created_at"],
                    "title": f"Chain of Thought: {th_text[:75]}...",
                    "payload": {"thinking_text": th_text},
                    "icon": "psychology",
                    "color": "#a855f7",
                    "hash": r["turn_hash"],
                })

            # 2. Atomic Tool Execution Actions
            tools = json.loads(r["tool_calls_json"]) if r["tool_calls_json"] else []
            for t_idx, t in enumerate(tools):
                t_name = t.get("name") or t.get("tool_name") or "tool"
                t_args = t.get("args") or t.get("arguments") or {}
                if isinstance(t_args, str):
                    try:
                        t_args = json.loads(t_args)
                    except Exception:
                        t_args = {"raw": t_args}
                elif not isinstance(t_args, dict):
                    t_args = {}

                tn_low = t_name.lower()

                if any(k in tn_low for k in ("command", "bash", "exec", "sh")):
                    cat = "command"
                    icon = "terminal"
                    color = "#00f0ff"
                    cmd = t_args.get("CommandLine") or t_args.get("command") or t_args.get("cmd") or t_name
                    if isinstance(cmd, str):
                        cmd = cmd.replace('"', "").strip()
                    summary = t_args.get("toolSummary") or t_args.get("summary") or cmd
                    title = f"$ {cmd[:60]}" if cmd else f"Command: {str(summary)[:60]}"
                elif any(k in tn_low for k in ("read_file", "view_file", "cat")):
                    cat = "file_read"
                    icon = "find_in_page"
                    color = "#fbbf24"
                    path = t_args.get("Path") or t_args.get("path") or "file"
                    title = f"Read: {str(path).split('/')[-1]}"
                elif any(k in tn_low for k in ("write_file", "edit_file", "patch")):
                    cat = "file_edit"
                    icon = "edit_document"
                    color = "#fb923c"
                    path = t_args.get("Path") or t_args.get("path") or "file"
                    title = f"Edit: {str(path).split('/')[-1]}"
                elif any(k in tn_low for k in ("mcp", "memory_", "super_", "cortex")):
                    cat = "mcp"
                    icon = "hub"
                    color = "#c084fc"
                    title = f"MCP: {t_name.replace('memory_', '')}"
                elif any(k in tn_low for k in ("search", "web", "fetch", "http")):
                    cat = "web"
                    icon = "travel_explore"
                    color = "#38bdf8"
                    title = f"Web: {t_name}"
                else:
                    cat = "tool"
                    icon = "build"
                    color = "#00f0ff"
                    title = f"Action: {t_name}"

                actions.append({
                    "action_id": f"act_t_{r['exchange_id']}_{t_idx}",
                    "type": "tool",
                    "category": cat,
                    "agent_id": r["agent_id"] or "agent",
                    "scope_id": r["scope_id"] or "shared",
                    "session_id": r["session_id"],
                    "exchange_id": r["exchange_id"],
                    "created_at": r["created_at"],
                    "title": title,
                    "tool_name": t_name,
                    "payload": t,
                    "icon": icon,
                    "color": color,
                    "hash": r["turn_hash"],
                })

            # 3. Agent Synthesis Action
            if r["response_text"]:
                actions.append({
                    "action_id": f"act_r_{r['exchange_id']}",
                    "type": "response",
                    "category": "synthesis",
                    "agent_id": r["agent_id"] or "agent",
                    "scope_id": r["scope_id"] or "shared",
                    "session_id": r["session_id"],
                    "exchange_id": r["exchange_id"],
                    "created_at": r["created_at"],
                    "title": f"Synthesis: {(r['response_text'] or '').strip()[:60]}...",
                    "payload": {"response_text": r["response_text"], "response_hash": r["response_hash"]},
                    "icon": "psychology",
                    "color": "#c084fc",
                    "hash": r["turn_hash"],
                })

            # 4. State Merkle Anchor Action
            actions.append({
                "action_id": f"act_a_{r['exchange_id']}",
                "type": "anchor",
                "category": "merkle",
                "agent_id": r["agent_id"] or "agent",
                "scope_id": r["scope_id"] or "shared",
                "session_id": r["session_id"],
                "exchange_id": r["exchange_id"],
                "created_at": r["created_at"],
                "title": f"Merkle Anchor: 0x{(r['turn_hash'] or '')[:10]}",
                "payload": {"turn_hash": r["turn_hash"], "parent_hash": r["parent_hash"]},
                "icon": "verified",
                "color": "#00ffa3",
                "hash": r["turn_hash"],
            })

        return actions

    def rebuild_session(self, session_id: str) -> dict[str, Any]:
        """Reconstruct the complete chronological session timeline between user and agent.
        
        Unfolds every turn into sequential atomic steps with exact timestamps, user prompts,
        agent reasoning (chain-of-thought), tool executions (commands, file operations, MCP calls),
        synthesis responses, and cryptographic Merkle leaf anchors.
        """
        turns = self.get_session_turns(session_id)
        if not turns:
            return {
                "session_id": session_id,
                "found": False,
                "error": f"Session '{session_id}' not found in provenance ledger.",
                "turn_count": 0,
                "step_count": 0,
                "timeline": [],
                "counts": {},
                "markdown_transcript": f"# Session Rebuild: {session_id}\n\nNo records found in provenance ledger.",
            }

        root = self.session_merkle_root(session_id)

        first_turn = turns[0]
        last_turn = turns[-1]
        start_ts = first_turn.get("created_at") or ""
        end_ts = last_turn.get("created_at") or ""

        dt_start = None
        dt_end = None
        try:
            dt_start = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
            dt_end = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
        except Exception:
            pass

        duration_sec = 0.0
        if dt_start and dt_end:
            duration_sec = max(0.0, (dt_end - dt_start).total_seconds())

        mins = int(duration_sec // 60)
        secs = int(duration_sec % 60)
        duration_fmt = f"{mins}m {secs}s" if mins > 0 else f"{duration_sec:.2f}s"

        timeline: list[dict[str, Any]] = []
        global_step = 1
        agent_id = first_turn.get("agent_id") or "agent"
        scope_id = first_turn.get("scope_id") or f"agent:{agent_id}"

        counts = {
            "user_prompts": 0,
            "agent_thoughts": 0,
            "tool_actions": 0,
            "agent_responses": 0,
            "merkle_anchors": 0,
            "commands": 0,
            "file_reads": 0,
            "file_edits": 0,
            "mcp_calls": 0,
            "other_tools": 0,
        }

        for t_idx, turn in enumerate(turns, start=1):
            ts = turn.get("created_at") or ""
            delta_str = "+00:00.000"
            try:
                dt_curr = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt_start and dt_curr:
                    delta_sec = max(0.0, (dt_curr - dt_start).total_seconds())
                    d_mins = int(delta_sec // 60)
                    d_s = delta_sec % 60
                    delta_str = f"+{d_mins:02d}:{d_s:06.3f}"
            except Exception:
                pass

            p_text = (turn.get("prompt_text") or "").strip()
            th_text = (turn.get("thinking_text") or "").strip()
            r_text = (turn.get("response_text") or "").strip()
            tools = turn.get("tool_calls") or []

            # 1. User Prompt
            timeline.append({
                "step_index": global_step,
                "turn_index": t_idx,
                "timestamp": ts,
                "relative_time": delta_str,
                "actor": "user",
                "actor_label": "USER",
                "step_type": "user_prompt",
                "category": "intent",
                "title": f"Turn {t_idx} Instruction",
                "summary": p_text[:120] + ("..." if len(p_text) > 120 else ""),
                "content": p_text,
                "hash": turn.get("turn_hash", ""),
                "icon": "person",
                "color": "#f59e0b",
                "exchange_id": turn.get("exchange_id"),
            })
            global_step += 1
            counts["user_prompts"] += 1

            # 2. Agent Chain-of-Thought
            if th_text:
                timeline.append({
                    "step_index": global_step,
                    "turn_index": t_idx,
                    "timestamp": ts,
                    "relative_time": delta_str,
                    "actor": "agent",
                    "actor_label": f"AGENT // {agent_id.upper()}",
                    "step_type": "agent_thought",
                    "category": "reasoning",
                    "title": f"Turn {t_idx} Reasoning (COT)",
                    "summary": th_text[:120] + ("..." if len(th_text) > 120 else ""),
                    "content": th_text,
                    "char_count": len(th_text),
                    "hash": turn.get("turn_hash", ""),
                    "icon": "psychology",
                    "color": "#a855f7",
                    "exchange_id": turn.get("exchange_id"),
                })
                global_step += 1
                counts["agent_thoughts"] += 1

            # 3. Tool Calls
            for tool_sub_idx, t in enumerate(tools, start=1):
                t_name = t.get("name") or t.get("tool_name") or "tool"
                t_args = t.get("args") or t.get("arguments") or {}
                if isinstance(t_args, str):
                    try:
                        t_args = json.loads(t_args)
                    except Exception:
                        t_args = {"raw": t_args}
                elif not isinstance(t_args, dict):
                    t_args = {}

                tn_low = t_name.lower()
                cmd_line = None
                file_path = None

                if any(k in tn_low for k in ("command", "bash", "exec", "sh")):
                    cat = "command"
                    icon = "terminal"
                    color = "#00f0ff"
                    cmd = t_args.get("CommandLine") or t_args.get("command") or t_args.get("cmd") or t_name
                    if isinstance(cmd, str):
                        cmd = cmd.strip()
                    summary = t_args.get("toolSummary") or t_args.get("summary") or cmd
                    title = f"$ {cmd}" if cmd else f"Command: {str(summary)[:60]}"
                    cmd_line = cmd
                    counts["commands"] += 1
                elif any(k in tn_low for k in ("read_file", "view_file", "cat")):
                    cat = "file_read"
                    icon = "find_in_page"
                    color = "#fbbf24"
                    path = t_args.get("Path") or t_args.get("path") or "file"
                    file_path = str(path)
                    title = f"Read: {file_path.split('/')[-1]}"
                    counts["file_reads"] += 1
                elif any(k in tn_low for k in ("write_file", "edit_file", "patch")):
                    cat = "file_edit"
                    icon = "edit_document"
                    color = "#fb923c"
                    path = t_args.get("Path") or t_args.get("path") or "file"
                    file_path = str(path)
                    title = f"Edit: {file_path.split('/')[-1]}"
                    counts["file_edits"] += 1
                elif any(k in tn_low for k in ("mcp", "memory_", "super_", "cortex")):
                    cat = "mcp"
                    icon = "hub"
                    color = "#c084fc"
                    title = f"MCP: {t_name.replace('memory_', '')}"
                    counts["mcp_calls"] += 1
                else:
                    cat = "tool"
                    icon = "build"
                    color = "#38bdf8"
                    title = f"Action: {t_name}"
                    counts["other_tools"] += 1

                timeline.append({
                    "step_index": global_step,
                    "turn_index": t_idx,
                    "tool_index": tool_sub_idx,
                    "timestamp": ts,
                    "relative_time": delta_str,
                    "actor": "agent",
                    "actor_label": f"AGENT // {agent_id.upper()}",
                    "step_type": "tool_execution",
                    "category": cat,
                    "tool_name": t_name,
                    "title": title,
                    "summary": title,
                    "arguments": t_args,
                    "command_line": cmd_line,
                    "file_path": file_path,
                    "content": json.dumps(t_args, indent=2),
                    "hash": turn.get("turn_hash", ""),
                    "icon": icon,
                    "color": color,
                    "exchange_id": turn.get("exchange_id"),
                })
                global_step += 1
                counts["tool_actions"] += 1

            # 4. Agent Synthesis
            if r_text:
                timeline.append({
                    "step_index": global_step,
                    "turn_index": t_idx,
                    "timestamp": ts,
                    "relative_time": delta_str,
                    "actor": "agent",
                    "actor_label": f"AGENT // {agent_id.upper()}",
                    "step_type": "agent_response",
                    "category": "synthesis",
                    "title": f"Turn {t_idx} Model Synthesis",
                    "summary": r_text[:120] + ("..." if len(r_text) > 120 else ""),
                    "content": r_text,
                    "char_count": len(r_text),
                    "hash": turn.get("turn_hash", ""),
                    "icon": "forum",
                    "color": "#c084fc",
                    "exchange_id": turn.get("exchange_id"),
                })
                global_step += 1
                counts["agent_responses"] += 1

            # 5. Merkle Anchor
            timeline.append({
                "step_index": global_step,
                "turn_index": t_idx,
                "timestamp": ts,
                "relative_time": delta_str,
                "actor": "provenance",
                "actor_label": "MERKLE PROVENANCE",
                "step_type": "merkle_anchor",
                "category": "merkle",
                "title": f"Turn {t_idx} Cryptographic Anchor",
                "summary": f"Leaf: 0x{turn.get('turn_hash', '')[:16]} | Parent: 0x{turn.get('parent_hash', '')[:16]}",
                "content": json.dumps({
                    "turn_hash": turn.get("turn_hash"),
                    "parent_hash": turn.get("parent_hash"),
                    "exchange_id": turn.get("exchange_id"),
                    "turn_index": t_idx,
                }, indent=2),
                "hash": turn.get("turn_hash", ""),
                "icon": "verified",
                "color": "#00ffa3",
                "exchange_id": turn.get("exchange_id"),
            })
            global_step += 1
            counts["merkle_anchors"] += 1

        md_lines = [
            f"# Session Forensic Rebuild & Audit Manifest",
            f"",
            f"- **Session ID:** `{session_id}`",
            f"- **Agent ID:** `{agent_id}` | **Scope:** `{scope_id}`",
            f"- **Domain-Separated Merkle Root:** `0x{root}`",
            f"- **Session Window:** `{start_ts}` to `{end_ts}` ({duration_fmt})",
            f"- **Total Turns:** `{len(turns)}` | **Total Atomic Steps:** `{len(timeline)}`",
            f"- **Action Breakdown:** {counts['user_prompts']} Prompts, {counts['agent_thoughts']} Thoughts, {counts['tool_actions']} Tools ({counts['commands']} CLI, {counts['file_reads']} Reads, {counts['file_edits']} Edits, {counts['mcp_calls']} MCP), {counts['agent_responses']} Responses",
            f"",
            f"---",
            f"",
            f"## Reconstructed Interaction Stream",
            f"",
        ]

        for step in timeline:
            s_idx = step["step_index"]
            t_idx = step["turn_index"]
            r_time = step["relative_time"]
            ts_str = step["timestamp"]
            s_type = step["step_type"]

            if s_type == "user_prompt":
                md_lines.append(f"### [Step {s_idx:02d} | Turn {t_idx}] {ts_str} ({r_time}) 👤 USER INSTRUCTION")
                md_lines.append(f"> {step['content']}")
                md_lines.append(f"")
            elif s_type == "agent_thought":
                md_lines.append(f"### [Step {s_idx:02d} | Turn {t_idx}] {ts_str} ({r_time}) 🧠 AGENT REASONING (COT)")
                md_lines.append(f"```text\n{step['content']}\n```")
                md_lines.append(f"")
            elif s_type == "tool_execution":
                t_name = step.get("tool_name", "tool")
                md_lines.append(f"### [Step {s_idx:02d} | Turn {t_idx}] {ts_str} ({r_time}) ⚡ ACTION: {t_name}")
                if step.get("command_line"):
                    md_lines.append(f"```bash\n$ {step['command_line']}\n```")
                elif step.get("file_path"):
                    md_lines.append(f"**Path:** `{step['file_path']}`")
                md_lines.append(f"```json\n{step['content']}\n```")
                md_lines.append(f"")
            elif s_type == "agent_response":
                md_lines.append(f"### [Step {s_idx:02d} | Turn {t_idx}] {ts_str} ({r_time}) 💬 AGENT SYNTHESIS")
                md_lines.append(f"{step['content']}")
                md_lines.append(f"")
            elif s_type == "merkle_anchor":
                md_lines.append(f"### [Step {s_idx:02d} | Turn {t_idx}] {ts_str} ({r_time}) 🔒 MERKLE LEAF ANCHOR")
                md_lines.append(f"- **Turn Hash:** `0x{step['hash']}`")
                md_lines.append(f"")

        markdown_transcript = "\n".join(md_lines)

        return {
            "session_id": session_id,
            "found": True,
            "agent_id": agent_id,
            "scope_id": scope_id,
            "merkle_root": root,
            "start_time": start_ts,
            "end_time": end_ts,
            "duration_seconds": duration_sec,
            "duration_formatted": duration_fmt,
            "turn_count": len(turns),
            "step_count": len(timeline),
            "counts": counts,
            "timeline": timeline,
            "markdown_transcript": markdown_transcript,
        }

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
            if scope and scope != "all":
                query += " AND coalesce(json_extract(metadata_json, '$.scope'), 'shared') = ?"
                params.append(scope)
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
        """Mark memory forgotten and remove from active index."""
        return self.update_memory_status(memory_id, LifecycleStatus.FORGOTTEN)

    def _resolve_env_key(self, provider_type: str, current_key: str) -> str:
        import os
        if current_key and current_key.strip():
            return current_key.strip()
        if provider_type == ProviderType.GEMINI.value:
            return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        elif provider_type == ProviderType.ANTHROPIC.value:
            return os.getenv("ANTHROPIC_API_KEY") or ""
        elif provider_type == ProviderType.OPENAI.value:
            return os.getenv("OPENAI_API_KEY") or ""
        elif provider_type == ProviderType.GROQ.value:
            return os.getenv("GROQ_API_KEY") or ""
        return ""

    def list_providers(self) -> list[ProviderRecord]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT id, name, provider_type, api_key, base_url, default_model, is_active, settings_json, created_at, updated_at FROM providers ORDER BY is_active DESC, name ASC"
            )
            rows = cursor.fetchall()
            providers = []
            for r in rows:
                try:
                    sett = json.loads(r["settings_json"]) if r["settings_json"] else {}
                except Exception:
                    sett = {}
                resolved_key = self._resolve_env_key(r["provider_type"], r["api_key"] or "")
                providers.append(
                    ProviderRecord(
                        id=r["id"],
                        name=r["name"],
                        provider_type=r["provider_type"],
                        api_key=resolved_key,
                        base_url=r["base_url"] or "",
                        default_model=r["default_model"] or "",
                        is_active=bool(r["is_active"]),
                        settings=sett,
                        created_at=r["created_at"],
                        updated_at=r["updated_at"],
                    )
                )
            return providers

    def get_provider(self, provider_id: str) -> ProviderRecord | None:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT id, name, provider_type, api_key, base_url, default_model, is_active, settings_json, created_at, updated_at FROM providers WHERE id = ?",
                (provider_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            try:
                sett = json.loads(r["settings_json"]) if r["settings_json"] else {}
            except Exception:
                sett = {}
            resolved_key = self._resolve_env_key(r["provider_type"], r["api_key"] or "")
            return ProviderRecord(
                id=r["id"],
                name=r["name"],
                provider_type=r["provider_type"],
                api_key=resolved_key,
                base_url=r["base_url"] or "",
                default_model=r["default_model"] or "",
                is_active=bool(r["is_active"]),
                settings=sett,
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )

    def get_active_provider(self) -> ProviderRecord | None:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT id, name, provider_type, api_key, base_url, default_model, is_active, settings_json, created_at, updated_at FROM providers WHERE is_active = 1 LIMIT 1"
            )
            r = cursor.fetchone()
            if not r:
                cursor = conn.execute(
                    "SELECT id, name, provider_type, api_key, base_url, default_model, is_active, settings_json, created_at, updated_at FROM providers WHERE (api_key IS NOT NULL AND api_key != '') OR provider_type = 'ollama' LIMIT 1"
                )
                r = cursor.fetchone()
            if not r:
                return self.get_provider("gemini")
            try:
                sett = json.loads(r["settings_json"]) if r["settings_json"] else {}
            except Exception:
                sett = {}
            resolved_key = self._resolve_env_key(r["provider_type"], r["api_key"] or "")
            return ProviderRecord(
                id=r["id"],
                name=r["name"],
                provider_type=r["provider_type"],
                api_key=resolved_key,
                base_url=r["base_url"] or "",
                default_model=r["default_model"] or "",
                is_active=bool(r["is_active"]),
                settings=sett,
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )

    def save_provider(self, record: ProviderRecord) -> ProviderRecord:
        now = utc_now_iso()
        with self._get_conn() as conn:
            if record.is_active:
                conn.execute("UPDATE providers SET is_active = 0")
            conn.execute(
                """
                INSERT INTO providers (id, name, provider_type, api_key, base_url, default_model, is_active, settings_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    provider_type = excluded.provider_type,
                    api_key = CASE WHEN excluded.api_key != '' THEN excluded.api_key ELSE providers.api_key END,
                    base_url = excluded.base_url,
                    default_model = excluded.default_model,
                    is_active = excluded.is_active,
                    settings_json = excluded.settings_json,
                    updated_at = excluded.updated_at
                """,
                (
                    record.id,
                    record.name,
                    record.provider_type,
                    record.api_key,
                    record.base_url,
                    record.default_model,
                    1 if record.is_active else 0,
                    json.dumps(record.settings),
                    record.created_at or now,
                    now,
                ),
            )
            conn.commit()
        return self.get_provider(record.id) or record

    def delete_provider(self, provider_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
            conn.commit()
            return cursor.rowcount > 0

    def set_active_provider(self, provider_id: str) -> bool:
        with self._get_conn() as conn:
            conn.execute("UPDATE providers SET is_active = 0")
            cursor = conn.execute(
                "UPDATE providers SET is_active = 1, updated_at = ? WHERE id = ?",
                (utc_now_iso(), provider_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Commercial Tenant & API Key Scoping
    # -------------------------------------------------------------------------

    def list_tenants(self) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT 
                    t.id, t.name, t.plan, t.rate_limit_rpm, t.daily_quota_requests, 
                    t.is_active, t.metadata_json, t.created_at, t.updated_at,
                    COUNT(k.key_id) as key_count,
                    COALESCE(SUM(k.requests_count), 0) as total_requests,
                    COALESCE(SUM(k.zero_inference_tokens_saved), 0) as total_tokens_saved
                FROM tenants t
                LEFT JOIN tenant_keys k ON t.id = k.tenant_id AND k.is_revoked = 0
                GROUP BY t.id
                ORDER BY t.created_at ASC
                """
            )
            rows = cursor.fetchall()
            result = []
            for r in rows:
                meta = {}
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    pass
                result.append({
                    "id": r["id"],
                    "name": r["name"],
                    "plan": r["plan"],
                    "rate_limit_rpm": r["rate_limit_rpm"],
                    "daily_quota_requests": r["daily_quota_requests"],
                    "is_active": bool(r["is_active"]),
                    "metadata": meta,
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "key_count": r["key_count"],
                    "total_requests": r["total_requests"],
                    "total_tokens_saved": r["total_tokens_saved"],
                    "estimated_dollar_savings": round(r["total_tokens_saved"] * 0.000003, 4),
                })
            return result

    def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT id, name, plan, rate_limit_rpm, daily_quota_requests, is_active, metadata_json, created_at, updated_at FROM tenants WHERE id = ?",
                (tenant_id,),
            )
            r = cursor.fetchone()
            if not r:
                return None
            meta = {}
            try:
                meta = json.loads(r["metadata_json"])
            except Exception:
                pass
            return {
                "id": r["id"],
                "name": r["name"],
                "plan": r["plan"],
                "rate_limit_rpm": r["rate_limit_rpm"],
                "daily_quota_requests": r["daily_quota_requests"],
                "is_active": bool(r["is_active"]),
                "metadata": meta,
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }

    def save_tenant(self, tenant: TenantRecord) -> TenantRecord:
        now = utc_now_iso()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO tenants (id, name, plan, rate_limit_rpm, daily_quota_requests, is_active, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    plan = excluded.plan,
                    rate_limit_rpm = excluded.rate_limit_rpm,
                    daily_quota_requests = excluded.daily_quota_requests,
                    is_active = excluded.is_active,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    tenant.id,
                    tenant.name,
                    tenant.plan,
                    tenant.rate_limit_rpm,
                    tenant.daily_quota_requests,
                    1 if tenant.is_active else 0,
                    json.dumps(tenant.metadata),
                    tenant.created_at or now,
                    now,
                ),
            )
            conn.commit()
        return tenant

    def delete_tenant(self, tenant_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
            conn.commit()
            return cursor.rowcount > 0

    def create_tenant_key(
        self,
        tenant_id: str,
        label: str,
        scopes: list[str] | None = None,
        rate_limit_rpm: int = 60,
        expires_at: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Issues a new scoped cryptographic API key for a tenant."""
        now = utc_now_iso()
        key_id = f"key_{uuid.uuid4().hex[:12]}"
        raw_key = f"sc_live_{secrets.token_urlsafe(24)}"
        key_prefix = f"{raw_key[:8]}...{raw_key[-4:]}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        scopes = scopes or ["read:graph", "read:memory", "write:memory", "exec:deterministic"]

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO tenant_keys (key_id, tenant_id, key_hash, key_prefix, label, scopes_json, rate_limit_rpm, requests_count, zero_inference_tokens_saved, last_used_at, expires_at, is_revoked, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?, 0, ?)
                """,
                (
                    key_id,
                    tenant_id,
                    key_hash,
                    key_prefix,
                    label,
                    json.dumps(scopes),
                    rate_limit_rpm,
                    expires_at,
                    now,
                ),
            )
            conn.commit()

        record = {
            "key_id": key_id,
            "tenant_id": tenant_id,
            "key_prefix": key_prefix,
            "label": label,
            "scopes": scopes,
            "rate_limit_rpm": rate_limit_rpm,
            "requests_count": 0,
            "zero_inference_tokens_saved": 0,
            "last_used_at": None,
            "expires_at": expires_at,
            "is_revoked": False,
            "created_at": now,
        }
        return record, raw_key

    def list_tenant_keys(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT k.key_id, k.tenant_id, k.key_prefix, k.label, k.scopes_json, 
                   k.rate_limit_rpm, k.requests_count, k.zero_inference_tokens_saved,
                   k.last_used_at, k.expires_at, k.is_revoked, k.created_at,
                   t.name as tenant_name, t.plan as tenant_plan
            FROM tenant_keys k
            JOIN tenants t ON k.tenant_id = t.id
        """
        params = []
        if tenant_id:
            query += " WHERE k.tenant_id = ?"
            params.append(tenant_id)
        query += " ORDER BY k.created_at DESC"

        with self._get_conn() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            results = []
            for r in rows:
                scopes = []
                try:
                    scopes = json.loads(r["scopes_json"])
                except Exception:
                    pass
                results.append({
                    "key_id": r["key_id"],
                    "tenant_id": r["tenant_id"],
                    "tenant_name": r["tenant_name"],
                    "tenant_plan": r["tenant_plan"],
                    "key_prefix": r["key_prefix"],
                    "label": r["label"],
                    "scopes": scopes,
                    "rate_limit_rpm": r["rate_limit_rpm"],
                    "requests_count": r["requests_count"],
                    "zero_inference_tokens_saved": r["zero_inference_tokens_saved"],
                    "estimated_savings_dollars": round(r["zero_inference_tokens_saved"] * 0.000003, 4),
                    "last_used_at": r["last_used_at"],
                    "expires_at": r["expires_at"],
                    "is_revoked": bool(r["is_revoked"]),
                    "created_at": r["created_at"],
                })
            return results

    def revoke_tenant_key(self, key_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.execute("UPDATE tenant_keys SET is_revoked = 1 WHERE key_id = ?", (key_id,))
            conn.commit()
            return cursor.rowcount > 0

    def verify_and_consume_key(self, raw_key: str, cost_tokens: int = 0) -> dict[str, Any] | None:
        """Authenticates an incoming API key, checks revocation, and increments metrics."""
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        now = utc_now_iso()
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT k.key_id, k.tenant_id, k.key_prefix, k.label, k.scopes_json,
                       k.rate_limit_rpm, k.requests_count, k.zero_inference_tokens_saved,
                       k.is_revoked, t.name as tenant_name, t.plan as tenant_plan, t.is_active as tenant_active
                FROM tenant_keys k
                JOIN tenants t ON k.tenant_id = t.id
                WHERE k.key_hash = ?
                """,
                (key_hash,),
            )
            r = cursor.fetchone()
            if not r or r["is_revoked"] or not r["tenant_active"]:
                return None

            conn.execute(
                """
                UPDATE tenant_keys 
                SET requests_count = requests_count + 1,
                    zero_inference_tokens_saved = zero_inference_tokens_saved + ?,
                    last_used_at = ?
                WHERE key_id = ?
                """,
                (cost_tokens, now, r["key_id"]),
            )
            conn.commit()

            scopes = []
            try:
                scopes = json.loads(r["scopes_json"])
            except Exception:
                pass

            return {
                "key_id": r["key_id"],
                "tenant_id": r["tenant_id"],
                "tenant_name": r["tenant_name"],
                "tenant_plan": r["tenant_plan"],
                "label": r["label"],
                "scopes": scopes,
                "rate_limit_rpm": r["rate_limit_rpm"],
            }


# Convenient alias
SuperCortexStore = ProvenanceStore
