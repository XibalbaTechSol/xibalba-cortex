from pathlib import Path

import pytest

from xibalba_cortex.store import GraphStore


def test_para_task_is_accepted_and_is_idempotent(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Launch the new website by Friday.", source={"kind": "test"}, status="active")
    task = store.request_inference_task(
        "classify_para",
        subject_type="memory",
        subject_id=memory["id"],
        input_payload={"source_content_hash": memory["content_hash"]},
        requested_by="test",
        idempotency_key="para-task-1",
    )
    store.claim_inference_task(task["id"], claimed_by="test-worker")
    claimed = store.get_inference_task(task["id"])
    completed = store.complete_inference_task(
        task["id"],
        claimed_by="test-worker",
        claim_token=claimed["claim_token"],
        output_payload={
            "category": "project",
            "confidence": 0.91,
            "rationale": "It has a concrete deliverable and deadline.",
            "signals": ["deliverable", "deadline"],
            "alternatives": [],
            "source_memory_id": memory["id"],
            "source_content_hash": memory["content_hash"],
        },
    )
    proposal = store.get_para_classification(task["id"])
    assert completed["status"] == "completed"
    assert proposal["status"] == "proposed"
    accepted = store.accept_para_classification(task["id"], decision="accept")
    assert accepted["status"] == "accepted"
    assert store.accept_para_classification(task["id"], decision="accept")["status"] == "accepted"


def test_para_completion_rejects_invalid_category_and_stale_source(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Reference notes.", source={"kind": "test"}, status="active")
    task = store.request_inference_task("classify_para", subject_type="memory", subject_id=memory["id"], input_payload={"source_content_hash": memory["content_hash"]})
    store.claim_inference_task(task["id"], claimed_by="test-worker")
    claimed = store.get_inference_task(task["id"])
    with pytest.raises(ValueError, match="category"):
        store.complete_inference_task(task["id"], claimed_by="test-worker", claim_token=claimed["claim_token"], output_payload={"category": "other"})
    with pytest.raises(ValueError, match="source_content_hash"):
        store.complete_inference_task(task["id"], claimed_by="test-worker", claim_token=claimed["claim_token"], output_payload={"category": "resource", "confidence": 0.8, "rationale": "reference", "source_memory_id": memory["id"], "source_content_hash": "sha256:stale"})


def test_stale_para_decision_is_recorded_without_mutating_memory(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Keep the original notes.", source={"kind": "test"}, status="active")
    task = store.request_inference_task(
        "classify_para",
        subject_type="memory",
        subject_id=memory["id"],
        input_payload={"source_content_hash": memory["content_hash"]},
    )
    store.claim_inference_task(task["id"], claimed_by="test-worker")
    claimed = store.get_inference_task(task["id"])
    store.complete_inference_task(
        task["id"],
        claimed_by="test-worker",
        claim_token=claimed["claim_token"],
        output_payload={
            "category": "resource",
            "confidence": 0.8,
            "rationale": "Reference material.",
            "source_memory_id": memory["id"],
            "source_content_hash": memory["content_hash"],
        },
    )
    original_hash = memory["content_hash"]
    with store._lock:
        store._connection.execute(
            "UPDATE para_classifications SET source_content_hash = ? WHERE task_id = ?",
            ("sha256:stale", task["id"]),
        )

    with pytest.raises(ValueError, match="stale"):
        store.accept_para_classification(task["id"], decision="accept")

    proposal = store.get_para_classification(task["id"])
    assert proposal["status"] == "stale"
    assert store.get_memory(memory["id"])["content_hash"] == original_hash
