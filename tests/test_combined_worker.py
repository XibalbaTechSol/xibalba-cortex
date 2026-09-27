from __future__ import annotations

import json

from xibalba_cortex.combined_worker import process_combined_tasks
from xibalba_cortex.store import GraphStore


def test_combined_worker_uses_one_call_and_completes_independent_tasks(tmp_path):
    store = GraphStore(tmp_path)
    memories = [
        store.store_memory("Cortex uses Hermes for extraction.", source={"kind": "test"}, status="confirmed"),
        store.store_memory("Ship the inference dashboard by Friday.", source={"kind": "test"}, status="confirmed"),
    ]
    for memory in memories:
        # classify_para is automatically queued for confirmed memories.
        for task_type in ("extract_entities", "extract_relations"):
            store.request_inference_task(task_type, subject_type="memory", subject_id=memory["id"], input_payload={"source_content_hash": memory["content_hash"]})

    calls: list[str] = []
    def runner(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps({"results": [
            {
                "memory_id": memories[0]["id"],
                "para": {"category": "resource", "confidence": 0.9, "rationale": "technical reference"},
                "entities": [{"name": "Hermes", "entity_type": "software", "evidence_quote": "Hermes", "confidence": 0.9}],
                "relations": [{"subject": "Cortex", "predicate": "uses", "object": "Hermes", "evidence_quote": "Cortex uses Hermes", "confidence": 0.9}],
            },
            {
                "memory_id": memories[1]["id"],
                "para": {"category": "project", "confidence": 0.95, "rationale": "deadline-bound deliverable"},
                "entities": [{"name": "inference dashboard", "entity_type": "deliverable", "evidence_quote": "inference dashboard", "confidence": 0.9}],
                "relations": [{"subject": "dashboard", "predicate": "due", "object": "Friday", "evidence_quote": "by Friday", "confidence": 0.85}],
            },
        ]})

    result = process_combined_tasks(store, runner=runner, enabled_task_types={"classify_para", "extract_entities", "extract_relations"}, limit=5)
    assert len(calls) == 1
    assert result == {
        "model_calls": 1, "memories": 2, "processed": 6, "completed": 6, "failed": 0,
        "by_type": {
            "classify_para": {"completed": 2, "failed": 0},
            "extract_entities": {"completed": 2, "failed": 0},
            "extract_relations": {"completed": 2, "failed": 0},
        },
    }
    assert len(store.list_inference_tasks(status="completed", limit=20)) == 6
    assert len(store.list_para_classifications(status="proposed")) == 2
    assert len(store.list_extraction_proposals(status="proposed")) == 4


def test_combined_worker_fails_each_claim_when_batch_json_is_invalid(tmp_path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Bounded evidence.", source={"kind": "test"}, status="confirmed")
    for task_type in ("extract_entities",):
        store.request_inference_task(task_type, subject_type="memory", subject_id=memory["id"], input_payload={"source_content_hash": memory["content_hash"]})
    result = process_combined_tasks(store, runner=lambda _: "not-json", enabled_task_types={"classify_para", "extract_entities"})
    assert result["processed"] == result["failed"] == 2
    assert result["model_calls"] == 2
    assert result["completed"] == 0
    assert len(store.list_inference_tasks(status="failed")) == 2


def test_combined_worker_repairs_a_missing_results_envelope(tmp_path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Ship the dashboard by Friday.", source={"kind": "test"}, status="confirmed")
    responses = iter([
        '{"memory_id":"wrong-shape"}',
        json.dumps({"results": [{"memory_id": memory["id"], "para": {"category": "project", "confidence": 0.9, "rationale": "deadline"}}]}),
    ])
    result = process_combined_tasks(store, runner=lambda _: next(responses), enabled_task_types={"classify_para"})
    assert result["model_calls"] == 2
    assert result["completed"] == 1
    assert result["failed"] == 0


def test_combined_worker_dead_letters_tasks_for_deleted_memory_without_crashing(tmp_path):
    store = GraphStore(tmp_path)
    task = store.request_inference_task(
        "classify_para", subject_type="memory", subject_id="deleted-memory",
        input_payload={"source_content_hash": "sha256:" + "a" * 64},
    )
    result = process_combined_tasks(
        store, runner=lambda _: (_ for _ in ()).throw(AssertionError("must not call model")),
        enabled_task_types={"classify_para"},
    )
    failed = store.get_inference_task(task["id"])
    assert result["memories"] == result["model_calls"] == 0
    assert failed["status"] == "failed"
    assert failed["dead_letter_reason"] == "orphaned_memory_subject"
