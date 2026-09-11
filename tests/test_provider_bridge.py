from __future__ import annotations

from xibalba_cortex import provider_bridge
from xibalba_cortex import server
from xibalba_cortex.store import GraphStore
import pytest


@pytest.mark.parametrize("agent_id", [None, "other.agent", "../escape"])
def test_provider_bridge_rejects_untrusted_agent_identity(agent_id):
    request = {"operation": "session_start", "session_id": "bridge-session"}
    if agent_id is not None:
        request["agent_id"] = agent_id
    with pytest.raises(PermissionError, match="registered xibalba.agent"):
        provider_bridge.dispatch(request)


def test_provider_bridge_persists_registered_agent_scope_and_is_idempotent(tmp_path):
    store = GraphStore(tmp_path / "graph", identity_mode="full")
    server.set_store_for_testing(store)
    try:
        started = provider_bridge.dispatch({
            "operation": "session_start",
            "session_id": "bridge-session",
            "retention_tier": "verbatim",
            "agent_id": "xibalba.agent",
        })
        first = provider_bridge.dispatch({
            "operation": "sync_turn",
            "session_id": "bridge-session",
            "prompt": "persistent marker",
            "response": "persistent response",
            "agent_id": "xibalba.agent",
            "idempotency_key": "bridge-session:1",
        })
        retry = provider_bridge.dispatch({
            "operation": "sync_turn",
            "session_id": "bridge-session",
            "prompt": "persistent marker",
            "response": "persistent response",
            "agent_id": "xibalba.agent",
            "idempotency_key": "bridge-session:1",
        })
        recalled = provider_bridge.dispatch({
            "operation": "recall",
            "query": "persistent marker",
            "agent_id": "xibalba.agent",
            "limit": 5,
        })

        assert started["agent_id"] == "xibalba.agent"
        assert first["session"]["agent_id"] == "xibalba.agent"
        assert first["exchange"]["sequence_number"] == 0
        assert retry["exchange"]["sequence_number"] == 0
        assert {row["source"]["agent_id"] for row in recalled["results"]} == {"xibalba.agent"}
    finally:
        store.close()
        server.set_store_for_testing(None)  # type: ignore[arg-type]
