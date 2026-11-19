import pytest
from starlette.testclient import TestClient
from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig
from super_cortex.memory import SuperCortex
from super_cortex.causal import discover_graph_causal_chains, trace_causal_chain


@pytest.fixture
def app_client(tmp_path):
    cfg = SuperCortexConfig(db_path=tmp_path / "provenance.db")
    app = create_app(config=cfg)
    sc = SuperCortex(config=cfg)
    return TestClient(app), sc


def test_discover_graph_causal_chains(app_client):
    client, sc = app_client
    # Record an exchange with thought
    sc.record_exchange(
        session_id="sess_test_causal_1",
        prompt_text="Investigate boundary integrity",
        response_text="Boundary integrity verified.",
        thinking_text="Checking BCC middleware and cryptographic signatures.",
    )
    chains = discover_graph_causal_chains(sc, max_chains=5)
    assert chains["status"] == "ok"
    assert chains["total_chains"] >= 1
    c0 = chains["chains"][0]
    assert "chain_id" in c0
    assert "metrics" in c0


def test_api_causal_chains_and_trace(app_client):
    client, sc = app_client
    # Test GET /api/causal/chains
    resp = client.get("/api/causal/chains?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"

    # Test POST /api/causal/trace
    trace_resp = client.post("/api/causal/trace", json={"mode": "root_cause", "target_id": "hub_shared"})
    assert trace_resp.status_code == 200
    tdata = trace_resp.json()
    assert tdata["status"] == "ok"
    assert tdata["root_cause_id"] == "hub_shared"


def test_api_record_thought(app_client):
    client, sc = app_client
    resp = client.post("/api/thoughts", json={
        "thought_text": "Real-time thought recorded via API endpoint.",
        "step_phase": "deliberation",
        "agent_id": "agy",
        "scope": "agent:agy",
        "session_id": "sess_test_thought_api",
        "prompt_context": "Run automated test"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "recorded"
    assert "turn_hash" in data
    assert data["graph_node_id"].startswith("thought_")
