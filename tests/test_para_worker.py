from pathlib import Path

from xibalba_cortex.para_worker import classify_para_payload, process_para_tasks
from xibalba_cortex.store import GraphStore


def test_para_worker_completes_a_claimed_task_with_hash_bound_output(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Prepare the quarterly launch plan by Friday.", source={"kind": "test"}, status="active")
    store.request_inference_task("classify_para", subject_type="memory", subject_id=memory["id"], input_payload={"source_content_hash": memory["content_hash"]}, idempotency_key="para-worker-1")

    def runner(_: str) -> str:
        return '{"category":"project","confidence":0.93,"rationale":"A concrete deliverable has a deadline.","signals":["deliverable","deadline"],"alternatives":[]}'

    result = process_para_tasks(store, runner=runner, worker_id="test-worker")
    assert result == {"processed": 1, "completed": 1, "failed": 0}
    task = store.list_inference_tasks(status="completed")[0]
    assert task["output"]["source_memory_id"] == memory["id"]
    assert task["output"]["source_content_hash"] == memory["content_hash"]
    assert store.get_para_classification(task["id"])["status"] == "proposed"


def test_para_payload_rejects_invalid_json():
    try:
        classify_para_payload("not json", source_memory_id="m", source_content_hash="h")
    except ValueError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("invalid output was accepted")


def test_para_worker_processes_classify_tasks_even_when_other_tasks_fill_the_page(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("A project with a deadline.", source={"kind": "test"}, status="active")
    for index in range(5):
        store.request_inference_task(
            "extract_memory_metadata",
            subject_type="memory",
            subject_id=memory["id"],
            input_payload={},
            idempotency_key=f"other-{index}",
        )
    store.request_inference_task(
        "classify_para",
        subject_type="memory",
        subject_id=memory["id"],
        input_payload={"source_content_hash": memory["content_hash"]},
        idempotency_key="para-after-other-tasks",
    )

    result = process_para_tasks(
        store,
        limit=1,
        runner=lambda _: '{"category":"project","confidence":0.9,"rationale":"deadline"}',
    )

    assert result == {"processed": 1, "completed": 1, "failed": 0}
