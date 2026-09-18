import json
import sqlite3
import socket
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest
import requests

from xibalba_cortex.ingest_tokens import issue_token
from xibalba_cortex.local_api import serve
from xibalba_cortex.local_api import _assert_session_access
from http.cookies import SimpleCookie

from xibalba_cortex.local_api import SESSION_COOKIE_NAME
from xibalba_cortex.store import EMBEDDING_DIM, GraphStore

_CURRENT_TOKEN: str | None = None


def _unit_vector(hot_index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[hot_index] = 1.0
    return vector


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_CURRENT_TOKEN}"} if _CURRENT_TOKEN else {}


def _get(port: int, path: str) -> tuple[int, object]:
    request = urllib.request.Request(f"http://localhost:{port}{path}", method="GET", headers=_auth_headers())
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post_capture_cookie(port: int, path: str, payload: dict[str, object]) -> tuple[int, object, str]:
    """POST and also return the session token the server set as an HttpOnly cookie.

    Browsers no longer receive the token in the response body, so a test that needs to act as a
    signed-in operator has to read it the same way a browser would.
    """
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"http://localhost:{port}{path}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", **_auth_headers()},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.headers.get("Set-Cookie", "")
            status, parsed = response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read()), ""
    morsel = SimpleCookie(raw).get(SESSION_COOKIE_NAME)
    return status, parsed, morsel.value if morsel else ""


def _post(port: int, path: str, payload: dict[str, object]) -> tuple[int, object]:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"http://localhost:{port}{path}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", **_auth_headers()},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _free_test_port() -> int:
    """Ask the OS for a currently free loopback port.

    The API server intentionally runs in a daemon thread without a shutdown hook;
    fixed test-port ranges therefore collide across repeated pytest invocations.
    An OS-selected port keeps each fixture isolated without killing unrelated local
    processes.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


@pytest.fixture(autouse=True)
def _no_real_oracle_identity_lookups(monkeypatch):
    """`/api/agents` calls integrity_sdk.agent_identity.resolve_agent_identities (added
    2026-09-13 for the cross-product identity-display standard), which makes real HTTP calls
    to an oracle backend. This suite has no oracle running and must not depend on one --
    without this, a reachable-but-slow oracle on the test machine (or one that's simply not
    there, timing out rather than refusing fast) can make these tests flaky or hang. Stubbed
    to return "no identity info", matching this function's own documented fail-open contract,
    so every existing assertion about agent_id/device_name/etc. is unaffected -- this only
    controls the fields this test suite doesn't exercise (display_name/on_chain/handle/...).
    """
    monkeypatch.setattr("xibalba_cortex.local_api.resolve_agent_identities", lambda dids, oracle_url, **kw: {})

    def _unreachable(*args, **kwargs):
        raise requests.RequestException("no oracle in this test suite")

    monkeypatch.setattr("xibalba_cortex.local_api.requests.get", _unreachable)


@pytest.fixture
def running_store(tmp_path):
    global _CURRENT_TOKEN
    store = GraphStore(tmp_path / "graph")
    _CURRENT_TOKEN = issue_token(
        store.home,
        "test-harness",
        roles=("admin",),
        scopes=("memory:read", "memory:write", "memory:delete", "proposal:decide"),
    )
    port = _free_test_port()
    thread = threading.Thread(target=serve, kwargs={"store": store, "port": port}, daemon=True)
    thread.start()
    time.sleep(0.3)  # let the server bind
    yield store, port
    store.close()
    _CURRENT_TOKEN = None


def test_get_without_token_is_rejected(running_store):
    _, port = running_store
    request = urllib.request.Request(f"http://localhost:{port}/api/stats", method="GET")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)
    assert excinfo.value.code == 401


def test_post_without_token_is_rejected(running_store):
    _, port = running_store
    body = json.dumps({}).encode()
    request = urllib.request.Request(
        f"http://localhost:{port}/api/memory/propositions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)
    assert excinfo.value.code == 401


def test_read_only_token_cannot_write(running_store):
    store, port = running_store
    reader_token = issue_token(store.home, "reader-only", roles=("reader",), scopes=("memory:read",))
    body = json.dumps({}).encode()
    request = urllib.request.Request(
        f"http://localhost:{port}/api/memory/propositions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {reader_token}"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)
    assert excinfo.value.code == 403


def test_token_cannot_access_a_different_profile(running_store):
    store, port = running_store
    wrong_profile_token = issue_token(
        store.home,
        "other-profile-reader",
        profile_id="other-profile",
        roles=("reader",),
        scopes=("memory:read",),
    )
    request = urllib.request.Request(
        f"http://localhost:{port}/api/stats",
        method="GET",
        headers={"Authorization": f"Bearer {wrong_profile_token}"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(request, timeout=5)
    assert excinfo.value.code == 403
    assert "not authorized for this profile" in excinfo.value.read().decode()


def test_bearer_scheme_is_case_insensitive(running_store):
    _, port = running_store
    request = urllib.request.Request(
        f"http://localhost:{port}/api/stats",
        method="GET",
        headers={"Authorization": f"bearer {_CURRENT_TOKEN}"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200


def test_cors_preflight_allows_authorization_header(running_store):
    _, port = running_store
    request = urllib.request.Request(
        f"http://localhost:{port}/api/stats",
        method="OPTIONS",
        headers={
            "Origin": "http://localhost:5190",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 204
        allowed = response.headers["Access-Control-Allow-Headers"].lower()
        assert "authorization" in allowed


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/metrics"])
def test_liveness_routes_exempt_from_auth(running_store, path):
    _, port = running_store
    request = urllib.request.Request(f"http://localhost:{port}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200


def test_stats_reports_real_counts(running_store):
    store, port = running_store
    store.store_memory(
        "A memory for stats.",
        source={"kind": "direct_user", "locator": "hermes://session/stats"},
        status="confirmed",
    )
    status, body = _get(port, "/api/stats")
    assert status == 200
    assert body["memories"] == 1


def test_inference_settings_round_trip_through_profile_config(running_store):
    store, port = running_store
    status, initial = _get(port, "/api/settings/inference")
    assert status == 200
    assert initial["enabled"] is True

    updated = {
        **initial,
        "task_types": ["classify_para", "extract_entities"],
        "batch_size": 12,
        "interval_seconds": 1.25,
    }
    status, result = _post(port, "/api/settings/inference", updated)
    assert status == 200
    assert result["inference"]["batch_size"] == 12
    assert (store.home / "config.yaml").exists()

    status, effective = _get(port, "/api/settings/inference")
    assert status == 200
    assert effective["task_types"] == ["classify_para", "extract_entities"]


def test_inference_settings_reject_unknown_task_without_replacing_config(running_store):
    store, port = running_store
    status, body = _post(port, "/api/settings/inference", {"task_types": ["invent_facts"]})
    assert status == 400
    assert "unsupported inference task types" in body["error"]
    assert not (store.home / "config.yaml").exists()


def test_status_and_integrity_links_routes(running_store):
    store, port = running_store
    memory = store.store_memory(
        "Memory with unavailable Integrity content.",
        source={"kind": "direct_user", "locator": "hermes://session/integrity-link"},
        status="confirmed",
    )
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            """
            INSERT INTO integrity_links(memory_id, node_id, verification_state, expected_content_hash, verified_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (memory["id"], "node-1", "content_unavailable", memory["content_hash"]),
        )
        connection.commit()

    status, body = _get(port, "/api/status")
    assert status == 200
    assert body["schema_version"] == 15
    assert body["journal_mode"] == "wal"
    assert body["backup_ready"] is True

    status, body = _get(port, "/api/integrity-links")
    assert status == 200
    assert body["states"]["content_unavailable"] == 1
    assert body["sample"][0]["memory_id"] == memory["id"]


