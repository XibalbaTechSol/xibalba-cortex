"""Separate-process inference isolation and starvation validation."""
from __future__ import annotations

import argparse
import json
import multiprocessing
import time
from pathlib import Path
from queue import Empty

from .config import load_config
from .store import GraphStore


def _inference_worker(home_value: str, process_index: int, task_count: int, result_queue) -> None:
    home = Path(home_value)
    config = load_config(home=home)
    store = GraphStore(config.storage.home, profile_id=config.profile_id, quotas=config.quotas.as_dict())
    completed: list[str] = []
    latencies: list[float] = []
    worker_id = f"process-{process_index}"
    try:
        for item in range(task_count):
            started = time.perf_counter()
            memory = store.store_memory(
                f"process inference validation profile={config.profile_id} process={process_index} item={item}",
                source={"kind": "tenant-process-inference-validation"},
                status="confirmed",
            )
            task = store.request_inference_task(
                "summarize_session",
                subject_type="memory",
                subject_id=memory["id"],
                input_payload={"validation": True},
                requested_by=worker_id,
            )
            claimed = store.claim_inference_task(task["id"], claimed_by=worker_id)
            finished = store.complete_inference_task(
                task["id"],
                output_payload={"summary": "deterministic validation output"},
                claimed_by=worker_id,
                claim_token=claimed["claim_token"],
            )
            if finished["status"] == "completed":
                completed.append(task["id"])
            latencies.append(time.perf_counter() - started)
        result_queue.put({"profile_id": config.profile_id, "process_index": process_index, "completed": completed, "latencies": latencies, "error": None})
    except BaseException as exc:
        result_queue.put({"profile_id": config.profile_id, "process_index": process_index, "completed": completed, "latencies": latencies, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        store.close()


def validate_process_inference(homes: list[str | Path], *, processes_per_profile: int = 2, tasks_per_process: int = 10, timeout_seconds: float = 60.0) -> dict[str, object]:
    if len(homes) < 2:
        raise ValueError("at least two tenant homes are required")
    if processes_per_profile < 1 or tasks_per_process < 1 or timeout_seconds <= 0:
        raise ValueError("process, task, and timeout values must be positive")
    resolved = [Path(home).expanduser().resolve() for home in homes]
    configs = [load_config(home=home) for home in resolved]
    profile_ids = [config.profile_id for config in configs]
    if len(set(profile_ids)) != len(profile_ids):
        raise ValueError("tenant homes must have unique profile ids")
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    processes = []
    started = time.perf_counter()
    for home in resolved:
        for index in range(processes_per_profile):
            process = context.Process(target=_inference_worker, args=(str(home), index, tasks_per_process, result_queue))
            process.start()
            processes.append(process)
    for process in processes:
        process.join(timeout_seconds)
    timed_out = [process.pid for process in processes if process.is_alive()]
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join(5)
    results = []
    for _ in processes:
        try:
            results.append(result_queue.get(timeout=2))
        except Empty:
            break
    errors = [result["error"] for result in results if result["error"]]
    exit_codes = [process.exitcode for process in processes]
    checks: dict[str, bool] = {
        "all_processes_reported": len(results) == len(processes),
        "no_timeouts": not timed_out,
        "clean_exit_codes": all(code == 0 for code in exit_codes),
        "no_worker_errors": not errors,
    }
    profiles: dict[str, object] = {}
    task_ids = {profile_id: [task_id for result in results if result["profile_id"] == profile_id for task_id in result["completed"]] for profile_id in profile_ids}
    expected = processes_per_profile * tasks_per_process
    for home, config in zip(resolved, configs, strict=True):
        store = GraphStore(config.storage.home, profile_id=config.profile_id, quotas=config.quotas.as_dict())
        try:
            own_ids = task_ids[config.profile_id]
            own_complete = len(own_ids) == expected and all(store.get_inference_task(task_id)["status"] == "completed" for task_id in own_ids)
            foreign_visible = 0
            for other_profile, other_ids in task_ids.items():
                if other_profile == config.profile_id:
                    continue
                for task_id in other_ids:
                    try:
                        store.get_inference_task(task_id)
                    except KeyError:
                        continue
                    foreign_visible += 1
            latencies = sorted(latency for result in results if result["profile_id"] == config.profile_id for latency in result["latencies"])
            p95_index = max(0, int(len(latencies) * 0.95) - 1)
            status = store.status()
            checks[f"{config.profile_id}_all_tasks_completed"] = own_complete
            checks[f"{config.profile_id}_no_cross_profile_tasks"] = foreign_visible == 0
            checks[f"{config.profile_id}_no_starvation"] = len(latencies) == expected
            checks[f"{config.profile_id}_integrity"] = status["integrity_check"] == "ok"
            profiles[config.profile_id] = {"home": str(home), "completed_tasks": len(own_ids), "foreign_tasks_visible": foreign_visible, "latency_p95_seconds": round(latencies[p95_index], 6) if latencies else None, "latency_max_seconds": round(max(latencies), 6) if latencies else None, "integrity_check": status["integrity_check"]}
        finally:
            store.close()
    return {"schema_version": "xibalba.tenant_process_inference_validation.v1", "passed": all(checks.values()), "duration_seconds": round(time.perf_counter() - started, 6), "processes_per_profile": processes_per_profile, "tasks_per_process": tasks_per_process, "profiles": profiles, "checks": checks, "errors": errors, "timed_out_pids": timed_out, "exit_codes": exit_codes, "disclaimer": "Local separate-process inference evidence only; not sustained external load, SLA, HA, or production proof."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", action="append", required=True, dest="homes")
    parser.add_argument("--processes-per-profile", type=int, default=2)
    parser.add_argument("--tasks-per-process", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    report = validate_process_inference(args.homes, processes_per_profile=args.processes_per_profile, tasks_per_process=args.tasks_per_process, timeout_seconds=args.timeout_seconds)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
