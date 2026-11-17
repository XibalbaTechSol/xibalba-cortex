from __future__ import annotations

import json
from pathlib import Path
import pytest

from super_cortex.config import SuperCortexConfig
from super_cortex.server import create_server


@pytest.fixture
def test_server(tmp_path: Path):
    db_file = tmp_path / "server_test.db"
    config = SuperCortexConfig(
        db_path=db_file,
        default_namespace="test-server",
    )
    return create_server(config)


def test_server_initialization(test_server):
    assert test_server.name == "super-cortex"


@pytest.mark.asyncio
async def test_server_health_tool(test_server):
    # In mcp 2.x, call_tool executes the registered tool function
    result = await test_server.call_tool("super_cortex_health", {})
    assert result is not None
    # Result content contains json text
    text_content = result.content[0].text
    data = json.loads(text_content)
    assert data["status"] == "healthy"
    assert data["chain_valid"] is True


@pytest.mark.asyncio
async def test_server_remember_tool(test_server):
    result = await test_server.call_tool(
        "memory_remember",
        {"text": "Xibalba Shield provides autonomous boundary validation."},
    )
    text_content = result.content[0].text
    data = json.loads(text_content)
    assert "memory_id" in data
    assert "event_hash" in data


@pytest.mark.asyncio
async def test_server_scope_and_agent_tools(test_server):
    # Test listing scopes
    scopes_res = await test_server.call_tool("memory_scopes_list", {})
    scopes_data = json.loads(scopes_res.content[0].text)
    assert len(scopes_data) >= 5
    assert any(s["scope_id"] == "shared" for s in scopes_data)

    # Test creating custom scope
    create_res = await test_server.call_tool(
        "memory_scope_create",
        {"scope_id": "agent:atlas", "name": "Atlas Agent Scope", "scope_type": "single_agent", "agent_id": "atlas"}
    )
    create_data = json.loads(create_res.content[0].text)
    assert create_data["scope_id"] == "agent:atlas"

    # Test listing agents
    agents_res = await test_server.call_tool("memory_agents_list", {})
    agents_data = json.loads(agents_res.content[0].text)
    assert len(agents_data) >= 4
    assert any(a["agent_id"] == "xibalba" for a in agents_data)

    # Test registering a new agent
    reg_res = await test_server.call_tool(
        "memory_agent_register",
        {"agent_id": "atlas", "name": "Atlas Execution Agent", "default_scope_id": "agent:atlas", "client_type": "custom"}
    )
    reg_data = json.loads(reg_res.content[0].text)
    assert reg_data["agent_id"] == "atlas"

    # Test remembering in single-agent scope
    mem_res = await test_server.call_tool(
        "memory_remember",
        {
            "text": "Atlas agent completed subagent task with zero errors.",
            "scope": "agent:atlas",
            "agent_id": "atlas"
        }
    )
    mem_data = json.loads(mem_res.content[0].text)
    assert mem_data["scope"] == "agent:atlas"
    assert mem_data["agent_id"] == "atlas"
    assert "para" in mem_data
    assert "triples" in mem_data


@pytest.mark.asyncio
async def test_server_record_thought_and_exchange(test_server):
    # Test recording reasoning step via memory_record_thought
    thought_res = await test_server.call_tool(
        "memory_record_thought",
        {
            "session_id": "sess_test_cot_stream",
            "thought_text": "Evaluating security policy: command complies with boundary constraints.",
            "step_phase": "pre_execution",
            "prompt_context": "Run unit test suite"
        }
    )
    thought_data = json.loads(thought_res.content[0].text)
    assert thought_data["status"] == "recorded"
    assert thought_data["session_id"] == "sess_test_cot_stream"
    assert "turn_hash" in thought_data
    assert thought_data.get("graph_dispatched") is True
    assert "graph_node_id" in thought_data

    # Test recording full exchange with thinking_text
    exch_res = await test_server.call_tool(
        "memory_record_model_exchange",
        {
            "session_id": "sess_test_cot_stream",
            "prompt_text": "Verify git status",
            "response_text": "Working tree is clean.",
            "thinking_text": "Inspecting branch tracking, checking uncommitted worktrees.",
            "tool_calls": [{"name": "run_command", "args": {"CommandLine": "git status"}}],
            "agent_id": "claude",
        }
    )
    exch_data = json.loads(exch_res.content[0].text)
    assert exch_data["session_id"] == "sess_test_cot_stream"
    assert "session_merkle_root" in exch_data
    assert "graph_thought_id" in exch_data

    # Test session rebuild via MCP
    rebuild_res = await test_server.call_tool(
        "memory_session_rebuild",
        {"session_id": "sess_test_cot_stream", "format": "json"}
    )
    rebuild_data = json.loads(rebuild_res.content[0].text)
    assert rebuild_data["found"] is True
    assert rebuild_data["counts"]["agent_thoughts"] >= 2
