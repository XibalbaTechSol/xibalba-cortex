from __future__ import annotations

import pytest

from integrity_sdk.did import load_or_create_did, write_did_file

from xibalba_cortex.identity import DidFileError, resolve_agent_id, require_agent_id


def _write_identity(root):
    root.mkdir()
    did, keypair, _ = load_or_create_did("cortex-agent", did_home_root=root / "keys")
    write_did_file(
        root,
        did=did,
        public_key=keypair.public_bytes(),
        agent_id="cortex-agent",
        harness="cortex",
        profile="default",
    )
    return did


def test_profile_did_is_primary_identity_source(tmp_path, monkeypatch):
    did = _write_identity(tmp_path / "profile")
    monkeypatch.setenv("XIBALBA_CORTEX_HOME", str(tmp_path / "profile"))
    monkeypatch.delenv("XIBALBA_AGENT_ID", raising=False)

    assert resolve_agent_id() == did
    assert require_agent_id() == did


def test_explicit_agent_override_is_compatible(tmp_path, monkeypatch):
    root = tmp_path / "profile"
    _write_identity(root)
    monkeypatch.setenv("XIBALBA_CORTEX_HOME", str(root))
    monkeypatch.setenv("XIBALBA_AGENT_ID", "managed-agent-override")

    assert resolve_agent_id() == "managed-agent-override"


def test_missing_identity_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("XIBALBA_CORTEX_HOME", str(tmp_path / "empty-profile"))
    monkeypatch.delenv("XIBALBA_AGENT_ID", raising=False)

    assert resolve_agent_id() is None
    with pytest.raises(RuntimeError, match="no Cortex agent identity"):
        require_agent_id()


def test_malformed_profile_did_fails_closed(tmp_path, monkeypatch):
    root = tmp_path / "profile"
    root.mkdir()
    (root / "agent.did.json").write_text("{}")
    monkeypatch.setenv("XIBALBA_CORTEX_HOME", str(root))
    monkeypatch.delenv("XIBALBA_AGENT_ID", raising=False)

    with pytest.raises(DidFileError):
        resolve_agent_id()
