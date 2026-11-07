"""Tests for Healthcare Researcher Latent Space Demo Dataset and Partitioning."""

from xibalba_cortex.store import GraphStore


def test_seed_healthcare_researcher_dataset(tmp_path):
    store = GraphStore(tmp_path / "graph")
    result = store.seed_sample_knowledge_graph(force=True, dataset="healthcare_researcher")

    assert result["seeded"] is True
    assert result["dataset"] == "healthcare_researcher"
    assert result["entities_created"] >= 50
    assert result["relations_created"] >= 100

    # Test agent partition is registered
    storage_id = store.storage_agent_id("demo-healthcare-researcher")
    assert store.has_agent_partition(storage_id) is True

    # Test graph payload scoped to demo agent returns rich graph
    payload = store.graph_payload(limit=500, agent_id="demo-healthcare-researcher")
    nodes = payload["nodes"]
    edges = payload["edges"]

    assert len(nodes) >= 50
    assert len(edges) >= 100

    # Verify key precision oncology and SOP entities are present
    labels = {n["label"] for n in nodes}
    assert any("Osimertinib" in l for l in labels)
    assert any("KRAS G12C" in l for l in labels)
    assert any("SOP: AMP/ASCO/CAP" in l for l in labels)
    assert any("Project: Pan-Cancer" in l for l in labels)

    store.close()
