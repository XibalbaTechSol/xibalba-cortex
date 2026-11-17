"""Run targets over a query set and report metrics, intervals, and the control check."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .metrics import bootstrap_ci, mean, paired_difference_ci, per_query_scores
from .targets import SearchTarget

METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10")


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def evaluate(targets: list[SearchTarget], queries: list[dict[str, Any]], k: int = 10) -> dict[str, Any]:
    per_target: dict[str, dict[str, Any]] = {}
    for target in targets:
        rows: dict[str, list[float]] = {m: [] for m in METRICS}
        latencies: list[float] = []
        failures = 0
        for q in queries:
            relevant = set(q["relevant"])
            started = time.perf_counter()
            try:
                ranked = target.search(q["query"], k)
            except Exception:
                ranked, failures = [], failures + 1
            latencies.append((time.perf_counter() - started) * 1000)
            for metric, value in per_query_scores(ranked, relevant).items():
                rows[metric].append(value)
        latencies.sort()
        per_target[target.name] = {
            "per_query": rows,
            "summary": {m: {"mean": mean(v), "ci95": bootstrap_ci(v)} for m, v in rows.items()},
            "latency_ms": {"p50": latencies[len(latencies) // 2] if latencies else 0.0,
                           "p95": latencies[int(len(latencies) * 0.95) - 1] if latencies else 0.0},
            "failures": failures,
        }
    return {"queries": len(queries), "k": k, "targets": per_target}


def compare(report: dict[str, Any], candidate: str, baseline: str, metric: str = "recall@10") -> dict[str, float]:
    a = report["targets"][candidate]["per_query"][metric]
    b = report["targets"][baseline]["per_query"][metric]
    diff, low, high = paired_difference_ci(a, b)
    return {"diff": diff, "ci_low": low, "ci_high": high}


def control_check(report: dict[str, Any], control: str, metric: str = "recall@10", margin: float = 0.25) -> dict[str, Any]:
    """The harness is only trusted if every real target beats the control by `margin`.

    A dataset where random ranking scores near the real engines (a tiny corpus, or queries
    that copy their passage) cannot distinguish a good engine from a broken one.
    """
    control_score = report["targets"][control]["summary"][metric]["mean"]
    verdicts = {}
    for name, data in report["targets"].items():
        if name == control:
            continue
        verdicts[name] = data["summary"][metric]["mean"] - control_score >= margin
    return {"control": control_score, "margin": margin, "discriminates": all(verdicts.values()), "per_target": verdicts}


def render_markdown(report: dict[str, Any], comparisons: dict[str, dict[str, float]] | None = None,
                    control: dict[str, Any] | None = None) -> str:
    lines = [f"Queries: {report['queries']}, k = {report['k']}", "",
             "| Target | " + " | ".join(METRICS) + " | p50 ms | p95 ms | failures |",
             "| --- | " + " | ".join("---" for _ in METRICS) + " | --- | --- | --- |"]
    for name, data in report["targets"].items():
        cells = []
        for m in METRICS:
            s = data["summary"][m]
            cells.append(f"{s['mean']:.3f} [{s['ci95'][0]:.3f}, {s['ci95'][1]:.3f}]")
        lines.append(f"| {name} | " + " | ".join(cells)
                     + f" | {data['latency_ms']['p50']:.0f} | {data['latency_ms']['p95']:.0f} | {data['failures']} |")
    if comparisons:
        lines += ["", "| Comparison (recall@10) | difference | 95% CI |", "| --- | --- | --- |"]
        for label, c in comparisons.items():
            lines.append(f"| {label} | {c['diff']:+.3f} | [{c['ci_low']:+.3f}, {c['ci_high']:+.3f}] |")
    if control:
        lines += ["", f"Control recall@10 = {control['control']:.3f}; harness discriminates: {control['discriminates']}"]
    return "\n".join(lines)
