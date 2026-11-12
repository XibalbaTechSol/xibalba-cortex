"""Exhaustive planner over the masked graph.

It enumerates simple paths (no node visited twice) by following `graph.out_edges` only, so
an edge that is not in the graph can never appear in a plan. Exhaustive search is
exponential in the worst case; this is meant for small verified graphs.
"""

from __future__ import annotations

from xibalba_cortex.ais_trajectory_reward import multiplicative_reward

from .graph import Edge, ToolCallGraph
from .reward import RewardFn, path_return


def best_path(
    graph: ToolCallGraph,
    start: bytes,
    goal: bytes,
    *,
    reward: RewardFn = multiplicative_reward,
    base_ais: float = 1000.0,
) -> list[Edge] | None:
    """The simple path from `start` to `goal` with the highest `path_return`.

    Returns `[]` when `start == goal` and `None` when the goal is unreachable. Ties keep the
    path found first in `graph.edges` order, so the result is deterministic.
    """
    start, goal = bytes(start), bytes(goal)
    if start == goal:
        return []
    best: list[Edge] | None = None
    best_return = 0.0
    path: list[Edge] = []
    visited = {start}

    def walk(node: bytes) -> None:
        nonlocal best, best_return
        for edge in graph.out_edges(node):
            if edge.to_node in visited:
                continue
            path.append(edge)
            if edge.to_node == goal:
                value = path_return(path, reward=reward, base_ais=base_ais)
                if best is None or value > best_return:
                    best, best_return = list(path), value
            else:
                visited.add(edge.to_node)
                walk(edge.to_node)
                visited.remove(edge.to_node)
            path.pop()

    walk(start)
    return best
