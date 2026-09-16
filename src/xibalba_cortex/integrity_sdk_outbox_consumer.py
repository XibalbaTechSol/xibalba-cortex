"""One-shot Integrity SDK consumer for the Hermes telemetry outbox.

This worker owns no signing keys and does not implement Oracle submission. It
claims redacted normalized events, forwards them to the existing identity.py
SDK boundary, and acknowledges only when that boundary reports ``ok: true``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .telemetry_outbox import TelemetryOutbox
from .protocol_receipts import record_oracle_receipt
from .store import GraphStore

DEFAULT_SDK_PYTHON = "/home/xibalba/Projects/integrity-core/integrity-sdk/.venv/bin/python"
DEFAULT_IDENTITY_CLI = "/home/xibalba/.claude/xibalba/identity.py"


class IntegritySdkOutboxConsumer:
    def __init__(
        self,
        outbox: TelemetryOutbox,
        *,
        agent_name: str = "xibalba",
        sdk_python: str = DEFAULT_SDK_PYTHON,
        identity_cli: str = DEFAULT_IDENTITY_CLI,
        store: GraphStore | None = None,
        run_fn: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.outbox = outbox
        self.agent_name = agent_name
        self.sdk_python = sdk_python
        self.identity_cli = identity_cli
        self.store = store
        self.run_fn = run_fn or subprocess.run

    def _submit(self, item: dict[str, Any], *, timeout: int) -> dict[str, Any]:
        completed = self.run_fn(
            [self.sdk_python, self.identity_cli, "report", self.agent_name, json.dumps(item["payload"], separators=(",", ":"))],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"SDK reporter exited {completed.returncode}: {completed.stderr[-500:]}")
        result = None
        for line in reversed((completed.stdout or "").splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                result = candidate
                break
        if result is None:
            raise RuntimeError("SDK reporter returned invalid JSON")
        if result.get("ok") is not True:
            raise RuntimeError(f"SDK reporter did not accept event: {result!r}")
        return {
            "accepted": True,
            "event_id": item["event_id"],
            "receipt": result.get("receipt"),
            "agent_did": result.get("agent_did"),
            "reporter": result,
        }

    def _reconcile_score(self, agent_did: str | None) -> dict[str, Any]:
        """Read the Oracle's current score projection without treating it as acceptance."""
        if not agent_did:
            return {"status": "unavailable", "reason": "reporter returned no agent DID"}
        base_url = os.environ.get("ORACLE_URL", "http://localhost:8080").rstrip("/")
        path = "/v1/agent/" + urllib.parse.quote(agent_did, safe="") + "/ais"
        try:
            with urllib.request.urlopen(base_url + path, timeout=10) as response:
                projection = json.load(response)
            if not isinstance(projection, dict) or not isinstance(projection.get("ais"), (int, float)):
                return {"status": "unavailable", "reason": "Oracle AIS response contained no numeric ais field"}
            return {
                "status": "observed",
                "source": "oracle_ais_projection",
                "endpoint": path,
                "ais": projection["ais"],
                "constraint_score": projection.get("constraint_score"),
                "event_count": projection.get("event_count"),
                "period_start": projection.get("period_start"),
                "period_end": projection.get("period_end"),
            }
        except (OSError, ValueError, urllib.error.URLError) as exc:
            return {"status": "unavailable", "reason": type(exc).__name__}

    def consume(self, *, limit: int = 50, lease_seconds: int = 60, timeout: int = 30) -> dict[str, Any]:
        claimed = self.outbox.claim("integrity_sdk", limit=limit, lease_seconds=lease_seconds)
        acked = 0
        retried = 0
        dead_lettered = 0
        errors: list[dict[str, str]] = []
        for item in claimed:
            try:
                receipt = self._submit(item, timeout=timeout)
                receipt["score_reconciliation"] = self._reconcile_score(receipt.get("agent_did"))
                if self.store is not None:
                    receipt["cortex_receipt"] = record_oracle_receipt(
                        self.store, event=item["payload"], reporter_result=receipt
                    )
                self.outbox.ack(item["event_id"], "integrity_sdk", receipt=receipt)
                acked += 1
            except Exception as exc:  # the outbox records the failure durably
                try:
                    state = self.outbox.fail(item["event_id"], "integrity_sdk", str(exc))
                    retried += int(state == "retry")
                    dead_lettered += int(state == "dead_letter")
                except Exception as state_exc:
                    errors.append({"event_id": item["event_id"], "error": str(state_exc)})
                errors.append({"event_id": item["event_id"], "error": str(exc)})
        return {
            "claimed": len(claimed),
            "acked": acked,
            "retried": retried,
            "dead_lettered": dead_lettered,
            "errors": errors,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Drain the Integrity SDK telemetry outbox once")
    parser.add_argument("--home", default=os.environ.get("XIBALBA_CORTEX_HOME", "~/.hermes/xibalba-cortex"))
    parser.add_argument("--agent", default=os.environ.get("XIBALBA_INTEGRITY_AGENT", "xibalba"))
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    home = Path(args.home).expanduser()
    outbox = TelemetryOutbox(
        home / "telemetry-outbox.sqlite3",
        max_events=int(os.environ.get("XIBALBA_CORTEX_OUTBOX_MAX_EVENTS", "1000")),
        max_bytes=int(os.environ.get("XIBALBA_CORTEX_OUTBOX_MAX_BYTES", str(16 * 1024 * 1024))),
    )
    store = GraphStore(home)
    try:
        print(json.dumps(IntegritySdkOutboxConsumer(outbox, agent_name=args.agent, store=store).consume(limit=args.limit), sort_keys=True))
    finally:
        store.close()
        outbox.close()


if __name__ == "__main__":
    main()