def test_operations_snapshot_exposes_control_plane_evidence(running_store):
    store, port = running_store
    store.store_memory("Operations evidence", source={"kind": "test"}, status="confirmed")
    status, body = _get(port, "/api/operations")
    assert status == 200
    assert body["schema_version"] == "xibalba.dashboard_operations.v1"
    assert body["profile_id"] == "default"
    assert body["health"]["status"]["memory_count"] == 1
    assert body["features"]["context_assembly"] is True
    assert "max_memories" in body["quotas"]
    assert body["connectors"]["webhook"]["state"] == "implemented"
    assert body["audit"]["memory_event_counts"]["create"] == 1


def test_search_returns_matching_memory(running_store):
    store, port = running_store
    store.store_memory(
        "Xibalba Shield local API test content.",
        source={"kind": "direct_user", "locator": "hermes://session/search"},
        status="confirmed",
    )
    status, body = _get(port, "/api/search?q=Shield")
    assert status == 200
    assert body[0]["content"] == "Xibalba Shield local API test content."


def test_operator_can_select_an_agent_partition_across_memory_views(running_store):
    store, port = running_store
    store.start_session("agent-a-session", agent_id="agent-a")
    store.start_session("agent-b-session", agent_id="agent-b")
    memory_a = store.store_memory(
        "Shared search term from agent A.",
        source={"kind": "direct_user", "session_id": "agent-a-session", "agent_id": "agent-a"},
        status="confirmed",
    )
    memory_b = store.store_memory(
        "Shared search term from agent B.",
        source={"kind": "direct_user", "session_id": "agent-b-session", "agent_id": "agent-b"},
        status="confirmed",
    )

    status, payload = _get(port, "/api/agents")
    assert status == 200
    agent_ids = {row["agent_id"] for row in payload["agents"]}
    source_agent_a = memory_a["source"]["agent_id"]
    source_agent_b = memory_b["source"]["agent_id"]
    assert agent_ids == {source_agent_a, source_agent_b}

    status, results = _get(port, f"/api/search?q=Shared&agent_id={source_agent_a}")
    assert status == 200
    assert [row["id"] for row in results] == [memory_a["id"]]

    status, sessions = _get(port, f"/api/sessions?agent_id={source_agent_a}")
    assert status == 200
    assert [row["external_session_id"] for row in sessions] == ["agent-a-session"]

    status, graph = _get(port, f"/api/graph?agent_id={source_agent_a}")
    assert status == 200
    graph_memory_ids = {node["id"] for node in graph["nodes"] if node["type"] == "memory"}
    assert graph_memory_ids == {f"memory:{memory_a['id']}"}


