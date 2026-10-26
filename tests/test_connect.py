from pathlib import Path
from xibalba_cortex.connect import connect

def test_connect_provisions_and_reuses_did(tmp_path: Path):
    first = connect(profile=tmp_path / "profile", agent="codex", harness="codex", mcp_url="http://127.0.0.1:8421/mcp", api_url="http://127.0.0.1:8421")
    second = connect(profile=tmp_path / "profile", agent="codex", harness="codex", mcp_url="http://127.0.0.1:8421/mcp", api_url="http://127.0.0.1:8421")
    assert first["did"] == second["did"]
    did_file = tmp_path / "profile" / "agent.did.json"
    assert did_file.is_file()
    assert not list((tmp_path / "profile").rglob("private_key.pem"))
    assert first["mcp_remote"]["headers"]["Authorization"] == "Bearer " + chr(36) + "{CORTEX_API_KEY}"
    assert first["mcp_stdio"]["mcpServers"]["cortex"]["env"]["XIBALBA_AGENT_ID"] == first["did"]

def test_connect_rejects_bad_agent(tmp_path: Path):
    try:
        connect(profile=tmp_path, agent="bad/name", harness="test", mcp_url="http://localhost/mcp", api_url="http://localhost")
    except ValueError as exc:
        assert "agent" in str(exc)
    else:
        raise AssertionError("invalid agent name was accepted")
