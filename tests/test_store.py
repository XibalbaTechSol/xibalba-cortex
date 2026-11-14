from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from super_cortex.models import LifecycleStatus, MemoryRecord
from super_cortex.store import GENESIS_HASH, ProvenanceStore, compute_merkle_root, sha256_hex


@pytest.fixture
def temp_store(tmp_path: Path) -> ProvenanceStore:
    db_file = tmp_path / "test_provenance.db"
    return ProvenanceStore(db_file)


def test_genesis_chain_verification(temp_store: ProvenanceStore):
    res = temp_store.verify_chain()
    assert res["valid"] is True
    assert res["event_count"] == 0
    assert res["head_hash"] == GENESIS_HASH


def test_append_event_and_verification(temp_store: ProvenanceStore):
    ev1 = temp_store.append_event(
        actor="test_agent", transition="remember", payload={"text": "First event"}
    )
    assert ev1.prior_hash == GENESIS_HASH
    assert len(ev1.event_hash) == 64

    ev2 = temp_store.append_event(
        actor="test_agent", transition="remember", payload={"text": "Second event"}
    )
    assert ev2.prior_hash == ev1.event_hash

    res = temp_store.verify_chain()
    assert res["valid"] is True
    assert res["event_count"] == 2
    assert res["head_hash"] == ev2.event_hash


def test_chain_tamper_detection(temp_store: ProvenanceStore):
    temp_store.append_event(actor="agent1", transition="remember", payload={"val": 1})
    temp_store.append_event(actor="agent1", transition="remember", payload={"val": 2})

    # Tamper with event payload in database directly
    with temp_store._get_conn() as conn:
        conn.execute("UPDATE events SET payload_json = '{\"val\": 999}' WHERE id = 1")
        conn.commit()

    res = temp_store.verify_chain()
    assert res["valid"] is False
    assert "corruption" in res["error"]


def test_memory_lifecycle(temp_store: ProvenanceStore):
    mem = MemoryRecord(
        id="mem_001",
        text="All systems operational.",
        content_hash=sha256_hex("All systems operational."),
        namespace="test_ns",
    )
    temp_store.save_memory(mem)

    fetched = temp_store.get_memory("mem_001")
    assert fetched is not None
    assert fetched.text == "All systems operational."
    assert fetched.lifecycle_status == LifecycleStatus.ACTIVE.value

    # Update lifecycle to contradicted
    updated = temp_store.update_memory_status("mem_001", LifecycleStatus.CONTRADICTED)
    assert updated is True

    fetched2 = temp_store.get_memory("mem_001")
    assert fetched2.lifecycle_status == LifecycleStatus.CONTRADICTED.value


def test_entity_graph(temp_store: ProvenanceStore):
    temp_store.add_entity("Xibalba", aliases=["XBS"])
    temp_store.add_entity("Supermemory")

    rel = temp_store.add_relation(
        subject="Xibalba",
        predicate="integrates",
        object="Supermemory",
        confidence=0.98,
        evidence_links=["https://xibalba.io/cortex"],
    )
    assert rel.predicate == "integrates"

    neighbors = temp_store.get_neighbors("Xibalba")
    assert len(neighbors) == 1
    assert neighbors[0]["object"] == "Supermemory"


def test_session_exchanges_and_merkle_root(temp_store: ProvenanceStore):
    session_id = "sess_123"
    ex1 = temp_store.save_exchange(
        session_id=session_id,
        prompt_text="Hello",
        response_text="Greetings",
    )
    assert ex1.turn_hash is not None

    ex2 = temp_store.save_exchange(
        session_id=session_id,
        prompt_text="Compute status",
        response_text="Nominal",
    )
    assert ex2.parent_hash == ex1.turn_hash

    root = temp_store.session_merkle_root(session_id)
    assert len(root) == 64
    assert root != GENESIS_HASH


def test_compute_merkle_root_empty_and_odd():
    assert compute_merkle_root([]) == GENESIS_HASH
    leaf1 = sha256_hex("leaf1")
    assert compute_merkle_root([leaf1]) == leaf1

    leaf2 = sha256_hex("leaf2")
    leaf3 = sha256_hex("leaf3")
    root_3 = compute_merkle_root([leaf1, leaf2, leaf3])
    assert len(root_3) == 64
