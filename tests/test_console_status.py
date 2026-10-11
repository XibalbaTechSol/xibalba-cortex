"""Operational status for the console: runtimes, workers, connectors, and the vault lookup.

These views are READS over what the store already records. The properties worth pinning:

  * a policy deny/ask is surfaced as an intervention, with its reason;
  * a worker's state is derived from its queue, and "idle" (nothing waiting) is never confused with
    "backlog" (work waiting, nothing servicing it) or "stalled" (a lease that ran out);
  * a connector with no attributable evidence gets no made-up count;
  * the routes are store-wide, so an agent-bound or non-operator credential is refused;
  * a vault error never carries a filesystem path to the browser.
"""
from __future__ import annotations

import json
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from xibalba_cortex.console_status import BACKLOG_AFTER, connector_status, runtime_overview, worker_status
from xibalba_cortex.ingest_tokens import issue_token
from xibalba_cortex.local_api import serve
from xibalba_cortex.providers import connector_manifest
from xibalba_cortex.store import GraphStore
from xibalba_cortex.vault_inspect import _leaf_preimage

from eth_hash.auto import keccak


@pytest.fixture
def store(tmp_path):
    s = GraphStore(tmp_path / "graph")
    yield s
    s.close()


def _tool(invocation: str, hook: str, runtime: str, **attrs):
    meta = {"hook": hook, "tool_call_id": f"call-{invocation}", **attrs.pop("metadata", {})}
    return {"kind": "span", "name": f"tool.{hook}", "attributes": {"invocation_id": invocation, "runtime": runtime, "tool_name": "write_file", "metadata": meta, **attrs}}


# --- runtimes ----------------------------------------------------------------------------------------------

def test_runtimes_count_what_each_left_and_surface_denials_with_their_reason(store):
    store.start_session("s1", retention_tier="digest")
    store.record_model_exchange("s1", user_prompt="q", model_response="a", runtime="claude", prompt_id="p1")
    store.record_otel_batch("s1", [
        _tool("i1", "pre_tool_call", "claude", metadata={"kernel_decision": {"verdict": "allow"}, "policy_reason": "within budget"}),
        _tool("i1", "post_tool_call", "claude", tool_outcome="success"),
        _tool("i2", "pre_tool_call", "claude", metadata={"kernel_decision": {"verdict": "deny"}, "policy_reason": "destructive action"}),
        _tool("i3", "pre_tool_call", "codex", metadata={"kernel_decision": {"verdict": "ask"}, "policy_reason": "needs approval"}),
    ])
    rows = {r["runtime"]: r for r in store.runtime_overview()}
    assert set(rows) == {"claude", "codex"}
    claude = rows["claude"]
    assert claude["invocations"] == 2 and claude["sessions"] == 1 and claude["memories"] >= 1
    assert claude["decisions"] == {"allow": 1, "deny": 1, "ask": 0, "other": 0}
    assert claude["outcomes"]["success"] == 1
    assert [(i["verdict"], i["reason"]) for i in claude["interventions"]] == [("deny", "destructive action")]
    assert rows["codex"]["decisions"]["ask"] == 1 and rows["codex"]["interventions"][0]["reason"] == "needs approval"


def test_a_runtime_that_has_not_written_lately_is_quiet_not_down(store):
    store.record_model_exchange("s1", user_prompt="q", model_response="a", runtime="old-runtime", prompt_id="p1")
    later = datetime.now(timezone.utc) + timedelta(days=3)
    assert runtime_overview(store._read_connection(), [], now=later)[0]["activity"] == "quiet"
    assert runtime_overview(store._read_connection(), [])[0]["activity"] == "recent"


def test_no_runtimes_is_an_empty_list_not_an_error(store):
    assert store.runtime_overview() == []


# --- workers -----------------------------------------------------------------------------------------------

def _memory(store, n=1):
    return store.store_memory(f"A fact number {n}.", source={"kind": "explicit_memory", "locator": f"t://{n}"}, status="active", idempotency_key=f"k{n}")


def _queued(store, task_type, memory):
    """The task the store already queued for this memory, or a new one. store_memory enqueues
    classification and extraction itself, so asking again would double the queue."""
    for task in store.list_inference_tasks(status="pending", task_type=task_type, limit=500):
        if task["subject_id"] == memory["id"]:
            return task
    return store.request_inference_task(task_type, subject_type="memory", subject_id=memory["id"], input_payload={"source_content_hash": memory["content_hash"]})


