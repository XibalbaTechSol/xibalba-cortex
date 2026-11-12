from __future__ import annotations

import dataclasses
import random

import pytest

from cortex_nav.canonical import ZERO_ADDRESS, ZERO_SELECTOR, node_id, selector_for
from cortex_nav.graph import Edge, ToolCallGraph


def _edge(frm="state:a", rel="tool:x", to="state:b", **kw) -> Edge:
    base = dict(
        from_node=node_id(frm),
        relation=node_id(rel),
        to_node=node_id(to),
        target=ZERO_ADDRESS,
        target_selector=ZERO_SELECTOR,
        risk_weight_bps=100,
        grounded=True,
        r_task=1.0,
    )
    base.update(kw)
    return Edge(**base)


def test_edge_is_frozen():
    e = _edge()
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.risk_weight_bps = 0  # type: ignore[misc]


def test_toy_graph_loads_with_expected_shape(toy, toy_spec):
    assert len(toy.edges) == 5
    start = node_id(toy_spec["start"])
    assert len(toy.out_edges(start)) == 3
    assert toy.out_edges(node_id("state:quarantine")) == ()
    assert toy.out_edges(node_id("state:never_declared")) == ()
    submit = next(e for e in toy.edges if e.relation == node_id("tool:submit_report"))
    assert submit.target_selector == selector_for("submitReport(bytes32)")
    assert submit.target == bytes.fromhex("00" * 19 + "ca")
    offchain = next(e for e in toy.edges if e.relation == node_id("tool:read_file"))
    assert offchain.target == bytes(20) and offchain.target_selector == ZERO_SELECTOR


def test_ordering_is_independent_of_insertion_order(toy):
    edges = list(toy.edges)
    for seed in range(5):
        shuffled = edges[:]
        random.Random(seed).shuffle(shuffled)
        other = ToolCallGraph(shuffled)
        assert other.edges == toy.edges
        for e in edges:
            assert other.out_edges(e.from_node) == toy.out_edges(e.from_node)


def test_duplicate_leaf_is_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        ToolCallGraph([_edge(), _edge(r_task=2.0, grounded=False)])


def test_forbidden_transitions_cannot_be_encoded_as_negative_weight():
    with pytest.raises(ValueError):
        _edge(r_task=-1.0)
    with pytest.raises(ValueError):
        _edge(r_task=float("nan"))
    with pytest.raises(ValueError):
        _edge(risk_weight_bps=-1)
    with pytest.raises(ValueError):
        _edge(risk_weight_bps=10001)


def test_contains_is_by_exact_leaf(toy):
    real = toy.edges[0]
    assert real in toy
    assert dataclasses.replace(real, risk_weight_bps=real.risk_weight_bps + 1) not in toy
