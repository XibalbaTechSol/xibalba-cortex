"""Memory kinds and the /profile endpoint. Synthetic text only (public repo).

Embedding similarity cannot tell a preference from a fact about the same topic (measured on the
Phase 2 eval set: a "preferences" query scored every memory around 0.55-0.6 and ranked plans and
config facts first). So extraction labels each memory's kind, and profile buckets select by kind.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from super_cortex.engine import EngineStore, HashingEmbedder
from super_cortex.engine.app import create_app
from super_cortex.engine.dreaming import RESPONSE_SCHEMA, DreamStats, apply_proposals
from super_cortex.engine.profile import BUCKET_KINDS, build_profile

NS = "t"
DOCS = {
    "a": "Priya prefers dark roast coffee and always reviews pull requests in the morning.",
    "b": "Priya plans to ship the billing dashboard by Friday.",
    "c": "The staging database runs on port 5433.",
    "d": "Never deploy on Fridays without a rollback plan, the team agreed.",
}


@pytest.fixture
def store():
    s = EngineStore(":memory:", HashingEmbedder())
    yield s
    s.close()


def remember(store, doc_id, text, quote, kind):
    store.upsert_document(NS, DOCS[doc_id], doc_id)
    docs = [d for d in store.pending_documents(50) if d["id"] == doc_id]
    apply_proposals(store, NS, docs, [], [{"memory": text, "doc": "D1", "quote": quote, "confidence": 0.9,
                                           "inference": False, "kind": kind}], "fake", DreamStats())


def seed(store):
    remember(store, "a", "Priya prefers dark roast coffee.", "prefers dark roast coffee", "preference")
    remember(store, "b", "Priya plans to ship the billing dashboard by Friday.", "ship the billing dashboard", "goal")
    remember(store, "c", "The staging database runs on port 5433.", "runs on port 5433", "fact")
    remember(store, "d", "Never deploy on Fridays without a rollback plan.", "Never deploy on Fridays", "rule")


def test_extraction_schema_requires_a_kind_from_a_fixed_set():
    item = RESPONSE_SCHEMA["properties"]["documents"]["items"]["properties"]["memories"]["items"]
    assert "kind" in item["required"]
    assert set(item["properties"]["kind"]["enum"]) == {"fact", "preference", "goal", "decision", "rule", "event"}


def test_kind_is_stored_and_unknown_kinds_fall_back_to_fact(store):
    seed(store)
    remember(store, "c", "Staging uses Postgres 16.", "staging database", "gossip")
    kinds = {m["memory"]: m["kind"] for m in store.list_memories(NS, limit=50)["memories"]}
    assert kinds["Priya prefers dark roast coffee."] == "preference"
    assert kinds["Staging uses Postgres 16."] == "fact"


def test_profile_shape_matches_supermemory(store):
    seed(store)
    profile = build_profile(store, NS)["profile"]
    assert set(profile) >= {"static", "dynamic", "buckets"}
    # dynamic: every latest memory, newest first, date-prefixed like Supermemory
    assert len(profile["dynamic"]) == 4
    assert profile["dynamic"][0]["memory"].startswith("[") and "Never deploy" in profile["dynamic"][0]["memory"]
    # static: standing preferences and rules, not one-off facts or goals
    assert {m["kind"] for m in profile["static"]} == {"preference", "rule"}
    # default bucket is preferences
    assert [m["memory"] for m in profile["buckets"]["preferences"]] == ["Priya prefers dark roast coffee."]


def test_requested_buckets_select_by_kind_and_unknown_buckets_are_reported(store):
    seed(store)
    result = build_profile(store, NS, buckets=["goals", "rules", "projects"])
    buckets = result["profile"]["buckets"]
    assert [m["memory"] for m in buckets["goals"]] == ["Priya plans to ship the billing dashboard by Friday."]
    assert [m["memory"] for m in buckets["rules"]] == ["Never deploy on Fridays without a rollback plan."]
    assert buckets["projects"] == []
    assert result["unsupportedBuckets"] == ["projects"]
    assert set(BUCKET_KINDS) >= {"preferences", "goals", "decisions", "rules", "facts", "events"}


def test_profile_items_keep_provenance_and_skip_superseded_or_candidates(store):
    seed(store)
    old = next(m for m in store.list_memories(NS, limit=50)["memories"] if "dark roast" in m["memory"])
    with store._conn:
        store._conn.execute("UPDATE memories SET status = 'superseded' WHERE id = ?", (old["id"],))
    profile = build_profile(store, NS)["profile"]
    assert all("dark roast" not in m["memory"] for m in profile["dynamic"])
    item = profile["dynamic"][0]
    assert item["dataClass"] == "metadata" and item["derivedFrom"] and item["id"].startswith("m_")


def test_profile_endpoint_accepts_the_live_client_payload(store):
    seed(store)
    client = TestClient(create_app(store, api_key="k"))
    r = client.post(f"/ns/{NS}/profile", json={"buckets": ["preferences"], "filter": {"x": 1}},
                    headers={"Authorization": "Bearer k"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"]["buckets"]["preferences"][0]["memory"] == "Priya prefers dark roast coffee."
    assert body["ignored"] == ["filter"]
    assert client.post(f"/ns/{NS}/profile", json={}).status_code == 401


def remember_dated(store, doc_id, text, quote, metadata):
    store.upsert_document(NS, DOCS[doc_id], doc_id, metadata)
    docs = [d for d in store.pending_documents(50) if d["id"] == doc_id]
    apply_proposals(store, NS, docs, [], [{"memory": text, "doc": "D1", "quote": quote, "confidence": 0.9,
                                           "inference": False, "kind": "fact"}], "fake", DreamStats())


def test_dynamic_items_are_dated_by_their_source_record_not_extraction_time(store):
    # A backfill extracts months-old records today; the profile must show when they were recorded.
    remember_dated(store, "b", "Priya plans to ship the billing dashboard.", "ship the billing dashboard",
                   {"recordCreatedAt": "2026-03-01 09:00:00"})
    remember_dated(store, "c", "The staging database runs on port 5433.", "runs on port 5433",
                   {"createdAt": "2026-05-02T10:00:00+00:00"})
    dynamic = build_profile(store, NS)["profile"]["dynamic"]
    assert [d["memory"] for d in dynamic] == [
        "[2026-05-02] The staging database runs on port 5433.",   # newest record first
        "[2026-03-01] Priya plans to ship the billing dashboard.",
    ]
    assert dynamic[0]["observedAt"].startswith("2026-05-02")


def test_a_non_date_record_time_falls_back_to_when_the_document_arrived(store):
    remember_dated(store, "c", "The staging database runs on port 5433.", "runs on port 5433",
                   {"recordCreatedAt": "yesterday-ish"})
    received = store.get_document(NS, "c")["createdAt"][:10]
    assert build_profile(store, NS)["profile"]["dynamic"][0]["memory"].startswith(f"[{received}]")
