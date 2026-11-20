"""Unit tests for Custom Nodes, Scopes, Configurable Properties, Relationships and Layout Parameters."""

import pytest
from starlette.testclient import TestClient

from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test_nodes_cortex.db"
    config = SuperCortexConfig(db_path=db_path)
    app = create_app(config=config)
    with TestClient(app) as test_client:
        yield test_client


def test_create_custom_node_with_custom_scope_and_relationships(client: TestClient):
    # 1. Create a target node first
    target_payload = {
        "title": "Quantum Key Distribution Policy",
        "content": "Defines cryptographic boundaries for high-assurance agent key handshakes.",
        "scope": "agent:shield",
        "node_type": "security_policy",
        "epistemic_class": "rule",
        "category": "project",
        "properties": {
            "criticality": "tier-1",
            "enforcement": "strict",
            "review_cycle_days": 30,
        },
    }
    r_target = client.post("/api/nodes", json=target_payload)
    assert r_target.status_code == 201
    target_data = r_target.json()
    assert target_data["ok"] is True
    target_node_id = target_data["node_id"]
    assert target_data["node"]["node_type"] == "security_policy"
    assert target_data["node"]["properties"]["criticality"] == "tier-1"

    # 2. Create custom node with completely custom scope and relationship to target
    custom_node_payload = {
        "title": "Autonomous Quant Controller",
        "content": "PID control system regulating market-making order depth and portfolio volatility.",
        "scope": "quant:control_systems",  # Brand new custom scope!
        "node_type": "control_daemon",
        "epistemic_class": "decision",
        "category": "project",
        "color": "#00ffa3",
        "size": 28,
        "confidence": 0.98,
        "status": "active",
        "properties": {
            "kp": 1.85,
            "ki": 0.22,
            "kd": 0.08,
            "engine": "PDE-Euler",
            "tags": ["quant", "control", "feedback"],
        },
        "relationships": [
            {
                "target": target_node_id,
                "predicate": "governed_by",
                "confidence": 0.99,
                "bidirectional": True,
            }
        ],
    }
    r_custom = client.post("/api/nodes", json=custom_node_payload)
    assert r_custom.status_code == 201
    custom_data = r_custom.json()
    assert custom_data["ok"] is True
    node_id = custom_data["node_id"]
    assert custom_data["node"]["scope"] == "quant:control_systems"
    assert custom_data["node"]["node_type"] == "control_daemon"
    assert custom_data["node"]["properties"]["kp"] == 1.85
    assert len(custom_data["relations"]) == 2  # Bidirectional: forward + inverse

    # 3. Verify custom scope was auto-registered in /api/scopes
    r_scopes = client.get("/api/scopes")
    assert r_scopes.status_code == 200
    scopes = r_scopes.json()["scopes"]
    scope_ids = [s["scope_id"] for s in scopes]
    assert "quant:control_systems" in scope_ids

    # 4. Fetch node detail and inspect configurable properties & relations
    r_detail = client.get(f"/api/nodes/{node_id}")
    assert r_detail.status_code == 200
    detail_data = r_detail.json()
    assert detail_data["node"]["id"] == node_id
    assert detail_data["node"]["properties"]["engine"] == "PDE-Euler"
    assert len(detail_data["relations"]) >= 1

    # 5. Update configurable properties
    update_payload = {
        "title": "Autonomous Quant Controller v2",
        "properties": {
            "kp": 2.10,
            "ki": 0.25,
            "kd": 0.09,
            "status": "calibrated",
        },
    }
    r_update = client.put(f"/api/nodes/{node_id}", json=update_payload)
    assert r_update.status_code == 200
    assert r_update.json()["ok"] is True

    # 6. Query /api/relations
    r_rels = client.get(f"/api/relations?source={node_id}")
    assert r_rels.status_code == 200
    assert len(r_rels.json()["relations"]) >= 1

    # 7. Add dedicated relation via POST /api/relations
    rel_create_payload = {
        "source": target_node_id,
        "target": node_id,
        "predicate": "audits",
        "confidence": 1.0,
    }
    r_add_rel = client.post("/api/relations", json=rel_create_payload)
    assert r_add_rel.status_code == 201
    assert r_add_rel.json()["ok"] is True
    rel_id = r_add_rel.json()["relations"][0]["relation_id"]

    # 8. Delete relation via DELETE /api/relations/{rel_id}
    r_del_rel = client.delete(f"/api/relations/{rel_id}")
    assert r_del_rel.status_code == 200
    assert r_del_rel.json()["ok"] is True

    # 9. Verify node in /api/graph
    r_graph = client.get("/api/graph?scope=all")
    assert r_graph.status_code == 200
    graph_data = r_graph.json()
    nodes = graph_data["nodes"]
    # Check custom scope hub exists
    hub_ids = [n["id"] for n in nodes if n.get("type") == "scope_hub"]
    assert "hub_scope_quant_control_systems" in hub_ids

    # Check custom node exists in graph with its properties
    matching_nodes = [n for n in nodes if n["id"] == node_id]
    assert len(matching_nodes) == 1
    custom_graph_node = matching_nodes[0]
    assert custom_graph_node["scope"] == "quant:control_systems"
    assert custom_graph_node["node_type"] == "control_daemon"
    assert custom_graph_node["properties"]["kp"] == 2.10

    # 10. Test layout configuration API
    r_layout_get = client.get("/api/config/layout-params")
    assert r_layout_get.status_code == 200
    assert r_layout_get.json()["config"]["preventScopeOverlap"] is True
    assert r_layout_get.json()["config"]["preventTypeOverlap"] is True

    r_layout_post = client.post("/api/config/layout-params", json={
        "minNodePadding": 32.0,
        "scopeSeparation": 180.0,
        "typeSpread": 1.4,
    })
    assert r_layout_post.status_code == 200
    assert r_layout_post.json()["config"]["minNodePadding"] == 32.0

    # 11. Delete custom node and verify cleanup
    r_del_node = client.delete(f"/api/nodes/{node_id}")
    assert r_del_node.status_code == 200
    assert r_del_node.json()["ok"] is True

    r_verify_gone = client.get(f"/api/nodes/{node_id}")
    assert r_verify_gone.status_code == 404
