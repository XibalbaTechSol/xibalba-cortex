from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from xibalba_cortex.local_api import serve
from xibalba_cortex.store import GraphStore

def _free_test_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


def _get(port: int, path: str) -> tuple[int, object]:
    request = urllib.request.Request(f"http://localhost:{port}{path}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post(port: int, path: str, payload: dict[str, object]) -> tuple[int, object]:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"http://localhost:{port}{path}", data=body, method="POST", headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def running_store(tmp_path):
    store = GraphStore(tmp_path / "graph")
    port = _free_test_port()
    thread = threading.Thread(target=serve, kwargs={"store": store, "port": port}, daemon=True)
    thread.start()
    time.sleep(0.3)
    yield store, port
    store.close()


def test_hybrid_retrieval_route_returns_trace_and_results(running_store):
    store, port = running_store
    store.store_memory("REST route content about eligibility.", source={"kind": "test"}, status="active")

    status, body = _post(port, "/api/retrieval/hybrid", {"query": "eligibility", "limit": 5})
    assert status == 200
    assert "trace_id" in body
    assert len(body["results"]) == 1

    status, trace = _get(port, f"/api/retrieval/trace/{body['trace_id']}")
    assert status == 200
    assert trace["root_hash"] == body["root_hash"]


def test_retrieval_trace_evidence_route_returns_verifiable_proof(running_store):
    store, port = running_store
    store.store_memory("Provable via REST.", source={"kind": "test"}, status="active")
    status, body = _post(port, "/api/retrieval/hybrid", {"query": "provable", "limit": 5})
    assert status == 200

    status, proof = _get(port, f"/api/retrieval/trace/{body['trace_id']}/evidence?rank=1")
    assert status == 200
    assert "root" in proof and "siblings" in proof


def test_hybrid_retrieval_route_applies_filters_and_budget(running_store):
    store, port = running_store
    store.store_memory("Filtered REST content.", source={"kind": "test"}, status="active", evidence_class="observed_event")
    store.store_memory("Summary REST content.", source={"kind": "test"}, status="active", evidence_class="summary")

    status, body = _post(port, "/api/retrieval/hybrid", {"query": "REST content", "limit": 10, "filters": {"evidence_class": ["observed_event"]}})
    assert status == 200
    assert all(r["evidence_class"] == "observed_event" for r in body["results"])


def test_projection_checkpoint_routes(running_store):
    store, port = running_store
    store.store_memory("Checkpointed via REST.", source={"kind": "test"}, status="active")

    status, checkpoint = _post(port, "/api/projections/memories/checkpoint", {})
    assert status == 200
    assert checkpoint["leaf_count"] == 1

    status, latest = _get(port, "/api/projections/memories/checkpoints/latest")
    assert status == 200
    assert latest["id"] == checkpoint["id"]

    status, history = _get(port, "/api/projections/memories/checkpoints")
    assert status == 200
    assert len(history) == 1

    status, reconciliation = _post(port, "/api/projections/memories/reconcile", {})
    assert status == 200
    assert reconciliation["equal"] is True

    status, rebuilt = _post(port, "/api/projections/memories/rebuild", {})
    assert status == 200
    assert rebuilt["verified"] is True


def test_projection_checkpoints_latest_returns_404_when_none_exist(running_store):
    _store, port = running_store
    status, body = _get(port, "/api/projections/memories/checkpoints/latest")
    assert status == 404


def test_embedding_models_route(running_store):
    _store, port = running_store
    status, models = _get(port, "/api/embedding/models")
    assert status == 200
    assert any(m["state"] == "active" for m in models)


def test_extraction_proposals_routes(running_store):
    store, port = running_store
    memory = store.store_memory("REST extraction subject.", source={"kind": "test"}, status="active")
    task = store.request_inference_task(
        "extract_entities", subject_type="memory", subject_id=memory["id"], input_payload={"source_content_hash": memory["content_hash"]},
    )
    claimed = store.claim_inference_task(task["id"], claimed_by="worker")
    store.complete_inference_task(
        task["id"], claimed_by="worker", claim_token=claimed["claim_token"],
        output_payload={
            "schema_version": "xibalba.entities.v1",
            "input_snapshot_hash": memory["content_hash"],
            "entities": [{"name": "REST", "entity_type": "concept", "evidence_quote": "REST extraction subject", "confidence": 0.9}],
        },
    )

    status, proposals = _get(port, f"/api/extraction-proposals?task_id={task['id']}")
    assert status == 200
    assert len(proposals) == 1

    status, decided = _post(port, f"/api/extraction-proposals/{proposals[0]['id']}/decision", {"decision": "accept", "decided_by": "operator"})
    assert status == 200
    assert decided["status"] == "accepted"
