import json
from pathlib import Path
import subprocess

from xibalba_cortex.integrity_sdk_outbox_consumer import IntegritySdkOutboxConsumer
from xibalba_cortex.store import GraphStore
from xibalba_cortex.telemetry_outbox import TelemetryOutbox


def _event():
    return {
        "schema_version": "xibalba.runtime.event.v3",
        "event_id": "evt-1",
        "session_id": "session-1",
        "event_type": "post_llm_call",
        "payload": {"runtime": "hermes", "session_id": "session-1"},
    }


def test_integrity_consumer_acknowledges_only_sdk_acceptance(tmp_path: Path):
    outbox = TelemetryOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(_event(), destinations=("integrity_sdk",))

    def accepted(argv, **kwargs):
        assert json.loads(argv[4]) == _event()
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"ok": True}), stderr="")

    result = IntegritySdkOutboxConsumer(outbox, run_fn=accepted).consume()
    assert result == {"claimed": 1, "acked": 1, "retried": 0, "dead_lettered": 0, "errors": []}
    assert {item["status"] for item in outbox.stats()["deliveries"]} == {"acked"}
    outbox.close()


def test_integrity_consumer_retries_reporter_rejection(tmp_path: Path):
    outbox = TelemetryOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(_event(), destinations=("integrity_sdk",))

    def rejected(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"ok": False}), stderr="")

    result = IntegritySdkOutboxConsumer(outbox, run_fn=rejected).consume()
    assert result["claimed"] == 1
    assert result["acked"] == 0
    assert result["retried"] == 1
    assert result["dead_lettered"] == 0
    assert any("did not accept" in item["error"] for item in result["errors"])
    outbox.close()


def test_integrity_consumer_accepts_json_result_after_reporter_diagnostics(tmp_path: Path):
    outbox = TelemetryOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(_event(), destinations=("integrity_sdk",))

    def accepted_with_diagnostics(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 0, stdout="reporter diagnostic\n" + json.dumps({"ok": True}), stderr=""
        )

    result = IntegritySdkOutboxConsumer(outbox, run_fn=accepted_with_diagnostics).consume()
    assert result["acked"] == 1
    assert result["errors"] == []
    outbox.close()


def test_integrity_acceptance_is_recorded_as_cortex_protocol_receipt_before_ack(tmp_path: Path):
    outbox = TelemetryOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(_event(), destinations=("integrity_sdk",))
    store = GraphStore(tmp_path / "graph")

    def accepted(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"ok": True, "receipt": {"accepted": True, "score": 0.91}}),
            stderr="",
        )

    result = IntegritySdkOutboxConsumer(outbox, store=store, run_fn=accepted).consume()
    assert result["acked"] == 1
    memories = store.list_memories(limit=10)
    assert len(memories) == 1
    assert "oracle_telemetry_acceptance" in memories[0]["content"]
    assert memories[0]["evidence_class"] == "protocol_receipt"
    store.close()
    outbox.close()
