from __future__ import annotations

from xibalba_cortex.store import GraphStore
from xibalba_cortex.summary_worker import _normalize_output, process_session_summary_tasks


def test_summary_worker_normalizes_structured_summary_text():
    output = _normalize_output(__import__("json").dumps({
        "schema_version": "xibalba.session_summary.v1",
        "input_snapshot_hash": "sha256:test",
        "summary": {
            "objective": "Prepare the release.",
            "decisions_actions": ["Checklist completed."],
            "outcomes": ["Deployment remains pending."],
            "unresolved_items": ["Schedule deployment."],
        },
        "confidence": 0.9,
        "evidence_ids": ["exchange-1"],
    }))
    assert "Objective: Prepare the release." in output["summary"]
    assert "Deployment remains pending." in output["summary"]


def test_end_session_queues_summary_and_worker_attaches_it(tmp_path):
    store = GraphStore(tmp_path / "summary-worker")
    store.start_session("summary-worker-session", agent_id="agent-a")
    store.store_memory(
        "Please prepare the release checklist.",
        source={"kind": "direct_user", "session_id": "summary-worker-session", "agent_id": "agent-a", "role": "user"},
    )
    store.store_memory(
        "The checklist is ready; deployment remains pending.",
        source={"kind": "direct_model_response", "session_id": "summary-worker-session", "agent_id": "agent-a", "role": "assistant"},
    )
    ended = store.end_session("summary-worker-session")
    assert ended["ended_at"]
    task = store.list_inference_tasks(status="pending", task_type="summarize_session")[0]
    contract = task["input"]["_contract"]
    expected = {
        "schema_version": "xibalba.session_summary.v1",
        "input_snapshot_hash": contract["input_snapshot_hash"],
        "summary": "Prepared the release checklist; deployment remains pending.",
        "confidence": 0.92,
        "evidence_ids": contract["evidence_item_ids"],
    }
    result = process_session_summary_tasks(store, runner=lambda _prompt: __import__("json").dumps(expected))
    assert result == {"processed": 1, "completed": 1, "failed": 0}
    session = store.get_session("summary-worker-session")
    summary = store.get_memory(session["summary_memory_id"])
    assert summary["content"] == expected["summary"]
    assert summary["evidence_class"] == "summary"
    assert summary["status"] == "candidate"
    assert summary["source"]["agent_id"] == session["agent_id"]
    store.close()


def test_end_session_without_exchange_does_not_queue_empty_summary(tmp_path):
    store = GraphStore(tmp_path / "empty-summary")
    store.start_session("empty-session", agent_id="agent-a")
    store.end_session("empty-session")
    assert store.list_inference_tasks(status="pending", task_type="summarize_session") == []
    store.close()


def test_summary_backfill_queues_only_identity_bound_closed_sessions(tmp_path):
    store = GraphStore(tmp_path / "summary-backfill")
    store.start_session("bound-ended", agent_id="agent-a")
    store.store_memory("A completed task.", source={"kind": "test", "session_id": "bound-ended", "agent_id": "agent-a"})
    store.end_session("bound-ended")
    task = store.list_inference_tasks(status="pending", task_type="summarize_session")[0]
    with store._lock:
        store._connection.execute("DELETE FROM memory_inference_tasks WHERE id = ?", (task["id"],))
    assert store.enqueue_missing_session_summaries(limit=1) == 1
    assert store.enqueue_missing_session_summaries(limit=1) == 0
    store.close()
