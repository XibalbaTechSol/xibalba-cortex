"""Upload a local structured Cortex bundle to managed memory in safe, idempotent batches."""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .store import GraphStore
from .structured_bundle import SCHEMA_VERSION, TABLES

def _empty() -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "tables": {name: [] for name in TABLES}}

def _append_sized(result: list[dict[str, object]], payload: dict[str, object], table: str, rows: list[object], *, batch_size: int) -> None:
    for row in rows:
        current = payload["tables"][table]
        candidate = current + [row]
        payload["tables"][table] = candidate
        if len(candidate) > batch_size or len(json.dumps(payload, separators=(",", ":"))) > 52_000:
            payload["tables"][table] = current
            if current:
                result.append(payload)
            payload = _empty()
            payload["tables"][table] = [row]
    if payload["tables"][table]: result.append(payload)

def batches(bundle: dict[str, object], *, batch_size: int = 40) -> list[dict[str, object]]:
    tables = bundle["tables"]
    result: list[dict[str, object]] = []
    sessions = list(tables.get("sessions", []))
    memories = list(tables.get("memories", []))
    sources = {row["id"]: row for row in tables.get("sources", [])}
    events = {}
    for row in tables.get("memory_events", []): events.setdefault(row["memory_id"], []).append(row)
    meta = {}
    for row in tables.get("meta_nodes", []): meta.setdefault(row["memory_id"], []).append(row)
    if sessions:
        for offset in range(0, len(sessions), batch_size):
            payload = _empty()
            payload["tables"]["sessions"] = sessions[offset:offset + batch_size]
            result.append(payload)
    for offset in range(0, len(memories), batch_size):
        chunk = memories[offset:offset + batch_size]
        payload = _empty()
        payload["tables"]["memories"] = chunk
        payload["tables"]["sources"] = [sources[row["source_id"]] for row in chunk]
        payload["tables"]["memory_events"] = [event for row in chunk for event in events.get(row["id"], [])]
        payload["tables"]["meta_nodes"] = [item for row in chunk for item in meta.get(row["id"], [])]
        if len(json.dumps(payload, separators=(",", ":"))) <= 52_000:
            result.append(payload)
        else:
            for row in chunk:
                one = _empty()
                one["tables"]["memories"] = [row]
                one["tables"]["sources"] = [sources[row["source_id"]]]
                one["tables"]["memory_events"] = events.get(row["id"], [])
                one["tables"]["meta_nodes"] = meta.get(row["id"], [])
                result.append(one)
    for table in ("entities", "entity_aliases", "memory_entities", "relations"):
        rows = list(tables.get(table, []))
        for offset in range(0, len(rows), batch_size):
            payload = _empty()
            payload["tables"][table] = rows[offset:offset + batch_size]
            result.append(payload)
    if not result: result.append(_empty())
    return result

def upload(bundle: dict[str, object], *, endpoint: str, api_key: str, batch_size: int = 40) -> dict[str, int]:
    totals: dict[str, int] = {}
    for index, payload in enumerate(batches(bundle, batch_size=batch_size), 1):
        body = json.dumps(payload, separators=(",", ":")).encode()
        request = urllib.request.Request(endpoint.rstrip("/") + "/api/managed/import", data=body, method="POST", headers={
            "Authorization": "Bearer " + api_key, "Content-Type": "application/json", "Idempotency-Key": f"structured-import-{index}",
        })
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"managed import batch {index} failed ({exc.code}): {detail}") from exc
        for table, count in result.get("inserted", {}).items(): totals[table] = totals.get(table, 0) + int(count)
    return totals

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xibalba-cortex-managed-import")
    parser.add_argument("--profile", type=Path, default=Path(os.environ.get("XIBALBA_CORTEX_HOME", "~/.hermes/xibalba-cortex")).expanduser())
    parser.add_argument("--endpoint", default=os.environ.get("CORTEX_MANAGED_URL", "https://cortex-managed-pilot.onrender.com"))
    parser.add_argument("--api-key", default=os.environ.get("CORTEX_API_KEY"))
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--exclude-forgotten", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.api_key and not args.dry_run: parser.error("set CORTEX_API_KEY or pass --api-key")
    store = GraphStore(args.profile, readonly=True)
    try: bundle = store.export_structured_bundle(include_forgotten=not args.exclude_forgotten)
    finally: store.close()
    if args.dry_run:
        print(json.dumps(bundle["counts"], sort_keys=True)); return 0
    print(json.dumps(upload(bundle, endpoint=args.endpoint, api_key=args.api_key, batch_size=max(1, min(args.batch_size, 200))), sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
