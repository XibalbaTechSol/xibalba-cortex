"""CLI bridge invoked by the Hermes plugin at ~/.hermes/plugins/xibalba_cortex_memory/.

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
import sys

from xibalba_cortex import hermes_watermark
from xibalba_cortex.hermes_observer import HermesObserverAdapter
from xibalba_cortex.server import _default_home, _identity_mode
from xibalba_cortex.store import GraphStore

_store: GraphStore | None = None


def _get_adapter() -> HermesObserverAdapter:
    global _store
    if _store is None:
        _store = GraphStore(_default_home(), identity_mode=_identity_mode())
    return HermesObserverAdapter(_store)


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


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: hermes_bridge.py <hook_name>", file=sys.stderr)
        sys.exit(2)
    hook_name = sys.argv[1]
    kwargs = json.loads(sys.stdin.read() or "{}")

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
        _record_watermark(hook_name, kwargs, success=False, error=str(exc))
        raise
    _record_watermark(hook_name, kwargs, success=True, error=None)


if __name__ == "__main__":
    main()
