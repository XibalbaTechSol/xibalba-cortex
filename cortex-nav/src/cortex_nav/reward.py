"""Per-edge integrity score and path return.

There is one reward function for the whole repository, `multiplicative_reward` in
`xibalba_cortex.ais_trajectory_reward`. It is imported here, never re-implemented.

`edge_ais` mapping (exact):

    edge_ais = clamp(base_ais, 0, 1000) * (10000 - risk_weight_bps) / 10000 * g
    g = 1.0 if the edge is grounded, 0.5 if it is not

It is strictly decreasing in `risk_weight_bps` over [0, 10000] for any positive base, reaches
0 at 10000 bps, and an ungrounded edge scores exactly half of the grounded edge with the same
risk weight. A base that is NaN, infinite or not positive gives 0.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import math

from xibalba_cortex.ais_trajectory_reward import multiplicative_reward

from .graph import MAX_RISK_WEIGHT_BPS, Edge

UNGROUNDED_FACTOR = 0.5

RewardFn = Callable[[float, float], float]


def edge_ais(edge: Edge, base_ais: float = 1000.0) -> float:
    """Integrity score in [0, 1000] for taking `edge`. See the module docstring for the mapping."""
    base = float(base_ais)
    if not math.isfinite(base) or base <= 0.0:
        return 0.0
    base = min(base, 1000.0)
    score = base * (MAX_RISK_WEIGHT_BPS - edge.risk_weight_bps) / MAX_RISK_WEIGHT_BPS
    return score if edge.grounded else score * UNGROUNDED_FACTOR


def path_return(
    edges: Iterable[Edge],
    *,
    reward: RewardFn = multiplicative_reward,
    base_ais: float = 1000.0,
) -> float:
    """Sum over hops of `reward(edge.r_task, edge_ais(edge, base_ais))`."""
    return math.fsum(reward(edge.r_task, edge_ais(edge, base_ais)) for edge in edges)