def test_agent_session_replay_requires_single_source_namespace(running_store):
    store, _port = running_store
    store.identity_mode = "full"
    store.start_session("legacy-owned-by-a")
    store.store_memory(
        "Agent A historical session evidence.",
        source={"kind": "test", "session_id": "legacy-owned-by-a", "agent_id": "did:agent:a"},
    )
    store.start_session("mixed-agent-session", agent_id="did:agent:a")
    store.store_memory(
        "Agent A source.",
        source={"kind": "test", "agent_id": "did:agent:a"},
    )
    store.store_memory(
        "Agent B source.",
        source={"kind": "test", "agent_id": "did:agent:b"},
    )
    with store._lock:
        store._connection.execute("UPDATE sources SET session_id = 'mixed-agent-session' WHERE id IN (SELECT source_id FROM memories WHERE content IN ('Agent A source.', 'Agent B source.'))")
    principal = {"agent_ids": ["did:agent:a"]}

    assert _assert_session_access(store, principal, "legacy-owned-by-a")["agent_id"] is None
    store.start_session("unattributed-session")
    store.store_memory(
        "Unattributed evidence.",
        source={"kind": "test", "session_id": "unattributed-session"},
    )
    with pytest.raises(PermissionError, match="unassigned, mixed"):
        _assert_session_access(store, principal, "unattributed-session")
    with pytest.raises(PermissionError, match="unassigned, mixed"):
        _assert_session_access(store, principal, "mixed-agent-session")


def test_registered_agent_set_can_switch_between_multiple_agents(running_store):
    global _CURRENT_TOKEN
    store, port = running_store
    store.identity_mode = "full"
    store.start_session("registered-agent-a", agent_id="did:integrity:agent-a")
    store.start_session("registered-agent-b", agent_id="did:integrity:agent-b")
    memory_a = store.store_memory(
        "Registered agent A private memory.",
        source={"kind": "test", "session_id": "registered-agent-a", "agent_id": "did:integrity:agent-a"},
        status="confirmed",
    )
    memory_b = store.store_memory(
        "Registered agent B private memory.",
        source={"kind": "test", "session_id": "registered-agent-b", "agent_id": "did:integrity:agent-b"},
        status="confirmed",
    )
    _CURRENT_TOKEN = issue_token(
        store.home,
        "registered-agent-user",
        roles=("reader",),
        scopes=("memory:read",),
        agent_ids=("did:integrity:agent-a", "did:integrity:agent-b"),
    )

    status, payload = _get(port, "/api/agents")
    assert status == 200
    assert {row["agent_id"] for row in payload["agents"]} == {"did:integrity:agent-a", "did:integrity:agent-b"}

    status, results = _get(port, "/api/search?q=private&agent_id=did%3Aintegrity%3Aagent-a")
    assert status == 200 and [row["id"] for row in results] == [memory_a["id"]]
    status, results = _get(port, "/api/search?q=private&agent_id=did%3Aintegrity%3Aagent-b")
    assert status == 200 and [row["id"] for row in results] == [memory_b["id"]]
    status, error = _get(port, "/api/search?q=private&agent_id=did%3Aintegrity%3Aagent-c")
    assert status == 403 and "not authorized" in error["error"]


def test_reader_identity_mode_does_not_hide_full_did_partitions(running_store):
    """Hermes may write full DIDs while the local API uses its pseudonymous default."""
    global _CURRENT_TOKEN
    store, port = running_store
    did = "did:integrity:hermes-agent"
    store.identity_mode = "full"
    memory = store.store_memory(
        "Memory written by the full identity Hermes MCP server.",
        source={"kind": "direct_user", "agent_id": did},
        status="confirmed",
    )
    # Reproduce the deployed mismatch: the API reader defaults to pseudonymous,
    # but existing source rows were written with the exact DID.
    store.identity_mode = "pseudonymous"
    _CURRENT_TOKEN = issue_token(
        store.home,
        "hermes-agent-reader",
        roles=("reader",),
        scopes=("memory:read",),
        agent_ids=(did,),
    )

    status, page = _get(port, f"/api/memories?agent_id={did}&status=confirmed")
    assert status == 200
    assert [row["id"] for row in page["memories"]] == [memory["id"]]

    status, results = _get(port, f"/api/search?q=full%20identity&agent_id={did}")
    assert status == 200
    assert [row["id"] for row in results] == [memory["id"]]


def test_operator_can_view_memories_from_a_readonly_profile_store(tmp_path):
    global _CURRENT_TOKEN
    root = GraphStore(tmp_path / "root")
    profile_writer = GraphStore(tmp_path / "quant", identity_mode="full")
    did = "did:integrity:quant-agent"
    memory = profile_writer.store_memory(
        "Quant profile memory remains in its own store.",
        source={"kind": "direct_user", "agent_id": did},
        status="confirmed",
    )
    profile_writer.close()
    profile_reader = GraphStore(tmp_path / "quant", identity_mode="full", readonly=True)
    _CURRENT_TOKEN = issue_token(
        root.home,
        "operator",
        roles=("admin",),
        scopes=("memory:read", "memory:write"),
    )
    port = _free_test_port()
    thread = threading.Thread(
        target=serve,
        kwargs={"store": root, "port": port, "agent_stores": (profile_reader,)},
        daemon=True,
    )
    thread.start()
    time.sleep(0.3)
    try:
        status, agents = _get(port, "/api/agents")
        assert status == 200
        assert did in {row["agent_id"] for row in agents["agents"]}
        workspace = next(row for row in agents["agents"] if row["agent_id"] == did)
        assert workspace["writable"] is False

        status, page = _get(port, f"/api/memories?agent_id={did}&status=confirmed")
        assert status == 200
        assert [row["id"] for row in page["memories"]] == [memory["id"]]

        status, results = _get(port, f"/api/search?q=Quant%20profile&agent_id={did}")
        assert status == 200
        assert [row["id"] for row in results] == [memory["id"]]
    finally:
        profile_reader.close()
        root.close()
        _CURRENT_TOKEN = None


