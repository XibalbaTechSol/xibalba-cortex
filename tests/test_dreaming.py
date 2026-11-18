"""Dreaming: grounding, supersession, merging, forgetting, budget. Synthetic text only (public repo)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from super_cortex.engine import EngineStore, HashingEmbedder
from super_cortex.engine.app import create_app
from super_cortex.engine.dreaming import (
    DreamStats,
    QuotaExhausted,
    TransientError,
    apply_proposals,
    build_prompt,
    related_memories,
    run_dreaming,
)
from super_cortex.engine.search import memory_search

NS = "t"
REVIEW = "Priya moved the weekly design review from Tuesday to Thursday at 3pm."
COFFEE = "Priya prefers dark roast coffee. She is allergic to peanuts."
MOVED_AGAIN = "Update: the weekly design review now happens on Friday at 10am."


class FakeExtractor:
    model = "fake-extractor"

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def propose(self, documents, related):
        self.calls.append((documents, related))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(documents, related) if callable(step) else step


@pytest.fixture
def store():
    s = EngineStore(":memory:", HashingEmbedder())
    yield s
    s.close()


def ingest(store, *docs, task_type="memory"):
    for doc_id, text in docs:
        store.upsert_document(NS, text, doc_id, task_type=task_type)
    return store.pending_documents()


def test_only_memory_task_documents_are_queued(store):
    ingest(store, ("a", REVIEW))
    ingest(store, ("b", COFFEE), task_type="superrag")
    assert [d["id"] for d in store.pending_documents()] == ["a"]
    assert store.dream_counts() == {"pending": 1, "skipped": 1}


def test_instant_documents_jump_the_queue(store):
    store.upsert_document(NS, REVIEW, "a")
    store.upsert_document(NS, COFFEE, "b", dreaming="instant")
    assert [d["id"] for d in store.pending_documents()] == ["b", "a"]


def test_grounded_memory_is_stored_and_ungrounded_ones_are_dropped(store):
    docs = ingest(store, ("a", REVIEW))
    stats = DreamStats()
    apply_proposals(store, NS, docs, [], [
        {"memory": "Priya's weekly design review is on Thursday at 3pm.", "doc": "D1",
         "quote": "from Tuesday to   THURSDAY at 3pm", "confidence": 0.9, "inference": False},
        {"memory": "Priya runs the design team.", "doc": "D1",
         "quote": "Priya leads the design team", "confidence": 0.9, "inference": False},   # not in the text
        {"memory": "The review is weekly.", "doc": "D7", "quote": "weekly", "confidence": 0.9, "inference": False},
        {"memory": "", "doc": "D1", "quote": "weekly", "confidence": 0.9, "inference": False},
    ], "fake", stats)
    assert (stats.proposed, stats.stored, stats.ungrounded) == (4, 1, 3)
    assert stats.grounded_rate == pytest.approx(0.25)
    memory = store.list_memories(NS)["memories"][0]
    assert memory["memory"].startswith("Priya's weekly design review")
    assert memory["sources"] == [{"documentId": "a", "chunkId": "a#0", "quote": "from Tuesday to   THURSDAY at 3pm"}]


def test_insert_memory_refuses_evidence_without_a_chunk(store):
    ingest(store, ("a", REVIEW))
    with pytest.raises(ValueError):
        store.insert_memory(NS, "x", [("a", None, "q")], confidence=1, status="latest", extractor="t")
    with pytest.raises(ValueError):
        store.insert_memory(NS, "x", [], confidence=1, status="latest", extractor="t")


def test_low_confidence_and_weak_inference_become_candidates_not_results(store):
    docs = ingest(store, ("a", COFFEE))
    stats = DreamStats()
    apply_proposals(store, NS, docs, [], [
        {"memory": "Priya likes strong flavours.", "doc": "D1", "quote": "prefers dark roast coffee",
         "confidence": 0.7, "inference": True},
        {"memory": "Priya is allergic to peanuts.", "doc": "D1", "quote": "allergic to peanuts",
         "confidence": 0.4, "inference": False},
    ], "fake", stats)
    assert stats.candidates == 2
    assert memory_search(store, NS, "peanuts allergy", threshold=0)["results"] == []
    found = memory_search(store, NS, "peanuts allergy", threshold=0, include_candidates=True)["results"]
    assert found and found[0]["memory"] == "Priya is allergic to peanuts."


def test_update_supersedes_the_old_memory_in_the_same_namespace(store):
    docs = ingest(store, ("a", REVIEW))
    apply_proposals(store, NS, docs, [], [
        {"memory": "The weekly design review is on Thursday at 3pm.", "doc": "D1",
         "quote": "to Thursday at 3pm", "confidence": 0.9, "inference": False}], "fake", DreamStats())
    store.mark_dreamed(NS, ["a"])
    docs = ingest(store, ("b", MOVED_AGAIN))
    related = related_memories(store, NS, docs)
    assert [m["memory"] for m in related] == ["The weekly design review is on Thursday at 3pm."]
    stats = DreamStats()
    apply_proposals(store, NS, docs, related, [
        {"memory": "The weekly design review is on Friday at 10am.", "doc": "D1",
         "quote": "now happens on Friday at 10am", "confidence": 0.95, "inference": False, "updates": "M1"}],
        "fake", stats)
    assert stats.superseded == 1
    latest = store.list_memories(NS)["memories"]
    assert [m["memory"] for m in latest] == ["The weekly design review is on Friday at 10am."]
    assert latest[0]["supersedes"] == related[0]["id"]
    old = store.list_memories(NS, status="superseded")["memories"]
    assert [m["id"] for m in old] == [related[0]["id"]]
    hits = memory_search(store, NS, "when is the design review", threshold=0)["results"]
    assert [h["memory"] for h in hits] == ["The weekly design review is on Friday at 10am."]


def test_supersede_cannot_cross_namespaces(store):
    store.upsert_document("other", REVIEW, "x")
    victim = store.insert_memory("other", "Review on Thursday.", [("x", "x#0", "Thursday")], confidence=1,
                                 status="latest", extractor="t")
    store.upsert_document(NS, MOVED_AGAIN, "b")
    store.insert_memory(NS, "Review on Friday.", [("b", "b#0", "Friday")], confidence=1, status="latest",
                        extractor="t", supersedes_id=victim)
    assert store.get_memories([victim])[victim]["status"] == "latest"


def test_near_duplicate_adds_evidence_instead_of_a_second_memory(store):
    docs = ingest(store, ("a", COFFEE), ("b", "Reminder: Priya prefers dark roast coffee."))
    stats = DreamStats()
    same = "Priya prefers dark roast coffee."
    apply_proposals(store, NS, docs, [], [
        {"memory": same, "doc": "D1", "quote": "prefers dark roast coffee", "confidence": 0.9, "inference": False},
        {"memory": same, "doc": "D2", "quote": "Priya prefers dark roast", "confidence": 0.9, "inference": False},
    ], "fake", stats)
    assert (stats.stored, stats.merged) == (1, 1)
    memory = store.list_memories(NS)["memories"][0]
    assert sorted(s["documentId"] for s in memory["sources"]) == ["a", "b"]


def test_deleting_the_only_source_forgets_the_memory_but_shared_evidence_survives(store):
    docs = ingest(store, ("a", COFFEE), ("b", "Reminder: Priya prefers dark roast coffee."))
    apply_proposals(store, NS, docs, [], [
        {"memory": "Priya prefers dark roast coffee.", "doc": "D1", "quote": "dark roast", "confidence": 0.9, "inference": False},
        {"memory": "Priya prefers dark roast coffee.", "doc": "D2", "quote": "dark roast", "confidence": 0.9, "inference": False},
        {"memory": "Priya is allergic to peanuts.", "doc": "D1", "quote": "allergic to peanuts", "confidence": 0.9, "inference": False},
    ], "fake", DreamStats())
    store.delete_documents(NS, ["a"])
    latest = {m["memory"]: m for m in store.list_memories(NS)["memories"]}
    assert set(latest) == {"Priya prefers dark roast coffee."}
    assert [s["documentId"] for s in latest["Priya prefers dark roast coffee."]["sources"]] == ["b"]
    assert [m["memory"] for m in store.list_memories(NS, status="forgotten")["memories"]] == ["Priya is allergic to peanuts."]
    assert "Priya is allergic to peanuts." not in [
        h["memory"] for h in memory_search(store, NS, "peanuts", threshold=0, include_candidates=True)["results"]]


def test_editing_a_document_drops_its_stale_evidence_and_requeues_it(store):
    docs = ingest(store, ("a", COFFEE))
    apply_proposals(store, NS, docs, [], [
        {"memory": "Priya is allergic to peanuts.", "doc": "D1", "quote": "allergic to peanuts", "confidence": 0.9, "inference": False},
    ], "fake", DreamStats())
    store.mark_dreamed(NS, ["a"])
    store.upsert_document(NS, "Priya prefers green tea now.", "a")
    assert store.list_memories(NS)["memories"] == []
    assert [d["id"] for d in store.pending_documents()] == ["a"]


def test_secret_looking_memories_are_rejected(store):
    docs = ingest(store, ("a", "The staging token is token=abcd1234efgh5678 for the demo."))
    stats = DreamStats()
    apply_proposals(store, NS, docs, [], [
        {"memory": "Staging uses token=abcd1234efgh5678.", "doc": "D1", "quote": "token=abcd1234efgh5678",
         "confidence": 0.9, "inference": False}], "fake", stats)
    assert (stats.rejected_secret, stats.stored) == (1, 0)


def test_run_dreaming_batches_marks_done_and_respects_budget(store):
    ingest(store, ("a", REVIEW), ("b", COFFEE), ("c", MOVED_AGAIN))

    def ground_first_sentence(documents, related):
        return [{"memory": d["content"], "doc": f"D{i}", "quote": d["content"][:20], "confidence": 0.9,
                 "inference": False} for i, d in enumerate(documents, 1)]

    extractor = FakeExtractor([ground_first_sentence, ground_first_sentence])
    stats = run_dreaming(store, extractor, max_requests=10, daily_budget=100, rpm=0, docs_per_request=2,
                         sleep=lambda s: None)
    assert [len(docs) for docs, _ in extractor.calls] == [2, 1]
    assert (stats.requests, stats.documents, stats.stored, stats.stopped) == (2, 3, 3, "queue empty")
    assert store.dream_counts() == {"done": 3}
    assert store.llm_requests_today("fake-extractor") == 2

    ingest(store, ("d", "Another note about the review room."))
    stats = run_dreaming(store, FakeExtractor([]), max_requests=10, daily_budget=2, rpm=0, sleep=lambda s: None)
    assert (stats.requests, stats.stopped) == (0, "daily budget reached")


def test_transient_errors_retry_and_daily_quota_stops(store):
    ingest(store, ("a", REVIEW))
    extractor = FakeExtractor([TransientError("503"), QuotaExhausted("rpm", per_day=False, retry_after=1), []])
    stats = run_dreaming(store, extractor, max_requests=10, daily_budget=100, rpm=0, sleep=lambda s: None)
    assert (stats.requests, stats.documents) == (3, 1)

    ingest(store, ("b", COFFEE))
    stats = run_dreaming(store, FakeExtractor([QuotaExhausted("day", per_day=True, retry_after=None)]),
                         max_requests=10, daily_budget=100, rpm=0, sleep=lambda s: None)
    assert stats.stopped == "provider daily quota exhausted"
    assert [d["id"] for d in store.pending_documents()] == ["b"]


def test_bad_responses_count_attempts_then_fail_the_documents(store):
    ingest(store, ("a", REVIEW))
    extractor = FakeExtractor([ValueError("garbage")] * 3)
    stats = run_dreaming(store, extractor, max_requests=10, daily_budget=100, rpm=0, sleep=lambda s: None)
    assert stats.failed_batches == 3
    assert store.dream_counts() == {"failed": 1}


def test_prompt_numbers_documents_and_existing_memories():
    prompt = build_prompt([{"content": REVIEW, "metadata": {"created_at": "2026-01-02"}}],
                          [{"memory": "Old fact."}])
    assert "M1: Old fact." in prompt and '<D1 written="2026-01-02">' in prompt


def test_api_memory_search_and_listing(store):
    client = TestClient(create_app(store, api_key="k"))
    auth = {"Authorization": "Bearer k"}
    assert client.post(f"/ns/{NS}/document", json={"content": COFFEE, "id": "a", "taskType": "memory"},
                       headers=auth).status_code == 201
    assert client.post(f"/ns/{NS}/document", json={"content": REVIEW, "id": "r", "taskType": "superrag"},
                       headers=auth).status_code == 201
    assert store.dream_counts() == {"pending": 1, "skipped": 1}
    apply_proposals(store, NS, store.pending_documents(), [], [
        {"memory": "Priya is allergic to peanuts.", "doc": "D1", "quote": "allergic to peanuts", "confidence": 0.9,
         "inference": False}], "fake", DreamStats())
    hits = client.post(f"/ns/{NS}/search", json={"query": "peanut allergy", "searchMode": "memories",
                                                 "include": {"documents": True}}, headers=auth).json()["results"]
    assert hits[0]["memory"] == "Priya is allergic to peanuts."
    assert hits[0]["included"]["document"]["id"] == "a"
    listed = client.post(f"/ns/{NS}/list/memories?page=1&limit=5", headers=auth).json()
    assert listed["pagination"]["totalItems"] == 1
    memory_id = listed["memories"][0]["id"]
    assert client.get(f"/ns/{NS}/memory/{memory_id}", headers=auth).json()["sources"][0]["documentId"] == "a"
    assert client.get(f"/ns/other/memory/{memory_id}", headers=auth).status_code == 404
    assert client.post(f"/ns/{NS}/list/memories", headers={}).status_code == 401
    assert client.get("/healthz").json()["dreaming"] == {"enabled": False}
