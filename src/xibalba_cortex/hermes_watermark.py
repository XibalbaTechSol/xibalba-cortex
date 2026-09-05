"""Durable liveness watermark for Hermes hook delivery, closing a real, previously undesigned
gap: `hermes_bridge.py` is spawned fire-and-forget, per hook call, by a Hermes agent process this
project does not control -- before this module, if that subprocess crashed (a bug in an observer
handler, a corrupted/unreachable store, an unhandled exception of any kind), the ONLY trace was a
traceback on the subprocess's own stderr, which nothing reads: Hermes never captures or surfaces
it (fire-and-forget by design, matching the observer contract's fail-open guarantee -- see
`hermes_bridge.py`'s own module docstring). A hook could silently stop being delivered, or start
silently failing every time, and nothing in this project would ever know.

This closes it with the same shape as `bcc_middleware/app/spool.py` in the sibling
`integrity-core` repo (durable local SQLite for something that must survive a crash, not process
memory) -- a small, SEPARATE SQLite file, deliberately NOT a table in `store.py`'s own schema:
`store.py`'s schema is declared frozen for v1 (`SPECIFICATION.md` §2), and this watermark is
liveness/ops metadata about hook DELIVERY, not part of the memory graph itself.

One row per `hook_name`, upserted on every dispatch (`record_invocation`): last-seen timestamp,
last session/session-key seen, running total/failure counts, consecutive-failure streak, and the
most recent error (if the last dispatch failed). `hermes_bridge.py`'s `main()` now wraps the
handler call and records the outcome BEFORE re-raising -- the external contract (nonzero exit,
traceback on stderr, Hermes never blocks on it) is unchanged; what's new is that the fact of
failure is now durable and queryable, not only ephemeral stderr.

`status()` / the `xibalba-cortex-hermes-watermark-status` console script (`main()` below) is the
verification surface: an operator (or a resuming session) can ask "is Hermes actually still
calling these hooks, and are they succeeding?" without needing to have been watching stderr at
the time. `staleness_report` flags any hook in an expected set that hasn't been seen recently --
useful when a session is known to be active but a specific hook type has gone quiet, which is
exactly the "wiring silently broke" failure mode this whole module exists to catch.

Disclosed scope limitation, same class as `bcc_middleware/app/spool.py`'s: single SQLite file,
single-process-writer-at-a-time (SQLite's own locking serializes concurrent hermes_bridge.py
invocations, which is correct here -- each is a short-lived write-then-exit process, not a
long-running writer contending for the file). No alerting is wired to this yet; it is a pull
(status/staleness-report), not a push, surface.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hook_watermark (
    hook_name TEXT PRIMARY KEY,
    last_invoked_at REAL NOT NULL,
    last_session_id TEXT,
    total_invocations INTEGER NOT NULL DEFAULT 0,
    total_failures INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_success INTEGER NOT NULL DEFAULT 1,
    last_error TEXT
)
"""


def _default_watermark_path() -> Path:
    # Deliberately reuses the same home-resolution rule as server.py::_default_home rather than
    # importing that function -- hermes_bridge.py already imports server.py for _default_home/
    # _identity_mode for the GraphStore itself, and this module must stay importable (and its
    # watermark file locatable) even when GraphStore construction is exactly the thing that
    # failed, so it cannot depend on anything that touches the store.
    import os

    override = os.environ.get("XIBALBA_CORTEX_HOME")
    if override:
        home = Path(override)
    else:
        hermes_home = os.environ.get("HERMES_HOME")
        home = Path(hermes_home) / "xibalba-cortex" if hermes_home else Path.home() / ".hermes" / "xibalba-cortex"
    return home.expanduser().resolve() / "hermes_hook_watermark.sqlite3"


