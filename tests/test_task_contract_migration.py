from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xibalba_cortex.store import GraphStore


def test_fresh_db_accepts_new_task_types(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Some content.", source={"kind": "test"}, status="active")
    for task_type in ("extract_propositions", "find_duplicates"):
        task = store.request_inference_task(
            task_type, subject_type="memory", subject_id=memory["id"], input_payload={},
        )
        assert task["task_type"] == task_type


def test_complete_inference_task_rejects_invalid_failure_class(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Some content.", source={"kind": "test"}, status="active")
    task = store.request_inference_task(
        "extract_memory_metadata", subject_type="memory", subject_id=memory["id"], input_payload={},
    )
    claimed = store.claim_inference_task(task["id"], claimed_by="worker")
    with pytest.raises(ValueError, match="failure_class"):
        store.complete_inference_task(
            task["id"], claimed_by="worker", claim_token=claimed["claim_token"],
            error="boom", failure_class="not-a-real-class",
        )


def test_reconcile_legacy_claimed_tasks_dead_letters_rows_without_claim_metadata(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Some content.", source={"kind": "test"}, status="active")
    task = store.request_inference_task(
        "extract_memory_metadata", subject_type="memory", subject_id=memory["id"], input_payload={},
    )
    with store._lock:
        store._connection.execute(
            "UPDATE memory_inference_tasks SET status = 'claimed', claim_owner = NULL, claim_token = NULL WHERE id = ?",
            (task["id"],),
        )
    result = store.reconcile_legacy_claimed_tasks()
    assert result["dead_lettered"] == 1
    reconciled = store.get_inference_task(task["id"])
    assert reconciled["status"] == "failed"
    assert reconciled["failure_class"] == "permanent"
    assert reconciled["dead_letter_reason"] == "legacy_claim_without_metadata"


def test_v8_database_migrates_task_type_check_and_dead_letters_legacy_claims(tmp_path: Path):
    home = tmp_path / "graph"
    store = GraphStore(home)
    memory = store.store_memory("Pre-migration content.", source={"kind": "test"}, status="active")
    task = store.request_inference_task(
        "extract_memory_metadata", subject_type="memory", subject_id=memory["id"], input_payload={},
    )
    store.close()

    # Simulate a v8 database: the old task_type CHECK (no extract_propositions/find_duplicates)
    # and a legacy-shaped claimed row with no claim metadata, the way a store created before
    # the claim-token mechanism existed would already have on disk.
    raw = sqlite3.connect(home / "graph-memory.sqlite3")
    raw.execute("DELETE FROM schema_migrations WHERE version = 9")
    raw.execute("ALTER TABLE memory_inference_tasks RENAME TO memory_inference_tasks_old")
    raw.execute(
        """
        CREATE TABLE memory_inference_tasks (
            id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL CHECK (task_type IN (
                'summarize_session', 'extract_memory_metadata', 'extract_entities',
                'extract_relations', 'detect_contradictions', 'consolidate_memories', 'classify_para'
            )),
            status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'completed', 'failed', 'cancelled')),
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            input_json TEXT NOT NULL,
            output_json TEXT,
            requested_by TEXT,
            claim_owner TEXT,
            claim_token TEXT,
            lease_expires_at TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            retry_after TEXT,
            failure_class TEXT,
            dead_letter_reason TEXT,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    raw.execute(
        """INSERT INTO memory_inference_tasks
        (id, task_type, status, subject_type, subject_id, input_json, output_json,
         requested_by, claim_owner, claim_token, lease_expires_at, attempt_count,
         retry_after, failure_class, dead_letter_reason, error, created_at, updated_at)
        SELECT id, task_type, status, subject_type, subject_id, input_json, output_json,
               requested_by, claim_owner, claim_token, lease_expires_at, attempt_count,
               retry_after, failure_class, dead_letter_reason, error, created_at, updated_at
        FROM memory_inference_tasks_old"""
    )
    # A legacy claimed row with no claim metadata -- must survive the migration and get
    # dead-lettered automatically.
    raw.execute(
        "INSERT INTO memory_inference_tasks (id, task_type, status, subject_type, subject_id, input_json) "
        "VALUES ('legacy-1', 'extract_memory_metadata', 'claimed', 'memory', ?, '{}')",
        (memory["id"],),
    )
    raw.execute("DROP TABLE memory_inference_tasks_old")
    raw.commit()
    raw.close()

    reopened = GraphStore(home)
    assert reopened.status()["schema_version"] == 11

    # Pre-existing row preserved.
    preserved = reopened.get_inference_task(task["id"])
    assert preserved["task_type"] == "extract_memory_metadata"

    # New task types now accepted.
    proposition_task = reopened.request_inference_task(
        "extract_propositions", subject_type="memory", subject_id=memory["id"], input_payload={},
    )
    assert proposition_task["task_type"] == "extract_propositions"

    # Legacy claimed row auto-dead-lettered by the migration.
    legacy = reopened.get_inference_task("legacy-1")
    assert legacy["status"] == "failed"
    assert legacy["dead_letter_reason"] == "legacy_claim_without_metadata"
