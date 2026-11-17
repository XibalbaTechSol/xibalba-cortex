"""Idempotent migration utility from legacy `xibalba-cortex` SQLite databases into Super-Cortex `ProvenanceStore`."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from .classifier import classify_epistemic, classify_para
from .models import EpistemicClass, LifecycleStatus, MemoryRecord, ScopeRecord, ScopeType
from .redaction_and_otlp import redact_secrets
from .store import ProvenanceStore

log = logging.getLogger(__name__)

DEFAULT_LEGACY_DB_PATHS: tuple[tuple[str, str, str], ...] = (
    ("~/.hermes/xibalba-cortex/graph-memory.sqlite3", "hermes", "shared"),
    ("~/.hermes/xibalba-cortex-quant/graph-memory.sqlite3", "quant", "agent:quant"),
    ("~/.hermes/xibalba-cortex-shield/graph-memory.sqlite3", "shield", "agent:shield"),
    ("~/.claude/xibalba-cortex-claude/graph-memory.sqlite3", "claude", "agent:claude"),
    ("~/.codex/xibalba-cortex-codex/graph-memory.sqlite3", "codex", "agent:codex"),
    ("~/.gemini/antigravity-cli/xibalba-cortex-agy/graph-memory.sqlite3", "agy", "agent:agy"),
)


def _is_noisy_telemetry_blob(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if "OPA unavailable: OPA response missing" in stripped:
        return True
    if stripped.startswith('{"decision":{"class":"policy_decision"') and len(stripped) > 600:
        return True
    return False


def _map_epistemic(derivation_family: str, text: str) -> str:
    fam = (derivation_family or "").lower()
    if fam == "policy":
        return EpistemicClass.RULE.value
    if fam == "inference":
        return EpistemicClass.INFERENCE.value
    classified = classify_epistemic(text)
    return str(classified.get("epistemic_class") or EpistemicClass.FACT.value)


def migrate_legacy_cortex_databases(
    store: ProvenanceStore,
    *,
    db_specs: list[tuple[Path | str, str, str]] | None = None,
    max_memories_per_db: int = 250,
    include_raw_candidates: bool = False,
) -> dict[str, Any]:
    """Migrate memories, entities, and relations from legacy `xibalba-cortex` SQLite DBs into `ProvenanceStore`."""
    specs = db_specs or list(DEFAULT_LEGACY_DB_PATHS)
    summary: dict[str, Any] = {
        "databases_scanned": 0,
        "memories_migrated": 0,
        "memories_skipped": 0,
        "entities_migrated": 0,
        "relations_migrated": 0,
        "per_database": [],
    }

    for raw_path, agent_id, scope_id in specs:
        db_path = Path(str(raw_path)).expanduser()
        if not db_path.exists():
            continue

        summary["databases_scanned"] += 1
        db_stats = {
            "path": str(db_path),
            "agent_id": agent_id,
            "scope_id": scope_id,
            "memories_migrated": 0,
            "memories_skipped": 0,
            "entities_migrated": 0,
            "relations_migrated": 0,
        }

        # Ensure scope exists in target store
        if not store.get_scope(scope_id):
            is_agent = scope_id.startswith("agent:")
            store.save_scope(
                ScopeRecord(
                    scope_id=scope_id,
                    name=f"Agent Scope ({agent_id})" if is_agent else "Shared",
                    scope_type=ScopeType.SINGLE_AGENT.value if is_agent else ScopeType.SHARED.value,
                    agent_id=agent_id if is_agent else None,
                    description=f"Migrated legacy Cortex scope for {agent_id}",
                )
            )

        conn = sqlite3.connect(str(db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            tables = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }

            # 1. Migrate Entities & build ID -> canonical_name map
            entity_id_to_name: dict[str, str] = {}
            if "entities" in tables:
                for erow in conn.execute("SELECT * FROM entities").fetchall():
                    edata = dict(erow)
                    eid = str(edata.get("id") or "")
                    cname = str(edata.get("canonical_name") or edata.get("normalized_name") or "").strip()
                    if not cname:
                        continue
                    entity_id_to_name[eid] = cname
                    store.add_entity(
                        label=cname,
                        aliases=[str(edata.get("normalized_name"))] if edata.get("normalized_name") else [],
                        evidence_links=[f"legacy:{agent_id}:{eid}"],
                    )
                    db_stats["entities_migrated"] += 1
                    summary["entities_migrated"] += 1

            # 2. Migrate Relations
            if "relations" in tables:
                for rrow in conn.execute("SELECT * FROM relations WHERE status != 'forgotten'").fetchall():
                    rdata = dict(rrow)
                    subj = entity_id_to_name.get(str(rdata.get("subject_entity_id") or "")) or str(
                        rdata.get("subject_entity_id") or ""
                    )
                    pred = str(rdata.get("predicate") or "related_to").strip()
                    obj = (
                        entity_id_to_name.get(str(rdata.get("object_entity_id") or ""))
                        or str(rdata.get("object_literal") or rdata.get("object_entity_id") or "")
                    ).strip()
                    if not subj or not obj:
                        continue
                    ev_id = str(rdata.get("evidence_memory_id") or "")
                    store.add_relation(
                        subject=subj,
                        predicate=pred,
                        object=obj,
                        confidence=float(rdata.get("confidence") or 1.0),
                        evidence_links=[f"legacy_mem:{ev_id}"] if ev_id else [f"legacy:{agent_id}"],
                    )
                    db_stats["relations_migrated"] += 1
                    summary["relations_migrated"] += 1

            # 3. Migrate high-signal Memories
            if "memories" in tables:
                where_clause = (
                    "WHERE status != 'forgotten'"
                    if include_raw_candidates
                    else "WHERE status != 'forgotten' AND (derivation_family IN ('summary', 'policy', 'inference') OR status = 'confirmed')"
                )
                query = f"""
                    SELECT id, source_id, content, content_hash, status, derivation_family, created_at
                    FROM memories
                    {where_clause}
                    ORDER BY CASE WHEN derivation_family IN ('summary', 'policy', 'inference') THEN 0 ELSE 1 END,
                             created_at DESC
                    LIMIT ?
                """
                rows = conn.execute(query, (max_memories_per_db * 3,)).fetchall()
                for mrow in rows:
                    if db_stats["memories_migrated"] >= max_memories_per_db:
                        break
                    mdata = dict(mrow)
                    raw_text = str(mdata.get("content") or "").strip()
                    if _is_noisy_telemetry_blob(raw_text) and not include_raw_candidates:
                        db_stats["memories_skipped"] += 1
                        summary["memories_skipped"] += 1
                        continue

                    clean_text = redact_secrets(raw_text)
                    content_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
                    mem_id = f"mem_{content_hash[:16]}"
                    if store.get_memory(mem_id) is not None:
                        db_stats["memories_skipped"] += 1
                        summary["memories_skipped"] += 1
                        continue

                    epistemic = _map_epistemic(str(mdata.get("derivation_family") or ""), clean_text)
                    para = classify_para(clean_text)
                    namespace = "xibalba" if scope_id == "shared" else scope_id.replace(":", "-")

                    store.save_memory(
                        MemoryRecord(
                            id=mem_id,
                            source_id=str(mdata.get("id") or ""),
                            text=clean_text,
                            epistemic_class=epistemic,
                            lifecycle_status=LifecycleStatus.ACTIVE.value,
                            content_hash=content_hash,
                            namespace=namespace,
                            metadata={
                                "scope": scope_id,
                                "agent_id": agent_id,
                                "para_category": para.get("para_category", "resource"),
                                "source_origin": f"legacy_cortex:{agent_id}",
                                "legacy_derivation_family": mdata.get("derivation_family"),
                                "legacy_status": mdata.get("status"),
                            },
                            created_at=str(mdata.get("created_at") or ""),
                        )
                    )
                    db_stats["memories_migrated"] += 1
                    summary["memories_migrated"] += 1
        finally:
            conn.close()

        summary["per_database"].append(db_stats)

    return summary
