"""The stdio transport must bind a principal, or every agent-scope check silently passes.

Before this, `current_principal()` returned None on stdio, so `_assert_memory_scope` and friends
returned unchecked on the transport local harnesses actually use.
"""
from __future__ import annotations

import pytest

from xibalba_cortex.auth_middleware import _current_principal, current_principal
from xibalba_cortex.server import _install_stdio_principal


AGENT = "did:integrity:2ea17967f7a65589d570ca7e800844701fb36e6aa7374243e8766de8651f6bc4"


@pytest.fixture(autouse=True)
def _reset_principal():
    token = _current_principal.set(None)
    yield
    _current_principal.reset(token)


def test_stdio_binds_the_launched_agent_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("XIBALBA_AGENT_ID", AGENT)
    monkeypatch.setenv("XIBALBA_CORTEX_HOME", str(tmp_path))
    _install_stdio_principal()
    principal = current_principal()
    assert principal is not None, "stdio must not leave the principal unset"
    assert principal["agent_id"] == AGENT
    assert "memory:read" in principal["scopes"]


@pytest.fixture
def no_identity(monkeypatch, tmp_path):
    """An identity-free profile home.

    Clearing `XIBALBA_AGENT_ID` is not enough to make a machine identity-free:
    `resolve_agent_id` falls back to the profile's `agent.did.json`, so on any box with a
    provisioned DID these tests took the identity branch instead of the one they name. The
    empty `tmp_path` home makes the outcome the same everywhere, CI included.
    """
    monkeypatch.delenv("XIBALBA_AGENT_ID", raising=False)
    monkeypatch.setenv("XIBALBA_CORTEX_HOME", str(tmp_path))
    return tmp_path


def test_stdio_fails_closed_without_an_agent_identity(monkeypatch, no_identity):
    monkeypatch.delenv("XIBALBA_CORTEX_ALLOW_UNSCOPED_STDIO", raising=False)
    with pytest.raises(SystemExit):
        _install_stdio_principal()


def test_unscoped_stdio_requires_an_explicit_opt_in(monkeypatch, no_identity):
    """The historical unscoped behavior stays reachable, but only deliberately."""
    monkeypatch.setenv("XIBALBA_CORTEX_ALLOW_UNSCOPED_STDIO", "1")
    _install_stdio_principal()
    # Unscoped means exactly that: the escape hatch binds no principal. Without this the test
    # passed on any box with a provisioned DID by taking the identity branch instead.
    assert current_principal() is None
