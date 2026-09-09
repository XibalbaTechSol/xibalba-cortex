import json
import sqlite3
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from xibalba_cortex.ingest_tokens import issue_token
from xibalba_cortex.local_api import serve
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
    assert body["schema_version"] == 13
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
    assert [item["id"] for item in tasks] == ["api-task-1"]

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

def test_account_signup_me_and_logout(running_store):
    store, port = running_store
    global _CURRENT_TOKEN
    status, signup = _post(port, "/api/auth/signup", {"email": "operator@example.com", "password": "correct horse battery staple", "display_name": "Account Operator"})
    assert status == 201
    assert signup["account"]["email"] == "operator@example.com"
    _CURRENT_TOKEN = signup["token"]
    status, me = _get(port, "/api/auth/me")
    assert status == 200 and me["account"]["email"] == "operator@example.com" and me["session_expires_at"]
    status, audit = _get(port, "/api/auth/events")
    assert status == 200 and any(event["event_type"] == "login_succeeded" for event in audit["events"])
    status, second = _post(port, "/api/auth/login", {"email": "operator@example.com", "password": "correct horse battery staple"})
    assert status == 200
    status, sessions = _get(port, "/api/auth/sessions")
    assert status == 200 and len(sessions["sessions"]) >= 2
    status, revoked = _post(port, "/api/auth/sessions/revoke", {"session_id": second["token"] and next(item["id"] for item in sessions["sessions"] if item["revoked_at"] is None and item["id"] != sessions["sessions"][0]["id"])})
    assert status == 200 and revoked["ok"] is True
    status, changed = _post(port, "/api/auth/password", {"current_password": "correct horse battery staple", "new_password": "new correct horse battery"})
    assert status == 200 and changed["ok"] is True

    # Request password reset (via API, but we can't extract the token)
    status, reset = _post(port, "/api/auth/password-reset/request", {"email": "operator@example.com"})
    assert status == 200 and reset.get("delivery") == "email"

    # Generate a fresh token via backend bypass to test the confirm endpoint
    from xibalba_cortex.accounts import request_password_reset
    raw_token = request_password_reset(store.home, email="operator@example.com")

    status, confirmed = _post(port, "/api/auth/password-reset/confirm", {"reset_token": raw_token, "new_password": "reset correct horse battery"})
    assert status == 200 and confirmed["ok"] is True

    status, login = _post(port, "/api/auth/login", {"email": "operator@example.com", "password": "reset correct horse battery"})
    assert status == 200

    _CURRENT_TOKEN = login["token"]
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
