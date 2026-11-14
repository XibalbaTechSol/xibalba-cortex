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
    assert "XIBALBA_AGENT_ID" not in first["mcp_stdio"]["mcpServers"]["cortex"]["env"]

def test_connect_rejects_bad_agent(tmp_path: Path):
    try:
        connect(profile=tmp_path, agent="bad/name", harness="test", mcp_url="http://localhost/mcp", api_url="http://localhost")
    except ValueError as exc:
        assert "agent" in str(exc)
    else:
        raise AssertionError("invalid agent name was accepted")


# --- off-chain Oracle registration on first run ---
import sys
import types

import pytest

_KW = dict(harness="codex", mcp_url="http://127.0.0.1:8421/mcp", api_url="http://127.0.0.1:8421")


def _fake_sdk(monkeypatch, fn):
    mod = types.ModuleType("integrity_sdk.registration_offchain")
    mod.register_offchain = fn
    monkeypatch.setitem(sys.modules, "integrity_sdk.registration_offchain", mod)


def test_first_run_registers_offchain(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ORACLE_URL", raising=False)
    calls = []

    def fake(oracle_url, did, keypair, **kw):
        calls.append((oracle_url, did))
        return types.SimpleNamespace(agent_id="a1", verification_tier=1, outcome="created", handle=None)

    _fake_sdk(monkeypatch, fake)
    result = connect(profile=tmp_path / "p", agent="codex", oracle_url="https://oracle.test", **_KW)
    assert result["oracle_registration"] == {"status": "registered", "tier": 1, "outcome": "created"}
    assert calls == [("https://oracle.test", result["did"])]


def test_first_run_survives_unreachable_oracle(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ORACLE_URL", raising=False)

    class Err(RuntimeError):
        status = None
        detail = "connection refused"

    def boom(*a, **kw):
        raise Err("unreachable")

    _fake_sdk(monkeypatch, boom)
    result = connect(profile=tmp_path / "p", agent="codex", oracle_url="https://oracle.test", **_KW)
    assert result["oracle_registration"] == {"status": "failed", "http_status": None, "detail": "connection refused"}
    assert (tmp_path / "p" / "agent.did.json").is_file()


def test_no_oracle_url_skips(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ORACLE_URL", raising=False)

    def must_not_call(*a, **kw):
        raise AssertionError("register_offchain called without an oracle_url")

    _fake_sdk(monkeypatch, must_not_call)
    result = connect(profile=tmp_path / "p", agent="codex", **_KW)
    assert result["oracle_registration"] == {"status": "skipped"}


def test_old_sdk_without_module_reports_failed(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(sys.modules, "integrity_sdk.registration_offchain", None)  # forces ImportError
    result = connect(profile=tmp_path / "p", agent="codex", oracle_url="https://oracle.test", **_KW)
    assert result["oracle_registration"]["status"] == "failed"
    assert "upgrade" in result["oracle_registration"]["detail"]
