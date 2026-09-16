from __future__ import annotations

import socket
import threading
import time

from integrity_sdk.integrations.cortex import CortexTransport

from xibalba_cortex.ingest_tokens import issue_token
from xibalba_cortex.local_api import serve
from xibalba_cortex.store import GraphStore


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


def test_sdk_cortex_transport_reaches_authenticated_local_api(tmp_path):
    store = GraphStore(tmp_path / "graph")
    try:
        token = issue_token(
            store.home,
            "sdk-integration-test",
            roles=("admin",),
            scopes=("memory:read", "memory:write"),
        )
        port = _free_port()
        thread = threading.Thread(
            target=serve,
            kwargs={"store": store, "port": port},
            daemon=True,
        )
        thread.start()
        time.sleep(0.3)

        session_id = "sdk-cortex-transport-session"
        event = {
            "event_id": "sdk-event-1",
            "event_type": "session_started",
            "agent_id": "payload-agent-does-not-authorize",
            "session_id": session_id,
            "harness": "sdk-integration-test",
        }
        result = CortexTransport(
            f"http://localhost:{port}",
            token,
            timeout=5,
        ).export([event])

        assert result["recorded"] == 1
        events = store.session_otel_events(session_id)
        assert len(events) == 1
        assert events[0]["session_id"] == session_id
        assert events[0]["name"] == "integrity.sdk.event"
    finally:
        store.close()


def test_sdk_cortex_transport_requires_a_session_id():
    transport = CortexTransport("http://localhost:1", "test-token")
    try:
        transport.export([{"event_id": "no-session"}])
    except ValueError as exc:
        assert "session_id" in str(exc)
    else:
        raise AssertionError("Cortex export accepted an event without session_id")
