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
