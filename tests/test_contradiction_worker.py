from __future__ import annotations

import json
from pathlib import Path

import pytest

from xibalba_cortex.contradiction_worker import process_contradiction_tasks
from xibalba_cortex.store import EMBEDDING_DIM, GraphStore
from xibalba_cortex.providers import EvidenceScope, InferenceTaskContract


def _unit_vector(hot_index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[hot_index] = 1.0
    return vector


def test_candidate_generation_finds_similar_pair_and_worker_completes(tmp_path: Path):
    store = GraphStore(tmp_path)
    subject = store.store_memory("Xibalba Shield ships in Q3.", source={"kind": "direct_user"}, status="active")
    candidate = store.store_memory("Xibalba Shield ships in Q1.", source={"kind": "web"}, status="active")
    store.store_embedding(subject["id"], _unit_vector(0))
    store.store_embedding(candidate["id"], _unit_vector(0))

    task = store.request_inference_task(
        "detect_contradictions", subject_type="memory", subject_id=subject["id"],
        input_payload={"source_content_hash": subject["content_hash"]},
        contract=InferenceTaskContract(
            evidence_scope=(subject["id"], candidate["id"]),
            evidence_limits=EvidenceScope(max_items=2),
        ),
    )

    def runner(prompt: str) -> str:
        assert candidate["id"] in prompt
        return json.dumps({
            "schema_version": "xibalba.contradictions.v1",
            "input_snapshot_hash": subject["content_hash"],
            "contradictions": [{"contradicting_memory_id": candidate["id"], "reason": "conflicting ship dates", "confidence": 0.9}],
        })

    result = process_contradiction_tasks(store, runner=runner, worker_id="test-worker")
    assert result == {"processed": 1, "completed": 1, "failed": 0}

    completed_task = store.get_inference_task(task["id"])
    assert completed_task["status"] == "completed"

    proposals = store.list_extraction_proposals(status="proposed", task_id=task["id"])
    assert len(proposals) == 1
    payload = proposals[0]["payload"]
    assert payload["contradicting_memory_id"] == candidate["id"]
    assert payload["subject_source_kind"] == "direct_user"
    assert payload["contradicting_source_kind"] == "web"
    assert payload["auto_recommendation"] == "prefer_subject"  # direct_user (1.0) > web (0.3)


def test_worker_completes_with_no_findings_when_no_embedding_exists(tmp_path: Path):
    store = GraphStore(tmp_path)
    subject = store.store_memory("Standalone content, no embedding.", source={"kind": "test"}, status="active")
    task = store.request_inference_task(
        "detect_contradictions", subject_type="memory", subject_id=subject["id"],
        input_payload={"source_content_hash": subject["content_hash"]},
        contract=InferenceTaskContract(
            evidence_scope=(subject["id"],),
            evidence_limits=EvidenceScope(max_items=1),
        ),
    )

    def runner(prompt: str) -> str:
        raise AssertionError("runner should not be called when there are no candidates")

    result = process_contradiction_tasks(store, runner=runner, worker_id="test-worker")
    assert result == {"processed": 1, "completed": 1, "failed": 0}
    assert store.get_inference_task(task["id"])["status"] == "completed"
    assert store.list_extraction_proposals(status="proposed", task_id=task["id"]) == []


def test_worker_rejects_missing_candidate_from_evidence_scope(tmp_path: Path):
    store = GraphStore(tmp_path)
    subject = store.store_memory("Subject statement.", source={"kind": "direct_user"}, status="active")
    candidate = store.store_memory("Candidate statement.", source={"kind": "web"}, status="active")
    task = store.request_inference_task(
        "detect_contradictions", subject_type="memory", subject_id=subject["id"],
        input_payload={"source_content_hash": subject["content_hash"]},
        contract=InferenceTaskContract(
            evidence_scope=(subject["id"],),
            evidence_limits=EvidenceScope(max_items=1),
        ),
    )
    result = process_contradiction_tasks(
        store,
        runner=lambda prompt: (_ for _ in ()).throw(AssertionError("runner must not see out-of-scope data")),
        worker_id="test-worker",
    )
    assert result == {"processed": 1, "completed": 1, "failed": 0}
    assert store.list_extraction_proposals(status="proposed", task_id=task["id"]) == []


def test_accepting_contradiction_proposal_rejects_stale_source_hash(tmp_path: Path):
    store = GraphStore(tmp_path)
    subject = store.store_memory("Xibalba Shield ships in Q3.", source={"kind": "direct_user"}, status="active")
    candidate = store.store_memory("Xibalba Shield ships in Q1.", source={"kind": "web"}, status="active")
    store.store_embedding(subject["id"], _unit_vector(0))
    store.store_embedding(candidate["id"], _unit_vector(0))

    def runner(prompt: str) -> str:
        return json.dumps({
            "schema_version": "xibalba.contradictions.v1",
            "input_snapshot_hash": subject["content_hash"],
            "contradictions": [{"contradicting_memory_id": candidate["id"], "reason": "conflicting ship dates", "confidence": 0.9}],
        })

    task = store.request_inference_task(
        "detect_contradictions", subject_type="memory", subject_id=subject["id"],
        input_payload={"source_content_hash": subject["content_hash"]},
        contract=InferenceTaskContract(
            evidence_scope=(subject["id"], candidate["id"]),
            evidence_limits=EvidenceScope(max_items=2),
        ),
    )
    process_contradiction_tasks(store, runner=runner, worker_id="test-worker")
    proposal = store.list_extraction_proposals(status="proposed", task_id=task["id"])[0]
    with store._lock:
        store._connection.execute(
            "UPDATE extraction_proposals SET source_content_hash = ? WHERE id = ?",
            ("sha256:" + "f" * 64, proposal["id"]),
        )

    with pytest.raises(ValueError, match="stale"):
        store.decide_extraction_proposal(proposal["id"], decision="accept")
    assert store.get_extraction_proposal(proposal["id"])["status"] == "stale"
    assert store.contradictions(subject["id"]) == []


def test_accepting_contradiction_proposal_rejects_changed_candidate_hash(tmp_path: Path):
    store = GraphStore(tmp_path)
    subject = store.store_memory("Xibalba Shield ships in Q3.", source={"kind": "direct_user"}, status="active")
    candidate = store.store_memory("Xibalba Shield ships in Q1.", source={"kind": "web"}, status="active")
    store.store_embedding(subject["id"], _unit_vector(0))
    store.store_embedding(candidate["id"], _unit_vector(0))
    task = store.request_inference_task(
        "detect_contradictions", subject_type="memory", subject_id=subject["id"],
        input_payload={"source_content_hash": subject["content_hash"]},
        contract=InferenceTaskContract(
            evidence_scope=(subject["id"], candidate["id"]),
            evidence_limits=EvidenceScope(max_items=2),
        ),
    )
    process_contradiction_tasks(
        store,
        runner=lambda _: json.dumps({
            "schema_version": "xibalba.contradictions.v1",
            "input_snapshot_hash": subject["content_hash"],
            "contradictions": [{"contradicting_memory_id": candidate["id"], "reason": "conflicting ship dates", "confidence": 0.9}],
        }),
        worker_id="test-worker",
    )
    proposal = store.list_extraction_proposals(status="proposed", task_id=task["id"])[0]
    changed_content = "Xibalba Shield ships in Q4."
    changed_hash = "sha256:" + __import__("hashlib").sha256(changed_content.encode()).hexdigest()
    with store._lock:
        store._connection.execute(
            "UPDATE memories SET content = ?, content_hash = ? WHERE id = ?",
            (changed_content, changed_hash, candidate["id"]),
        )

    with pytest.raises(ValueError, match="contradicting memory changed"):
        store.decide_extraction_proposal(proposal["id"], decision="accept")
    assert store.get_extraction_proposal(proposal["id"])["status"] == "stale"
    assert store.contradictions(subject["id"]) == []


def test_accepting_contradiction_proposal_marks_contradiction(tmp_path: Path):
    store = GraphStore(tmp_path)
    subject = store.store_memory("Xibalba Shield ships in Q3.", source={"kind": "direct_user"}, status="active")
    candidate = store.store_memory("Xibalba Shield ships in Q1.", source={"kind": "web"}, status="active")
    store.store_embedding(subject["id"], _unit_vector(0))
    store.store_embedding(candidate["id"], _unit_vector(0))

    def runner(prompt: str) -> str:
        return json.dumps({
            "schema_version": "xibalba.contradictions.v1",
            "input_snapshot_hash": subject["content_hash"],
            "contradictions": [{"contradicting_memory_id": candidate["id"], "reason": "conflicting ship dates", "confidence": 0.9}],
        })

    store.request_inference_task(
        "detect_contradictions", subject_type="memory", subject_id=subject["id"],
        input_payload={"source_content_hash": subject["content_hash"]},
        contract=InferenceTaskContract(
            evidence_scope=(subject["id"], candidate["id"]),
            evidence_limits=EvidenceScope(max_items=2),
        ),
    )
    process_contradiction_tasks(store, runner=runner, worker_id="test-worker")
    proposal = store.list_extraction_proposals(status="proposed")[0]

    before = store.get_memory(subject["id"])
    accepted = store.decide_extraction_proposal(proposal["id"], decision="accept")
    assert accepted["status"] == "accepted"
    after = store.get_memory(subject["id"])
    assert after["content_hash"] == before["content_hash"]  # accept never mutates the source
    assert any(other["id"] == candidate["id"] for other in store.contradictions(subject["id"]))
    with pytest.raises(ValueError, match="not actionable"):
        store.decide_extraction_proposal(proposal["id"], decision="accept")
    assert len(store.contradictions(subject["id"])) == 1
