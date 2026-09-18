from __future__ import annotations

from xibalba_cortex import provider_bridge
from xibalba_cortex import server
from xibalba_cortex.store import GraphStore
import pytest


@pytest.mark.parametrize("agent_id", [None, "other.agent", "../escape"])
def test_provider_bridge_rejects_untrusted_agent_identity(agent_id, monkeypatch):
    monkeypatch.setenv("XIBALBA_AGENT_ID", "did:integrity:test-agent")
    request = {"operation": "session_start", "session_id": "bridge-session"}
    if agent_id is not None:
        request["agent_id"] = agent_id
    with pytest.raises(PermissionError, match="bound agent"):
        provider_bridge.dispatch(request)


def test_provider_bridge_persists_registered_agent_scope_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("XIBALBA_AGENT_ID", "did:integrity:test-agent")
    store = GraphStore(tmp_path / "graph", identity_mode="full")
    server.set_store_for_testing(store)
    try:
        started = provider_bridge.dispatch({
            "operation": "session_start",
            "session_id": "bridge-session",
            "retention_tier": "verbatim",
            "agent_id": "did:integrity:test-agent",
        })
        first = provider_bridge.dispatch({
            "operation": "sync_turn",
            "session_id": "bridge-session",
            "prompt": "persistent marker",
            "response": "persistent response",
            "agent_id": "did:integrity:test-agent",
            "idempotency_key": "bridge-session:1",
        })
        retry = provider_bridge.dispatch({
            "operation": "sync_turn",
            "session_id": "bridge-session",
            "prompt": "persistent marker",
            "response": "persistent response",
            "agent_id": "did:integrity:test-agent",
            "idempotency_key": "bridge-session:1",
        })
        recalled = provider_bridge.dispatch({
            "operation": "recall",
            "query": "persistent marker",
            "agent_id": "did:integrity:test-agent",
            "limit": 5,
        })

        assert started["agent_id"] == "did:integrity:test-agent"
        assert first["session"]["agent_id"] == "did:integrity:test-agent"
        assert first["exchange"]["sequence_number"] == 0
        assert retry["exchange"]["sequence_number"] == 0
        assert retry["exchange"]["id"] == first["exchange"]["id"]
        assert len(store.session_exchanges("bridge-session")) == 1
        assert {row["source"]["agent_id"] for row in recalled["results"]} == {"did:integrity:test-agent"}
    finally:
        store.close()
        server.set_store_for_testing(None)  # type: ignore[arg-type]


def test_provider_bridge_rejects_non_full_effective_identity_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("XIBALBA_AGENT_ID", "did:integrity:test-agent")
    store = GraphStore(tmp_path / "pseudonymous", identity_mode="pseudonymous")
    server.set_store_for_testing(store)
    try:
        with pytest.raises(PermissionError, match="requires full identity"):
            provider_bridge.dispatch({
                "operation": "session_start", "session_id": "must-not-write",
                "agent_id": "did:integrity:test-agent",
            })
        assert store.list_sessions() == []
    finally:
        store.close()
        server.set_store_for_testing(None)  # type: ignore[arg-type]


def test_provider_bridge_rejects_identity_that_resolves_to_another_namespace(tmp_path, monkeypatch):
    monkeypatch.setenv("XIBALBA_AGENT_ID", "did:integrity:test-agent")
    store = GraphStore(tmp_path / "wrong-namespace", identity_mode="full")
    server.set_store_for_testing(store)
    monkeypatch.setattr(store, "storage_agent_id", lambda agent_id: "unexpected.agent")
    try:
        with pytest.raises(PermissionError, match="does not resolve"):
            provider_bridge.dispatch({
                "operation": "session_start", "session_id": "must-not-write",
                "agent_id": "did:integrity:test-agent",
            })
        assert store.list_sessions() == []
    finally:
        store.close()
        server.set_store_for_testing(None)  # type: ignore[arg-type]


