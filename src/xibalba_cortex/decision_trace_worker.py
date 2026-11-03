"""Bounded retry worker for unavailable DecisionTrace Jev annotations."""
from __future__ import annotations

from typing import Any

from integrity_sdk.core.decision_trace import DecisionEnvelope

from .jev_gateway import JevGateway
from .store import GraphStore


def process_decision_trace_advisories(
    store: GraphStore, gateway: JevGateway, *, limit: int = 10, max_attempts: int = 8,
) -> dict[str, int]:
    """Retry due analyses and attach only hash-bound available projections."""
    processed = completed = retried = failed = 0
    for task in store.claim_decision_trace_advisory_tasks(limit=limit):
        processed += 1
        event_hash = str(task["event_hash"])
        try:
            envelope_body = dict(task["envelope"])
            envelope_body.pop("envelope_version", None)
            envelope = DecisionEnvelope(**envelope_body)
            advisory = gateway.analyze(envelope)
            store.finish_decision_trace_advisory(
                event_hash, advisory=advisory, max_attempts=max_attempts,
            )
            if advisory.status == "available" and advisory.observed_event_hash == event_hash:
                completed += 1
            elif int(task["attempts"]) >= max_attempts:
                failed += 1
            else:
                retried += 1
        except Exception as exc:  # provider and persistence outages are isolated per task
            try:
                store.finish_decision_trace_advisory(
                    event_hash, error=f"{type(exc).__name__}: {exc}", max_attempts=max_attempts,
                )
            except Exception:
                failed += 1
            else:
                retried += 1
    return {"processed": processed, "completed": completed, "retried": retried, "failed": failed}
