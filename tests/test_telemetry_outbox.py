from pathlib import Path

import pytest

from xibalba_cortex.telemetry_outbox import (
    OutboxLimitExceeded,
    OutboxStateError,
    TelemetryOutbox,
)


def _event(event_id="event-1"):
    return {
        "schema_version": "xibalba.runtime.event.v3",
        "event_id": event_id,
        "session_id": "session-1",
        "turn_id": "turn-1",
        "invocation_id": "invocation-1",
        "tool_call_id": "tool-1",
        "payload": {"status": "success"},
    }


def test_outbox_default_byte_limit_is_16_mib(tmp_path: Path):
    outbox = TelemetryOutbox(tmp_path / "outbox.sqlite3")
    assert outbox.max_bytes == 16 * 1024 * 1024
    outbox.close()


def test_outbox_persists_one_event_with_independent_destinations(tmp_path: Path):
    path = tmp_path / "outbox.sqlite3"
    outbox = TelemetryOutbox(path, max_events=10, max_bytes=10_000)
    queued = outbox.enqueue(_event())
    assert queued["duplicate"] is False

    cortex = outbox.claim("cortex")
    sdk = outbox.claim("integrity_sdk")
    assert cortex[0]["event_id"] == sdk[0]["event_id"] == "event-1"
    assert cortex[0]["payload_hash"] == sdk[0]["payload_hash"]

    outbox.ack("event-1", "cortex", receipt={"stored": True})
    assert outbox.stats()["events"] == 1
    assert {item["status"] for item in outbox.stats()["deliveries"] if item["destination"] == "cortex"} == {"acked"}
    outbox.close()

    reopened = TelemetryOutbox(path)
    assert reopened.claim("cortex") == []
    sdk_delivery = [
        item for item in reopened.stats()["deliveries"]
        if item["destination"] == "integrity_sdk"
    ]
    assert sdk_delivery == [{"destination": "integrity_sdk", "status": "in_flight", "count": 1}]
    reopened.close()


def test_duplicate_event_is_idempotent_and_payload_collision_is_rejected(tmp_path: Path):
    outbox = TelemetryOutbox(tmp_path / "outbox.sqlite3")
    first = outbox.enqueue(_event())
    duplicate = outbox.enqueue(_event())
    assert first["payload_hash"] == duplicate["payload_hash"]
    assert duplicate["duplicate"] is True

    changed = _event()
    changed["payload"] = {"status": "error"}
    with pytest.raises(OutboxStateError, match="collision"):
        outbox.enqueue(changed)
    outbox.close()


def test_outbox_rejects_resource_limit_without_dropping_existing_data(tmp_path: Path):
    outbox = TelemetryOutbox(tmp_path / "outbox.sqlite3", max_events=1, max_bytes=10_000)
    outbox.enqueue(_event("event-1"))
    with pytest.raises(OutboxLimitExceeded, match="max_events=1"):
        outbox.enqueue(_event("event-2"))
    assert outbox.stats()["events"] == 1
    outbox.close()


def test_terminal_retention_removes_old_acked_rows_but_keeps_pending(tmp_path: Path):
    outbox = TelemetryOutbox(tmp_path / "retention.sqlite3")
    outbox.enqueue(_event("acked"), destinations=("cortex",))
    outbox.enqueue(_event("pending"), destinations=("cortex",))
    claimed = outbox.claim("cortex", limit=1)
    outbox.ack(claimed[0]["event_id"], "cortex", receipt={"stored": True})
    outbox.connection.execute("UPDATE outbox_deliveries SET updated_at=0 WHERE event_id='acked'")

    result = outbox.prune_terminal(now=2 * 86400)

    assert result == {"deliveries": 1, "events": 1}
    assert outbox.connection.execute("SELECT COUNT(*) FROM outbox_events WHERE event_id='pending'").fetchone()[0] == 1
    assert outbox.connection.execute("SELECT COUNT(*) FROM outbox_deliveries WHERE event_id='pending' AND status='pending'").fetchone()[0] == 1
    outbox.close()


def test_failed_delivery_retries_then_dead_letters(tmp_path: Path):
    outbox = TelemetryOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(_event())
    outbox.claim("cortex")
    assert outbox.fail("event-1", "cortex", "temporary failure", max_attempts=2, retry_delay=0) == "retry"
    outbox.claim("cortex")
    assert outbox.fail("event-1", "cortex", "permanent failure", max_attempts=2, retry_delay=0) == "dead_letter"
    assert outbox.claim("cortex") == []
    outbox.close()


def test_event_requires_identity_fields(tmp_path: Path):
    outbox = TelemetryOutbox(tmp_path / "outbox.sqlite3")
    with pytest.raises(ValueError, match="event_id"):
        outbox.enqueue({"schema_version": "xibalba.runtime.event.v3", "session_id": "s"})
    outbox.close()
