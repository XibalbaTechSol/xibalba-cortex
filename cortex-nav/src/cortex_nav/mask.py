"""Action masking over the graph's fixed action space (`graph.edges`).

An action that is not an outgoing edge of the current node gets probability exactly `0.0`:
it is never exponentiated, so no logit, however large, can leak mass onto it.
"""

from __future__ import annotations

from collections.abc import Sequence
import math

from .graph import ToolCallGraph


def action_mask(graph: ToolCallGraph, node: bytes) -> list[bool]:
    """One flag per entry of `graph.edges`: `True` iff that edge leaves `node`."""
    node = bytes(node)
    return [edge.from_node == node for edge in graph.edges]


def masked_probabilities(logits: Sequence[float], mask: Sequence[bool]) -> list[float]:
    """Softmax over the allowed actions only.

    Masked entries are exactly `0.0` and their logits are never read. When nothing is
    allowed (a dead end), or every allowed logit is `-inf`, the result is all zeros: an
    empty distribution, not a uniform one and not NaN. An allowed logit of NaN or `+inf`
    is an error.
    """
    if len(logits) != len(mask):
        raise ValueError("logits and mask must have the same length")
    probs = [0.0] * len(mask)
    allowed = [i for i, ok in enumerate(mask) if ok]
    if not allowed:
        return probs
    values = {i: float(logits[i]) for i in allowed}
    if any(math.isnan(v) or v == math.inf for v in values.values()):
        raise ValueError("an allowed logit must be finite or -inf")
    top = max(values.values())
    if top == -math.inf:
        return probs
    weights = {i: math.exp(v - top) for i, v in values.items()}
    total = math.fsum(weights.values())
    for i, w in weights.items():
        probs[i] = w / total
    return probs
