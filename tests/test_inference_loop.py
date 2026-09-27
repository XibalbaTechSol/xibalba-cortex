from __future__ import annotations

from xibalba_cortex.inference_loop import process_inference_cycle
from xibalba_cortex.config import InferenceConfig
import threading


def test_cycle_reconciles_claims_and_services_all_inference_workers(monkeypatch):
    calls: list[tuple[str, int]] = []

    class Store:
        def reconcile_legacy_claimed_tasks(self):
            calls.append(("legacy", 0))
            return {"dead_lettered": 2}

        def requeue_expired_inference_tasks(self, *, limit, max_attempts):
            calls.append(("requeue", limit))
            assert max_attempts == 3
            return {"expired": 1, "requeued": 1, "failed": 0, "dead_lettered": 0}

    monkeypatch.setattr(
        "xibalba_cortex.inference_loop.process_extraction_tasks",
        lambda store, limit: calls.append(("extraction", limit)) or {"processed": 1, "completed": 1, "failed": 0},
    )
    monkeypatch.setattr(
        "xibalba_cortex.inference_loop.process_para_tasks",
        lambda store, limit: calls.append(("para", limit)) or {"processed": 1, "completed": 1, "failed": 0},
    )
    monkeypatch.setattr(
        "xibalba_cortex.inference_loop.process_contradiction_tasks",
        lambda store, limit: calls.append(("contradiction", limit)) or {"processed": 1, "completed": 1, "failed": 0},
    )

    result = process_inference_cycle(Store(), limit=5)

    assert calls == [("legacy", 0), ("requeue", 5), ("extraction", 5), ("para", 5), ("contradiction", 5)]
    assert result == {
        "backfill": {"classifications_queued": 0, "session_summaries_queued": 0},
        "recovery": {"legacy_dead_lettered": 2, "expired": 1, "requeued": 1, "failed": 0, "dead_lettered": 0},
        "extraction": {"processed": 1, "completed": 1, "failed": 0},
        "para": {"processed": 1, "completed": 1, "failed": 0},
        "contradiction": {"processed": 1, "completed": 1, "failed": 0},
    }


def test_cycle_obeys_disabled_task_families(monkeypatch):
    class Store:
        def reconcile_legacy_claimed_tasks(self): return {"dead_lettered": 0}
        def requeue_expired_inference_tasks(self, *, limit, max_attempts): return {"expired": 0, "requeued": 0, "failed": 0, "dead_lettered": 0}

    monkeypatch.setattr("xibalba_cortex.inference_loop.process_extraction_tasks", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("disabled")))
    monkeypatch.setattr("xibalba_cortex.inference_loop.process_contradiction_tasks", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("disabled")))
    monkeypatch.setattr("xibalba_cortex.inference_loop.process_para_tasks", lambda store, **kwargs: {"processed": 1, "completed": 1, "failed": 0})

    result = process_inference_cycle(Store(), config=InferenceConfig(task_types=("classify_para",), combined_batching=False))
    assert result["para"]["completed"] == 1
    assert result["extraction"] == {"disabled": True}
    assert result["contradiction"] == {"disabled": True}


def test_configured_cycle_runs_enabled_worker_families_on_parallel_threads(monkeypatch):
    threads: set[str] = set()
    barrier = threading.Barrier(2)

    class Store:
        def reconcile_legacy_claimed_tasks(self): return {"dead_lettered": 0}
        def requeue_expired_inference_tasks(self, *, limit, max_attempts): return {"expired": 0, "requeued": 0, "failed": 0, "dead_lettered": 0}

    def worker(*args, **kwargs):
        threads.add(threading.current_thread().name)
        barrier.wait(timeout=2)
        return {"processed": 1, "completed": 1, "failed": 0}

    monkeypatch.setattr("xibalba_cortex.inference_loop.process_extraction_tasks", worker)
    monkeypatch.setattr("xibalba_cortex.inference_loop.process_para_tasks", worker)
    result = process_inference_cycle(Store(), config=InferenceConfig(task_types=("extract_entities", "classify_para"), max_parallel_families=2, combined_batching=False))
    assert result["extraction"]["completed"] == result["para"]["completed"] == 1
    assert len(threads) == 2
    assert result["duration_seconds"] >= 0