def _connect(db_path: Path | None) -> sqlite3.Connection:
    path = db_path or _default_watermark_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def record_invocation(
    hook_name: str,
    *,
    session_id: str | None,
    success: bool,
    error: str | None = None,
    db_path: Path | None = None,
    now: float | None = None,
) -> None:
    """Best-effort itself, matching `spool.py::enqueue`'s own posture: if even writing the
    watermark fails (disk full, permissions), that's logged to stderr by the caller
    (`hermes_bridge.py`) and swallowed here -- the ORIGINAL hook outcome (success or failure) is
    what must still propagate to the caller's own exit code, never masked by a watermark-write
    failure."""
    if now is None:
        now = time.time()
    conn = _connect(db_path)
    try:
        existing = conn.execute(
            "SELECT total_invocations, total_failures, consecutive_failures FROM hook_watermark WHERE hook_name = ?",
            (hook_name,),
        ).fetchone()
        total_invocations = (existing[0] if existing else 0) + 1
        total_failures = (existing[1] if existing else 0) + (0 if success else 1)
        consecutive_failures = 0 if success else (existing[2] if existing else 0) + 1
        conn.execute(
            "INSERT INTO hook_watermark (hook_name, last_invoked_at, last_session_id, total_invocations, "
            "total_failures, consecutive_failures, last_success, last_error) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(hook_name) DO UPDATE SET last_invoked_at = excluded.last_invoked_at, "
            "last_session_id = excluded.last_session_id, total_invocations = excluded.total_invocations, "
            "total_failures = excluded.total_failures, consecutive_failures = excluded.consecutive_failures, "
            "last_success = excluded.last_success, last_error = excluded.last_error",
            (hook_name, now, session_id, total_invocations, total_failures, consecutive_failures, int(success), error),
        )
        conn.commit()
    finally:
        conn.close()


@dataclass
class HookWatermark:
    hook_name: str
    last_invoked_at: float
    last_session_id: str | None
    total_invocations: int
    total_failures: int
    consecutive_failures: int
    last_success: bool
    last_error: str | None


def status(db_path: Path | None = None) -> list[HookWatermark]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT hook_name, last_invoked_at, last_session_id, total_invocations, total_failures, "
            "consecutive_failures, last_success, last_error FROM hook_watermark ORDER BY hook_name"
        ).fetchall()
    finally:
        conn.close()
    return [
        HookWatermark(
            hook_name=row[0], last_invoked_at=row[1], last_session_id=row[2],
            total_invocations=row[3], total_failures=row[4], consecutive_failures=row[5],
            last_success=bool(row[6]), last_error=row[7],
        )
        for row in rows
    ]


def staleness_report(
    expected_hooks: list[str], *, max_age_seconds: float, db_path: Path | None = None, now: float | None = None
) -> dict[str, dict]:
    """For each name in `expected_hooks`, reports whether it has EVER been seen, and if so
    whether it's stale (`last_invoked_at` older than `max_age_seconds`) -- the check an operator
    or a resuming session actually wants: "is Hermes still calling every hook I expect it to,"
    not just "what does the raw watermark table currently say." A hook never seen at all is
    reported distinctly from one seen-but-stale -- "never wired up" and "was working, stopped"
    are different failure modes worth telling apart."""
    if now is None:
        now = time.time()
    seen = {w.hook_name: w for w in status(db_path=db_path)}
    report: dict[str, dict] = {}
    for hook_name in expected_hooks:
        watermark = seen.get(hook_name)
        if watermark is None:
            report[hook_name] = {"seen": False, "stale": True, "age_seconds": None}
            continue
        age = now - watermark.last_invoked_at
        report[hook_name] = {
            "seen": True,
            "stale": age > max_age_seconds,
            "age_seconds": age,
            "last_success": watermark.last_success,
            "consecutive_failures": watermark.consecutive_failures,
        }
    return report


# The hook names `hermes_observer.HermesObserverAdapter` actually implements (see that module's
# own "Hooks mapped" table) -- the default expected set for `staleness_report` when the caller
# doesn't supply its own narrower list.
ALL_KNOWN_HOOKS = [
    "on_session_start", "on_session_end", "post_llm_call", "post_api_request",
    "api_request_error", "post_tool_call", "post_approval_response", "subagent_start", "subagent_stop",
]


def main() -> None:
    """`xibalba-cortex-hermes-watermark-status` console script: prints a JSON status report."""
    import json
    import sys

    max_age = float(sys.argv[1]) if len(sys.argv) > 1 else 3600.0
    report = {
        "watermarks": [w.__dict__ for w in status()],
        "staleness": staleness_report(ALL_KNOWN_HOOKS, max_age_seconds=max_age),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
