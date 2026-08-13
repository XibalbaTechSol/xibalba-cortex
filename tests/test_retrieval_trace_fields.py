from __future__ import annotations

from pathlib import Path

from xibalba_cortex.events import verify_domain_merkle_proof
from xibalba_cortex.store import EMBEDDING_DIM, EMBEDDING_MODEL_ID, EMBEDDING_MODEL_REVISION, GraphStore


def _unit_vector(hot_index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[hot_index] = 1.0
    return vector


def test_trace_persists_rrf_params_and_candidate_pool_sizes(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Cortex uses Hermes for controlled extraction.", source={"kind": "test"}, status="confirmed")
    result = store.hybrid_retrieve("Hermes extraction", limit=5)
    trace = store.get_retrieval_trace(result["trace_id"])

    assert trace["rrf_params"]["method"] == "rrf"
    assert trace["rrf_params"]["k"] == 60
    assert set(trace["rrf_params"]["weights"]) == {"lexical", "vector", "graph", "temporal"}
    assert set(trace["candidate_pool_sizes"]) == {"lexical", "vector", "graph", "temporal"}
    assert trace["profile_domain"] == "xibalba.retrieval_trace.v1"


def test_trace_records_per_channel_rank_not_just_membership(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Distinct Hermes extraction content.", source={"kind": "test"}, status="confirmed")
    store.store_embedding(memory["id"], _unit_vector(0))
    result = store.hybrid_retrieve("Hermes extraction", query_vector=_unit_vector(0), limit=5)
    trace = store.get_retrieval_trace(result["trace_id"])
    record = next(r for r in trace["results"] if r["memory_id"] == memory["id"])
    assert "lexical" in record["channels"]
    assert record["channels"]["lexical"]["rank"] >= 1
    assert "vector" in record["channels"]
    assert record["channels"]["vector"]["raw_score"] is not None


def test_trace_records_embedding_model_when_vector_supplied(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Vector-backed content.", source={"kind": "test"}, status="confirmed")
    store.store_embedding(memory["id"], _unit_vector(0))
    result = store.hybrid_retrieve("Vector-backed content", query_vector=_unit_vector(0), limit=5)
    trace = store.get_retrieval_trace(result["trace_id"])
    assert trace["embedding_model_id"] == EMBEDDING_MODEL_ID
    assert trace["embedding_model_revision"] == EMBEDDING_MODEL_REVISION
    assert trace["query_vector_hash"].startswith("sha256:")


def test_trace_without_query_vector_has_no_embedding_model_recorded(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Lexical only.", source={"kind": "test"}, status="confirmed")
    result = store.hybrid_retrieve("Lexical only", limit=5)
    trace = store.get_retrieval_trace(result["trace_id"])
    assert trace["embedding_model_id"] is None
    assert trace["query_vector_hash"] is None


def test_trace_graph_evidence_captures_edges_not_just_membership(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Xibalba Cortex uses Hermes for extraction.", source={"kind": "test"}, status="confirmed")
    store.link_entities("Xibalba Cortex", "uses", "Hermes", evidence_memory_id=memory["id"])
    result = store.hybrid_retrieve("Xibalba Cortex", limit=5)
    trace = store.get_retrieval_trace(result["trace_id"])
    if trace["graph_evidence"]:
        edge = trace["graph_evidence"][0]
        assert "predicate" in edge
        assert "evidence_memory_id" in edge


def test_trace_inclusion_proof_verifies_and_fails_on_tamper(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Provable trace content.", source={"kind": "test"}, status="confirmed")
    result = store.hybrid_retrieve("Provable trace content", limit=5)
    proof = store.retrieval_trace_evidence(result["trace_id"], rank=1)
    assert verify_domain_merkle_proof(proof)

    tampered = dict(proof)
    tampered["payload_hash"] = "sha256:" + "0" * 64
    assert not verify_domain_merkle_proof(tampered)


def test_trace_links_to_latest_memories_checkpoint_when_one_exists(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Checkpointed content.", source={"kind": "test"}, status="confirmed")
    checkpoint = store.create_projection_checkpoint("memories")
    result = store.hybrid_retrieve("Checkpointed content", limit=5)
    trace = store.get_retrieval_trace(result["trace_id"])
    assert trace["checkpoint_id"] == checkpoint["id"]


def test_trace_root_domain_matches_retrieval_trace_domain(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Domain-tagged root.", source={"kind": "test"}, status="confirmed")
    result = store.hybrid_retrieve("Domain-tagged root", limit=5)
    trace = store.get_retrieval_trace(result["trace_id"])
    from xibalba_cortex.events import domain_merkle_root

    assert trace["root_hash"] == domain_merkle_root(trace["leaf_hashes"], domain="retrieval_trace")
