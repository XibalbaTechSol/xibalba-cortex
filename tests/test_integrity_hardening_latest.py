from __future__ import annotations

import json
from pathlib import Path

import pytest

from xibalba_cortex.hermes_worker import process_extraction_tasks, validate_extraction_result
from xibalba_cortex.projection_reconcile import compare_roots
from xibalba_cortex.store import GraphStore


def test_temporal_as_of_excludes_future_memories(tmp_path: Path):
    store = GraphStore(tmp_path / "graph")
    old = store.store_memory("old Hermes fact", source={"kind": "test", "observed_at": "2026-08-01T00:00:00Z"}, status="confirmed")
    future = store.store_memory("future Hermes fact", source={"kind": "test", "observed_at": "2026-09-01T00:00:00Z"}, status="confirmed")
    result = store.hybrid_retrieve("Hermes fact", temporal_at="2026-08-15T00:00:00Z", limit=10)
    ids = {item["id"] for item in result["results"]}
    assert old["id"] in ids
    assert future["id"] not in ids
    assert result["channel_status"]["vector"] == "unavailable"


def test_extraction_quote_must_be_contained_in_source():
    with pytest.raises(ValueError, match="evidence_quote"):
        validate_extraction_result(
            {
                "schema_version": "xibalba.entities.v1",
                "input_snapshot_hash": "sha256:" + "1" * 64,
                "entities": [{"name": "Hermes", "entity_type": "software", "evidence_quote": "not present", "confidence": 0.9}],
            },
            expected_hash="sha256:" + "1" * 64,
            kind="entities",
            source_content="Hermes is the worker.",
        )


def test_projection_root_is_recomputed_from_ordered_leaves():
    with pytest.raises(ValueError, match="root_hash"):
        compare_roots(
            {"root_profile": "xibalba.projection_checkpoint.v1", "root_hash": "sha256:" + "f" * 64, "leaf_hashes": ["sha256:" + "1" * 64]},
            {"root_profile": "xibalba.projection_checkpoint.v1", "root_hash": "sha256:" + "f" * 64, "leaf_hashes": ["sha256:" + "1" * 64]},
        )


def test_worker_failure_completion_does_not_escape_when_claim_is_lost(tmp_path: Path):
    store = GraphStore(tmp_path / "graph")
    memory = store.store_memory("Hermes source", source={"kind": "test"}, status="confirmed")
    store.request_inference_task("extract_entities", subject_type="memory", subject_id=memory["id"], input_payload={"source_content_hash": memory["content_hash"]}, idempotency_key="lost-claim")
    original = store.complete_inference_task
    calls = {"count": 0}

    def lose_claim(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("simulated lost claim")
        return original(*args, **kwargs)

    store.complete_inference_task = lose_claim  # type: ignore[method-assign]
    result = process_extraction_tasks(store, runner=lambda _: "{}", worker_id="worker")
    assert result["failed"] == 1
    assert calls["count"] == 1