def test_registered_agent_without_memory_is_visible_in_directory(running_store):
    global _CURRENT_TOKEN
    store, port = running_store
    store.identity_mode = "full"
    _CURRENT_TOKEN = issue_token(
        store.home,
        "registered-empty-user",
        roles=("reader",),
        scopes=("memory:read",),
        agent_ids=("did:integrity:registered-but-empty",),
    )

    status, payload = _get(port, "/api/agents")
    assert status == 200
    assert len(payload["agents"]) == 1
    workspace = payload["agents"][0]
    assert workspace["agent_id"] == "did:integrity:registered-but-empty"
    assert workspace["store_id"].startswith("store-")
    assert workspace["profile_id"] == "default"
    assert workspace["store_access"] == "writable"
    assert workspace["writable"] is True
    assert workspace["memories"] == 0
    assert workspace["memories_counted"] is False
    assert workspace["sessions"] == 0
    assert workspace["sessions_counted"] is False
    assert workspace["identity_verified"] is False


def test_account_session_carries_synced_registered_agent_set(running_store):
    global _CURRENT_TOKEN
    from xibalba_cortex.accounts import create_account, issue_account_session, set_account_agent_ids

    store, port = running_store
    store.identity_mode = "full"
    account = create_account(store.home, email="registered@example.com", password="correct horse battery staple", display_name="Registered User", profile_id=store.profile_id)
    assert set_account_agent_ids(store.home, account_id=str(account["id"]), agent_ids=["did:integrity:agent-a", "did:integrity:agent-b"])
    store.store_memory("Account agent A memory", source={"kind": "test", "agent_id": "did:integrity:agent-a"}, status="confirmed")
    store.store_memory("Account agent B memory", source={"kind": "test", "agent_id": "did:integrity:agent-b"}, status="confirmed")
    _CURRENT_TOKEN, session = issue_account_session(store.home, email="registered@example.com", password="correct horse battery staple")
    assert session["agent_ids"] == ["did:integrity:agent-a", "did:integrity:agent-b"]
    status, payload = _get(port, "/api/agents")
    assert status == 200
    assert {row["agent_id"] for row in payload["agents"]} == {"did:integrity:agent-a", "did:integrity:agent-b"}


def test_operator_can_manage_agent_device_pairs(running_store):
    store, port = running_store
    agent_id = store.storage_agent_id("did:integrity:managed-agent")

    status, pair = _post(port, "/api/agent-devices/associate", {
        "agent_id": "did:integrity:managed-agent",
        "device_id": "managed-device",
        "display_name": "Managed device",
    })
    assert status == 200
    assert pair["agent_id"] == agent_id
    assert pair["status"] == "active"

    status, renamed = _post(port, "/api/agent-devices/managed-device/rename", {"display_name": "Renamed device"})
    assert status == 200 and renamed["display_name"] == "Renamed device"
    status, detached = _post(port, "/api/agent-devices/managed-device/detach", {})
    assert status == 200 and detached["status"] == "detached"
    status, revoked = _post(port, "/api/agent-devices/managed-device/revoke", {})
    assert status == 200 and revoked["status"] == "revoked"


def test_agents_route_marks_identity_unverified_when_oracle_unreachable(running_store):
    store, port = running_store
    store.store_memory(
        "Agent-attributed content.",
        source={"kind": "direct_user", "locator": "hermes://session/agents-unverified", "agent_id": "did:integrity:unverified-agent"},
        status="confirmed",
    )
    status, body = _get(port, "/api/agents")
    assert status == 200
    assert body["oracle_reachable"] is False
    assert body["agents"]
    for item in body["agents"]:
        assert item["identity_verified"] is False


def test_agents_route_marks_identity_verified_when_oracle_reachable(running_store, monkeypatch):
    store, port = running_store
    store.store_memory(
        "Agent-attributed content.",
        source={"kind": "direct_user", "locator": "hermes://session/agents-verified", "agent_id": "did:integrity:verified-agent"},
        status="confirmed",
    )

    class _FakeResponse:
        def raise_for_status(self):
            return None

    monkeypatch.setattr("xibalba_cortex.local_api.requests.get", lambda *a, **kw: _FakeResponse())

    status, body = _get(port, "/api/agents")
    assert status == 200
    assert body["oracle_reachable"] is True
    assert body["agents"]
    for item in body["agents"]:
        assert item["identity_verified"] is True