def _states(store, now=None):
    return {w["id"]: w for w in worker_status(store._read_connection(), store.embedding_coverage(), now=now)["workers"]}


def test_waiting_work_nothing_has_picked_up_is_backlog_and_an_empty_queue_is_idle(store):
    m = _memory(store)
    _queued(store, "classify_para", m)
    para = _states(store)["para"]
    assert para["pending"] >= 1 and para["state"] == "backlog" and para["last_activity_at"] is None
    assert _states(store)["contradiction"]["state"] in {"idle", "no work seen"} and _states(store)["contradiction"]["pending"] == 0


def test_a_claimed_task_under_a_live_lease_is_working_and_an_expired_lease_is_stalled(store):
    m = _memory(store)
    task = _queued(store, "classify_para", m)
    store.claim_inference_task(task["id"], claimed_by="para-worker-1", provider_id="hermes")
    working = _states(store)["para"]
    assert working["state"] == "working" and working["in_flight"] == 1 and working["claimed_by"] == ["para-worker-1"]
    # the same lease, judged from after it expired: nobody finished it
    stalled = _states(store, now=datetime.now(timezone.utc) + timedelta(hours=2))["para"]
    assert stalled["state"] == "stalled" and stalled["stalled_leases"] == 1 and stalled["in_flight"] == 0


def test_finished_work_with_an_empty_queue_is_idle_and_old_waiting_work_is_backlog(store):
    m = _memory(store, 1)
    done = _queued(store, "detect_contradictions", m)
    claimed = store.claim_inference_task(done["id"], claimed_by="w", provider_id="hermes")
    store.complete_inference_task(done["id"], claimed_by="w", claim_token=claimed["claim_token"], error="boom", failure_class="permanent", dead_letter_reason="test")
    state = _states(store)["contradiction"]
    assert state["pending"] == 0 and state["failed_24h"] == 1 and state["state"] == "failing"
    # new waiting work, long after the last activity, with nothing servicing it
    m2 = _memory(store, 2)
    _queued(store, "detect_contradictions", m2)
    later = datetime.now(timezone.utc) + BACKLOG_AFTER + timedelta(minutes=1)
    assert _states(store, now=later)["contradiction"]["state"] in {"backlog", "failing"}


def test_embedding_state_comes_from_coverage_and_says_how_it_knows(store):
    _memory(store)
    status = worker_status(store._read_connection(), store.embedding_coverage())
    embedding = next(w for w in status["workers"] if w["id"] == "embedding")
    assert embedding["pending"] >= 1 and embedding["state"] == "backlog"
    assert embedding["coverage"]["eligible"] >= 1
    assert "no heartbeat" in status["basis"].lower()


# --- connectors --------------------------------------------------------------------------------------------

def test_a_connector_gets_a_count_only_where_the_store_can_attribute_one(store):
    store.ingest_connector_event("pagerduty", "evt-1", "An incident was opened.", metadata={})
    store.ingest_connector_event("pagerduty", "evt-2", "An incident was closed.", metadata={})
    store.ingest_connector_event("statuspage", "evt-9", "A component recovered.", metadata={})
    status = store.connector_status(connector_manifest())
    by_name = {c["name"]: c for c in status["connectors"]}
    assert by_name["webhook"]["evidence"]["memories"] == 3
    assert by_name["claude_transcripts"]["evidence"] is None  # not attributable, so no number
    senders = {s["connector"]: s["events"] for s in status["webhook_senders"]}
    assert senders == {"pagerduty": 2, "statuspage": 1}
    assert any(k["kind"] == "connector_event" and k["memories"] == 3 for k in status["ingest_by_source_kind"])
    assert "does not start or drive" in status["basis"]


def test_connector_status_on_an_empty_store(store):
    status = connector_status(store._read_connection(), connector_manifest())
    assert status["webhook_senders"] == [] and status["ingest_by_source_kind"] == []
    assert all(c["evidence"] in (None, {"memories": 0, "last_at": None}) for c in status["connectors"])


# --- routes ------------------------------------------------------------------------------------------------

def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


