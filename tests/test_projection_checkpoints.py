from __future__ import annotations

from pathlib import Path

import pytest

from xibalba_cortex.store import GraphStore


def test_create_and_recompute_projection_checkpoint_round_trip(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("First memory.", source={"kind": "test"}, status="active")
    checkpoint = store.create_projection_checkpoint("memories")
    assert checkpoint["status"] == "active"
    assert checkpoint["leaf_count"] == 1
    assert checkpoint["root_hash"].startswith("sha256:")

    recomputed = store.compute_projection_leaves("memories")
    assert recomputed == checkpoint["leaf_hashes"]


def test_checkpoint_history_accumulates_per_projection(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("One.", source={"kind": "test"}, status="active")
    first = store.create_projection_checkpoint("memories")
    store.store_memory("Two.", source={"kind": "test"}, status="active")
    second = store.create_projection_checkpoint("memories")

    assert first["id"] != second["id"]
    assert first["leaf_count"] == 1
    assert second["leaf_count"] == 2
    history = store.list_projection_checkpoints("memories")
    assert [c["id"] for c in history] == [second["id"], first["id"]]
    assert store.get_latest_projection_checkpoint("memories")["id"] == second["id"]


def test_reconcile_with_no_drift_reports_equal_and_noop(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Unchanged.", source={"kind": "test"}, status="active")
    checkpoint = store.create_projection_checkpoint("memories")
    result = store.reconcile_projection_checkpoint("memories")
    assert result["equal"] is True
    assert result["action"] == "noop"
    assert store.get_projection_checkpoint(checkpoint["id"])["status"] == "active"


def test_reconcile_detects_new_canonical_row_and_marks_checkpoint_degraded(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Original.", source={"kind": "test"}, status="active")
    checkpoint = store.create_projection_checkpoint("memories")
    store.store_memory("Added after the checkpoint.", source={"kind": "test"}, status="active")

    result = store.reconcile_projection_checkpoint("memories")
    assert result["equal"] is False
    assert result["action"] == "rebuild_projection"
    assert len(result["missing"]) == 1
    assert store.get_projection_checkpoint(checkpoint["id"])["status"] == "degraded"


def test_rebuild_projection_checkpoint_verifies_against_a_new_root(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Content.", source={"kind": "test"}, status="active")
    rebuilt = store.rebuild_projection_checkpoint("memories")
    assert rebuilt["verified"] is True
    assert rebuilt["status"] == "active"


def test_unknown_projection_id_is_rejected(tmp_path: Path):
    store = GraphStore(tmp_path)
    with pytest.raises(ValueError, match="unknown projection_id"):
        store.compute_projection_leaves("not-a-real-projection")


def test_projection_checkpoint_root_domain_differs_from_retrieval_trace_domain(tmp_path: Path):
    # The two root domains must never collide -- this is the whole point of B1's
    # domain-tagged Merkle construction. Confirm a trace root and a checkpoint root over
    # equivalent leaf content are not comparable/interchangeable.
    from xibalba_cortex.events import domain_merkle_root

    store = GraphStore(tmp_path)
    store.store_memory("Shared content shape.", source={"kind": "test"}, status="active")
    leaves = store.compute_projection_leaves("memories")
    checkpoint_root = domain_merkle_root(leaves, domain="projection_checkpoint")
    trace_root = domain_merkle_root(leaves, domain="retrieval_trace")
    assert checkpoint_root != trace_root
