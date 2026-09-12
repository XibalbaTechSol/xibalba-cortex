"""The stdio transport must bind a principal, or every agent-scope check silently passes.

Before this, `current_principal()` returned None on stdio, so `_assert_memory_scope` and friends
returned unchecked on the transport local harnesses actually use.
"""
from __future__ import annotations

import pytest

from xibalba_cortex.auth_middleware import current_principal
from xibalba_cortex.server import _install_stdio_principal


AGENT = "did:integrity:2ea17967f7a65589d570ca7e800844701fb36e6aa7374243e8766de8651f6bc4"


def test_stdio_binds_the_launched_agent_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("XIBALBA_AGENT_ID", AGENT)
    monkeypatch.setenv("XIBALBA_CORTEX_HOME", str(tmp_path))
    _install_stdio_principal()
    principal = current_principal()
    assert principal is not None, "stdio must not leave the principal unset"
    assert principal["agent_id"] == AGENT
    assert "memory:read" in principal["scopes"]


def test_stdio_fails_closed_without_an_agent_identity(monkeypatch):
    monkeypatch.delenv("XIBALBA_AGENT_ID", raising=False)
    monkeypatch.delenv("XIBALBA_CORTEX_ALLOW_UNSCOPED_STDIO", raising=False)
    with pytest.raises(SystemExit):
        _install_stdio_principal()


def test_unscoped_stdio_requires_an_explicit_opt_in(monkeypatch):
    """The historical unscoped behavior stays reachable, but only deliberately."""
    monkeypatch.delenv("XIBALBA_AGENT_ID", raising=False)
    monkeypatch.setenv("XIBALBA_CORTEX_ALLOW_UNSCOPED_STDIO", "1")
    _install_stdio_principal()