class _Api:
    def __init__(self, port, bearer):
        self.port, self.bearer = port, bearer

    def get(self, path):
        request = urllib.request.Request(f"http://localhost:{self.port}{path}", headers={"Authorization": f"Bearer {self.bearer}"})
        try:
            with urllib.request.urlopen(request, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


def _serve(tmp_path, *, roles, scopes=("memory:read",), agent_id=None):
    s = GraphStore(tmp_path / "graph")
    bearer = issue_token(s.home, "t", roles=roles, scopes=scopes, agent_id=agent_id)
    port = _port()
    threading.Thread(target=serve, kwargs={"store": s, "port": port}, daemon=True).start()
    time.sleep(0.3)
    return s, _Api(port, bearer)


def test_status_routes_answer_an_operator(tmp_path):
    s, api = _serve(tmp_path, roles=("operator",))
    try:
        for path, key in (("/api/runtimes", "runtimes"), ("/api/workers", "workers"), ("/api/connectors", "connectors")):
            status, body = api.get(path)
            assert status == 200 and key in body, path
    finally:
        s.close()


@pytest.mark.parametrize("roles", [("reader",), ("writer",), ("reviewer",)])
def test_status_routes_refuse_a_non_operator(tmp_path, roles):
    s, api = _serve(tmp_path, roles=roles)
    try:
        assert [api.get(p)[0] for p in ("/api/runtimes", "/api/workers", "/api/connectors", "/api/vault/leaf?leaf_hash=0x" + "0" * 64)] == [403] * 4
    finally:
        s.close()


def test_status_routes_refuse_an_agent_bound_operator(tmp_path):
    s, api = _serve(tmp_path, roles=("operator",), agent_id="agent-a")
    try:
        status, body = api.get("/api/workers")
        assert status == 403 and "agent-bound" in body["error"]
    finally:
        s.close()


# --- vault -------------------------------------------------------------------------------------------------

def _leaf(vault, *, anchored: bool) -> str:
    fields = ("commit", "task-1", "abc123", "0x" + "11" * 32, 1_760_000_000)
    leaf_hash = "0x" + keccak(_leaf_preimage(*fields)).hex()
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "leaves.jsonl").write_text(json.dumps({"kind": fields[0], "task_id": fields[1], "commit_sha": fields[2], "test_result_hash": fields[3], "timestamp": fields[4], "leaf_hash": leaf_hash}) + "\n")
    (vault / "anchors.jsonl").write_text((json.dumps({"leaves_through": 1, "tx_hash": "0xabc"}) + "\n") if anchored else "")
    return leaf_hash


def test_vault_lookup_validates_and_reports_unconfigured(tmp_path, monkeypatch):
    s, api = _serve(tmp_path, roles=("operator",))
    try:
        monkeypatch.delenv("XIBALBA_VAULT_DIR", raising=False)
        assert api.get("/api/vault/leaf?leaf_hash=nonsense")[0] == 400
        status, body = api.get("/api/vault/leaf?leaf_hash=0x" + "ab" * 32)
        assert status == 503 and "no trust vault is configured" in body["error"]
    finally:
        s.close()


def test_vault_lookup_finds_anchored_unanchored_and_missing_leaves(tmp_path, monkeypatch):
    s, api = _serve(tmp_path, roles=("operator",))
    try:
        vault = tmp_path / "vault"
        monkeypatch.setenv("XIBALBA_VAULT_DIR", str(vault))
        leaf = _leaf(vault, anchored=False)
        status, body = api.get(f"/api/vault/leaf?leaf_hash={leaf}")
        assert status == 200 and body["found"] is True and body["anchored"] is False and body["recomputed_hash_matches"] is True
        leaf = _leaf(vault, anchored=True)
        assert api.get(f"/api/vault/leaf?leaf_hash={leaf}")[1]["anchored"] is True
        assert api.get("/api/vault/leaf?leaf_hash=0x" + "ee" * 32)[1] == {"found": False, "anchored": False, "leaf": None, "anchor": None}
    finally:
        s.close()


def test_a_vault_error_never_names_a_path(tmp_path, monkeypatch):
    s, api = _serve(tmp_path, roles=("operator",))
    try:
        vault = tmp_path / "secret-vault-location"
        vault.mkdir()
        (vault / "leaves.jsonl").write_text("{not json\n")
        monkeypatch.setenv("XIBALBA_VAULT_DIR", str(vault))
        status, body = api.get("/api/vault/leaf?leaf_hash=0x" + "ab" * 32)
        assert status == 200 and body["found"] is False and body["error"] == "the vault could not be read"
        assert "secret-vault-location" not in json.dumps(body) and str(tmp_path) not in json.dumps(body)
    finally:
        s.close()