def test_invocations_route_returns_protocol_correlations(running_store):
    store, port = running_store
    invocation_id = "d32c93ca-7c8e-49fb-8071-0941572cecf6"
    store.start_session("correlation-api", retention_tier="verbatim")
    store.record_otel_batch("correlation-api", [{
        "kind": "log",
        "name": "xibalba.runtime.event",
        "attributes": {
            "invocation_id": invocation_id,
            "tool_name": "shell",
            "metadata": {"hook": "pre_tool_call", "tool_call_id": "call-1"},
        },
    }])

    status, body = _get(port, "/api/invocations?limit=20")

    assert status == 200
    assert body[0]["invocation_id"] == invocation_id
    assert body[0]["runtime_status"] == "awaiting_outcome"


def test_memory_detail_and_404(running_store):
    store, port = running_store
    memory = store.store_memory(
        "Detail lookup content.",
        source={"kind": "direct_user", "locator": "hermes://session/detail"},
        status="confirmed",
    )
    status, body = _get(port, f"/api/memory/{memory['id']}")
    assert status == 200
    assert body["content"] == "Detail lookup content."

    status, body = _get(port, "/api/memory/does-not-exist")
    assert status == 404


def test_memory_forget_route_returns_deletion_receipt_and_404_for_missing(running_store):
    store, port = running_store
    memory = store.store_memory(
        "Forget me content.",
        source={"kind": "direct_user", "locator": "hermes://session/forget"},
        status="confirmed",
    )
    status, body = _post(port, f"/api/memory/{memory['id']}/forget", {})
    assert status == 200
    assert body["deletion_receipt"]["memory_id"] == memory["id"]
    assert body["content_hash_retained"] is True

    status, body = _get(port, f"/api/memory/{memory['id']}")
    assert status == 200
    assert body["status"] == "forgotten"

    status, body = _post(port, "/api/memory/does-not-exist/forget", {})
    assert status == 404


def test_memories_list_route_paginates_and_filters_by_status(running_store):
    store, port = running_store
    ids = []
    for i in range(3):
        memory = store.store_memory(
            f"Explorer content {i}.",
            source={"kind": "direct_user", "locator": f"hermes://session/explorer-{i}"},
            status="confirmed",
        )
        ids.append(memory["id"])

    status, body = _get(port, "/api/memories?limit=2&status=confirmed")
    assert status == 200
    assert len(body["memories"]) == 2
    assert body["has_more"] is True

    status, body = _get(port, "/api/memories?limit=2&offset=2&status=confirmed")
    assert status == 200
    assert len(body["memories"]) == 1
    assert body["has_more"] is False

    store.forget_memory(ids[0])
    status, body = _get(port, "/api/memories?status=forgotten")
    assert status == 200
    assert [m["id"] for m in body["memories"]] == [ids[0]]


def test_memory_similar_endpoint(running_store):
    store, port = running_store
    anchor = store.store_memory(
        "Anchor content.",
        source={"kind": "direct_user", "locator": "hermes://session/similar-anchor"},
        status="confirmed",
    )
    near = store.store_memory(
        "Near content.",
        source={"kind": "direct_user", "locator": "hermes://session/similar-near"},
        status="confirmed",
    )
    store.store_embedding(anchor["id"], _unit_vector(0))
    store.store_embedding(near["id"], _unit_vector(0))

    status, body = _get(port, f"/api/memory/{anchor['id']}/similar")
    assert status == 200
    assert body[0]["memory"]["id"] == near["id"]
    assert body[0]["cosine_similarity"] == pytest.approx(1.0)


def test_memory_neighbors_endpoint(running_store):
    store, port = running_store
    memory = store.store_memory(
        "Evidence for a relation.",
        source={"kind": "direct_user", "locator": "hermes://session/neighbors"},
        status="confirmed",
    )
    store.link_entities("Xibalba Shield", "emits_evidence_to", "Integrity Oracle", evidence_memory_id=memory["id"])

    status, body = _get(port, f"/api/memory/{memory['id']}/neighbors")
    assert status == 200
    assert body[0]["predicate"] == "emits_evidence_to"


def test_entity_traversal_endpoints(running_store):
    store, port = running_store
    memory = store.store_memory(
        "Xibalba Shield emits evidence to the Integrity Oracle.",
        source={"kind": "direct_user", "locator": "hermes://session/entity-traversal"},
        status="confirmed",
    )
    store.link_entities("Xibalba Shield", "emits_evidence_to", "Integrity Oracle", evidence_memory_id=memory["id"])
    store.link_entities("Integrity Oracle", "anchors_into", "Integrity DAG", evidence_memory_id=memory["id"])

    status, body = _get(port, "/api/entity/Xibalba%20Shield/neighbors?max_depth=1")
    assert status == 200
    assert body["truncated"] is False
    assert body["edges"][0]["evidence_memory_id"] == memory["id"]

    status, body = _get(port, "/api/entity/path?from=Xibalba%20Shield&to=Integrity%20DAG&max_depth=2")
    assert status == 200
    assert [edge["predicate"] for edge in body["edges"]] == ["emits_evidence_to", "anchors_into"]


