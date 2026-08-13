from __future__ import annotations

from pathlib import Path

from xibalba_cortex.store import GraphStore


def test_exact_identifier_channel_matches_by_memory_id(tmp_path: Path):
    store = GraphStore(tmp_path)
    target = store.store_memory("A very specific fact about eligibility.", source={"kind": "test"}, status="active")
    store.store_memory("Unrelated content entirely.", source={"kind": "test"}, status="active")

    result = store.hybrid_retrieve(target["id"], limit=5)
    assert result["channel_status"]["exact"] == "matched"
    assert result["results"][0]["id"] == target["id"]


def test_exact_identifier_channel_matches_by_content_hash(tmp_path: Path):
    store = GraphStore(tmp_path)
    target = store.store_memory("A very specific fact about eligibility.", source={"kind": "test"}, status="active")

    result = store.hybrid_retrieve(target["content_hash"], limit=5)
    assert result["channel_status"]["exact"] == "matched"
    assert result["results"][0]["id"] == target["id"]


def test_no_exact_match_reports_no_match_status(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Some content.", source={"kind": "test"}, status="active")
    result = store.hybrid_retrieve("plain text query", limit=5)
    assert result["channel_status"]["exact"] == "no_match"


def test_filters_narrow_results_by_evidence_class(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory(
        "Observed eligibility review event.", source={"kind": "test"}, status="active", evidence_class="observed_event",
    )
    store.store_memory(
        "Summary of eligibility reviews.", source={"kind": "test"}, status="active", evidence_class="summary",
    )

    unfiltered = store.hybrid_retrieve("eligibility review", limit=10)
    assert len(unfiltered["results"]) == 2

    filtered = store.hybrid_retrieve("eligibility review", limit=10, filters={"evidence_class": ["observed_event"]})
    assert all(r["evidence_class"] == "observed_event" for r in filtered["results"])
    assert len(filtered["results"]) == 1


def test_max_per_source_diversity_cap_records_degraded_drops(tmp_path: Path):
    store = GraphStore(tmp_path)
    for i in range(3):
        store.store_memory(f"Repeated topic mention number {i}.", source={"kind": "test", "locator": "same-source"}, status="active")

    result = store.hybrid_retrieve("repeated topic mention", limit=10, max_per_source=1)
    assert len(result["results"]) == 1
    assert len(result["degraded"]) == 2
    assert all(d["reason"] == "diversity" and d["source_group"] == "same-source" for d in result["degraded"])


def test_max_total_chars_budget_records_degraded_drops(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Short budget topic content.", source={"kind": "test"}, status="active")
    store.store_memory("Another short budget topic content entry.", source={"kind": "test"}, status="active")

    result = store.hybrid_retrieve("budget topic content", limit=10, max_total_chars=10)
    assert len(result["results"]) <= 1
    assert any(d["reason"] == "token_budget" for d in result["degraded"])


def test_trace_persists_effective_filters_and_degraded(tmp_path: Path):
    store = GraphStore(tmp_path)
    store.store_memory("Filtered trace content.", source={"kind": "test"}, status="active", evidence_class="observed_event")
    result = store.hybrid_retrieve("filtered trace content", limit=5, filters={"evidence_class": ["observed_event"]})
    trace = store.get_retrieval_trace(result["trace_id"])
    assert trace["filters"] == {"evidence_class": ["observed_event"]}
    assert trace["degraded"] == []
