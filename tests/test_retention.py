"""Retention policy per namespace: audit keeps everything provably, standard keeps the current
version, research keeps only memories. Synthetic text only (public repo)."""

from __future__ import annotations

import sqlite3

import pytest
from starlette.testclient import TestClient

from super_cortex.engine import EngineStore, HashingEmbedder
from super_cortex.engine.app import create_app
from super_cortex.engine.dreaming import DreamStats, apply_proposals
from super_cortex.engine.policy import build_policy

NS = "t"
V1 = "Priya moved the weekly design review from Tuesday to Thursday at 3pm."
V2 = "Update: the weekly design review now happens on Friday at 10am."
ALLERGY = "Priya prefers dark roast coffee. She is allergic to peanuts."


@pytest.fixture
def store():
    s = EngineStore(":memory:", HashingEmbedder())
    yield s
    s.close()


def remember_peanuts(store, ns=NS):
    docs = [d for d in store.pending_documents() if d["namespace"] == ns]
    apply_proposals(store, ns, docs, [], [
        {"memory": "Priya is allergic to peanuts.", "doc": "D1", "quote": "allergic to peanuts",
         "confidence": 0.9, "inference": False}], "fake", DreamStats())
    return store.list_memories(ns)["memories"][0]["id"]


def contents(store, ns=NS, doc="a"):
    return [v["content"] for v in store.document_versions(ns, doc)]


# -- policy model ---------------------------------------------------------------------------------

def test_default_is_standard_and_the_env_can_change_it(monkeypatch, store):
    assert store.get_policy("fresh").preset == "standard"
    monkeypatch.setenv("SUPER_CORTEX_DEFAULT_RETENTION", "research")
    assert store.get_policy("fresh").preset == "research"


def test_first_write_pins_the_policy_against_later_default_changes(monkeypatch, store):
    store.upsert_document(NS, V1, "a")
    monkeypatch.setenv("SUPER_CORTEX_DEFAULT_RETENTION", "research")
    assert store.get_policy(NS).preset == "standard"


def test_invalid_settings_are_refused():
    with pytest.raises(ValueError):
        build_policy("audit", {"versions": "latest"})
    with pytest.raises(ValueError):
        build_policy("standard", {"raw_after_dream": "drop", "dreaming": "off"})
    with pytest.raises(ValueError):
        build_policy("standard", {"version_ttl_days": 30})          # needs versions=all
    with pytest.raises(ValueError):
        build_policy("standard", {"colour": "blue"})
    assert build_policy("standard", {"versions": "all", "version_ttl_days": 30}).version_ttl_days == 30


# -- standard -------------------------------------------------------------------------------------

def test_standard_keeps_only_the_current_version_and_delete_removes_it(store):
    store.upsert_document(NS, V1, "a")
    store.upsert_document(NS, V2, "a")
    assert contents(store) == [V2]
    store.delete_documents(NS, ["a"])
    assert contents(store) == []


def test_standard_with_all_versions_keeps_history(store):
    store.set_policy(NS, "standard", {"versions": "all"})
    store.upsert_document(NS, V1, "a")
    store.upsert_document(NS, V2, "a")
    assert contents(store) == [V1, V2]


def test_dreaming_off_never_queues_documents(store):
    store.set_policy(NS, "standard", {"dreaming": "off"})
    store.upsert_document(NS, V1, "a", task_type="memory")
    assert store.pending_documents() == []


# -- audit ----------------------------------------------------------------------------------------

def test_audit_keeps_every_version_through_edits_and_deletes(store):
    store.set_policy(NS, "audit")
    assert store.upsert_document(NS, V1, "a", {"by": "x"})["version"] == 1
    assert store.upsert_document(NS, V1, "a", {"by": "y"})["version"] == 2     # metadata-only change
    assert store.upsert_document(NS, V2, "a", {"by": "y"})["version"] == 3
    store.delete_documents(NS, ["a"])
    assert store.get_document(NS, "a") is None
    versions = store.document_versions(NS, "a")
    assert [(v["version"], v["content"], v["metadata"]) for v in versions] == [
        (1, V1, {"by": "x"}), (2, V1, {"by": "y"}), (3, V2, {"by": "y"})]
    assert versions[-1]["deletedAt"] and versions[-1]["replacedAt"] is None
    assert store.upsert_document(NS, ALLERGY, "a")["version"] == 4          # history continues


def test_audit_evidence_names_the_exact_version_and_survives_replacement(store):
    store.set_policy(NS, "audit")
    store.upsert_document(NS, ALLERGY, "a")
    memory_id = remember_peanuts(store)
    store.upsert_document(NS, V1, "a")
    memory = store.get_memories([memory_id])[memory_id]
    assert memory["status"] == "forgotten" and memory["sources"] == []
    [evidence] = memory["detachedSources"]
    assert evidence["documentVersion"] == 1
    assert evidence["quote"] in store.document_versions(NS, "a")[0]["content"]