def test_graph_endpoint_includes_nodes_and_similarity_edges(running_store):
    store, port = running_store
    anchor = store.store_memory(
        "Graph anchor content.",
        source={"kind": "direct_user", "locator": "hermes://session/graph-anchor"},
        status="confirmed",
    )
    near = store.store_memory(
        "Graph near content.",
        source={"kind": "direct_user", "locator": "hermes://session/graph-near"},
        status="confirmed",
    )
    store.store_embedding(anchor["id"], _unit_vector(0))
    store.store_embedding(near["id"], _unit_vector(0))

    status, body = _get(port, "/api/graph")
    assert status == 200
    node_ids = {node["id"] for node in body["nodes"]}
    assert f"memory:{anchor['id']}" in node_ids
    assert f"memory:{near['id']}" in node_ids
    similarity_edges = [e for e in body["edges"] if e["type"] == "similarity"]
    assert len(similarity_edges) == 1
    assert similarity_edges[0]["cosine_similarity"] == pytest.approx(1.0)


def test_returns_404_for_unconfigured_path(running_store):
    _store, port = running_store
    status, _body = _get(port, "/api/nonexistent")
    assert status == 404


def test_model_exchange_session_and_merkle_routes(running_store):
    _store, port = running_store

    status, body = _post(
        port,
        "/api/exchanges/model",
        {
            "external_session_id": "ui-session",
            "user_prompt": "Remember that I prefer direct engineering updates.",
            "model_response": "Recorded the preference.",
            "context": [
                {
                    "content": "The user values concise implementation notes.",
                    "contribution_id": "recall-1",
                    "context_kind": "retrieved_memory",
                    "relevance": 0.9,
                }
            ],
            "prompt_id": "turn-1",
        },
    )
    assert status == 200
    exchange_id = body["exchange"]["id"]
    assert body["exchange"]["context_contributions"][0]["contribution_id"] == "recall-1"

    status, sessions = _get(port, "/api/sessions")
    assert status == 200
    assert sessions[0]["external_session_id"] == "ui-session"

    status, exchanges = _get(port, "/api/session/ui-session/exchanges")
    assert status == 200
    assert exchanges[0]["id"] == exchange_id

    status, root = _get(port, "/api/session/ui-session/merkle-root")
    assert status == 200
    assert root["root_node_id"] == body["exchange"]["node_id"]
    assert root["valid"] is True

    status, proof = _get(port, "/api/session/ui-session/merkle-proof?index=0")
    assert status == 200
    assert proof["tree_kind"] == "xibalba.exchange_batch.merkle.v2"
    assert proof["leaf"] == body["exchange"]["node_id"]
    assert proof["proof"]["root"].startswith("sha256:")


def test_memory_detail_supporting_routes(running_store):
    store, port = running_store
    memory = store.store_memory(
        "A memory with supporting detail routes.",
        source={"kind": "direct_user", "locator": "hermes://session/detail-routes", "prompt_id": "p1"},
        status="confirmed",
    )
    store.start_session("detail-routes-session")
    store.record_otel_batch(
        "detail-routes-session",
        [{"kind": "log", "name": "test.event", "prompt_id": "p1", "attributes": {"ok": True}}],
    )

    for suffix in ("events", "otel", "attachments", "contradictions"):
        status, body = _get(port, f"/api/memory/{memory['id']}/{suffix}")
        assert status == 200
        assert isinstance(body, list)


def test_inference_task_routes(running_store):
    store, port = running_store
    memory = store.store_memory(
        "The user prefers terse engineering notes.",
        source={"kind": "direct_user", "locator": "xibalba://memory/preferences"},
        status="confirmed",
    )

    status, manifest = _get(port, "/api/inference/manifest")
    assert status == 200
    assert manifest["name"] == "xibalba-memory-inference"

    status, task = _post(
        port,
        "/api/inference/tasks",
        {
            "task_type": "extract_memory_metadata",
            "subject_type": "memory",
            "subject_id": memory["id"],
            "input_payload": {"memory_id": memory["id"]},
            "idempotency_key": "api-task-1",
        },
    )
    assert status == 200
    assert task["status"] == "pending"

    status, tasks = _get(port, "/api/inference/tasks?status=pending")
    assert status == 200
    assert "api-task-1" in [item["id"] for item in tasks]

    status, claimed = _post(port, "/api/inference/tasks/api-task-1/claim", {"claimed_by": "ui"})
    assert status == 200
    assert claimed["status"] == "claimed"

    status, completed = _post(
        port,
        "/api/inference/tasks/api-task-1/complete",
        {"output_payload": {"metadata": {"kind": "preference"}}, "claimed_by": "ui", "claim_token": claimed["claim_token"]},
    )
    assert status == 200
    assert completed["status"] == "completed"


