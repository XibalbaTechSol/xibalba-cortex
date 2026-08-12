import os
import subprocess

import pytest


@pytest.mark.skipif(
    os.environ.get("XIBALBA_RUN_HERMES_MCP_SMOKE") != "1",
    reason="live Hermes profile smoke is opt-in",
)
def test_live_hermes_profile_discovers_xibalba_cortex_memory_mcp():
    listed = subprocess.run(
        ["hermes", "mcp", "list"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert listed.returncode == 0, listed.stderr
    assert "xibalba_cortex_memory" in listed.stdout
    assert "enabled" in listed.stdout

    tested = subprocess.run(
        ["hermes", "mcp", "test", "xibalba_cortex_memory"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert tested.returncode == 0, tested.stderr or tested.stdout
