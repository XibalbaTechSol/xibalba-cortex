"""Ranking metrics and a paired bootstrap for comparing two systems on the same queries."""

from __future__ import annotations

import random
from collections.abc import Sequence


def recall_at(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: set[str], k: int = 10) -> float:
    for position, doc_id in enumerate(ranked[:k], 1):
        if doc_id in relevant:
            return 1.0 / position
    return 0.0


def per_query_scores(ranked: Sequence[str], relevant: set[str]) -> dict[str, float]:
    return {
        "recall@1": recall_at(ranked, relevant, 1),
        "recall@5": recall_at(ranked, relevant, 5),
        "recall@10": recall_at(ranked, relevant, 10),
        "mrr@10": reciprocal_rank(ranked, relevant, 10),
    }


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def bootstrap_ci(values: Sequence[float], iterations: int = 2000, seed: int = 7) -> tuple[float, float]:
    """95% percentile bootstrap interval of the mean."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(mean([values[rng.randrange(n)] for _ in range(n)]) for _ in range(iterations))
    return (means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1])


def paired_difference_ci(
    a: Sequence[float], b: Sequence[float], iterations: int = 2000, seed: int = 7
) -> tuple[float, float, float]:
    """Mean of (a - b) over the same queries, with its 95% bootstrap interval.

    Pairing matters: both systems answer the same queries, so per-query differences cancel
    query difficulty, which an unpaired comparison would count as noise.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    diffs = [x - y for x, y in zip(a, b)]
    low, high = bootstrap_ci(diffs, iterations, seed)
    return mean(diffs), low, high
