"""Bounded durable fan-out queue for normalized runtime telemetry.

The outbox is deliberately independent from GraphStore. It provides one durable
copy of a versioned event and one delivery state per consumer, so Cortex and the
Integrity SDK can retry independently without inventing separate event IDs.

This is local evidence plumbing, not an authority boundary: enqueueing proves
only that this profile accepted bytes into its local queue. Consumer receipts
must establish Cortex persistence or Oracle acceptance separately.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


OUTBOX_SCHEMA_VERSION = "xibalba.telemetry.outbox.v1"
EVENT_SCHEMA_VERSION = "xibalba.runtime.event.v3"
DEFAULT_DESTINATIONS = ("cortex", "integrity_sdk")
_TERMINAL = {"acked", "dead_letter"}


class OutboxLimitExceeded(RuntimeError):
    """Raised when a queue resource limit would be exceeded."""


class OutboxStateError(RuntimeError):
    """Raised for invalid queue state transitions."""


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class TelemetryOutbox:
    """A bounded SQLite outbox with independent destination delivery state."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_events: int = 10_000,
        max_bytes: int = 16 * 1024 * 1024,
        busy_timeout_ms: int = 2_000,
    ) -> None:
        if max_events < 1 or max_bytes < 1:
            raise ValueError("outbox limits must be positive")
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.max_events = int(max_events)
        self.max_bytes = int(max_bytes)
        self.connection = sqlite3.connect(self.path, timeout=busy_timeout_ms / 1000, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS outbox_events (
                event_id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_bytes INTEGER NOT NULL CHECK (payload_bytes > 0),
                payload_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox_deliveries (
                event_id TEXT NOT NULL REFERENCES outbox_events(event_id) ON DELETE CASCADE,
                destination TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'in_flight', 'retry', 'acked', 'dead_letter')),
                attempts INTEGER NOT NULL DEFAULT 0,
                available_at REAL NOT NULL,
                lease_until REAL,
                last_error TEXT,
                receipt_json TEXT,
                updated_at REAL NOT NULL,
                PRIMARY KEY (event_id, destination)
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_delivery_claim
                ON outbox_deliveries(destination, status, available_at, updated_at);
            """
        )

    def close(self) -> None:
        self.connection.close()

    def _validate_event(self, event: Mapping[str, Any]) -> tuple[str, str, int, str]:
        required = {"event_id", "schema_version", "session_id"}
        missing = sorted(required - set(event))
        if missing:
            raise ValueError(f"telemetry event missing required fields: {', '.join(missing)}")
        event_id = str(event["event_id"]).strip()
        schema_version = str(event["schema_version"]).strip()
        session_id = str(event["session_id"]).strip()
        if not event_id or not schema_version or not session_id:
            raise ValueError("event_id, schema_version, and session_id must be non-empty")
        payload = _canonical_json(event)
        payload_bytes = len(payload.encode("utf-8"))
        payload_hash = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return event_id, payload, payload_bytes, payload_hash

    def enqueue(
        self,
        event: Mapping[str, Any],
        *,
        destinations: Iterable[str] = DEFAULT_DESTINATIONS,
    ) -> dict[str, Any]:
        event_id, payload, payload_bytes, payload_hash = self._validate_event(event)
        targets = tuple(dict.fromkeys(str(item).strip() for item in destinations if str(item).strip()))
        if not targets:
            raise ValueError("at least one destination is required")
        now = time.time()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT payload_hash FROM outbox_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise OutboxStateError(f"event_id collision with different payload: {event_id}")
                for destination in targets:
                    self.connection.execute(
                        """INSERT OR IGNORE INTO outbox_deliveries
                           (event_id, destination, status, available_at, updated_at)
                           VALUES (?, ?, 'pending', ?, ?)""",
                        (event_id, destination, now, now),
                    )
                self.connection.execute("COMMIT")
                return {"event_id": event_id, "duplicate": True, "payload_hash": payload_hash, "destinations": list(targets)}

            row = self.connection.execute(
                "SELECT COUNT(*) AS events, COALESCE(SUM(payload_bytes), 0) AS bytes FROM outbox_events"
            ).fetchone()
            if int(row["events"]) + 1 > self.max_events:
                raise OutboxLimitExceeded(f"outbox event limit exceeded: max_events={self.max_events}")
            if int(row["bytes"]) + payload_bytes > self.max_bytes:
                raise OutboxLimitExceeded(f"outbox byte limit exceeded: max_bytes={self.max_bytes}")
            self.connection.execute(
                """INSERT INTO outbox_events
                   (event_id, schema_version, payload_json, payload_bytes, payload_hash, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (event_id, str(event["schema_version"]), payload, payload_bytes, payload_hash, now),
            )
            self.connection.executemany(
                """INSERT INTO outbox_deliveries
                   (event_id, destination, status, available_at, updated_at)
                   VALUES (?, ?, 'pending', ?, ?)""",
                [(event_id, destination, now, now) for destination in targets],
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        return {"event_id": event_id, "duplicate": False, "payload_hash": payload_hash, "destinations": list(targets)}

    def claim(self, destination: str, *, limit: int = 50, lease_seconds: int = 60,
              event_id: str | None = None) -> list[dict[str, Any]]:
        destination = str(destination).strip()
        if not destination:
            raise ValueError("destination is required")
        if limit < 1 or lease_seconds < 1:
            raise ValueError("limit and lease_seconds must be positive")
        now = time.time()
        lease_until = now + lease_seconds
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            rows = self.connection.execute(
                """SELECT d.event_id, e.schema_version, e.payload_json, e.payload_hash,
                          d.attempts
                   FROM outbox_deliveries d JOIN outbox_events e ON e.event_id = d.event_id
                   WHERE d.destination = ? AND (? IS NULL OR d.event_id = ?) AND
                         ((d.status IN ('pending', 'retry') AND d.available_at <= ?) OR
                          (d.status = 'in_flight' AND d.lease_until <= ?))
                   ORDER BY d.updated_at, d.event_id LIMIT ?""",
                (destination, event_id, event_id, now, now, min(int(limit), 1000)),
            ).fetchall()
            result = []
            for row in rows:
                attempts = int(row["attempts"]) + 1
                self.connection.execute(
                    """UPDATE outbox_deliveries
                       SET status='in_flight', attempts=?, lease_until=?, updated_at=?
                       WHERE event_id=? AND destination=?""",
                    (attempts, lease_until, now, row["event_id"], destination),
                )
                result.append({
                    "event_id": row["event_id"],
                    "schema_version": row["schema_version"],
                    "payload": json.loads(row["payload_json"]),
                    "payload_hash": row["payload_hash"],
                    "attempts": attempts,
                    "lease_until": lease_until,
                    "destination": destination,
                })
            self.connection.execute("COMMIT")
            return result
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def ack(self, event_id: str, destination: str, *, receipt: Mapping[str, Any] | None = None) -> None:
        now = time.time()
        cursor = self.connection.execute(
            """UPDATE outbox_deliveries SET status='acked', lease_until=NULL,
                      receipt_json=?, last_error=NULL, updated_at=?
               WHERE event_id=? AND destination=? AND status='in_flight'""",
            (json.dumps(dict(receipt or {}), sort_keys=True), now, event_id, destination),
        )
        if cursor.rowcount != 1:
            raise OutboxStateError(f"delivery is not in-flight: {event_id}/{destination}")

    def fail(self, event_id: str, destination: str, error: str, *, max_attempts: int = 8, retry_delay: float = 5.0) -> str:
        if max_attempts < 1 or retry_delay < 0:
            raise ValueError("max_attempts must be positive and retry_delay must be non-negative")
        row = self.connection.execute(
            "SELECT attempts, status FROM outbox_deliveries WHERE event_id=? AND destination=?",
            (event_id, destination),
        ).fetchone()
        if row is None or row["status"] != "in_flight":
            raise OutboxStateError(f"delivery is not in-flight: {event_id}/{destination}")
        status = "dead_letter" if int(row["attempts"]) >= max_attempts else "retry"
        self.connection.execute(
            """UPDATE outbox_deliveries SET status=?, available_at=?, lease_until=NULL,
                      last_error=?, updated_at=? WHERE event_id=? AND destination=?""",
            (status, time.time() + retry_delay, str(error)[:2_000], time.time(), event_id, destination),
        )
        return status

    def stats(self) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT COUNT(*) AS events, COALESCE(SUM(payload_bytes), 0) AS bytes FROM outbox_events"
        ).fetchone()
        deliveries = self.connection.execute(
            "SELECT destination, status, COUNT(*) AS count FROM outbox_deliveries GROUP BY destination, status"
        ).fetchall()
        return {
            "schema_version": OUTBOX_SCHEMA_VERSION,
            "events": int(row["events"]),
            "bytes": int(row["bytes"]),
            "max_events": self.max_events,
            "max_bytes": self.max_bytes,
            "deliveries": [dict(item) for item in deliveries],
        }