def test_default_profile_recall_includes_verified_legacy_namespaces_without_rewriting_them(tmp_path, monkeypatch):
    did = "did:integrity:test-agent"
    monkeypatch.setenv("XIBALBA_AGENT_ID", did)
    monkeypatch.setenv("XIBALBA_AGENT_PROFILE", "default")

    full_store = GraphStore(tmp_path / "graph", identity_mode="full")
    full_store.store_memory(
        "Legacy full-identity memory marker for default Hermes.",
        source={"kind": "direct_user", "agent_id": "xibalba.agent", "metadata": {"profile": "default", "runtime": "hermes"}},
        status="confirmed",
    )
    full_store.store_memory(
        "Canonical DID memory marker for default Hermes.",
        source={"kind": "direct_user", "agent_id": did, "metadata": {"profile": "default", "runtime": "hermes"}},
        status="confirmed",
    )
    full_store.close()

    pseudonymous_store = GraphStore(tmp_path / "graph", identity_mode="pseudonymous")
    pseudonym = pseudonymous_store.storage_agent_id("xibalba.agent")
    pseudonymous_store.store_memory(
        "Legacy pseudonymous memory marker for default Hermes.",
        source={"kind": "direct_user", "agent_id": "xibalba.agent", "metadata": {"profile": "default", "runtime": "hermes"}},
        status="confirmed",
    )
    pseudonymous_store.close()

    store = GraphStore(tmp_path / "graph", identity_mode="full")
    server.set_store_for_testing(store)
    try:
        recalled = provider_bridge.dispatch({
            "operation": "recall",
            "query": "memory marker default Hermes",
            "agent_id": did,
            "profile": "default",
            "limit": 8,
        })
        rows = recalled["results"]
        assert {row["content"] for row in rows} == {
            "Legacy full-identity memory marker for default Hermes.",
            "Canonical DID memory marker for default Hermes.",
            "Legacy pseudonymous memory marker for default Hermes.",
        }
        source_ids = {row["source"]["agent_id"] for row in rows}
        assert source_ids == {did, "xibalba.agent", pseudonym}
    finally:
        store.close()
        server.set_store_for_testing(None)  # type: ignore[arg-type]


def test_provider_bridge_session_end_preserves_close_when_exchange_finalization_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("XIBALBA_AGENT_ID", "did:integrity:test-agent")
    store = GraphStore(tmp_path / "graph", identity_mode="full")
    server.set_store_for_testing(store)
    store.start_session("finalization-failure", agent_id="did:integrity:test-agent")
    from xibalba_cortex import exchange_builder

    def fail_finalization(*args, **kwargs):
        raise RuntimeError("exchange backend unavailable")

    monkeypatch.setattr(exchange_builder, "build_session_exchanges", fail_finalization)
    try:
        result = provider_bridge.dispatch({
            "operation": "session_end", "session_id": "finalization-failure",
            "agent_id": "did:integrity:test-agent", "source": {"runtime": "hermes"},
        })
        assert result["ended_at"] is not None
        assert result["finalization_error"].startswith("RuntimeError:")
        assert store.get_session("finalization-failure")["ended_at"] is not None
    finally:
        store.close()
        server.set_store_for_testing(None)  # type: ignore[arg-type]


def test_full_identity_memory_survives_restart_and_profile_stores_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XIBALBA_AGENT_ID", "did:integrity:test-agent")
    default = GraphStore(tmp_path / "default", identity_mode="full")
    server.set_store_for_testing(default)
    try:
        provider_bridge.dispatch({
            "operation": "session_start", "session_id": "restart-session",
            "agent_id": "did:integrity:test-agent",
        })
        provider_bridge.dispatch({
            "operation": "sync_turn", "session_id": "restart-session",
            "prompt": "restart marker", "response": "durable result",
            "agent_id": "did:integrity:test-agent", "idempotency_key": "restart:1",
        })
    finally:
        default.close()

    reopened = GraphStore(tmp_path / "default", identity_mode="full")
    quant = GraphStore(tmp_path / "quant", identity_mode="full")
    try:
        server.set_store_for_testing(reopened)
        recovered = provider_bridge.dispatch({
            "operation": "recall", "query": "restart marker",
            "agent_id": "did:integrity:test-agent", "limit": 5,
        })
        assert recovered["results"]
        assert {row["source"]["agent_id"] for row in recovered["results"]} == {"did:integrity:test-agent"}
        server.set_store_for_testing(quant)
        isolated = provider_bridge.dispatch({
            "operation": "recall", "query": "restart marker",
            "agent_id": "did:integrity:test-agent", "limit": 5,
        })
        assert isolated["results"] == []
        assert quant.list_sessions() == []
    finally:
        reopened.close()
        quant.close()
        server.set_store_for_testing(None)  # type: ignore[arg-type]
