"""Separate-process inference isolation and starvation validation."""
from __future__ import annotations

import argparse
import json
import multiprocessing
import tempfile
import time
from pathlib import Path
from queue import Empty

from .config import load_config
from .store import GraphStore


def _write_heartbeat(heartbeat_path: Path | None, *, item: int, op: str) -> None:
    """Best-effort, out-of-band progress marker written to disk after every
    sub-operation. Exists so a hung worker's exact stuck point (which task
    item, which of the four store calls) is directly observable from outside
    the process -- e.g. via multiprocessing.Queue -- goes silent the moment a
    worker blocks, which is exactly the failure mode this validation exists to
    catch. Deliberately swallows its own I/O errors: heartbeat writes must
    never become a second way for this worker to fail."""
    if heartbeat_path is None:
        return
    try:
        heartbeat_path.write_text(json.dumps({"item": item, "op": op, "ts": time.time()}))
    except OSError:
        pass


def _inference_worker(home_value: str, process_index: int, task_count: int, result_queue, heartbeat_path: str | None = None) -> None:
    home = Path(home_value)
    hb = Path(heartbeat_path) if heartbeat_path else None
    config = load_config(home=home)
    store = GraphStore(config.storage.home, profile_id=config.profile_id, quotas=config.quotas.as_dict())
    completed: list[str] = []
    latencies: list[float] = []
    worker_id = f"process-{process_index}"
    try:
        for item in range(task_count):
            started = time.perf_counter()
            _write_heartbeat(hb, item=item, op="store_memory:start")
            memory = store.store_memory(
                f"process inference validation profile={config.profile_id} process={process_index} item={item}",
                source={"kind": "tenant-process-inference-validation"},
                status="confirmed",
            )
            _write_heartbeat(hb, item=item, op="request_inference_task:start")
            task = store.request_inference_task(
                "summarize_session",
                subject_type="memory",
                subject_id=memory["id"],
                input_payload={"validation": True},
                requested_by=worker_id,
            )
            _write_heartbeat(hb, item=item, op="claim_inference_task:start")
            claimed = store.claim_inference_task(task["id"], claimed_by=worker_id)
            _write_heartbeat(hb, item=item, op="complete_inference_task:start")
            finished = store.complete_inference_task(
                task["id"],
                output_payload={"summary": "deterministic validation output"},
                claimed_by=worker_id,
                claim_token=claimed["claim_token"],
            )
            if finished["status"] == "completed":
                completed.append(task["id"])
            latencies.append(time.perf_counter() - started)
            _write_heartbeat(hb, item=item, op="item:done")
        _write_heartbeat(hb, item=task_count - 1, op="queue_put:start")
        result_queue.put({"profile_id": config.profile_id, "process_index": process_index, "completed": completed, "latencies": latencies, "error": None})
        _write_heartbeat(hb, item=task_count - 1, op="queue_put:done")
    except BaseException as exc:
        result_queue.put({"profile_id": config.profile_id, "process_index": process_index, "completed": completed, "latencies": latencies, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        _write_heartbeat(hb, item=task_count - 1, op="store_close:start")
        store.close()
        _write_heartbeat(hb, item=task_count - 1, op="store_close:done")


def validate_process_inference(homes: list[str | Path], *, processes_per_profile: int = 2, tasks_per_process: int = 10, timeout_seconds: float = 60.0, heartbeat_dir: str | Path | None = None) -> dict[str, object]:
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

    heartbeat_root: Path | None = None
    heartbeat_cleanup = None
    if heartbeat_dir is not None:
        heartbeat_root = Path(heartbeat_dir).expanduser().resolve()
        heartbeat_root.mkdir(parents=True, exist_ok=True)
    else:
        # Always on unless the caller opts out: heartbeats are cheap (one small
        # file write per sub-operation) and are the only way to see WHERE a
        # hung worker is stuck rather than just THAT it's stuck.
        tmp_ctx = tempfile.TemporaryDirectory(prefix="xibalba-cortex-inference-heartbeat-")
        heartbeat_root = Path(tmp_ctx.name)
        heartbeat_cleanup = tmp_ctx

    processes = []
    heartbeat_paths: dict[int, Path] = {}
    started = time.perf_counter()
    for home, config in zip(resolved, configs, strict=True):
        for index in range(processes_per_profile):
            hb_path = heartbeat_root / f"{config.profile_id}-{index}.json"
            process = context.Process(
                target=_inference_worker,
                args=(str(home), index, tasks_per_process, result_queue, str(hb_path)),
            )
            process.start()
            processes.append(process)
            heartbeat_paths[process.pid] = hb_path

    deadline = time.monotonic() + timeout_seconds

    # Real, root-caused fix for a real deadlock: this used to join every
    # process FIRST and only drain result_queue afterward. multiprocessing.Queue
    # writes through a background feeder thread into an OS pipe with bounded
    # buffer capacity; the Python docs explicitly warn that a child which has
    # put() a large-enough payload will not finish exiting until that data is
    # flushed, so joining before draining can deadlock the exact way observed
    # here: process.join(timeout_seconds) used to also be called per-process
    # sequentially (a second, now-separately-fixed bug, see below), and with
    # heartbeat instrumentation added to prove it, every one of 8 workers at
    # 200 tasks/process reached "store_close:done" -- ALL application work
    # completed -- while 2-3 of their underlying OS processes remained alive
    # for the full timeout, with one caught mid-exit showing a live
    # `QueueFeederThread`, exactly the pipe-flush-blocks-exit scenario the
    # docs name. Draining the queue first (which does not require the
    # producer to have exited) unblocks that feeder thread, so the join below
    # becomes fast once a process has actually finished its work.
    results = []
    while len(results) < len(processes) and time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            results.append(result_queue.get(timeout=min(1.0, remaining) or 0.01))
        except Empty:
            if remaining <= 0:
                break

    # Second, independently real bug, fixed the same way regardless of the
    # queue-drain-order fix above: this used to be `for process in processes:
    # process.join(timeout_seconds)` -- each process got its OWN full
    # timeout_seconds budget, sequentially. A single slow process at the
    # front of the list could burn the entire budget before the loop ever
    # reached its already-finished siblings, masking real completion and
    # making "N processes hung" indistinguishable from "1 process hung,
    # N-1 finished and are waiting to be reaped." Share one deadline instead.
    for process in processes:
        remaining = max(0.0, deadline - time.monotonic())
        process.join(remaining)
    timed_out = [process.pid for process in processes if process.is_alive()]
    timed_out_heartbeats: dict[str, object] = {}
    for pid in timed_out:
        hb_path = heartbeat_paths.get(pid)
        try:
            timed_out_heartbeats[str(pid)] = json.loads(hb_path.read_text()) if hb_path and hb_path.exists() else None
        except (OSError, json.JSONDecodeError):
            timed_out_heartbeats[str(pid)] = None
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join(5)
    # A process whose join() above timed out but had, in fact, already put
    # its result before getting stuck in exit teardown may still have a
    # result sitting in the queue -- drain any remainder now that everyone
    # has been joined or terminated, so a slow-to-exit-but-actually-done
    # worker isn't misreported as having produced no result at all.
    while len(results) < len(processes):
        try:
            results.append(result_queue.get(timeout=2))
        except Empty:
            break
    if heartbeat_cleanup is not None:
        heartbeat_cleanup.cleanup()
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
    return {"schema_version": "xibalba.tenant_process_inference_validation.v1", "passed": all(checks.values()), "duration_seconds": round(time.perf_counter() - started, 6), "processes_per_profile": processes_per_profile, "tasks_per_process": tasks_per_process, "profiles": profiles, "checks": checks, "errors": errors, "timed_out_pids": timed_out, "timed_out_heartbeats": timed_out_heartbeats, "exit_codes": exit_codes, "disclaimer": "Local separate-process inference evidence only; not sustained external load, SLA, HA, or production proof."}


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
