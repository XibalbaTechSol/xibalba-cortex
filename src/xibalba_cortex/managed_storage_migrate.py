"""Preview, import, or roll back a Cortex managed SQLite control-plane batch.

The legacy SQLite file is read-only. Tenant GraphStore files remain on the
Render persistent disk; this command migrates only control-plane tables.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .managed.storage import SupabaseManagedDbFactory


class MigrationConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class TableSpec:
    name: str
    keys: tuple[str, ...]
    source_columns: tuple[str, ...]

    def values(self, row: sqlite3.Row) -> dict[str, Any]:
        values = {name: row[name] for name in self.source_columns}
        if self.name == "tenants":
            values["owner_user_id"] = None
            values["updated_at"] = values["created_at"]
        return values


TABLES = (
    TableSpec("tenants", ("id",), ("id", "owner_account_id", "plan", "status", "customer_id",
                                    "subscription_id", "period_end", "cancel_at_period_end", "created_at")),
    TableSpec("usage", ("tenant_id", "month", "meter"), ("tenant_id", "month", "meter", "amount")),
    TableSpec("operations", ("tenant_id", "request_key"), ("tenant_id", "request_key", "fingerprint")),
    TableSpec("stripe_events", ("id",), ("id", "processed_at")),
    TableSpec("checkout_requests", ("tenant_id",), ("tenant_id", "plan", "attempt", "checkout_id", "url")),
    TableSpec("email_verifications", ("token_hash",), ("token_hash", "account_id", "expires_at")),
)


def _source_rows(connection: sqlite3.Connection, spec: TableSpec) -> list[dict[str, Any]]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (spec.name,)
    ).fetchone()
    if not exists:
        return []
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({spec.name})")}
    missing = set(spec.source_columns) - columns
    if missing:
        raise ValueError(f"SQLite table {spec.name} is missing required columns: {sorted(missing)}")
    return [spec.values(row) for row in connection.execute(f"SELECT * FROM {spec.name}")]


def _where(spec: TableSpec) -> str:
    return " AND ".join(f"{key}=?" for key in spec.keys)


def _key(values: dict[str, Any], spec: TableSpec) -> dict[str, Any]:
    return {name: values[name] for name in spec.keys}


def _fetch_target(db, spec: TableSpec, key: dict[str, Any]):
    row = db.execute(f"SELECT * FROM {spec.name} WHERE {_where(spec)}",
                     tuple(key[name] for name in spec.keys)).fetchone()
    return dict(row) if row is not None else None


def _digest(row: dict[str, Any]) -> str:
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _conflicts(source: dict[str, Any], target: dict[str, Any] | None) -> bool:
    return target is not None and any(target.get(name) != value for name, value in source.items())


def migrate_storage(source_path: Path, db_factory, *, batch_id: str, action: str) -> dict[str, Any]:
    if not batch_id.strip():
        raise ValueError("batch_id is required")
    if action not in {"preview", "apply", "rollback"}:
        raise ValueError("action must be preview, apply, or rollback")
    source_path = source_path.expanduser().resolve()
    if action != "rollback" and not source_path.is_file():
        raise FileNotFoundError(f"SQLite managed database not found: {source_path}")

    if action == "rollback":
        return _rollback(db_factory, batch_id)

    source = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True, timeout=30)
    source.row_factory = sqlite3.Row
    try:
        source.execute("BEGIN")
        rows = [(spec, row) for spec in TABLES for row in _source_rows(source, spec)]
        with db_factory(write=action == "apply") as db:
            if action == "apply":
                db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (batch_id,))
            planned = []
            conflicts = []
            counts = {spec.name: {"source": 0, "already_present": 0, "to_import": 0} for spec in TABLES}
            for spec, values in rows:
                counts[spec.name]["source"] += 1
                key = _key(values, spec)
                target = _fetch_target(db, spec, key)
                if target is None:
                    counts[spec.name]["to_import"] += 1
                    planned.append((spec, values, key, None))
                elif _conflicts(values, target):
                    conflicts.append({"table": spec.name, "key": key})
                    planned.append((spec, values, key, target))
                else:
                    counts[spec.name]["already_present"] += 1
                    planned.append((spec, values, key, target))
            if conflicts:
                return {"batch_id": batch_id, "action": action, "conflicts": conflicts, "tables": counts}
            if action == "apply":
                for spec, values, key, target in planned:
                    if target is not None:
                        continue
                    columns = tuple(values)
                    placeholders = ",".join("?" for _ in columns)
                    db.execute(f"INSERT INTO {spec.name} ({','.join(columns)}) VALUES ({placeholders})",
                               tuple(values[name] for name in columns))
                    state = _fetch_target(db, spec, key)
                    db.execute(
                        "INSERT INTO managed_storage_migration_rows(batch_id,table_name,row_key,row_digest) "
                        "VALUES(?,?,?::jsonb,?)",
                        (batch_id, spec.name, json.dumps(key, sort_keys=True), _digest(state)),
                    )
        return {"batch_id": batch_id, "action": action, "tables": counts}
    finally:
        source.rollback()
        source.close()


def _rollback(db_factory, batch_id: str) -> dict[str, Any]:
    spec_by_name = {spec.name: spec for spec in TABLES}
    with db_factory(write=True) as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (batch_id,))
        rows = db.execute(
            "SELECT table_name,row_key,row_digest FROM managed_storage_migration_rows "
            "WHERE batch_id=?", (batch_id,)
        ).fetchall()
        planned = []
        for row in rows:
            table_name = row["table_name"]
            spec = spec_by_name.get(table_name)
            if spec is None:
                raise MigrationConflict(f"batch {batch_id} contains an unknown table")
            key = row["row_key"]
            state = _fetch_target(db, spec, key)
            if state is not None and _digest(state) != row["row_digest"]:
                raise MigrationConflict(
                    f"cannot roll back modified {table_name} row; batch left intact"
                )
            planned.append((spec, key, state))
        # Child tables first so tenant foreign keys never cascade away unrelated data.
        order = {spec.name: index for index, spec in enumerate(reversed(TABLES))}
        planned.sort(key=lambda item: order[item[0].name])
        for spec, key, state in planned:
            if state is not None:
                db.execute(f"DELETE FROM {spec.name} WHERE {_where(spec)}",
                           tuple(key[name] for name in spec.keys))
        db.execute("DELETE FROM managed_storage_migration_rows WHERE batch_id=?", (batch_id,))
    return {"batch_id": batch_id, "action": "rollback", "rolled_back": len(planned)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply", "rollback"))
    parser.add_argument("--batch", required=True)
    parser.add_argument("--source", type=Path,
                        default=Path(os.environ.get("CORTEX_MANAGED_HOME", "/data/cortex-managed")) / "managed.sqlite3")
    args = parser.parse_args(argv)
    dsn = os.environ.get("CORTEX_MANAGED_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("CORTEX_MANAGED_DATABASE_URL must be set")
    try:
        result = migrate_storage(args.source, SupabaseManagedDbFactory(dsn), batch_id=args.batch, action=args.action)
    except (MigrationConflict, ValueError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if not result.get("conflicts") else 2


if __name__ == "__main__":
    raise SystemExit(main())
