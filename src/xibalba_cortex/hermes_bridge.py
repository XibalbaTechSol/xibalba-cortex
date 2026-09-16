"""CLI bridge invoked by the Hermes plugin at ~/.hermes/plugins/xibalba_cortex/.

The Hermes agent's own venv (~/.hermes/hermes-agent/venv) does not have xibalba_cortex
installed -- it's a separate project with its own dependencies (mcp, eth-hash, sqlite-vec) --
so the plugin shells out to this project's own venv, the same cross-venv pattern already
established by ~/.hermes/plugins/integrity_telemetry (which shells out to integrity-sdk's venv
for the same reason). This process is spawned fire-and-forget per hook call; it must exit
promptly and never raise past its own boundary, matching the observer contract's fail-open
guarantee at the Hermes side and integrity_telemetry's swallow-everything posture at the
subprocess side.

Usage: python -m xibalba_cortex.hermes_bridge <hook_name>, with the hook's kwargs as a JSON
object on stdin. stdin (not argv) because hook payloads carry full prompt/response text, which
can exceed OS argv length limits and contain characters that need cross-venv shell escaping.

**Every dispatch attempt is recorded to the local hook-watermark** (`hermes_watermark.py`) before
this process exits, success or failure. Before that module existed, a crash here (a bug in an
observer handler, an unreachable/corrupted store) left only a traceback on this subprocess's own
stderr -- fire-and-forget means nothing on the Hermes side ever reads it, so a hook could start
silently failing every single time and this project would never know. The external contract is
unchanged (still fails open, still a nonzero exit, still a traceback on stderr); what's new is
that the fact of failure is now durable and queryable via
`xibalba-cortex-hermes-watermark-status`, not only ephemeral stderr.
"""
from __future__ import annotations

import json
import hashlib
import os
import sys

from integrity_sdk import normalize_hook
from xibalba_cortex import hermes_watermark
from xibalba_cortex.hermes_observer import HermesObserverAdapter
from xibalba_cortex.redaction import redact
from xibalba_cortex.runtime_bridge_contract import CONTROLLER_EVENT_SCHEMA_VERSION
from xibalba_cortex.server import _default_home, _identity_mode
from xibalba_cortex.store import GraphStore
from xibalba_cortex.telemetry_outbox import TelemetryOutbox

_store: GraphStore | None = None
_outbox: TelemetryOutbox | None = None


def _get_adapter() -> HermesObserverAdapter:
    global _store
    if _store is None:
        _store = GraphStore(_default_home(), identity_mode=_identity_mode())
    return HermesObserverAdapter(_store)


def _get_outbox() -> TelemetryOutbox:
    global _outbox
    if _outbox is None:
        home = _default_home()
        _outbox = TelemetryOutbox(
            home / "telemetry-outbox.sqlite3",
            max_events=int(os.environ.get("XIBALBA_CORTEX_OUTBOX_MAX_EVENTS", "1000")),
            max_bytes=int(os.environ.get("XIBALBA_CORTEX_OUTBOX_MAX_BYTES", str(16 * 1024 * 1024))),
        )
    return _outbox


def _extract_session_id(kwargs: dict) -> str | None:
    # Hook payloads carry the session identity under different field names depending on hook
    # (see hermes_observer.py's own "Hooks mapped" table: subagent hooks use
    # parent_session_id, post_approval_response uses session_key, everything else uses
    # session_id) -- tried in the same order the adapter itself checks them, purely for the
    # watermark's own `last_session_id` column, never used for dispatch logic.
    for key in ("session_id", "session_key", "parent_session_id"):
        value = kwargs.get(key)
        if value:
            return str(value)
    return None


def _record_watermark(hook_name: str, kwargs: dict, *, success: bool, error: str | None) -> None:
    try:
        hermes_watermark.record_invocation(
            hook_name, session_id=_extract_session_id(kwargs), success=success, error=error
        )
    except Exception as exc:
        # Best-effort, matching spool.py's own posture in the sibling integrity-core repo: a
        # failure to WRITE the watermark must never mask or change the real hook outcome, which
        # has already been decided by the time this runs.
        print(f"failed to record hook watermark for {hook_name}: {exc}", file=sys.stderr)


def _enqueue_cortex_event(hook_name: str, kwargs: dict) -> tuple[str, bool] | None:
    """Enqueue one redacted normalized event; return its claimed delivery if available."""
    # Keep Hermes-specific aliases at the bridge edge, then let the SDK own the
    # shared correlation vocabulary used by Agy and other harnesses.
    normalized_input = dict(kwargs)
    normalized_input.setdefault("session_id", _extract_session_id(kwargs))
    normalized = normalize_hook(hook_name, normalized_input)
    session_id = normalized["session_id"] or _extract_session_id(kwargs)
    if not session_id:
        return None
    payload = redact(dict(kwargs))
    identity = {
        "normalized": normalized,
        "payload": payload,
    }
    event_id = "evt:sha256:" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    event = {
        "schema_version": CONTROLLER_EVENT_SCHEMA_VERSION,
        "event_id": event_id,
        "runtime": "hermes",
        "event_type": hook_name,
        "session_id": session_id,
        "turn_id": normalized["turn_id"],
        "invocation_id": normalized["invocation_id"],
        "tool_call_id": normalized["tool_call_id"],
        "observed_at_utc": kwargs.get("observed_at_utc"),
        "payload": payload,
    }
    _get_outbox().enqueue(event, destinations=("cortex", "integrity_sdk"))
    claimed = _get_outbox().claim("cortex", limit=1, lease_seconds=60, event_id=event_id)
    return event_id, bool(claimed and claimed[0]["event_id"] == event_id)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: hermes_bridge.py <hook_name>", file=sys.stderr)
        sys.exit(2)
    hook_name = sys.argv[1]
    kwargs = json.loads(sys.stdin.read() or "{}")

    claimed_event: tuple[str, bool] | None = None
    try:
        claimed_event = _enqueue_cortex_event(hook_name, kwargs)
    except Exception as exc:
        # Outbox failure must be visible but must not break Hermes's fail-open observer hook.
        print(f"failed to enqueue Cortex telemetry for {hook_name}: {exc}", file=sys.stderr)

    try:
        adapter = _get_adapter()
    except Exception as exc:
        # Store construction itself failed (corrupted DB, unreachable path, etc.) -- there is no
        # adapter to dispatch through, but the failure is exactly the kind of silent-forever
        # problem this module exists to surface, so it's still recorded before re-raising.
        _record_watermark(hook_name, kwargs, success=False, error=f"store construction failed: {exc}")
        raise

    handler = getattr(adapter, hook_name, None)
    if handler is None:
        _record_watermark(hook_name, kwargs, success=False, error=f"unknown hook: {hook_name}")
        print(f"unknown hook: {hook_name}", file=sys.stderr)
        sys.exit(1)

    try:
        handler(**kwargs)
    except Exception as exc:
        if claimed_event and claimed_event[1]:
            try:
                _get_outbox().fail(claimed_event[0], "cortex", str(exc), retry_delay=1.0)
            except Exception as outbox_exc:
                print(f"failed to record Cortex outbox failure: {outbox_exc}", file=sys.stderr)
        _record_watermark(hook_name, kwargs, success=False, error=str(exc))
        raise
    if claimed_event and claimed_event[1]:
        _get_outbox().ack(claimed_event[0], "cortex", receipt={"stored": True, "handler": hook_name})
    _record_watermark(hook_name, kwargs, success=True, error=None)


if __name__ == "__main__":
    main()
