"""
Tests for Atlas Autonomous Graph AI Agent, Tool Action Extraction, and Git Tree Manifold Ingestion.
"""

import json
import pytest
from starlette.testclient import TestClient

from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig
from super_cortex.connectors import SuperCortexConnectors
from super_cortex.graph_agent import GraphAIAgent
from super_cortex.memory import SuperCortex


@pytest.fixture
def test_cortex(tmp_path):
    db_file = tmp_path / "test_agent_prov.db"
    cfg = SuperCortexConfig(db_path=str(db_file))
    cortex = SuperCortex(config=cfg)

    # Register scopes & agents
    cortex.create_scope("shared", "Shared Memory Fabric", "shared")
    cortex.create_scope("agent:agy", "AGY Scope", "single_agent")
    cortex.create_scope("agent:claude", "Claude Scope", "single_agent")
    cortex.register_agent("agy", "Antigravity", "antigravity", "agent:agy")
    cortex.register_agent("claude", "Claude Code", "claude_code", "agent:claude")

    # Insert test memories
    cortex.store.add_entity("Xibalba Shield")
    cortex.store.add_entity("Integrity Core")
    cortex.store.add_relation("Xibalba Shield", "integrates_with", "Integrity Core", confidence=0.98)

    # Insert test exchanges with thinking and tool calls
    cortex.record_exchange(
        session_id="sess_test_alpha",
        prompt_text="Audit system boundary policies",
        response_text="Audited all policies successfully.",
        thinking_text="Verifying boundary integrity. Step 1: inspect permissions. Step 2: run bash verification.",
        tool_calls=[{"name": "eval_boundary_policy", "args": {"strict": True}}, {"name": "run_command", "args": {"cmd": "ls"}}],
        actor="did:integrity:agy-test",
    )
    cortex.record_exchange(
        session_id="sess_test_alpha",
        prompt_text="Execute secondary verification",
        response_text="Secondary check passed.",
        thinking_text="Proceeding with second turn verification in same session.",
        tool_calls=[{"name": "verify_signature", "args": {"algorithm": "Ed25519"}}],
        actor="did:integrity:agy-test",
    )

    return cortex


def test_graph_agent_manifold_and_patterns(test_cortex):
    agent = GraphAIAgent(test_cortex.store)
    summary = agent.get_manifold_summary()
    assert summary["total_exchanges"] == 2
    assert summary["total_thoughts"] == 2
    assert summary["total_tool_calls"] == 2

    patterns = agent.discover_patterns()
    assert len(patterns) >= 1
    # Check that tool action pattern is recognized
    action_pat = next((p for p in patterns if p["category"] == "action"), None)
    assert action_pat is not None
    assert "eval_boundary_policy" in action_pat["distribution"]


def test_graph_agent_chat_and_operation_dispatch(test_cortex):
    agent = GraphAIAgent(test_cortex.store)

    # Test edge style and leaf pruning intent extraction
    res = agent.chat("Please declutter the graph and switch edges to cylinders")
    assert res["agent"] == "Atlas"
    assert "ATLAS KNOWLEDGE SYNTHESIS" in res["response"]

    op_names = [op["op"] for op in res["operations"]]
    assert "prune_leaves" in op_names
    assert "set_edge_style" in op_names
    assert any(op["op"] == "set_edge_style" and op["style"] == "cylinders" for op in res["operations"])

    # Test epistemic filter intent extraction
    res_actions = agent.chat("Show all tool actions and executions")
    assert any(op["op"] == "filter_epistemic" and op["class"] == "action" for op in res_actions["operations"])


def test_api_graph_renders_action_and_causal_nodes(test_cortex):
    app = create_app(config=test_cortex.config)
    client = TestClient(app)

    res = client.get("/api/graph")
    assert res.status_code == 200
    data = res.json()

    nodes = data.get("nodes", [])
    links = data.get("links", [])

    # Verify Action / Tool Call Nodes exist
    action_nodes = [n for n in nodes if n.get("type") in ("action", "tool_call") or n.get("node_type") == "tool_call"]
    assert len(action_nodes) == 3  # 2 in first exchange, 1 in second exchange
    assert any(n["title"] == "Action: eval_boundary_policy" for n in action_nodes)
    assert any(n["title"] == "Action: verify_signature" for n in action_nodes)

    # Verify executes links connect Thought -> Action
    executes_links = [l for l in links if l.get("type") == "executes"]
    assert len(executes_links) == 3

    # Verify causal link connects consecutive thoughts in sess_test_alpha
    causal_links = [l for l in links if l.get("type") == "causal"]
    assert len(causal_links) >= 1


def test_api_graph_agent_routes(test_cortex):
    app = create_app(config=test_cortex.config)
    client = TestClient(app)

    # 1. Pattern discovery endpoint
    res_pat = client.get("/api/graph/agent/patterns")
    assert res_pat.status_code == 200
    pdata = res_pat.json()
    assert "patterns" in pdata
    assert "manifold_summary" in pdata

    # 2. Interactive Agent Chat endpoint
    res_chat = client.post(
        "/api/graph/agent/chat",
        json={"message": "Analyze tool executions and switch to cylinders", "scope": "all"}
    )
    assert res_chat.status_code == 200
    cdata = res_chat.json()
    assert cdata["agent"] == "Atlas"
    assert len(cdata["operations"]) >= 1


@pytest.mark.asyncio
async def test_connectors_git_tree_manifold_ingestion(test_cortex):
    connectors = SuperCortexConnectors(test_cortex)
    res = await connectors.ingest_git_tree_manifold()
    assert res["repo_name"] == "XibalbaTechSol/super-cortex"
    assert "branches" in res
    assert res["commits_ingested"] >= 0
