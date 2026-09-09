"""One bounded maintenance cycle for all local inference queues.

The cycle is deliberately orchestration-only. Each worker retains responsibility for claiming,
scoping, validating, and completing its own task type; this module makes sure that recovery and
all supported workers are serviced by the same background loop.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import InferenceConfig, load_config
from .combined_worker import process_combined_tasks
from .contradiction_worker import process_contradiction_tasks
from .hermes_worker import process_extraction_tasks
from .metadata_worker import process_metadata_tasks
from .para_worker import process_para_tasks
from .store import GraphStore
from .providers import NativeHarnessInferenceProvider


def _run_safely(function: Any, store: GraphStore, *, limit: int) -> dict[str, Any]:
    try:
        return function(store, limit=limit)
    except Exception as exc:
        # A provider or task-type failure must not starve the other queues. The error remains
        # observable in the cycle result and the next cycle can retry it.
        return {"error": f"{type(exc).__name__}: {exc}"}


def process_inference_cycle(
    store: GraphStore,
    *,
    limit: int = 5,
    max_attempts: int = 3,
    config: InferenceConfig | None = None,
) -> dict[str, Any]:
    """Recover stale work and service every supported inference worker once."""
    policy = config or InferenceConfig(batch_size=limit, max_attempts=max_attempts)
    limit = policy.batch_size if config is not None else limit
    max_attempts = policy.max_attempts if config is not None else max_attempts
    if limit < 1 or max_attempts < 1:
        raise ValueError("limit and max_attempts must be positive")

    if not policy.enabled:
        return {"enabled": False, "recovery": {}, "extraction": {"disabled": True}, "para": {"disabled": True}, "contradiction": {"disabled": True}}

    provider = NativeHarnessInferenceProvider(harness=policy.harness, profile_name=policy.profile_name)
    runner = lambda prompt: provider.infer(prompt, timeout=policy.timeout_seconds)
    enabled = set(policy.task_types)

    try:
        legacy = store.reconcile_legacy_claimed_tasks()
    except Exception as exc:
        legacy = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        expired = store.requeue_expired_inference_tasks(limit=limit, max_attempts=max_attempts)
    except Exception as exc:
        expired = {"error": f"{type(exc).__name__}: {exc}"}

    result: dict[str, Any] = {
        "recovery": {
            "legacy_dead_lettered": int(legacy.get("dead_lettered", 0)),
            **expired,
        },
    }
    jobs: dict[str, Any] = {}
    combined_types = enabled & {"extract_entities", "extract_relations", "classify_para"}
    if config is not None and policy.combined_batching and combined_types:
        jobs["combined"] = lambda: process_combined_tasks(
            store, runner=runner, enabled_task_types=combined_types, limit=limit,
            max_evidence_chars_per_memory=policy.max_evidence_chars_per_memory,
            max_items_per_type=policy.max_items_per_type,
        )
    elif enabled & {"extract_entities", "extract_relations"}:
        jobs["extraction"] = lambda: _run_safely(lambda current, limit: process_extraction_tasks(current, limit=limit, runner=runner), store, limit=limit)
    if "classify_para" in enabled and not (config is not None and policy.combined_batching):
        jobs["para"] = lambda: _run_safely(lambda current, limit: process_para_tasks(current, limit=limit, runner=runner), store, limit=limit)
    if "detect_contradictions" in enabled:
        jobs["contradiction"] = lambda: _run_safely(lambda current, limit: process_contradiction_tasks(current, limit=limit, runner=runner), store, limit=limit)
    if "extract_memory_metadata" in enabled:
        jobs["metadata"] = lambda: _run_safely(lambda current, limit: process_metadata_tasks(current, limit=limit, runner=runner), store, limit=limit)

    if config is None:
        result["extraction"] = _run_safely(process_extraction_tasks, store, limit=limit)
        result["para"] = _run_safely(process_para_tasks, store, limit=limit)
        result["contradiction"] = _run_safely(process_contradiction_tasks, store, limit=limit)
    else:
        cycle_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=min(policy.max_parallel_families, len(jobs) or 1), thread_name_prefix="cortex-inference") as executor:
            futures = {name: executor.submit(job) for name, job in jobs.items()}
            for name in ("combined", "extraction", "para", "contradiction", "metadata"):
                result[name] = futures[name].result() if name in futures else {"disabled": True}
        result["enabled"] = True
        result["duration_seconds"] = round(time.perf_counter() - cycle_started, 3)
        if hasattr(store, "auto_accept_high_confidence_proposals"):
            result["promotion"] = store.auto_accept_high_confidence_proposals(
                threshold=policy.human_review_confidence_threshold,
                task_thresholds=policy.task_confidence_thresholds,
                promotion_policy=policy.promotion_policy,
                contradictions_require_review=policy.contradictions_require_review,
            )
        else:
            result["promotion"] = {"disabled": True}
    return result


def main(argv: Iterable[str] | None = None) -> int:
    """Run the profile-configured inference cycle continuously."""
    parser = argparse.ArgumentParser(description="Run the Cortex profile inference daemon")
    parser.add_argument("--home", required=True, help="Cortex profile home containing config.yaml")
    parser.add_argument("--once", action="store_true", help="Run one bounded cycle and exit")
    args = parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    home = Path(args.home).expanduser()
    store = GraphStore(home=home)
    try:
        while True:
            policy = load_config(home=home).inference
            result = process_inference_cycle(store, config=policy)
            logging.info("inference cycle %s", json.dumps(result, sort_keys=True))
            if args.once:
                return 0 if not any(isinstance(value, dict) and "error" in value for value in result.values()) else 1
            time.sleep(policy.interval_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
