"""Real end-to-end test of the network-reachable ingestion path: a real uvicorn server
serving the real MCP streamable-HTTP app, wrapped in the real BearerTokenAuth middleware,
hit with real HTTP requests -- matching this repo's established real-server (not mocked)
testing convention (test_local_api.py, test_hermes_bridge.py).
"""
import itertools
import json
import threading
import time
import urllib.error
import urllib.request

import pytest
import uvicorn

from xibalba_cortex import server as server_module
from xibalba_cortex.auth_middleware import BearerTokenAuth
from xibalba_cortex.ingest_tokens import issue_token
from xibalba_cortex.store import GraphStore

# Separate range from test_local_api.py's 18420+ and test_otlp_receiver.py's own range, so a
# leftover bound socket from one test module can never collide with another's.
_next_test_port = itertools.count(19420)


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    graph_store = GraphStore(tmp_path / "graph")
    server_module.set_store_for_testing(graph_store)

    token = issue_token(tmp_path / "tokens", "test-harness", scopes=("memory:read", "memory:write"))

    port = next(_next_test_port)
    app = server_module.server.streamable_http_app(streamable_http_path="/mcp", host="127.0.0.1")
    authed_app = BearerTokenAuth(app, home=tmp_path / "tokens")
    config = uvicorn.Config(authed_app, host="127.0.0.1", port=port, log_level="warning")
    uv_server = uvicorn.Server(config)

    thread = threading.Thread(target=uv_server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not uv_server.started and time.monotonic() < deadline:
        time.sleep(0.05)

    yield port, token

    uv_server.should_exit = True
    thread.join(timeout=5)
    graph_store.close()
    server_module.set_store_for_testing(None)  # type: ignore[arg-type]


def _post(port, path, payload, *, token=None):
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.getheader("mcp-session-id"), response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, None, exc.read().decode()


def _init_payload():
    return {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2026-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    }


def test_initialize_without_a_token_is_rejected(running_server):
    port, _token = running_server
    status, _sid, _body = _post(port, "/mcp", _init_payload(), token=None)
    assert status == 401


def test_initialize_with_an_invalid_token_is_rejected(running_server):
    port, _token = running_server
    status, _sid, _body = _post(port, "/mcp", _init_payload(), token="not-a-real-token")
    assert status == 401


def test_initialize_with_a_valid_token_succeeds(running_server):
    port, token = running_server
    status, session_id, body = _post(port, "/mcp", _init_payload(), token=token)
    assert status == 200
    assert session_id is not None
    assert '"name":"xibalba-cortex"' in body


def test_ingest_agent_turn_tool_call_lands_real_data_over_the_wire(running_server):
    port, token = running_server
    status, session_id, _body = _post(port, "/mcp", _init_payload(), token=token)
    assert status == 200

    notify = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    body = json.dumps(notify).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
            "Mcp-Session-Id": session_id,
        },
    )
    urllib.request.urlopen(request, timeout=5).close()

    call_payload = {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {
            "name": "memory_ingest_agent_turn",
            "arguments": {
                "external_session_id": "wire-test-session",
                "runtime": "perplexity-computer",
                "prompt": "What is 2+2?",
                "response": "4",
                "tool_calls": [{"name": "calculator", "attributes": {"expr": "2+2"}}],
            },
        },
    }
    body = json.dumps(call_payload).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
            "Mcp-Session-Id": session_id,
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200
        response_body = response.read().decode()
    assert '"isError":false' in response_body

    # Verify against the real store directly, not just the wire response.
    store = server_module.get_store()
    exchange = store.session_exchanges("wire-test-session")[0]
    assert exchange["prompt_memories"][0]["content"] == "What is 2+2?"
    assert exchange["response_memories"][0]["content"] == "4"
    assert exchange["tool_calls"][0]["name"] == "tool_call.calculator"
