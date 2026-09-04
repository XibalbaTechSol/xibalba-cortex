"""Concurrent isolation validation for provisioned Cortex tenant profiles."""
from __future__ import annotations

import argparse
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import load_config
from .store import GraphStore


def _write_batch(home: Path, marker: str, worker: int, count: int) -> list[str]:
    config = load_config(home=home)
    store = GraphStore(config.storage.home, profile_id=config.profile_id, quotas=config.quotas.as_dict())
    try:
        return [store.store_memory(f"{marker} worker={worker} item={item}", source={"kind": "tenant-load-validation"}, status="confirmed")["id"] for item in range(count)]
    finally:
        store.close()


def validate_profiles(homes: list[str | Path], *, workers_per_profile: int = 2, writes_per_worker: int = 10) -> dict[str, object]:
    if len(homes) < 2:
        raise ValueError("at least two tenant homes are required")
    if workers_per_profile < 1 or writes_per_worker < 1:
        raise ValueError("worker and write counts must be positive")
    resolved = [Path(home).expanduser().resolve() for home in homes]
    configs = [load_config(home=home) for home in resolved]
    profile_ids = [config.profile_id for config in configs]
    if len(set(profile_ids)) != len(profile_ids):
        raise ValueError("tenant homes must have unique profile ids")
    markers = {profile_id: f"cortex-load-{profile_id}-{uuid.uuid4().hex}" for profile_id in profile_ids}
    started = time.perf_counter()
    ids: dict[str, list[str]] = {profile_id: [] for profile_id in profile_ids}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=len(resolved) * workers_per_profile) as pool:
        futures = {}
        for home, profile_id in zip(resolved, profile_ids, strict=True):
            for worker in range(workers_per_profile):
                futures[pool.submit(_write_batch, home, markers[profile_id], worker, writes_per_worker)] = profile_id
        for future in as_completed(futures):
            profile_id = futures[future]
            try:
                ids[profile_id].extend(future.result())
            except Exception as exc:
                errors.append(f"{profile_id}: {type(exc).__name__}: {exc}")
    checks: dict[str, bool] = {"no_write_errors": not errors}
    profiles: dict[str, object] = {}
    expected = workers_per_profile * writes_per_worker
    for home, config in zip(resolved, configs, strict=True):
        store = GraphStore(config.storage.home, profile_id=config.profile_id, quotas=config.quotas.as_dict())
        try:
            own = store.search(markers[config.profile_id], limit=min(expected + 1, 100))
            foreign = []
            for profile_id, marker in markers.items():
                if profile_id != config.profile_id:
                    foreign.extend(store.search(marker, limit=1))
            status = store.status()
            own_ids = set(ids[config.profile_id])
            checks[f"{config.profile_id}_writes_complete"] = len(own_ids) == expected and own_ids == {item["id"] for item in own}
            checks[f"{config.profile_id}_foreign_invisible"] = foreign == []
            checks[f"{config.profile_id}_integrity"] = status["integrity_check"] == "ok"
            profiles[config.profile_id] = {"home": str(home), "writes": len(own_ids), "integrity_check": status["integrity_check"], "foreign_matches": len(foreign)}
        finally:
            store.close()
    return {"schema_version": "xibalba.tenant_load_validation.v1", "passed": all(checks.values()), "duration_seconds": round(time.perf_counter() - started, 6), "workers_per_profile": workers_per_profile, "writes_per_worker": writes_per_worker, "profiles": profiles, "checks": checks, "errors": errors, "disclaimer": "Local concurrent profile-isolation evidence only; not SLA, HA, or external pilot proof."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", action="append", required=True, dest="homes")
    parser.add_argument("--workers-per-profile", type=int, default=2)
    parser.add_argument("--writes-per-worker", type=int, default=10)
    args = parser.parse_args()
    report = validate_profiles(args.homes, workers_per_profile=args.workers_per_profile, writes_per_worker=args.writes_per_worker)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
