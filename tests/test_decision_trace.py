from __future__ import annotations

import pytest

from integrity_sdk.core import DecisionEnvelope, DecisionTraceError, FixtureJevProvider, GENESIS_PARENT
from xibalba_cortex.decision_trace_view import render_decision_trace_html
from xibalba_cortex.jev_gateway import JevGateway
from xibalba_cortex.store import GraphStore
from xibalba_cortex.decision_trace_worker import process_decision_trace_advisories
from integrity_sdk.core import JevAnalysis


def _event(event_id: str, parent: str = GENESIS_PARENT) -> DecisionEnvelope:
    return DecisionEnvelope(
        tenant_id="tenant-a", agent_id="agent-a", trace_id="trace-a", event_id=event_id,
        event_type="policy_decision", timestamp="2026-09-29T12:00:00Z",
        session_id="session-a", invocation_id="inv-a", parent_event_hash=parent,
        policy_ref="hipaa/tool-call", policy_decision="deny", metadata={"risk_hint": "high"},
    )


def test_cortex_persists_redacted_trace_and_jev_projection(tmp_path):
    store = GraphStore(tmp_path)
    store.start_session("session-a", retention_tier="digest", agent_id="agent-a")
    first = _event("event-1")
    stored = store.record_decision_trace_event("session-a", first, advisory=FixtureJevProvider().analyze(first))
    second = _event("event-2", first.event_hash)
    store.record_decision_trace_event("session-a", second)

    projection = store.session_decision_trace("session-a", "trace-a")
    assert projection["valid"] is True
    assert projection["root"]
    assert projection["events"][0]["advisory"]["risk_category"] == "high"
    assert stored["event_hash"] == first.event_hash

    # The second delivery is idempotent and does not add another event.
    assert store.record_decision_trace_event("session-a", first)["event_id"] == "event-1"
    assert len(store.session_decision_trace("session-a", "trace-a")["events"]) == 2


def test_cortex_rejects_missing_parent_and_conflicting_replay(tmp_path):
    store = GraphStore(tmp_path)
    store.start_session("session-a", retention_tier="digest", agent_id="agent-a")
    with pytest.raises(DecisionTraceError, match="parent"):
        store.record_decision_trace_event("session-a", _event("event-1", "0x" + "11" * 32))
    first = _event("event-1")
    store.record_decision_trace_event("session-a", first)
    with pytest.raises(DecisionTraceError, match="different event hash"):
        store.record_decision_trace_event("session-a", DecisionEnvelope(
            tenant_id="tenant-a", agent_id="agent-a", trace_id="trace-a", event_id="event-1",
            event_type="tool_call", timestamp="2026-09-29T12:00:00Z",
        ))


def test_jev_gateway_rejects_provider_binding_mismatch_and_renders_audit_view():
    first = _event("event-1")

    class WrongBinding:
        provider_id = "jev.bad"

        def analyze(self, event):
            from integrity_sdk.core import JevAnalysis
            return JevAnalysis(self.provider_id, "available", observed_event_hash="0x" + "11" * 32)

    advisory = JevGateway(WrongBinding()).analyze(first)
    assert advisory.status == "rejected"

    store_projection = {
        "trace_id": "trace-a", "root": "0x" + "22" * 32, "valid": True,
        "events": [{
            "event_id": "event-1", "parent_event_hash": GENESIS_PARENT,
            "envelope": first.body(),
            "advisory": {"status": "available", "transition_probabilities": {"escalate": 0.65}},
        }],
    }
    html = render_decision_trace_html(store_projection)
    assert "DecisionTrace" in html
    assert "Observational estimate" in html
    assert "Causal claim: <b>false</b>" in html
    assert "0x2222" in html


def test_unavailable_advisory_is_retried_and_attached_to_original_event(tmp_path):
    store = GraphStore(tmp_path)
    store.start_session("session-a", retention_tier="digest", agent_id="agent-a")
    event = _event("retry-event")
    unavailable = JevGateway(type("Down", (), {"provider_id": "jev.test", "analyze": lambda self, e: JevAnalysis("jev.test", "unavailable")})())
    down = unavailable.analyze(event)
    store.record_decision_trace_event("session-a", event, advisory=down)
    assert store.enqueue_decision_trace_advisory("session-a", event) is True
    assert store.enqueue_decision_trace_advisory("session-a", event) is False

    recovered = JevGateway(FixtureJevProvider())
    result = process_decision_trace_advisories(store, recovered, limit=1)
    projection = store.session_decision_trace("session-a", "trace-a")
    assert result == {"processed": 1, "completed": 1, "retried": 0, "failed": 0}
    assert projection["events"][0]["event_hash"] == event.event_hash
    assert projection["events"][0]["advisory"]["status"] == "available"


def test_advisory_retry_is_bounded_and_reclaims_expired_lease(tmp_path):
    store = GraphStore(tmp_path)
    store.start_session("session-a", retention_tier="digest", agent_id="agent-a")
    event = _event("exhaust-event")
    store.record_decision_trace_event("session-a", event)
    store.enqueue_decision_trace_advisory("session-a", event)
    claim = store.claim_decision_trace_advisory_tasks(limit=1)[0]
    with store._lock:
        store._connection.execute("UPDATE decision_trace_advisory_tasks SET claim_until='2000-01-01 00:00:00' WHERE event_hash=?", (event.event_hash,))
    reclaimed = store.claim_decision_trace_advisory_tasks(limit=1)[0]
    assert reclaimed["attempts"] == claim["attempts"] + 1
    store.finish_decision_trace_advisory(event.event_hash, error="provider unavailable", max_attempts=3)
    for _ in range(7):
        with store._lock:
            store._connection.execute("UPDATE decision_trace_advisory_tasks SET retry_after='2000-01-01 00:00:00' WHERE event_hash=?", (event.event_hash,))
        claimed = store.claim_decision_trace_advisory_tasks(limit=1)
        if not claimed:
            break
        store.finish_decision_trace_advisory(event.event_hash, error="provider unavailable", max_attempts=3)
    assert store.get_decision_trace_advisory_task(event.event_hash)["status"] == "failed"
