"""Versioned structured export/import for graph memory workspaces."""
from __future__ import annotations

import sqlite3
from typing import Any

SCHEMA_VERSION = "xibalba.structured_memory_bundle.v1"
TABLES: dict[str, tuple[str, ...]] = {
    "sessions": ("id", "external_session_id", "retention_tier", "started_at", "ended_at", "summary_memory_id", "agent_id"),
    "sources": ("id", "kind", "locator", "role", "session_id", "message_id", "tool_name", "observed_at", "agent_id", "identity_mode", "prompt_id", "content_hash", "metadata_json", "created_at"),
    "memories": ("id", "source_id", "content", "content_hash", "status", "valid_from", "valid_to", "supersedes_id", "derivation_family", "idempotency_key", "created_at"),
    "memory_events": ("memory_id", "event_type", "detail_json", "node_id", "parent_event_id", "created_at"),
    "entities": ("id", "canonical_name", "normalized_name", "entity_type", "normalization_version", "created_at", "agent_id"),
    "entity_aliases": ("id", "entity_id", "alias", "normalized_alias", "evidence_memory_id", "confidence"),
    "memory_entities": ("memory_id", "entity_id", "evidence_quote"),
    "relations": ("id", "subject_entity_id", "predicate", "object_entity_id", "object_literal", "evidence_memory_id", "confidence", "status", "valid_from", "valid_to", "created_at", "agent_id"),
    "meta_nodes": ("id", "memory_id", "type", "relevance_score", "status", "metadata_json", "created_at", "updated_at"),
}

def _rows(connection: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    available = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    selected = tuple(column for column in columns if column in available)
    if not selected:
        return []
    names = ",".join(selected)
    return [dict(row) for row in connection.execute(f"SELECT {names} FROM {table} ORDER BY rowid").fetchall()]

def export_bundle(connection: sqlite3.Connection, *, include_forgotten: bool = True) -> dict[str, Any]:
    connection.row_factory = sqlite3.Row
    tables = {name: _rows(connection, name, columns) for name, columns in TABLES.items()}
    if not include_forgotten:
        ids = {row["id"] for row in tables["memories"] if row.get("status") != "forgotten"}
        tables["memories"] = [row for row in tables["memories"] if row["id"] in ids]
        tables["memory_events"] = [row for row in tables["memory_events"] if row["memory_id"] in ids]
        tables["memory_entities"] = [row for row in tables["memory_entities"] if row["memory_id"] in ids]
        tables["relations"] = [row for row in tables["relations"] if row["evidence_memory_id"] in ids]
    return {"schema_version": SCHEMA_VERSION, "tables": tables, "counts": {name: len(rows) for name, rows in tables.items()}}

def _validate(bundle: dict[str, Any], connection: sqlite3.Connection | None = None) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(bundle, dict) or bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported structured bundle; expected {SCHEMA_VERSION}")
    raw = bundle.get("tables")
    if not isinstance(raw, dict):
        raise ValueError("Structured bundle tables must be an object")
    result = {name: raw.get(name, []) for name in TABLES}
    if any(not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) for rows in result.values()):
        raise ValueError("Structured bundle tables must contain row objects")
    memories = {row["id"] for row in result["memories"]}
    sources = {row["id"] for row in result["sources"]}
    entities = {row["id"] for row in result["entities"]}
    if connection is not None:
        memories.update(row[0] for row in connection.execute("SELECT id FROM memories"))
        sources.update(row[0] for row in connection.execute("SELECT id FROM sources"))
        entities.update(row[0] for row in connection.execute("SELECT id FROM entities"))
    if any(row["source_id"] not in sources for row in result["memories"]): raise ValueError("Memory references a missing source")
    if any(row["memory_id"] not in memories for row in result["memory_events"] + result["memory_entities"]): raise ValueError("Bundle references a missing memory")
    if any(row["entity_id"] not in entities for row in result["entity_aliases"] + result["memory_entities"]): raise ValueError("Bundle references a missing entity")
    if any(row["subject_entity_id"] not in entities or (row["object_entity_id"] and row["object_entity_id"] not in entities) or row["evidence_memory_id"] not in memories for row in result["relations"]): raise ValueError("Relation references a missing graph node")
    return result

def import_bundle(connection: sqlite3.Connection, bundle: dict[str, Any], *, max_memories: int | None = None) -> dict[str, int]:
    tables = _validate(bundle, connection)
    if max_memories is not None and connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0] + len(tables["memories"]) > max_memories:
        raise RuntimeError(f"memory quota exceeded: max_memories={max_memories}")
    inserted = {name: 0 for name in TABLES}
    connection.execute("BEGIN IMMEDIATE")
    try:
        for table in ("sessions", "sources", "memories", "entities", "entity_aliases", "memory_entities", "relations", "meta_nodes"):
            columns = TABLES[table]
            for row in tables[table]:
                present = tuple(column for column in columns if column in row)
                existing = connection.execute(f"SELECT 1 FROM {table} WHERE id=?", (row["id"],)).fetchone() if "id" in present else None
                if existing: continue
                placeholders = ",".join("?" for _ in present)
                connection.execute(f"INSERT INTO {table} ({','.join(present)}) VALUES ({placeholders})", tuple(row[column] for column in present))
                inserted[table] += 1
        for row in tables["memory_events"]:
            existing = connection.execute("SELECT 1 FROM memory_events WHERE node_id=?", (row["node_id"],)).fetchone()
            if not existing:
                connection.execute("INSERT INTO memory_events(memory_id,event_type,detail_json,node_id,parent_event_id,created_at) VALUES(?,?,?,?,?,?)", tuple(row[column] for column in TABLES["memory_events"]))
                inserted["memory_events"] += 1
        for row in tables["memories"]:
            connection.execute("INSERT OR IGNORE INTO memory_fts(memory_id,content) VALUES(?,?)", (row["id"], row["content"]))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return inserted
