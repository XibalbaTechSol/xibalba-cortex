from __future__ import annotations

from pathlib import Path

import pytest

from xibalba_cortex.store import GraphStore


def _entity_task(store: GraphStore, content: str = "Xibalba Solutions LLC is based in Texas."):
    memory = store.store_memory(content, source={"kind": "test"}, status="active")
    task = store.request_inference_task(
        "extract_entities",
        subject_type="memory",
        subject_id=memory["id"],
        input_payload={"source_content_hash": memory["content_hash"]},
    )
    claimed = store.claim_inference_task(task["id"], claimed_by="test-worker")
    return memory, claimed


def _valid_entities_output(memory) -> dict:
    return {
        "schema_version": "xibalba.entities.v1",
        "input_snapshot_hash": memory["content_hash"],
        "entities": [
            {"name": "Xibalba Solutions LLC", "entity_type": "organization", "evidence_quote": "Xibalba Solutions LLC", "confidence": 0.9},
            {"name": "Texas", "entity_type": "location", "evidence_quote": "Texas", "confidence": 0.8},
        ],
    }


def test_completion_inserts_one_proposal_row_per_item(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory, claimed = _entity_task(store)
    completed = store.complete_inference_task(
        claimed["id"], claimed_by="test-worker", claim_token=claimed["claim_token"],
        output_payload=_valid_entities_output(memory),
    )
    assert completed["status"] == "completed"
    proposals = store.list_extraction_proposals(status="proposed", task_id=claimed["id"])
    assert len(proposals) == 2
    assert {p["payload"]["name"] for p in proposals} == {"Xibalba Solutions LLC", "Texas"}
    assert all(p["source_memory_id"] == memory["id"] for p in proposals)
    assert all(p["source_content_hash"] == memory["content_hash"] for p in proposals)


def test_completion_is_idempotent_on_reinsert(tmp_path: Path):
    # Re-inserting proposals for the same task_id/item_index should replace, not duplicate.
    store = GraphStore(tmp_path)
    memory, claimed = _entity_task(store)
    store.complete_inference_task(
        claimed["id"], claimed_by="test-worker", claim_token=claimed["claim_token"],
        output_payload=_valid_entities_output(memory),
    )
    task = store.get_inference_task(claimed["id"])
    store._insert_extraction_proposals(task, _valid_entities_output(memory)["entities"], source_content_hash=memory["content_hash"])
    assert len(store.list_extraction_proposals(status="proposed", task_id=claimed["id"])) == 2


def test_completion_fails_closed_on_contaminated_evidence_quote(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory, claimed = _entity_task(store)
    output = _valid_entities_output(memory)
    output["entities"][0]["evidence_quote"] = "totally unrelated recalled context"
    completed = store.complete_inference_task(
        claimed["id"], claimed_by="test-worker", claim_token=claimed["claim_token"], output_payload=output,
    )
    assert completed["status"] == "failed"
    assert completed["failure_class"] == "validation"
    assert completed["dead_letter_reason"] == "extraction_validation_failed"
    assert store.list_extraction_proposals(status="proposed", task_id=claimed["id"]) == []


def test_completion_fails_closed_on_snapshot_hash_mismatch(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory, claimed = _entity_task(store)
    output = _valid_entities_output(memory)
    output["input_snapshot_hash"] = "sha256:" + "0" * 64
    completed = store.complete_inference_task(
        claimed["id"], claimed_by="test-worker", claim_token=claimed["claim_token"], output_payload=output,
    )
    assert completed["status"] == "failed"
    assert store.list_extraction_proposals(status="proposed", task_id=claimed["id"]) == []


def test_accept_extraction_proposal_never_mutates_source_memory(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory, claimed = _entity_task(store)
    store.complete_inference_task(
        claimed["id"], claimed_by="test-worker", claim_token=claimed["claim_token"],
        output_payload=_valid_entities_output(memory),
    )
    proposal = store.list_extraction_proposals(status="proposed", task_id=claimed["id"])[0]
    before = store.get_memory(memory["id"])
    accepted = store.decide_extraction_proposal(proposal["id"], decision="accept", decided_by="operator")
    after = store.get_memory(memory["id"])
    assert accepted["status"] == "accepted"
    assert after["content_hash"] == before["content_hash"]
    assert after["content"] == before["content"]
    neighbors = store.neighbors(proposal["payload"]["name"]) if proposal["task_type"] == "extract_relations" else None
    assert store._find_entity(proposal["payload"]["name"]) is not None


def test_accept_extraction_proposal_rejects_when_source_hash_diverged(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory, claimed = _entity_task(store)
    store.complete_inference_task(
        claimed["id"], claimed_by="test-worker", claim_token=claimed["claim_token"],
        output_payload=_valid_entities_output(memory),
    )
    proposal = store.list_extraction_proposals(status="proposed", task_id=claimed["id"])[0]
    with store._lock:
        store._connection.execute(
            "UPDATE extraction_proposals SET source_content_hash = ? WHERE id = ?",
            ("sha256:" + "f" * 64, proposal["id"]),
        )

    with pytest.raises(ValueError, match="stale"):
        store.decide_extraction_proposal(proposal["id"], decision="accept")

    stale = store.get_extraction_proposal(proposal["id"])
    assert stale["status"] == "stale"


def test_dismiss_extraction_proposal(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory, claimed = _entity_task(store)
    store.complete_inference_task(
        claimed["id"], claimed_by="test-worker", claim_token=claimed["claim_token"],
        output_payload=_valid_entities_output(memory),
    )
    proposal = store.list_extraction_proposals(status="proposed", task_id=claimed["id"])[0]
    dismissed = store.decide_extraction_proposal(proposal["id"], decision="dismiss", note="not relevant")
    assert dismissed["status"] == "dismissed"
    assert dismissed["decision_note"] == "not relevant"


def test_extract_relations_proposal_applies_as_relation_edge(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Xibalba Solutions LLC operates Xibalba Shield.", source={"kind": "test"}, status="active")
    task = store.request_inference_task(
        "extract_relations", subject_type="memory", subject_id=memory["id"],
        input_payload={"source_content_hash": memory["content_hash"]},
    )
    claimed = store.claim_inference_task(task["id"], claimed_by="test-worker")
    output = {
        "schema_version": "xibalba.relations.v1",
        "input_snapshot_hash": memory["content_hash"],
        "relations": [
            {"subject": "Xibalba Solutions LLC", "predicate": "operates", "object": "Xibalba Shield", "evidence_quote": "Xibalba Solutions LLC operates Xibalba Shield", "confidence": 0.9},
        ],
    }
    store.complete_inference_task(claimed["id"], claimed_by="test-worker", claim_token=claimed["claim_token"], output_payload=output)
    proposal = store.list_extraction_proposals(status="proposed", task_id=claimed["id"])[0]
    store.decide_extraction_proposal(proposal["id"], decision="accept")
    neighbors = store.neighbors("Xibalba Solutions LLC")
    assert any(edge["predicate"] == "operates" and edge["object"] == "Xibalba Shield" for edge in neighbors["edges"])
