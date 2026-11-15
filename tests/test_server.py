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