def test_inference_writeback_routes_are_explicit_operator_actions(running_store):
    store, port = running_store
    original = store.store_memory(
        "The MVP is only a search page.",
        source={"kind": "direct_user", "locator": "hermes://session/original"},
        status="confirmed",
    )
    conflict = store.store_memory(
        "The MVP includes timeline, graph, recall, inference, and integrity tabs.",
        source={"kind": "direct_user", "locator": "hermes://session/conflict"},
        status="confirmed",
    )

    status, proposition = _post(
        port,
        "/api/memory/propositions",
        {
            "content": "The MVP memory page exposes operator-mediated write-back actions.",
            "source": {"kind": "inference_output", "locator": "xibalba://task/writeback"},
            "status": "confirmed",
            "evidence_class": "extracted_proposition",
        },
    )
    assert status == 200
    assert proposition["evidence_class"] == "extracted_proposition"

    status, relation = _post(
        port,
        "/api/memory/link-entities",
        {
            "subject": "MVP Memory Page",
            "predicate": "exposes",
            "object": "Write Back Actions",
            "evidence_memory_id": proposition["id"],
            "confidence": 0.8,
        },
    )
    assert status == 200
    assert relation["evidence_memory_id"] == proposition["id"]

    status, contradiction = _post(
        port,
        "/api/memory/contradictions",
        {"memory_id_a": original["id"], "memory_id_b": conflict["id"], "reason": "MVP scope changed"},
    )
    assert status == 200
    assert contradiction["status"] == "recorded"

    status, superseding = _post(
        port,
        f"/api/memory/{original['id']}/supersede",
        {
            "new_content": "The MVP is an operator dashboard with write-back controls.",
            "source": {"kind": "inference_output", "locator": "xibalba://task/supersede"},
            "status": "confirmed",
            "evidence_class": "extracted_proposition",
        },
    )
    assert status == 200
    assert superseding["supersedes_id"] == original["id"]
    assert store.get_memory(original["id"])["status"] == "superseded"


def test_inference_task_route_rejects_invalid_type(running_store):
    _store, port = running_store
    status, body = _post(
        port,
        "/api/inference/tasks",
        {
            "task_type": "invent_truth",
            "subject_type": "memory",
            "subject_id": "x",
            "input_payload": {},
        },
    )
    assert status == 400
    assert "task_type" in body["error"]

def test_account_signup_me_and_logout(running_store, monkeypatch):
    store, port = running_store
    global _CURRENT_TOKEN
    status, signup, cookie_token = _post_capture_cookie(port, "/api/auth/signup", {"email": "operator@example.com", "password": "correct horse battery staple", "display_name": "Account Operator"})
    assert status == 201
    assert signup["account"]["email"] == "operator@example.com"
    assert "token" not in signup, "raw session token must not be returned in the response body"
    assert cookie_token, "signup must set the session cookie"
    _CURRENT_TOKEN = cookie_token
    status, me = _get(port, "/api/auth/me")
    assert status == 200 and me["account"]["email"] == "operator@example.com" and me["session_expires_at"]
    status, audit = _get(port, "/api/auth/events")
    assert status == 200 and any(event["event_type"] == "login_succeeded" for event in audit["events"])
    status, second, second_cookie = _post_capture_cookie(port, "/api/auth/login", {"email": "operator@example.com", "password": "correct horse battery staple"})
    assert status == 200 and second_cookie
    status, sessions = _get(port, "/api/auth/sessions")
    assert status == 200 and len(sessions["sessions"]) >= 2
    status, revoked = _post(port, "/api/auth/sessions/revoke", {"session_id": second_cookie and next(item["id"] for item in sessions["sessions"] if item["revoked_at"] is None and item["id"] != sessions["sessions"][0]["id"])})
    assert status == 200 and revoked["ok"] is True
    status, changed = _post(port, "/api/auth/password", {"current_password": "correct horse battery staple", "new_password": "new correct horse battery"})
    assert status == 200 and changed["ok"] is True

    # Request password reset (via API, but we can't extract the token)
    monkeypatch.setenv("CORTEX_PASSWORD_RESET_URL", "https://cortex.example/reset")
    with patch("xibalba_cortex.email_delivery.send_email") as delivery:
        status, reset = _post(port, "/api/auth/password-reset/request", {"email": "operator@example.com"})
    assert status == 200 and reset.get("delivery") == "email"
    assert "token=" in delivery.call_args.args[2]

    # Generate a fresh token via backend bypass to test the confirm endpoint
    from xibalba_cortex.accounts import request_password_reset
    with patch("xibalba_cortex.email_delivery.send_email"):
        raw_token = request_password_reset(store.home, email="operator@example.com")

    status, confirmed = _post(port, "/api/auth/password-reset/confirm", {"reset_token": raw_token, "new_password": "reset correct horse battery"})
    assert status == 200 and confirmed["ok"] is True

    status, login, login_cookie = _post_capture_cookie(port, "/api/auth/login", {"email": "operator@example.com", "password": "reset correct horse battery"})
    assert status == 200

    _CURRENT_TOKEN = login_cookie
    status, logged_out = _post(port, "/api/auth/logout", {})
    assert status == 200 and logged_out["ok"] is True
    status, _ = _get(port, "/api/auth/me")
    assert status == 401

def test_account_auth_rate_limits_repeated_attempts(running_store):
    store, port = running_store
    global _CURRENT_TOKEN
    statuses = []
    for _ in range(9):
        status, _ = _post(port, "/api/auth/login", {"email": "rate@example.com", "password": "wrong password"})
        statuses.append(status)
    assert statuses[-1] == 429


def test_password_reset_fails_closed_without_delivery_config(running_store, monkeypatch):
    store, port = running_store
    monkeypatch.delenv("CORTEX_PASSWORD_RESET_URL", raising=False)
    status, _signup = _post(port, "/api/auth/signup", {"email": "reset@example.com", "password": "correct horse battery staple", "display_name": "Reset Operator"})
    assert status == 201

    status, response = _post(port, "/api/auth/password-reset/request", {"email": "reset@example.com"})
    assert status == 503
    assert response == {"error": "password reset delivery is unavailable"}
    with sqlite3.connect(store.home / "ingest_tokens.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM password_reset_tokens").fetchone()[0] == 0

