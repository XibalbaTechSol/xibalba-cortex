import pytest
from super_cortex.deterministic import (
    compute_pagerank,
    compute_shannon_entropy,
    compute_temporal_retention,
    detect_contradictions,
    detect_cycles,
)


def test_contradiction_detection():
    memories = [
        {
            "id": "mem_1",
            "text": "Live trading is strictly prohibited and forbidden for all automated daemons.",
            "epistemic_class": "rule",
            "lifecycle_status": "active",
        },
        {
            "id": "mem_2",
            "text": "Live trading is mandatory and always enabled for automated daemons.",
            "epistemic_class": "rule",
            "lifecycle_status": "active",
        },
        {
            "id": "mem_3",
            "text": "System metrics are collected every 60 seconds.",
            "epistemic_class": "fact",
            "lifecycle_status": "active",
        },
    ]

    relations = [
        {"relation_id": "rel_1", "subject": "Hermes", "predicate": "allows", "object": "trading"},
        {"relation_id": "rel_2", "subject": "Hermes", "predicate": "forbids", "object": "trading"},
    ]

    contradictions = detect_contradictions(memories, relations)
    assert len(contradictions) >= 2

    # Check memory polar clash
    mem_clashes = [c for c in contradictions if c["type"] == "polar_dialectic_opposition"]
    assert len(mem_clashes) == 1
    assert mem_clashes[0]["memory_a"] == "mem_1"
    assert mem_clashes[0]["memory_b"] == "mem_2"

    # Check relation predicate conflict
    rel_clashes = [c for c in contradictions if c["type"] == "relational_predicate_conflict"]
    assert len(rel_clashes) == 1


def test_pagerank_computation():
    nodes = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
    links = [
        {"source": "A", "target": "B"},
        {"source": "B", "target": "C"},
        {"source": "A", "target": "C"},
    ]
    ranks = compute_pagerank(nodes, links)
    assert "C" in ranks
    assert "A" in ranks
    # C should have highest rank because it receives from A and B
    assert ranks["C"] >= ranks["A"]


def test_shannon_entropy():
    text_repetitive = "test test test test test test test"
    text_dense = "Quantum chromodynamics governs strong subatomic interactions between quarks and gluons"
    ent_rep = compute_shannon_entropy(text_repetitive)
    ent_dense = compute_shannon_entropy(text_dense)

    assert ent_dense["entropy_bits"] > ent_rep["entropy_bits"]


def test_temporal_retention():
    now_res = compute_temporal_retention(None, "rule")
    assert now_res["retention_score"] == 1.0
    assert now_res["status"] == "fresh"


def test_cycle_detection():
    nodes = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
    links = [
        {"source": "A", "target": "B"},
        {"source": "B", "target": "C"},
        {"source": "C", "target": "A"},
    ]
    cycles = detect_cycles(nodes, links)
    assert len(cycles) == 1
    assert len(cycles[0]) == 3
