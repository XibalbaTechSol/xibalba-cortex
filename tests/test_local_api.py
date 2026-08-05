import itertools
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from xibalba_graph.local_api import serve
from xibalba_graph.store import EMBEDDING_DIM, GraphStore


def _unit_vector(hot_index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[hot_index] = 1.0
    return vector


def _get(port: int, path: str) -> tuple[int, object]:
    request = urllib.request.Request(f"http://localhost:{port}{path}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


_next_test_port = itertools.count(18420)  # each test gets its own port: serve() never shuts
# down between tests (matches test_otlp_receiver.py's own daemon-thread pattern), so reusing one
# fixed port across tests would collide with the still-bound previous test's listener.


@pytest.fixture
def running_store(tmp_path):
    store = GraphStore(tmp_path / "graph")
    port = next(_next_test_port)
    thread = threading.Thread(target=serve, kwargs={"store": store, "port": port}, daemon=True)
    thread.start()
    time.sleep(0.3)  # let the server bind
    yield store, port
    store.close()


def test_stats_reports_real_counts(running_store):
    store, port = running_store
    store.store_memory(
        "A memory for stats.",
        source={"kind": "direct_user", "locator": "hermes://session/stats"},
        status="confirmed",
    )
    status, body = _get(port, "/api/stats")
    assert status == 200
    assert body["memories"] == 1


def test_search_returns_matching_memory(running_store):
    store, port = running_store
    store.store_memory(
        "Xibalba Shield local API test content.",
        source={"kind": "direct_user", "locator": "hermes://session/search"},
        status="confirmed",
    )
    status, body = _get(port, "/api/search?q=Shield")
    assert status == 200
    assert body[0]["content"] == "Xibalba Shield local API test content."


def test_memory_detail_and_404(running_store):
    store, port = running_store
    memory = store.store_memory(
        "Detail lookup content.",
        source={"kind": "direct_user", "locator": "hermes://session/detail"},
        status="confirmed",
    )
    status, body = _get(port, f"/api/memory/{memory['id']}")
    assert status == 200
    assert body["content"] == "Detail lookup content."

    status, body = _get(port, "/api/memory/does-not-exist")
    assert status == 404


def test_memory_similar_endpoint(running_store):
    store, port = running_store
    anchor = store.store_memory(
        "Anchor content.",
        source={"kind": "direct_user", "locator": "hermes://session/similar-anchor"},
        status="confirmed",
    )
    near = store.store_memory(
        "Near content.",
        source={"kind": "direct_user", "locator": "hermes://session/similar-near"},
        status="confirmed",
    )
    store.store_embedding(anchor["id"], _unit_vector(0))
    store.store_embedding(near["id"], _unit_vector(0))

    status, body = _get(port, f"/api/memory/{anchor['id']}/similar")
    assert status == 200
    assert body[0]["memory"]["id"] == near["id"]
    assert body[0]["cosine_similarity"] == pytest.approx(1.0)


def test_memory_neighbors_endpoint(running_store):
    store, port = running_store
    memory = store.store_memory(
        "Evidence for a relation.",
        source={"kind": "direct_user", "locator": "hermes://session/neighbors"},
        status="confirmed",
    )
    store.link_entities("Xibalba Shield", "emits_evidence_to", "Integrity Oracle", evidence_memory_id=memory["id"])

    status, body = _get(port, f"/api/memory/{memory['id']}/neighbors")
    assert status == 200
    assert body[0]["predicate"] == "emits_evidence_to"


def test_graph_endpoint_includes_nodes_and_similarity_edges(running_store):
    store, port = running_store
    anchor = store.store_memory(
        "Graph anchor content.",
        source={"kind": "direct_user", "locator": "hermes://session/graph-anchor"},
        status="confirmed",
    )
    near = store.store_memory(
        "Graph near content.",
        source={"kind": "direct_user", "locator": "hermes://session/graph-near"},
        status="confirmed",
    )
    store.store_embedding(anchor["id"], _unit_vector(0))
    store.store_embedding(near["id"], _unit_vector(0))

    status, body = _get(port, "/api/graph")
    assert status == 200
    node_ids = {node["id"] for node in body["nodes"]}
    assert f"memory:{anchor['id']}" in node_ids
    assert f"memory:{near['id']}" in node_ids
    similarity_edges = [e for e in body["edges"] if e["type"] == "similarity"]
    assert len(similarity_edges) == 1
    assert similarity_edges[0]["cosine_similarity"] == pytest.approx(1.0)


def test_returns_404_for_unconfigured_path(running_store):
    _store, port = running_store
    status, _body = _get(port, "/api/nonexistent")
    assert status == 404
