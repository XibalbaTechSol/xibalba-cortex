"""REST ingestion on the managed edition: one handler (GraphStore.ingest_agent_turn), scoped by the key."""
import time

from xibalba_cortex.ingest_tokens import issue_token
from xibalba_cortex.managed.plans import PLANS

TURN = {"external_session_id": "s-1", "runtime": "grok", "prompt": "hello", "response": "hi"}


def bearer(token, key="ingest-key-0001"):
    return {"Authorization": "Bearer " + token, "Idempotency-Key": key}


def usage(app, name):
    return app.service.usage(app.tenant(name))["used"].get("writes", 0)


def set_tenant(app, name, **fields):
    tenant = app.tenant(name)
    with app.service.db(write=True) as db:
        db.execute("UPDATE tenants SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?", (*fields.values(), tenant["id"]))


def set_writes_used(app, name, amount):
    tenant = app.tenant(name)
    month = app.service.usage(tenant)["month"]
    with app.service.db(write=True) as db:
        db.execute("INSERT OR REPLACE INTO usage VALUES(?,?,?,?)", (tenant["id"], month, "writes", amount))


def test_a_full_turn_lands_with_its_tool_calls(managed_app, api_key):
    r = managed_app.post("/api/managed/ingest", headers=bearer(api_key), json={**TURN, "tool_calls": [{"name": "web_search"}]})
    assert r.status_code == 200, r.text
    store = managed_app.store("acct-1")
    stored = store.session_exchanges("s-1")
    assert [t["name"] for t in stored[0]["tool_calls"]] == ["tool_call.web_search"]   # tool calls are committed
    assert len(r.json()["tool_call_otel_event_ids"]) == 1
    assert store.verify_exchange_chain("s-1")["valid"] is True


def test_ingest_requires_an_idempotency_key(managed_app, api_key):
    r = managed_app.post("/api/managed/ingest", headers={"Authorization": "Bearer " + api_key}, json=TURN)
    assert r.status_code == 400
    assert "Idempotency-Key" in r.json()["error"]
    assert managed_app.store("acct-1").list_sessions(limit=10) == []


def test_ingest_without_memory_write_scope_is_refused_and_writes_nothing(managed_app, api_key):
    read_only = issue_token(managed_app.service.identity_home, "managed-api:ro",
        profile_id=managed_app.tenant("acct-1")["id"], roles=("writer",), scopes=("memory:read",), ttl_hours=1)
    r = managed_app.post("/api/managed/ingest", headers=bearer(read_only), json=TURN)
    assert r.status_code == 403
    assert managed_app.store("acct-1").list_sessions(limit=10) == []


def test_a_payload_naming_another_workspace_is_refused_and_writes_nowhere(managed_app, api_key):
    """The workspace comes from the token. A payload naming a different one is a client bug, and
    answering 200 would tell that client its turn landed in B when it landed in A."""
    managed_app.register("acct-2")
    other = managed_app.tenant("acct-2")["id"]
    for field in ("workspace_id", "tenant_id", "profile_id"):
        r = managed_app.post("/api/managed/ingest", headers=bearer(api_key, key=f"scope-key-{field}"),
            json={**TURN, field: other})
        assert r.status_code == 403, f"{field}: {r.text}"
        assert managed_app.store("acct-1").list_sessions(limit=10) == [], field
        assert managed_app.store("acct-2").list_sessions(limit=10) == [], field


def test_a_payload_workspace_that_matches_the_key_is_accepted(managed_app, api_key):
    mine = managed_app.tenant("acct-1")["id"]
    r = managed_app.post("/api/managed/ingest", headers=bearer(api_key),
        json={**TURN, "workspace_id": mine, "tenant_id": mine, "profile_id": mine})
    assert r.status_code == 200, r.text
    assert len(managed_app.store("acct-1").session_exchanges("s-1")) == 1


def test_caller_metadata_cannot_shadow_the_identity_the_handler_stamps(managed_app, api_key):
    r = managed_app.post("/api/managed/ingest", headers=bearer(api_key),
        json={**TURN, "metadata": {"runtime": "forged", "session_id": "forged", "note": "kept"}})
    assert r.status_code == 200, r.text
    prompt = r.json()["prompt_memory"]
    source = managed_app.store("acct-1").get_memory(prompt["id"])["source"]
    assert source["session_id"] == "s-1"
    assert source["metadata"]["runtime"] == "grok" and source["metadata"]["note"] == "kept"


def test_a_key_cannot_claim_an_agent_it_was_not_issued_for(managed_app, api_key):
    r = managed_app.post("/api/managed/ingest", headers=bearer(api_key),
        json={**TURN, "agent_id": "did:integrity:someone-else"})
    assert r.status_code == 403
    assert managed_app.store("acct-1").list_sessions(limit=10) == []


def test_free_tier_is_refused_at_the_write_boundary_and_pro_is_not(managed_app, api_key):
    limit = PLANS["free"].writes_per_month
    set_writes_used(managed_app, "acct-1", limit)
    refused = managed_app.post("/api/managed/ingest", headers=bearer(api_key), json=TURN)
    assert refused.status_code == 429
    assert "limit" in refused.json()["error"]
    assert managed_app.store("acct-1").list_sessions(limit=10) == []
    set_tenant(managed_app, "acct-1", plan="pro", status="active", period_end=time.time() + 86400)
    assert managed_app.post("/api/managed/ingest", headers=bearer(api_key), json=TURN).status_code == 200


def test_a_retried_ingest_is_not_charged_twice(managed_app, api_key):
    for _ in range(2):
        assert managed_app.post("/api/managed/ingest", headers=bearer(api_key, "retry-key-0001"), json=TURN).status_code == 200
    assert usage(managed_app, "acct-1") == 1
    assert len(managed_app.store("acct-1").session_exchanges("s-1")) == 1


def test_a_read_only_subscription_refuses_ingest_but_still_reads(managed_app, api_key):
    set_tenant(managed_app, "acct-1", plan="pro", status="canceled", period_end=time.time() + 86400)
    r = managed_app.post("/api/managed/ingest", headers=bearer(api_key), json=TURN)
    assert r.status_code == 403
    assert r.json()["error"].startswith("Subscription is read-only")
    assert managed_app.client.get("/api/managed/memories", headers={"Authorization": "Bearer " + api_key}).status_code == 200


def test_revoking_an_api_key_stops_ingestion_on_the_next_call(managed_app):
    key_id, token = managed_app.issue_key("acct-1")
    assert managed_app.post("/api/managed/ingest", headers=bearer(token), json=TURN).status_code == 200
    managed_app.revoke_key("acct-1", key_id)
    assert managed_app.post("/api/managed/ingest", headers=bearer(token, "ingest-key-0002"), json=TURN).status_code == 401
