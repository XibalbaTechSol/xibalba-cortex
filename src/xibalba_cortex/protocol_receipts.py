"""Cortex-side storage for Oracle protocol receipts.

Only acceptance/score/attestation metadata is stored here. The Oracle receipt
is not treated as a replacement for Cortex's raw session or provenance record.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .store import GraphStore


def record_oracle_receipt(
    store: GraphStore,
    *,
    event: Mapping[str, Any],
    reporter_result: Mapping[str, Any],
) -> dict[str, Any]:
    if reporter_result.get("accepted") is not True:
        raise ValueError("only accepted reporter results can become Oracle receipt evidence")
    receipt = reporter_result.get("receipt")
    if not isinstance(receipt, Mapping):
        raise ValueError("accepted reporter result has no structured Oracle receipt")
    receipt_payload = {
        "schema_version": "xibalba.protocol_receipt.v1",
        "receipt_type": "oracle_telemetry_acceptance",
        "event_id": str(event["event_id"]),
        "event_payload_hash": str(event.get("payload_hash") or ""),
        "agent_did": reporter_result.get("agent_did"),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "oracle_response": dict(receipt),
        "score_reconciliation": reporter_result.get("score_reconciliation"),
    }
    content = json.dumps(receipt_payload, sort_keys=True, separators=(",", ":"), default=str)
    receipt_hash = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    receipt_payload["receipt_hash"] = receipt_hash
    content = json.dumps(receipt_payload, sort_keys=True, separators=(",", ":"), default=str)
    memory = store.store_memory(
        content,
        source={
            "kind": "oracle_protocol_receipt",
            "session_id": event.get("session_id"),
            "event_id": event.get("event_id"),
            "agent_did": reporter_result.get("agent_did"),
            "verification_status": "provider_response_unverified",
            "authority": "oracle_acceptance_metadata",
        },
        status="confirmed",
        evidence_class="protocol_receipt",
        idempotency_key=f"oracle-receipt:{event['event_id']}:{receipt_hash}",
    )
    return {"memory_id": memory["id"], "receipt_hash": receipt_hash, "event_id": event["event_id"]}
