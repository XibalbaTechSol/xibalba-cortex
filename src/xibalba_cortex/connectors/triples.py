"""Triples Knowledge Graph Ingestion Connector (CSV, TSV, JSON, Tuples)."""
from __future__ import annotations

import csv
import io
import json
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..store import GraphStore
from .base import ConnectorResult


class TriplesConnector:
    """Ingests relational triples (subject, predicate, object) directly into the Cortex knowledge graph."""

    def __init__(self, store: GraphStore):
        self.store = store

    def ingest_triples(
        self,
        triples: Iterable[dict[str, Any] | tuple[str, str, str]],
        *,
        source_name: str = "dataset_ingest",
        agent_id: str | None = None,
        shared: bool = True,
    ) -> ConnectorResult:
        """Ingest in-memory iterable of triples into Cortex.
        
        Tuples should be (subject, predicate, object) or (subject, predicate, object, confidence).
        Dicts can use flexible keys: {subject/head/source, predicate/relation/rel, object/tail/target}.
        """
        result = ConnectorResult(connector="triples")
        cleaned_records: list[dict[str, Any]] = []

        for item in triples:
            if isinstance(item, (tuple, list)):
                if len(item) < 3:
                    result.errors.append(f"Invalid tuple triple (need >= 3 items): {item}")
                    continue
                sub, pred, obj = str(item[0]).strip(), str(item[1]).strip(), str(item[2]).strip()
                conf = float(item[3]) if len(item) > 3 and item[3] is not None else 1.0
                cleaned_records.append({
                    "subject": sub,
                    "predicate": pred,
                    "object": obj,
                    "confidence": max(0.0, min(1.0, conf)),
                    "subject_type": "entity",
                    "object_type": "entity",
                })
            elif isinstance(item, Mapping):
                sub = (
                    item.get("subject") or item.get("head") or item.get("source") or item.get("entity1") or item.get("s")
                )
                pred = (
                    item.get("predicate") or item.get("relation") or item.get("rel") or item.get("edge") or item.get("p")
                )
                obj = (
                    item.get("object") or item.get("tail") or item.get("target") or item.get("entity2") or item.get("o")
                )
                if not sub or not pred or not obj:
                    result.errors.append(f"Missing required triple fields in dict: {item}")
                    continue
                
                conf = 1.0
                raw_conf = item.get("confidence") or item.get("weight") or item.get("score")
                if raw_conf is not None:
                    try:
                        conf = float(raw_conf)
                    except (ValueError, TypeError):
                        conf = 1.0

                cleaned_records.append({
                    "subject": str(sub).strip(),
                    "predicate": str(pred).strip(),
                    "object": str(obj).strip(),
                    "confidence": max(0.0, min(1.0, conf)),
                    "subject_type": str(item.get("subject_type") or item.get("head_type") or "entity").strip(),
                    "object_type": str(item.get("object_type") or item.get("tail_type") or "entity").strip(),
                    "literal": bool(item.get("is_literal", False)),
                })

        if not cleaned_records:
            result.success = len(result.errors) == 0
            return result

        # Create provenance source and memory
        with self.store._lock:
            mem_record = self.store.store_memory(
                content=f"Knowledge graph ingestion: {len(cleaned_records)} triples from '{source_name}'",
                source={
                    "kind": "dataset_ingest",
                    "locator": source_name,
                    "agent_id": agent_id or "",
                    "metadata": {"triples_count": len(cleaned_records), "shared": shared},
                },
                status="confirmed",
                evidence_class="observed_event",
            )
            result.sources_created += 1
            result.memories_created += 1
            memory_id = str(mem_record["id"])
            source_id = str(mem_record["source"]["id"])

            # Insert entities and relations atomically
            self.store._connection.execute("BEGIN IMMEDIATE")
            try:
                scope = "" if shared else (agent_id or "")
                created_entity_ids = set()
                created_relation_ids = []

                for rec in cleaned_records:
                    sub_entity = self.store._get_or_create_entity(
                        rec["subject"],
                        entity_type=rec["subject_type"],
                        agent_id=scope,
                        shared=shared,
                    )
                    created_entity_ids.add(sub_entity["id"])

                    obj_entity_id = None
                    obj_literal = None

                    if rec.get("literal"):
                        obj_literal = rec["object"]
                    else:
                        obj_entity = self.store._get_or_create_entity(
                            rec["object"],
                            entity_type=rec["object_type"],
                            agent_id=scope,
                            shared=shared,
                        )
                        obj_entity_id = obj_entity["id"]
                        created_entity_ids.add(obj_entity_id)

                    # Check existing active relation to prevent duplicates
                    existing = self.store._connection.execute(
                        """
                        SELECT id FROM relations
                        WHERE subject_entity_id = ? AND predicate = ? 
                          AND (object_entity_id = ? OR (object_entity_id IS NULL AND object_literal = ?))
                          AND status = 'active' AND agent_id = ?
                        LIMIT 1
                        """,
                        (sub_entity["id"], rec["predicate"], obj_entity_id, obj_literal, scope),
                    ).fetchone()

                    if existing is not None:
                        continue

                    rel_id = str(uuid.uuid4())
                    self.store._connection.execute(
                        """
                        INSERT INTO relations(
                            id, subject_entity_id, predicate, object_entity_id, object_literal,
                            evidence_memory_id, confidence, agent_id, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
                        """,
                        (
                            rel_id,
                            sub_entity["id"],
                            rec["predicate"],
                            obj_entity_id,
                            obj_literal,
                            memory_id,
                            rec["confidence"],
                            scope,
                        ),
                    )
                    created_relation_ids.append(rel_id)

                self.store._connection.execute("COMMIT")
                result.entities_created = len(created_entity_ids)
                result.relations_created = len(created_relation_ids)
                result.entity_ids = list(created_entity_ids)
                result.relation_ids = created_relation_ids
                result.details = {
                    "source_id": source_id,
                    "memory_id": memory_id,
                    "total_processed": len(cleaned_records),
                }
            except Exception as e:
                self.store._connection.execute("ROLLBACK")
                result.success = False
                result.errors.append(f"Transaction failed: {e}")
                raise

        return result

    def ingest_csv(
        self,
        content_or_path: str | Path,
        *,
        source_name: str | None = None,
        delimiter: str = ",",
        has_header: bool = True,
        agent_id: str | None = None,
        shared: bool = True,
    ) -> ConnectorResult:
        """Parse and ingest a CSV or TSV string or file path."""
        path = None
        if isinstance(content_or_path, Path) or (isinstance(content_or_path, str) and "\n" not in content_or_path and Path(content_or_path).exists()):
            path = Path(content_or_path)
            raw_text = path.read_text(encoding="utf-8")
            resolved_source_name = source_name or path.name
        else:
            raw_text = str(content_or_path)
            resolved_source_name = source_name or "csv_import"

        reader = csv.DictReader(io.StringIO(raw_text), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return ConnectorResult(connector="triples", success=True, details={"message": "Empty CSV dataset"})

        return self.ingest_triples(
            rows,
            source_name=resolved_source_name,
            agent_id=agent_id,
            shared=shared,
        )

    def ingest_json(
        self,
        content_or_path: str | Path,
        *,
        source_name: str | None = None,
        agent_id: str | None = None,
        shared: bool = True,
    ) -> ConnectorResult:
        """Parse and ingest JSON array of triples or JSONL content."""
        if isinstance(content_or_path, Path) or (isinstance(content_or_path, str) and "\n" not in content_or_path and Path(content_or_path).exists()):
            path = Path(content_or_path)
            raw_text = path.read_text(encoding="utf-8")
            resolved_source_name = source_name or path.name
        else:
            raw_text = str(content_or_path).strip()
            resolved_source_name = source_name or "json_import"

        if raw_text.startswith("["):
            data = json.loads(raw_text)
        else:
            # Try JSONL
            data = []
            for line in raw_text.splitlines():
                if line.strip():
                    data.append(json.loads(line))

        return self.ingest_triples(
            data,
            source_name=resolved_source_name,
            agent_id=agent_id,
            shared=shared,
        )
