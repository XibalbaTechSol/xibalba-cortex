"""SuperCortex engine: store transactions, hybrid search, and the Supermemory-shaped API."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from super_cortex.engine import EngineStore, HashingEmbedder, hybrid_search
from super_cortex.engine.app import create_app
from super_cortex.engine.chunking import chunk_text
from super_cortex.engine.store import fts_query

DOCS = {
    "deploy": "We deployed the Oracle to Render after applying migration 25 as the postgres role.",
    "billing": "Stripe sandbox checkout passed for the Team plan with webhooks returning 200.",
    "outage": "The sensor outage was caused by a port mismatch between 8435 and the retired 8421.",
    "embed": "The embedding worker projects confirmed memories into a sqlite-vec index.",
}


@pytest.fixture
def store():
    s = EngineStore(":memory:", HashingEmbedder())
    for doc_id, text in DOCS.items():
        s.upsert_document("ns", text, doc_id)
    yield s
    s.close()


def doc_ids(result):
    return [r["documentId"] for r in result["results"]]


def test_upsert_is_idempotent_and_update_replaces_old_text(store):
    assert store.upsert_document("ns", DOCS["deploy"], "deploy")["status"] == "unchanged"
    store.upsert_document("ns", "Completely different content about kittens.", "deploy")
    assert "deploy" not in doc_ids(hybrid_search(store, "ns", "Oracle migration postgres", mode="lexical"))
    assert doc_ids(hybrid_search(store, "ns", "kittens", mode="lexical")) == ["deploy"]
    assert store._conn.execute("SELECT COUNT(*) FROM chunks WHERE doc_id = 'deploy'").fetchone()[0] == 1


def test_delete_removes_document_keyword_index_and_vectors_together(store):
    assert store.delete_documents("ns", ["outage"]) == 1
    assert store.get_document("ns", "outage") is None
    for mode in ("lexical", "vector", "hybrid"):
        assert "outage" not in doc_ids(hybrid_search(store, "ns", "sensor port mismatch", mode=mode, threshold=0.0))
    count = store._conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunk_id LIKE 'outage#%'").fetchone()[0]
    assert count == 0


def test_namespaces_are_isolated(store):
    store.upsert_document("other", "Stripe checkout for another tenant.", "x")
    assert doc_ids(hybrid_search(store, "other", "Stripe checkout", threshold=0.0)) == ["x"]
    assert "x" not in doc_ids(hybrid_search(store, "ns", "Stripe checkout", threshold=0.0))


def test_keyword_hit_survives_threshold_but_unrelated_vector_noise_does_not(store):
    result = hybrid_search(store, "ns", "8421", threshold=0.99)
    assert doc_ids(result) == ["outage"]
    assert "lexical" in result["results"][0]["signals"]


def test_limit_above_ten_is_honoured():
    s = EngineStore(":memory:", HashingEmbedder())
    for i in range(25):
        s.upsert_document("ns", f"release note number {i} about the gateway", f"d{i}")
    assert len(hybrid_search(s, "ns", "release gateway", limit=20, threshold=0.0)["results"]) == 20


def test_python_and_sqlite_vec_backends_rank_identically(store):
    if store.vector_backend != "sqlite-vec":
        pytest.skip("sqlite-vec extension not loadable on this Python build")
    qv = store.embedder.embed(["sensor outage port"])[0]
    fast = store.vector_ranked("ns", qv, 4)
    store.vector_backend = "python"
    slow = store.vector_ranked("ns", qv, 4)
    assert [c for c, _ in fast] == [c for c, _ in slow]
    assert all(abs(a - b) < 1e-5 for (_, a), (_, b) in zip(fast, slow))


def test_fts_query_ors_content_words_and_drops_stopwords():
    assert fts_query("What was the cause of the outage?") == '"cause" OR "outage"'
    assert fts_query("the of a") is None


def test_chunking_keeps_short_text_whole_and_overlaps_long_text():
    assert chunk_text("short memory") == ["short memory"]
    text = " ".join(f"Sentence number {i} has some words." for i in range(60))
    chunks = chunk_text(text, max_chars=200)
    assert len(chunks) > 1 and all(len(c) <= 200 for c in chunks)
    assert chunks[0].split(". ")[-1].rstrip(".") in chunks[1]


# -- API ------------------------------------------------------------------------------------

@pytest.fixture
def api():
    s = EngineStore(":memory:", HashingEmbedder())
    return TestClient(create_app(s, api_key="secret"))


AUTH = {"Authorization": "Bearer secret"}


def test_api_requires_bearer_key(api):
    assert api.get("/namespaces").status_code == 401
    assert api.get("/namespaces", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api.get("/healthz").status_code == 200


def test_api_refuses_to_start_without_a_key(monkeypatch):
    monkeypatch.delenv("SUPER_CORTEX_ENGINE_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_app(EngineStore(":memory:", HashingEmbedder()))


def test_api_round_trip_matches_supermemory_shapes(api):
    r = api.post("/ns/agent-claude/document", json={"content": DOCS["billing"], "id": "mem_1", "metadata": {"scope": "agent:claude"}}, headers=AUTH)
    assert r.status_code == 201 and r.json()["id"] == "mem_1"
    assert api.get("/namespaces", headers=AUTH).json() == {"namespaces": [{"namespace": "agent-claude"}]}
    hits = api.post("/ns/agent-claude/search", json={"query": "Stripe checkout", "include": {"documents": True}}, headers=AUTH).json()
    assert hits["results"][0]["included"]["document"]["id"] == "mem_1"
    assert hits["results"][0]["metadata"] == {"scope": "agent:claude"}
    assert api.get("/ns/agent-claude/document/mem_1", headers=AUTH).json()["content"] == DOCS["billing"]
    assert api.request("DELETE", "/ns/agent-claude/document", json={"ids": ["mem_1"]}, headers=AUTH).json() == {"deleted": 1}
    assert api.get("/ns/agent-claude/document/mem_1", headers=AUTH).status_code == 404


def test_api_rejects_bad_input(api):
    assert api.post("/ns/bad%20ns/search", json={"query": "x"}, headers=AUTH).status_code == 400
    assert api.post("/ns/ok/search", json={}, headers=AUTH).status_code == 400
    assert api.post("/ns/ok/document", json={"content": "   "}, headers=AUTH).status_code == 400
    assert api.post("/ns/ok/search", json={"query": "x", "searchMode": "nonsense"}, headers=AUTH).status_code == 400


def test_api_batch_and_list(api):
    docs = [{"content": f"note {i} about deploys", "id": f"n{i}"} for i in range(12)]
    assert len(api.post("/ns/ns1/document/batch", json={"documents": docs}, headers=AUTH).json()["results"]) == 12
    page = api.post("/ns/ns1/list/documents", json={"page": 2, "limit": 10}, headers=AUTH).json()
    assert page["pagination"] == {"currentPage": 2, "limit": 10, "totalItems": 12, "totalPages": 2}
    assert len(page["documents"]) == 2
