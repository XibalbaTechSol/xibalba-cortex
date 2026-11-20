"""Unit tests for Supermemory-Style 2D Circular Cluster Layout & Boundaries."""

import math
import pytest
from starlette.testclient import TestClient

from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test_2d_clusters.db"
    config = SuperCortexConfig(db_path=db_path)
    app = create_app(config=config)
    with TestClient(app) as test_client:
        yield test_client


def test_supermemory_2d_clusters_in_api_graph(client: TestClient):
    # 1. Populate nodes across various scopes
    scopes_and_nodes = [
        ("shared", "System Wide Operational Invariant", "rule"),
        ("shared", "Global Orchestrator Boundary Policy", "rule"),
        ("shared", "Cryptographic Ed25519 Authority Key", "fact"),
        ("agent:xibalba", "Hermes Quant Execution Alpha Strategy", "decision"),
        ("agent:xibalba", "Dynamic Grid PID Feedback Controller", "decision"),
        ("agent:claude", "Code Architecture Review Guideline", "rule"),
        ("agent:claude", "Automated Subagent Verification Protocol", "inference"),
        ("github:XibalbaTechSol/super-cortex:code", "API Router Implementation in api.py", "fact"),
        ("github:XibalbaTechSol/super-cortex:code", "Storage SQLite Engine in store.py", "fact"),
        ("github:XibalbaTechSol/super-cortex:images", "Neon Brain Logo Vector Asset", "fact"),
        ("github:XibalbaTechSol/super-cortex:images", "Favicon Icon Graphic Asset", "fact"),
    ]

    for scope, title, ep in scopes_and_nodes:
        is_img = ":images" in scope
        payload = {
            "title": title,
            "content": f"Content for {title} in {scope}",
            "scope": scope,
            "node_type": "image_media" if is_img else "memory_item",
            "epistemic_class": ep,
            "category": "image" if is_img else "resource",
        }
        res = client.post("/api/nodes", json=payload)
        assert res.status_code == 201

    # 2. Query /api/graph
    r_graph = client.get("/api/graph?scope=all")
    assert r_graph.status_code == 200
    data = r_graph.json()

    assert "nodes" in data
    assert "clusters" in data
    clusters = data["clusters"]
    nodes = data["nodes"]

    assert len(clusters) >= 3, f"Expected at least 3 clusters, got {len(clusters)}"

    # 3. Verify each cluster structure
    cluster_map = {}
    for c in clusters:
        assert "id" in c
        assert "title" in c
        assert "center" in c
        assert len(c["center"]) == 2  # [cx, cy]
        assert "radius" in c
        assert c["radius"] >= 40.0
        assert "count" in c
        assert c["count"] >= 1
        assert "color" in c
        cluster_map[c["id"]] = c

    # 4. Verify no overlapping clusters: dist(C_i, C_j) >= R_i + R_j
    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            c_a = clusters[i]
            c_b = clusters[j]
            dx = c_a["center"][0] - c_b["center"][0]
            dy = c_a["center"][1] - c_b["center"][1]
            dist = math.hypot(dx, dy)
            min_allowed = (c_a["radius"] + c_b["radius"]) * 0.90  # Allow slight tolerance
            assert dist >= min_allowed, (
                f"Clusters {c_a['title']} and {c_b['title']} overlap! "
                f"Dist={dist:.1f}, MinAllowed={min_allowed:.1f}"
            )

    # 5. Verify every node has valid 2D coordinates within its cluster boundary
    for node in nodes:
        pos2d = node.get("pos2D")
        assert pos2d is not None, f"Node {node['id']} missing pos2D"
        assert len(pos2d) == 3
        assert pos2d[2] == 0 or abs(pos2d[2]) < 0.001, f"pos2D Z should be 0, got {pos2d[2]}"

        # Node should have an assigned cluster
        cid = node.get("cluster_id")
        if cid and cid in cluster_map:
            c = cluster_map[cid]
            cx, cy = c["center"]
            dx = pos2d[0] - cx
            dy = pos2d[1] - cy
            d_from_center = math.hypot(dx, dy)
            # Node should lie within cluster radius (with margin)
            assert d_from_center <= c["radius"] + 15.0, (
                f"Node {node['id']} at ({pos2d[0]}, {pos2d[1]}) outside cluster {c['title']} "
                f"(center={cx},{cy}, radius={c['radius']}, dist={d_from_center})"
            )