def test_account_failed_logins_lock_account_and_record_audit(running_store):
    store, _port = running_store
    from xibalba_cortex.accounts import create_account, issue_account_session
    create_account(store.home, email="lock@example.com", password="correct horse battery staple", display_name="Lock User", profile_id=store.profile_id)
    for _ in range(5):
        try:
            issue_account_session(store.home, email="lock@example.com", password="wrong password")
        except ValueError:
            pass
    try:
        issue_account_session(store.home, email="lock@example.com", password="correct horse battery staple")
    except ValueError as exc:
        assert "temporarily locked" in str(exc)
    else:
        raise AssertionError("locked account accepted a password")
    rows = store.home.joinpath("ingest_tokens.sqlite3")
    import sqlite3
    with sqlite3.connect(rows) as conn:
        events = conn.execute("SELECT event_type, detail FROM auth_events WHERE email=? ORDER BY id", ("lock@example.com",)).fetchall()
    assert events[-1][0] == "login_blocked"


def test_session_cookie_is_httponly_secure_samesite_none(running_store):
    """The browser credential must be unreadable from JavaScript, and (2026-09-15) explicitly
    shareable cross-site so a cross-origin browser app (e.g. integrity-dashboard) can present
    it -- SameSite=None replaces SameSite=Strict's implicit CSRF protection, so assert these
    attributes directly rather than trusting the helper.
    """
    _store, port = running_store
    import urllib.request

    body = json.dumps({"email": "cookie@example.com", "password": "correct horse battery staple", "display_name": "Cookie Operator"}).encode()
    request = urllib.request.Request(f"http://localhost:{port}/api/auth/signup", data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        raw = response.headers.get("Set-Cookie", "")
        payload = json.loads(response.read())

    assert SESSION_COOKIE_NAME in raw
    assert "HttpOnly" in raw
    assert "Secure" in raw
    assert "SameSite=None" in raw
    assert "token" not in payload


def _cookie_request(port: int, path: str, *, cookie: str, method: str = "GET", payload: dict[str, object] | None = None, csrf_token: str | None = None) -> tuple[int, object]:
    """Simulate a real browser call: session identified purely by Cookie header, never Bearer --
    exercises the same code path _verify_csrf() actually guards, unlike _post()/_get() (which
    authenticate via Authorization: Bearer even when the token came from a cookie response)."""
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if csrf_token is not None:
        headers["X-Cortex-CSRF-Token"] = csrf_token
    request = urllib.request.Request(f"http://localhost:{port}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_cookie_authenticated_write_requires_csrf_token(running_store):
    """A SameSite=None cookie is attached to forged cross-site requests automatically -- the
    CSRF token header is what a forger can't produce, since it can't read this origin's
    HttpOnly cookie or a CORS-blocked response naming the token (see _csrf_token_for)."""
    _store, port = running_store
    status, _signup, cookie = _post_capture_cookie(port, "/api/auth/signup", {"email": "csrf@example.com", "password": "correct horse battery staple", "display_name": "CSRF Operator"})
    assert status == 201 and cookie

    # No CSRF header at all: rejected, even though the (SameSite=None) cookie is valid.
    status, body = _cookie_request(port, "/api/memory/propositions", cookie=cookie, method="POST", payload={"content": "csrf probe", "source": {"kind": "test"}})
    assert status == 403 and "csrf" in body["error"].lower()

    # Wrong CSRF token: also rejected.
    status, body = _cookie_request(port, "/api/memory/propositions", cookie=cookie, method="POST", payload={"content": "csrf probe", "source": {"kind": "test"}}, csrf_token="not-the-real-token")
    assert status == 403

    # Fetch the real token the way the browser would, then the write succeeds.
    status, csrf_body = _cookie_request(port, "/api/auth/csrf", cookie=cookie)
    assert status == 200 and csrf_body["csrf_token"]
    status, body = _cookie_request(port, "/api/memory/propositions", cookie=cookie, method="POST", payload={"content": "csrf probe", "source": {"kind": "test"}}, csrf_token=csrf_body["csrf_token"])
    assert status == 200

    # A bearer-token caller (no cookie) is exempt from the CSRF check entirely.
    global _CURRENT_TOKEN
    _CURRENT_TOKEN = cookie
    status, body = _post(port, "/api/memory/propositions", {"content": "bearer caller, no csrf needed", "source": {"kind": "test"}})
    assert status == 200
    _CURRENT_TOKEN = None


def test_dev_bypass_token_is_not_accepted(running_store):
    """`Authorization: Bearer dev` used to authenticate any caller with any scope it asked for."""
    _store, port = running_store
    global _CURRENT_TOKEN
    previous = _CURRENT_TOKEN
    try:
        _CURRENT_TOKEN = "dev"
        status, body = _get(port, "/api/stats")
        assert status == 401, "the literal 'dev' token must no longer authenticate"
        assert body["error"] == "invalid or revoked token"
    finally:
        _CURRENT_TOKEN = previous
