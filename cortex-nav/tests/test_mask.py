from __future__ import annotations

import math

import pytest

from cortex_nav.canonical import node_id
from cortex_nav.mask import action_mask, masked_probabilities


def test_mask_marks_exactly_the_outgoing_edges(toy, toy_spec):
    start = node_id(toy_spec["start"])
    mask = action_mask(toy, start)
    assert len(mask) == len(toy.edges)
    assert [e for e, ok in zip(toy.edges, mask) if ok] == list(toy.out_edges(start))
    assert sum(mask) == 3


def test_masked_probability_is_exactly_zero(toy, toy_spec):
    mask = action_mask(toy, node_id(toy_spec["start"]))
    # Give the masked actions overwhelmingly large logits: they must still get exactly 0.0.
    logits = [0.5 if ok else 1e6 for ok in mask]
    probs = masked_probabilities(logits, mask)
    for p, ok in zip(probs, mask):
        if ok:
            assert p > 0.0
        else:
            assert p == 0.0 and math.copysign(1.0, p) == 1.0
    assert abs(math.fsum(probs) - 1.0) <= 1e-12
    allowed = [p for p, ok in zip(probs, mask) if ok]
    assert max(allowed) - min(allowed) <= 1e-12  # equal logits, equal probability


def test_probabilities_follow_logits_among_allowed_actions():
    probs = masked_probabilities([0.0, math.log(3.0), 50.0], [True, True, False])
    assert probs[2] == 0.0
    assert abs(probs[0] - 0.25) <= 1e-12 and abs(probs[1] - 0.75) <= 1e-12


def test_large_logits_do_not_overflow():
    probs = masked_probabilities([1e308, 1e308, -1e308], [True, True, True])
    assert all(math.isfinite(p) for p in probs)
    assert abs(probs[0] - 0.5) <= 1e-12 and probs[2] == 0.0


def test_dead_end_is_a_clean_zero_distribution(toy):
    dead = node_id("state:quarantine")
    mask = action_mask(toy, dead)
    assert mask == [False] * len(toy.edges)
    probs = masked_probabilities([0.3] * len(mask), mask)
    assert probs == [0.0] * len(mask)  # no NaN, and no uniform fallback over masked entries
    assert masked_probabilities([], []) == []


def test_allowed_minus_infinity_logit_is_zero_and_all_minus_infinity_is_empty():
    assert masked_probabilities([float("-inf"), 0.0], [True, True]) == [0.0, 1.0]
    assert masked_probabilities([float("-inf"), float("-inf")], [True, True]) == [0.0, 0.0]


def test_bad_inputs_are_rejected():
    with pytest.raises(ValueError):
        masked_probabilities([0.0], [True, False])
    with pytest.raises(ValueError):
        masked_probabilities([float("nan"), 0.0], [True, True])
    with pytest.raises(ValueError):
        masked_probabilities([float("inf"), 0.0], [True, True])
    # A NaN under the mask is never read.
    assert masked_probabilities([float("nan"), 0.0], [False, True]) == [0.0, 1.0]


def test_action_index_maps_to_the_same_edge_across_calls(toy, toy_spec):
    start = node_id(toy_spec["start"])
    first = [(i, toy.edges[i].leaf) for i, ok in enumerate(action_mask(toy, start)) if ok]
    for _ in range(3):
        again = [(i, toy.edges[i].leaf) for i, ok in enumerate(action_mask(toy, start)) if ok]
        assert again == first
    # ...and across an independently rebuilt graph with a different insertion order.
    from cortex_nav.graph import ToolCallGraph

    rebuilt = ToolCallGraph(reversed(toy.edges))
    assert [(i, rebuilt.edges[i].leaf) for i, ok in enumerate(action_mask(rebuilt, start)) if ok] == first
