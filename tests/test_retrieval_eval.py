"""Phase 0 harness: metrics, the random control, and proof the control check can fail."""

from __future__ import annotations

import json

import pytest

from super_cortex.engine import EngineStore, HashingEmbedder, hybrid_search
from super_cortex.retrieval_eval.dataset import generate_queries, lexical_overlap, looks_secret
from super_cortex.retrieval_eval.metrics import paired_difference_ci, per_query_scores, reciprocal_rank
from super_cortex.retrieval_eval.runner import compare, control_check, evaluate, render_markdown
from super_cortex.retrieval_eval.targets import RandomTarget, dedupe, document_id

TOPICS = ["oracle", "stripe", "sensor", "embedding", "worktree", "billing", "pilot", "ledger",
          "merkle", "gateway", "telemetry", "policy", "quarantine", "spool", "registry", "anvil",
          "render", "supabase", "viewer", "extension", "hermes", "agy", "codex", "shield", "cortex",
          "contract", "token", "schema", "migration", "webhook", "checkout", "deploy", "runtime",
          "session", "profile", "namespace", "scope", "tenant", "invoice", "allowance"]


class EngineTarget:
    def __init__(self, store, name="engine"):
        self.name, self.store = name, store

    def search(self, query, k):
        res = hybrid_search(self.store, "ns", query, limit=k * 3, threshold=0.0)
        return dedupe([r["documentId"] for r in res["results"]])[:k]


class ConstantTarget:
    """A broken engine: same answer for every query."""

    def __init__(self, ids):
        self.name, self.ids = "broken:constant", ids

    def search(self, query, k):
        return self.ids[:k]


@pytest.fixture(scope="module")
def corpus():
    store = EngineStore(":memory:", HashingEmbedder())
    ids = []
    for i, topic in enumerate(TOPICS):
        doc_id = f"d{i}"
        store.upsert_document("ns", f"Notes on the {topic} component: owner team {i}, status green.", doc_id)
        ids.append(doc_id)
    queries = [{"qid": f"q{i}", "query": f"what is the status of {t}", "relevant": [f"d{i}"]} for i, t in enumerate(TOPICS)]
    return store, ids, queries


def test_metrics():
    assert per_query_scores(["a", "b", "c"], {"c"}) == {"recall@1": 0.0, "recall@5": 1.0, "recall@10": 1.0, "mrr@10": pytest.approx(1 / 3)}
    assert reciprocal_rank(["x"] * 10 + ["a"], {"a"}) == 0.0


def test_paired_difference_detects_a_consistent_gap():
    diff, low, high = paired_difference_ci([1.0] * 50, [0.0] * 25 + [1.0] * 25)
    assert diff == pytest.approx(0.5) and low > 0.3 and high <= 0.7


def test_harness_separates_a_real_engine_from_the_random_control(corpus):
    store, ids, queries = corpus
    report = evaluate([EngineTarget(store), RandomTarget(ids)], queries)
    assert report["targets"]["engine"]["summary"]["recall@10"]["mean"] > 0.9
    assert report["targets"]["control:random"]["summary"]["recall@10"]["mean"] < 0.5
    assert control_check(report, "control:random")["discriminates"] is True
    assert "control:random" in render_markdown(report)


def test_control_check_fails_when_a_target_is_no_better_than_random(corpus):
    """The check must be able to fail, or a passing check measures nothing."""
    store, ids, queries = corpus
    report = evaluate([EngineTarget(store), ConstantTarget(ids), RandomTarget(ids)], queries)
    check = control_check(report, "control:random")
    assert check["discriminates"] is False
    assert check["per_target"] == {"engine": True, "broken:constant": False}
    assert compare(report, "engine", "broken:constant")["ci_low"] > 0.5


def test_document_id_reads_supermemory_included_document_not_hit_id():
    item = {"id": "chunkabc", "chunk": "...", "included": {"document": {"id": "mem_1"}}}
    assert document_id(item) == "mem_1"
    assert document_id({"id": "chunkabc"}) is None
    assert document_id({"id": "d#0", "documentId": "d"}) == "d"


def test_generate_queries_resumes_and_maps_numbers_to_documents(tmp_path):
    docs = [{"id": f"d{i}", "content": f"passage {i}"} for i in range(5)]
    prompts = []

    def fake(prompt):
        prompts.append(prompt)
        count = prompt.count("[")
        return json.dumps([{"n": n, "question": f"question {n}?"} for n in range(1, count + 1)])

    out = tmp_path / "q.jsonl"
    first = generate_queries(docs[:3], out, generate=fake, batch_size=2, pause_seconds=0)
    assert [q["relevant"] for q in first] == [["d0"], ["d1"], ["d2"]]
    again = generate_queries(docs, out, generate=fake, batch_size=2, pause_seconds=0)
    assert len(again) == 5 and len(prompts) == 3  # only d3, d4 were generated on the rerun


def test_secret_filter_and_overlap():
    assert looks_secret("key sm_Arh5aaaaaaaaaaaaaaaaaaaaaaaa here")
    assert looks_secret("postgres://user:hunter2pass@db:5432/x")
    assert not looks_secret("ordinary memory about deploys")
    assert lexical_overlap("which port broke the sensor", "the sensor port was wrong") == pytest.approx(2 / 4)
