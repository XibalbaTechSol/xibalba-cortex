from pathlib import Path

from xibalba_cortex.metadata_worker import process_metadata_tasks
from xibalba_cortex.store import GraphStore


def test_metadata_worker_merges_validated_fields_into_meta_node(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Prepare the launch plan for Q4.", source={"kind": "test"}, status="active")
    task = store.request_inference_task(
        "extract_memory_metadata", subject_type="memory", subject_id=memory["id"],
        input_payload={"source_content_hash": memory["content_hash"]}, idempotency_key="metadata-worker-1",
    )

    result = process_metadata_tasks(
        store,
        runner=lambda prompt: '{"schema_version":"xibalba.memory.metadata.v1","source_content_hash":"%s","metadata":{"title":"Launch plan","topics":["planning"],"time_horizon":"short_term"}}' % memory["content_hash"],
    )

    assert result == {"processed": 1, "completed": 1, "failed": 0}
    completed = store.get_inference_task(task["id"])
    assert completed["status"] == "completed"
    refreshed = store.get_memory(memory["id"])
    assert refreshed["meta_json"]["inferred"]["title"] == "Launch plan"
    assert refreshed["meta_json"]["inference_provenance"]["source_content_hash"] == memory["content_hash"]
    assert store.verify_chain(memory["id"])["valid"] is True


def test_metadata_worker_rejects_unknown_fields(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("A note.", source={"kind": "test"}, status="active")
    store.request_inference_task("extract_memory_metadata", subject_type="memory", subject_id=memory["id"], input_payload={}, idempotency_key="metadata-worker-2")
    result = process_metadata_tasks(
        store,
        runner=lambda _: '{"schema_version":"xibalba.memory.metadata.v1","source_content_hash":"%s","metadata":{"secret":"no"}}' % memory["content_hash"],
    )
    assert result == {"processed": 1, "completed": 0, "failed": 1}
    assert store.get_memory(memory["id"])["meta_json"] == {}
