from __future__ import annotations

import dataclasses

import pytest

from xibalba_cortex.ais_trajectory_reward import multiplicative_reward

from cortex_nav import reward as nav_reward
from cortex_nav.canonical import node_id
from cortex_nav.graph import ToolCallGraph
from cortex_nav.planner import best_path
from cortex_nav.reward import edge_ais, path_return


def additive_reward(r_task: float, ais: float) -> float:
    """The legacy additive form. Used only as the mutation that must flip the planner."""
    return r_task + 0.5 * ais / 1000.0


def _named_path(toy, toy_spec, name):
    by_relation = {e.relation: e for e in toy.edges}
    return [by_relation[node_id(rel)] for rel in toy_spec["paths"][name]]


def test_default_reward_is_the_repo_wide_multiplicative_reward():
    assert nav_reward.multiplicative_reward is multiplicative_reward
    assert path_return.__kwdefaults__["reward"] is multiplicative_reward
    assert best_path.__kwdefaults__["reward"] is multiplicative_reward


def test_edge_ais_mapping(toy, toy_spec):
    compliant = _named_path(toy, toy_spec, "compliant")
    risky = _named_path(toy, toy_spec, "risky")
    assert [edge_ais(e) for e in compliant] == pytest.approx([990.0, 980.0], abs=1e-9)
    # 6000 bps and ungrounded: 1000 * 0.4 * 0.5; 5000 bps grounded: 1000 * 0.5
    assert [edge_ais(e) for e in risky] == pytest.approx([200.0, 500.0], abs=1e-9)
    assert edge_ais(compliant[0], base_ais=500.0) == pytest.approx(495.0, abs=1e-9)
    assert edge_ais(compliant[0], base_ais=5000.0) == pytest.approx(990.0, abs=1e-9)  # base clamps to 1000
    assert edge_ais(compliant[0], base_ais=float("nan")) == 0.0
    assert edge_ais(compliant[0], base_ais=-5.0) == 0.0


def test_edge_ais_is_strictly_decreasing_in_risk_and_lower_when_ungrounded(toy):
    e = toy.edges[0]
    for grounded in (True, False):
        scores = [edge_ais(dataclasses.replace(e, risk_weight_bps=bps, grounded=grounded)) for bps in range(0, 10001)]
        assert all(hi > lo for hi, lo in zip(scores, scores[1:]))
        assert 0.0 <= scores[-1] and scores[0] <= 1000.0
    for bps in (0, 1, 5000, 9999):
        g = dataclasses.replace(e, risk_weight_bps=bps, grounded=True)
        u = dataclasses.replace(e, risk_weight_bps=bps, grounded=False)
        assert edge_ais(u) < edge_ais(g)


def test_path_return_sums_per_hop_reward(toy, toy_spec):
    compliant = _named_path(toy, toy_spec, "compliant")
    risky = _named_path(toy, toy_spec, "risky")
    assert path_return(compliant) == pytest.approx(1.0 * 0.99 + 1.0 * 0.98, abs=1e-9)
    assert path_return(risky) == pytest.approx(3.0 * 0.2 + 2.0 * 0.5, abs=1e-9)
    assert path_return([]) == 0.0
    assert path_return(risky, reward=additive_reward) == pytest.approx(3.1 + 2.25, abs=1e-9)


def test_fixture_premise_risky_path_has_the_higher_task_reward(toy, toy_spec):
    compliant = _named_path(toy, toy_spec, "compliant")
    risky = _named_path(toy, toy_spec, "risky")
    assert sum(e.r_task for e in risky) > sum(e.r_task for e in compliant)
    for path in (compliant, risky):
        assert path[0].from_node == node_id(toy_spec["start"]) and path[-1].to_node == node_id(toy_spec["goal"])
        assert path[0].to_node == path[1].from_node


def test_best_path_picks_the_compliant_path(toy, toy_spec):
    chosen = best_path(toy, node_id(toy_spec["start"]), node_id(toy_spec["goal"]))
    assert chosen == _named_path(toy, toy_spec, "compliant")


def test_mutation_additive_reward_flips_the_planner_to_the_risky_path(toy, toy_spec):
    """Same graph, same planner, only the reward form swapped: the preference reverses.

    This is what shows the compliant choice above comes from the multiplicative reward
    rather than from how the fixture was tuned.
    """
    chosen = best_path(toy, node_id(toy_spec["start"]), node_id(toy_spec["goal"]), reward=additive_reward)
    assert chosen == _named_path(toy, toy_spec, "risky")
    assert chosen != _named_path(toy, toy_spec, "compliant")


def test_planner_only_traverses_edges_that_exist(toy, toy_spec):
    start, goal = node_id(toy_spec["start"]), node_id(toy_spec["goal"])
    for reward in (multiplicative_reward, additive_reward):
        path = best_path(toy, start, goal, reward=reward)
        assert all(e in toy for e in path)
    # Remove the compliant route's last hop: the planner must fall back, not invent the hop.
    pruned = ToolCallGraph(e for e in toy.edges if e.relation != node_id("tool:submit_report"))
    assert best_path(pruned, start, goal) == _named_path(toy, toy_spec, "risky")
    # Remove both last hops: no route at all.
    cut = ToolCallGraph(e for e in pruned.edges if e.relation != node_id("tool:force_submit"))
    assert best_path(cut, start, goal) is None
    assert best_path(toy, node_id("state:quarantine"), goal) is None
    assert best_path(toy, start, start) == []


def test_planner_terminates_on_cycles_and_keeps_paths_simple(toy, toy_spec):
    from cortex_nav.canonical import ZERO_ADDRESS, ZERO_SELECTOR
    from cortex_nav.graph import Edge

    back = Edge(
        from_node=node_id("state:context_loaded"),
        relation=node_id("tool:reset"),
        to_node=node_id(toy_spec["start"]),
        target=ZERO_ADDRESS,
        target_selector=ZERO_SELECTOR,
        risk_weight_bps=0,
        grounded=True,
        r_task=50.0,
    )
    cyclic = ToolCallGraph([*toy.edges, back])
    path = best_path(cyclic, node_id(toy_spec["start"]), node_id(toy_spec["goal"]))
    visited = [path[0].from_node, *[e.to_node for e in path]]
    assert len(visited) == len(set(visited))
    assert path == _named_path(toy, toy_spec, "compliant")
