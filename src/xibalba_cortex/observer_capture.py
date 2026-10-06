"""Local observer capture for Claude/Codex hooks and copied Codex app-server messages.

Observation only: never forwards approval responses or reads transcript paths.
The existing bounded outbox and GraphStore remain persistence authorities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import redact
from .telemetry_outbox import TelemetryOutbox

SCHEMA = "xibalba.observer.capture.v1"
DESTINATION = "observer_cortex"
MAX_INPUT_BYTES = 1024 * 1024
MAX_CONTENT_BYTES = 6000
CLAUDE_HOOKS = (
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PostToolUseFailure", "PermissionRequest", "Stop", "SubagentStart", "SubagentStop",
)
CODEX_HOOKS = (
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PermissionRequest", "Stop", "SubagentStart", "SubagentStop", "Interrupt",
    "PreCompact", "PostCompact",
)
CODEX_METHODS = {
    "thread/started", "thread/closed", "turn/started", "turn/completed",
    "item/started", "item/completed", "item/agentMessage/delta",
    "item/commandExecution/outputDelta", "thread/tokenUsage/updated", "error",
    "item/commandExecution/requestApproval", "item/fileChange/requestApproval",
    "serverRequest/resolved",
}
_SECRET_KEYS = {"password", "secret", "token", "api_key", "apikey", "authorization", "private_key"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if str(k).lower().replace("-", "_") in _SECRET_KEYS
                else _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return redact(value)


def _bounded_content(value: Any, mode: str) -> dict[str, Any]:
    encoded = json.dumps(_scrub(value), ensure_ascii=False, sort_keys=True).encode()
    result = {"sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded),
              "state": "omitted_by_policy"}
    if mode == "redacted":
        if len(encoded) <= MAX_CONTENT_BYTES:
            result.update(value=json.loads(encoded), state="redacted")
        else:
            # Bounded metadata instead of silently storing a broken JSON prefix.
            result["state"] = "omitted_size_limit"
    return result


def normalize(runtime: str, payload: dict[str, Any], *, mode: str = "metadata",
              occurrence_id: str | None = None) -> dict[str, Any] | None:
    """Normalize one occurrence; callers reuse its ID when retrying delivery.

    Callback/receipt time is explicitly labeled, never represented as original model time.
    IDs are occurrence-based so identical text is never globally deduplicated.
    """
    if mode not in {"metadata", "redacted"}:
        raise ValueError("unsupported capture mode")
    received = _now()
    if runtime == "claude" or (runtime == "codex" and "hook_event_name" in payload):
        hook = payload.get("hook_event_name")
        if hook not in (CLAUDE_HOOKS if runtime == "claude" else CODEX_HOOKS):
            return None
        session = payload.get("session_id")
        item = payload.get("tool_use_id")
        turn = payload.get("turn_id")  # Often unavailable on native callbacks.
        metadata = {k: payload[k] for k in ("tool_name", "duration_ms", "is_interrupt", "agent_type", "model", "source", "trigger") if k in payload}
        metadata["capture_surface"] = "native_hook"
        if payload.get("agent_id"):
            metadata["subagent_id"] = payload["agent_id"]  # Not a protocol DID.
        content = {k: payload[k] for k in (
            "prompt", "tool_input", "tool_response", "error", "last_assistant_message"
        ) if k in payload}
        event_type = str(hook)
        # Tool callback identity is stable; repeated identical prompts remain occurrences.
        stable = f"{runtime}:{session}:{hook}:{item}" if item else None
    elif runtime == "codex":
        method = payload.get("method")
        if method not in CODEX_METHODS:
            return None
        params = payload.get("params")
        if not isinstance(params, dict):
            raise ValueError("Codex params must be an object")
        thread = params.get("thread") or {}
        turn_obj = params.get("turn") or {}
        item_obj = params.get("item") or {}
        if not all(isinstance(v, dict) for v in (thread, turn_obj, item_obj)):
            raise ValueError("invalid Codex correlation object")
        session = params.get("threadId") or thread.get("id")
        turn = params.get("turnId") or turn_obj.get("id")
        item = params.get("itemId") or item_obj.get("id")
        if method.startswith("item/reasoning") or item_obj.get("type") == "reasoning":
            return None
        if method in {"item/started", "item/completed"} and item_obj.get("type") not in {
            "userMessage", "agentMessage", "commandExecution", "fileChange", "mcpToolCall",
            "dynamicToolCall", "collabToolCall", "webSearch", "contextCompaction",
        }:
            return None
        metadata = {"item_type": item_obj.get("type"), "status": item_obj.get("status") or turn_obj.get("status"), "capture_surface": "app_server"}
        if "exitCode" in item_obj:
            metadata["exit_code"] = item_obj["exitCode"]
        if "durationMs" in item_obj:
            metadata["duration_ms"] = item_obj["durationMs"]
        # Allowlisted content only; no reasoning, auth, arbitrary params or local paths.
        content = {k: item_obj[k] for k in (
            "text", "content", "command", "arguments", "aggregatedOutput", "result", "error", "contentItems"
        ) if k in item_obj}
        if "delta" in params:
            content["delta"] = params["delta"]
        event_type = str(method)
        stable = f"codex:{session}:{turn}:{method}:{item}" if item and not method.endswith("delta") else None
    else:
        raise ValueError("unsupported runtime")
    if not isinstance(session, str) or not session.strip():
        raise ValueError("missing session identity")
    for identifier in (session, turn, item, occurrence_id):
        if identifier is not None and (not isinstance(identifier, str) or len(identifier) > 512):
            raise ValueError("invalid correlation identity")
    for key, value in metadata.items():
        if isinstance(value, str):
            metadata[key] = value[:256]
        elif value is not None and not isinstance(value, (int, float, bool)):
            metadata[key] = None
    event_id = occurrence_id or ("observer:" + hashlib.sha256(stable.encode()).hexdigest() if stable else "observer:" + str(uuid.uuid4()))
    # Source timestamps are optional. Invalid values are not accepted as trusted timing.
    source_time = payload.get("observed_at_utc")
    if source_time is not None:
        if not isinstance(source_time, str):
            raise ValueError("invalid source timestamp")
        parsed = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("source timestamp requires timezone")
    return {
        "schema_version": SCHEMA, "event_id": event_id, "runtime": runtime,
        "session_id": session, "turn_id": turn, "tool_call_id": item,
        "event_type": event_type, "observed_at_utc": source_time or received,
        "received_at_utc": received, "timestamp_source": "source" if source_time else "callback_received",
        "metadata": _scrub(metadata), "content": _bounded_content(content, mode),
        "capture_mode": mode,
    }


def enqueue(home: Path, event: dict[str, Any]) -> dict[str, Any]:
    # Runtime observer queues are per profile, separate from unrelated SDK backlogs.
    home = home.expanduser().resolve()
    outbox = TelemetryOutbox(home / "observer-outbox.sqlite3")
    try:
        previous = outbox.connection.execute(
            "SELECT payload_json FROM outbox_events WHERE event_id=?", (event["event_id"],)
        ).fetchone()
        if previous:
            old = json.loads(previous["payload_json"])
            def identity(value):
                value = dict(value)
                value.pop("received_at_utc", None)
                if value.get("timestamp_source") == "callback_received":
                    value.pop("observed_at_utc", None)
                return value
            if identity(old) != identity(event):
                raise ValueError("conflicting observer event identity")
            event = old
        return outbox.enqueue(event, destinations=(DESTINATION,))
    finally:
        outbox.close()


def drain(home: Path, *, limit: int = 100) -> dict[str, int]:
    """Persist pending observations; retries use GraphStore's existing dedupe boundary."""
    from .store import GraphStore

    home = home.expanduser().resolve()
    outbox = TelemetryOutbox(home / "observer-outbox.sqlite3")
    store = None
    recorded = failed = 0
    try:
        store = GraphStore(home)
        for delivery in outbox.claim(DESTINATION, limit=limit):
            event = delivery["payload"]
            try:
                store.start_session(event["session_id"], retention_tier="digest")
                store.record_otel_batch(event["session_id"], [{
                    "kind": "log", "name": "xibalba.observer.event",
                    "trace_id": event["session_id"], "prompt_id": event.get("turn_id"),
                    "span_id": event.get("tool_call_id"),
                    "start_time": event["observed_at_utc"],
                    "end_time": event["observed_at_utc"],
                    "attributes": event, "idempotency_key": event["event_id"],
                }])
                outbox.ack(event["event_id"], DESTINATION, receipt={"stored": True})
                recorded += 1
            except Exception:
                # Error bodies can contain paths/content. Keep only a fixed failure code.
                outbox.fail(event["event_id"], DESTINATION, "OBSERVER_PERSIST_FAILED")
                failed += 1
        return {"acked": recorded, "failed": failed}
    finally:
        if store is not None:
            store.close()
        outbox.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("claude-hook", "codex-hook", "codex-stream", "drain", "status"))
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--mode", choices=("metadata", "redacted"), default="metadata")
    parser.add_argument("--watch", action="store_true", help="Continuously drain the queue")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args()
    args.home = args.home.expanduser().resolve()
    if args.action == "drain":
        if args.poll_interval < 0.1 or args.poll_interval > 60:
            parser.error("poll interval must be between 0.1 and 60 seconds")
        first = True
        while True:
            try:
                result = drain(args.home)
                if first or not args.watch or result["acked"] or result["failed"]:
                    print(json.dumps(result), flush=True)
                first = False
            except Exception:
                print("Cortex observer persistence unavailable; queue retained.", file=sys.stderr)
                if not args.watch:
                    return 1
            if not args.watch:
                return 0
            time.sleep(args.poll_interval)
    if args.action == "status":
        outbox = TelemetryOutbox(args.home / "observer-outbox.sqlite3")
        try:
            print(json.dumps(outbox.stats()))
        finally:
            outbox.close()
        return 0
    runtime = "claude" if args.action == "claude-hook" else "codex"
    is_hook = args.action.endswith("-hook")
    # Native-hook stdin is one JSON object; copied app-server messages are JSONL.
    if is_hook:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        inputs = [raw]
    else:
        inputs = iter(lambda: sys.stdin.buffer.readline(MAX_INPUT_BYTES + 1), b"")
    failures = 0
    for raw in inputs:
        try:
            if len(raw) > MAX_INPUT_BYTES:
                raise ValueError("input too large")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("input must be an object")
            event = normalize(runtime, payload, mode=args.mode)
            if event:
                enqueue(args.home, event)
        except Exception:
            failures += 1
            print("Cortex observer capture failed; inspect recorder status.", file=sys.stderr)
            if not is_hook and len(raw) > MAX_INPUT_BYTES and not raw.endswith(b"\n"):
                # Discard the rest of this oversized frame in bounded reads.
                while raw and not raw.endswith(b"\n"):
                    raw = sys.stdin.buffer.readline(MAX_INPUT_BYTES + 1)
    # Observer hooks never block, approve, modify input, or print model context.
    if args.action == "codex-hook":
        # Codex Stop/SubagentStop expect JSON. An empty object conveys no decision/context.
        print("{}")
    return 0 if is_hook else int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
