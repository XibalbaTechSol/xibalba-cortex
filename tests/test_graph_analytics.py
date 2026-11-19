"""
Tests for Graph Theory & Quantitative Analytics Engine.
Verifies pure-Python spectral graph Laplacian, Fiedler algebraic connectivity,
LPA / modularity community detection, PageRank, Brandes betweenness, and analytics API endpoints.
"""

import json
import math
import pytest
from starlette.testclient import TestClient

from super_cortex.analytics import (
    compute_betweenness_centrality,
    compute_clustering_coefficients,
    compute_connected_components,
    compute_degree_centrality,
    compute_full_graph_scorecard,
    compute_pagerank,
    compute_spectral_properties,
    detect_communities_lpa,
)
from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig
from super_cortex.memory import SuperCortex


@pytest.fixture
def analytics_cortex(tmp_path):
    db_file = tmp_path / "test_analytics.db"
    cfg = SuperCortexConfig(db_path=str(db_file))
    cortex = SuperCortex(config=cfg)

    # Scopes & Agents
    cortex.create_scope("shared", "Shared Memory Fabric", "shared")
    cortex.create_scope("agent:quant", "Quant Research Scope", "single_agent")
    cortex.register_agent("quant", "Hermes Quant", "hermes", "agent:quant")

    # Entities forming a triangle community + a bridge to a second community
    # Community A: e1, e2, e3 (dense triangle)
    cortex.store.add_entity("ModelA")
    cortex.store.add_entity("OptimizerA")
    cortex.store.add_entity("LossA")
    cortex.store.add_relation("ModelA", "uses", "OptimizerA", confidence=1.0)
    cortex.store.add_relation("OptimizerA", "minimizes", "LossA", confidence=1.0)
    cortex.store.add_relation("LossA", "evaluates", "ModelA", confidence=1.0)

    # Bridge: e1 -> e4
    cortex.store.add_entity("DataBridge")
    cortex.store.add_relation("ModelA", "connects", "DataBridge", confidence=0.85)

    # Community B: e4, e5, e6
    cortex.store.add_entity("PipelineB")
    cortex.store.add_entity("StorageB")
    cortex.store.add_relation("DataBridge", "feeds", "PipelineB", confidence=0.9)
    cortex.store.add_relation("PipelineB", "persists_to", "StorageB", confidence=0.95)
    cortex.store.add_relation("StorageB", "caches_for", "DataBridge", confidence=0.8)

    # Memories
    with cortex.store._get_conn() as conn:
        conn.execute(
            """
            INSERT INTO memories (id, source_id, text, epistemic_class, lifecycle_status, content_hash, namespace, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                "mem_analytics_1",
                "quant:spectral",
                "Spectral graph partitioning isolates modular clusters using the Fiedler vector.",
                "rule",
                "active",
                "0xSPECTRAL",
                "agent:quant",
                json.dumps({"scope": "agent:quant"}),
            ),
        )
        conn.commit()

    return cortex


def test_degree_centrality():
    nodes = [
        {"id": "A", "title": "Node A"},
        {"id": "B", "title": "Node B"},
        {"id": "C", "title": "Node C"},
    ]
    edges = [
        {"source": "A", "target": "B"},
        {"source": "A", "target": "C"},
    ]
    dc = compute_degree_centrality(nodes, edges)
    assert dc["A"]["total_degree"] == 2
    assert dc["A"]["degree_centrality"] == 1.0  # 2 / (3-1)
    assert dc["B"]["total_degree"] == 1
    assert dc["B"]["degree_centrality"] == 0.5


def test_pagerank():
    nodes = [
        {"id": "A", "title": "A"},
        {"id": "B", "title": "B"},
        {"id": "C", "title": "C"},
    ]
    edges = [
        {"source": "A", "target": "B"},
        {"source": "C", "target": "B"},
    ]
    pr = compute_pagerank(nodes, edges)
    # B receives all inbound links; should have highest rank
    assert pr["B"] > pr["A"]
    assert pr["B"] > pr["C"]
    assert math.isclose(sum(pr.values()), 1.0, rel_tol=1e-4)


def test_betweenness_centrality():
    # Linear graph: A - B - C
    nodes = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
    edges = [{"source": "A", "target": "B"}, {"source": "B", "target": "C"}]
    bc = compute_betweenness_centrality(nodes, edges)
    # B is the bottleneck; betweenness of B should be 1.0 (or normalized max)
    assert bc["B"] > bc["A"]
    assert bc["B"] > bc["C"]
    assert bc["A"] == 0.0
    assert bc["C"] == 0.0


def test_clustering_coefficients():
    # Triangle: A - B - C - A
    nodes = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
    edges = [{"source": "A", "target": "B"}, {"source": "B", "target": "C"}, {"source": "C", "target": "A"}]
    local_c, avg_c = compute_clustering_coefficients(nodes, edges)
    assert local_c["A"] == 1.0
    assert local_c["B"] == 1.0
    assert local_c["C"] == 1.0
    assert avg_c == 1.0


def test_community_detection_lpa():
    # Two distinct cliques connected by a weak bridge
    nodes = [{"id": f"A{i}"} for i in range(4)] + [{"id": f"B{i}"} for i in range(4)]
    edges = []
    # Clique A
    for i in range(4):
        for j in range(i + 1, 4):
            edges.append({"source": f"A{i}", "target": f"A{j}"})
    # Clique B
    for i in range(4):
        for j in range(i + 1, 4):
            edges.append({"source": f"B{i}", "target": f"B{j}"})
    # Bridge: A0 - B0
    edges.append({"source": "A0", "target": "B0"})

    res = detect_communities_lpa(nodes, edges)
    assert len(res["communities"]) >= 2
    assert res["modularity"] > 0.25  # High modularity for two distinct cliques


def test_spectral_properties():
    # Disconnected graph test
    nodes_disc = [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}]
    edges_disc = [{"source": "A", "target": "B"}, {"source": "C", "target": "D"}]
    spec_disc = compute_spectral_properties(nodes_disc, edges_disc)
    assert spec_disc["is_connected"] is False
    assert spec_disc["algebraic_connectivity"] == 0.0

    # Connected barbell graph
    nodes_conn = [{"id": "A1"}, {"id": "A2"}, {"id": "B1"}, {"id": "B2"}]
    edges_conn = [
        {"source": "A1", "target": "A2"},
        {"source": "B1", "target": "B2"},
        {"source": "A2", "target": "B1"},  # Bridge
    ]
    spec_conn = compute_spectral_properties(nodes_conn, edges_conn)
    assert spec_conn["is_connected"] is True
    assert spec_conn["algebraic_connectivity"] > 0.0
    assert len(spec_conn["bisection_partition"]["cluster_a"]) > 0
    assert len(spec_conn["bisection_partition"]["cluster_b"]) > 0


def test_cortex_sdk_methods(analytics_cortex):
    sc = analytics_cortex.get_graph_analytics()
    assert sc["node_count"] >= 6
    assert sc["edge_count"] >= 5
    assert "top_pagerank_hubs" in sc
    assert "top_betweenness_bridges" in sc

    comms = analytics_cortex.get_communities()
    assert len(comms["communities"]) >= 1

    spec = analytics_cortex.get_spectral_properties()
    assert "algebraic_connectivity" in spec

    pr = analytics_cortex.get_centrality(metric="pagerank")
    assert len(pr) >= 6

    bc = analytics_cortex.get_centrality(metric="betweenness")
    assert len(bc) >= 6


def test_api_analytics_endpoints(analytics_cortex):
    app = create_app(config=analytics_cortex.config)
    client = TestClient(app)

    # 1. /api/spectral (updated with real math)
    resp_spectral = client.get("/api/spectral")
    assert resp_spectral.status_code == 200
    s_data = resp_spectral.json()
    assert "fiedler_lambda2" in s_data
    assert "eigenvalues" in s_data
    assert "top_pagerank_hubs" in s_data

    # 2. /api/analytics/summary
    resp_sum = client.get("/api/analytics/summary")
    assert resp_sum.status_code == 200
    sum_data = resp_sum.json()
    assert sum_data["node_count"] >= 6
    assert "avg_clustering_coefficient" in sum_data

    # 3. /api/analytics/communities
    resp_comm = client.get("/api/analytics/communities")
    assert resp_comm.status_code == 200
    comm_data = resp_comm.json()
    assert "communities" in comm_data

    # 4. /api/analytics/centrality
    resp_cent_pr = client.get("/api/analytics/centrality?metric=pagerank")
    assert resp_cent_pr.status_code == 200
    assert resp_cent_pr.json()["metric"] == "pagerank"

    resp_cent_bc = client.get("/api/analytics/centrality?metric=betweenness")
    assert resp_cent_bc.status_code == 200
    assert resp_cent_bc.json()["metric"] == "betweenness"

    # 5. /api/analytics/spectral
    resp_spec = client.get("/api/analytics/spectral")
    assert resp_spec.status_code == 200
    assert "algebraic_connectivity" in resp_spec.json()