def test_audit_rows_are_protected_by_the_database_itself(store):
    store.set_policy(NS, "audit")
    store.upsert_document(NS, ALLERGY, "a")
    remember_peanuts(store)
    for sql in ("DELETE FROM document_versions", "UPDATE document_versions SET content = 'x'",
                "DELETE FROM memory_sources", "DELETE FROM memories", "UPDATE memories SET content = 'x'",
                "UPDATE documents SET content = ''", "DELETE FROM namespace_policies",
                "UPDATE namespace_policies SET preset = 'standard'"):
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(sql)


def test_the_same_raw_sql_is_allowed_outside_audit(store):
    store.upsert_document(NS, ALLERGY, "a")
    remember_peanuts(store)
    store._conn.execute("DELETE FROM memory_sources")
    store._conn.execute("DELETE FROM document_versions")


def test_audit_is_a_one_way_lock(store):
    store.set_policy(NS, "audit")
    store.set_policy(NS, "audit")                       # re-asserting is fine
    with pytest.raises(PermissionError):
        store.set_policy(NS, "standard")
    assert store.get_policy(NS).preset == "audit"
    store.set_policy("other", "standard")
    store.set_policy("other", "audit")                  # tightening is fine


# -- research -------------------------------------------------------------------------------------

def test_research_drops_raw_content_once_memories_exist(store):
    store.set_policy(NS, "research")
    store.upsert_document(NS, ALLERGY, "a")
    memory_id = remember_peanuts(store)
    store.mark_dreamed(NS, ["a"])
    doc = store.get_document(NS, "a")
    assert doc["content"] == "" and doc["rawDropped"]
    assert contents(store) == [] and store.chunks([f"a#0"]) == {}
    memory = store.get_memories([memory_id])[memory_id]
    assert memory["isLatest"] and memory["sources"][0]["quote"] == "allergic to peanuts"


def test_research_keeps_raw_content_until_extraction_succeeds(store):
    store.set_policy(NS, "research")
    store.upsert_document(NS, ALLERGY, "a")
    store.record_dream_failure(NS, ["a"], max_attempts=1)
    assert store.get_document(NS, "a")["content"] == ALLERGY


# -- API ------------------------------------------------------------------------------------------

def test_policy_api_and_default_search_mode(store):
    client = TestClient(create_app(store, api_key="k"))
    auth = {"Authorization": "Bearer k"}
    assert client.get(f"/ns/{NS}/policy", headers=auth).json()["preset"] == "standard"
    r = client.put(f"/ns/{NS}/policy", json={"preset": "research"}, headers=auth)
    assert r.status_code == 200 and r.json()["default_search"] == "memories"
    client.post(f"/ns/{NS}/document", json={"content": ALLERGY, "id": "a", "taskType": "memory"}, headers=auth)
    remember_peanuts(store)
    hit = client.post(f"/ns/{NS}/search", json={"query": "peanut allergy"}, headers=auth).json()["results"][0]
    assert hit["memory"] == "Priya is allergic to peanuts."
    assert client.put(f"/ns/{NS}/policy", json={"preset": "nope"}, headers=auth).status_code == 400
    assert client.put("/ns/locked/policy", json={"preset": "audit"}, headers=auth).json()["locked"] is True
    assert client.put("/ns/locked/policy", json={"preset": "standard"}, headers=auth).status_code == 409
    assert client.get(f"/ns/{NS}/policy").status_code == 401


def test_api_serves_kept_version_history(store):
    client = TestClient(create_app(store, api_key="k"))
    auth = {"Authorization": "Bearer k"}
    client.put(f"/ns/{NS}/policy", json={"preset": "audit"}, headers=auth)
    client.post(f"/ns/{NS}/document", json={"content": V1, "id": "a"}, headers=auth)
    client.post(f"/ns/{NS}/document", json={"content": V2, "id": "a"}, headers=auth)
    client.request("DELETE", f"/ns/{NS}/document", json={"ids": ["a"]}, headers=auth)
    assert client.get(f"/ns/{NS}/document/a", headers=auth).status_code == 404
    history = client.get(f"/ns/{NS}/document/a/versions", headers=auth).json()["versions"]
    assert [v["content"] for v in history] == [V1, V2]
    assert client.get(f"/ns/{NS}/document/zzz/versions", headers=auth).status_code == 404


# -- data classes: ingested content is the record, everything synthesised is metadata ------------

def test_synthesised_items_are_metadata_with_provenance_and_documents_are_content(store):
    from super_cortex.engine.search import hybrid_search, memory_search

    store.upsert_document(NS, ALLERGY, "a")
    remember_peanuts(store)
    doc = store.get_document(NS, "a")
    assert doc["dataClass"] == "content"
    assert store.document_versions(NS, "a")[0]["dataClass"] == "content"

    chunk = hybrid_search(store, NS, "peanuts", threshold=0)["results"][0]
    assert chunk["dataClass"] == "metadata"
    assert chunk["derivedFrom"] == [{"documentId": "a", "documentVersion": 1}]
    assert chunk["generator"]["process"] == "chunking"

    memory = memory_search(store, NS, "peanuts", threshold=0)["results"][0]
    assert memory["dataClass"] == "metadata"
    assert memory["derivedFrom"] == [{"documentId": "a", "documentVersion": 1, "quote": "allergic to peanuts"}]
    assert memory["generator"]["process"] == "extraction" and memory["generator"]["model"] == "fake"
