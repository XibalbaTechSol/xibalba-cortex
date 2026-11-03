"""Enrollment codes: the one-shot bearer secret that binds an agent DID to a workspace.

An operator issues a code on the console; the agent redeems it from its own harness with
`cortex connect --code`. The code proves the operator authorised *this* enrollment; the
signature proves the redeemer holds the private key for the DID it is claiming. Both are
required: a code alone would let anyone who intercepts it bind an identity of their
choosing, and a signature alone would let any agent enroll itself unasked.

Three properties this module exists to hold:

1. **The signature is checked against the DID being claimed, not merely against the key
   that was handed in.** `did:integrity:<hex>` is SHA-256 over the raw Ed25519 public key
   (`integrity_sdk.did.fingerprint_for_pubkey`), so the fingerprint of the supplied key
   must equal the DID's suffix. Without that comparison an attacker signs the code with
   their own key, presents a victim's DID beside it, and the signature verifies perfectly
   against the wrong identity.

2. **The refusals do not enumerate.** Expired, already-redeemed, unknown and bad-signature
   all raise `EnrollmentRefused` with one message. Distinguishable messages would make this
   an oracle: whether a code ever existed, whether it was already used, which workspace it
   belongs to. The specific reason is written to the audit trail, which only an operator
   reads.

3. **The code itself is never stored.** Only SHA-256 of it, as `ingest_tokens` does for
   bearer tokens, so the database is not a second copy of every live secret. The audit
   trail does not record it either.

Cortex is not an identity authority: this binds an existing DID to a workspace. It does not
mint keys, and no key material is generated here or in the browser.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from integrity_sdk.did import fingerprint_for_pubkey, verify_signature

from .ingest_tokens import _connect

#: How long a freshly issued code stays redeemable. Short because it is a bearer secret
#: that travels out of band (a console page to a terminal), not a credential to keep.
DEFAULT_TTL_SECONDS = 600

#: Redemption attempts allowed per window, counted per home. A code is 43 url-safe
#: characters, so this is not what makes guessing infeasible -- it is what stops an
#: attacker from grinding against a *live* code's remaining TTL.
MAX_ATTEMPTS_PER_WINDOW = 10
ATTEMPT_WINDOW_SECONDS = 60

#: The one thing a failed redemption ever says. See property 2 in the module docstring.
_REFUSED = "that enrollment code cannot be redeemed"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS enrollment_codes (
    code_hash TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    redeemed_at TEXT,
    redeemed_did TEXT,
    redeemed_device_id TEXT
);
CREATE TABLE IF NOT EXISTS enrollment_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_enrollment_attempts_at ON enrollment_attempts(attempted_at);
CREATE TABLE IF NOT EXISTS enrollment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    workspace_id TEXT,
    did TEXT,
    device_id TEXT,
    detail TEXT,
    created_at TEXT NOT NULL
);
"""


class EnrollmentRefused(Exception):
    """A redemption was refused. The message is deliberately the same for every cause."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _ensure_schema(home: str | Path) -> None:
    conn = _connect(home)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _record(home: str | Path, *, event_type: str, workspace_id: str | None = None,
            did: str | None = None, device_id: str | None = None,
            detail: str | None = None) -> None:
    conn = _connect(home)
    try:
        conn.execute(
            "INSERT INTO enrollment_events(event_type,workspace_id,did,device_id,detail,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (event_type, workspace_id, did, device_id, detail, _iso(_now())),
        )
        conn.commit()
    finally:
        conn.close()


def enrollment_events(home: str | Path, *, limit: int = 100) -> list[dict[str, Any]]:
    """The enrollment audit trail, newest first. Never contains a code."""
    _ensure_schema(home)
    conn = _connect(home)
    try:
        rows = conn.execute(
            "SELECT event_type, workspace_id, did, device_id, detail, created_at"
            " FROM enrollment_events ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def issue_code(workspace_id: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS,
               home: str | Path | None = None) -> str:
    """Mint a single-use code for `workspace_id` and return it. It is returned exactly once;
    only its hash is kept, so a lost code cannot be recovered, only reissued."""
    if home is None:
        raise ValueError("home is required")
    if not workspace_id:
        raise ValueError("workspace_id is required")
    _ensure_schema(home)
    code = secrets.token_urlsafe(32)
    now = _now()
    conn = _connect(home)
    try:
        conn.execute(
            "INSERT INTO enrollment_codes(code_hash,workspace_id,created_at,expires_at)"
            " VALUES(?,?,?,?)",
            (_code_hash(code), workspace_id, _iso(now),
             _iso(now + timedelta(seconds=ttl_seconds))),
        )
        conn.commit()
    finally:
        conn.close()
    _record(home, event_type="enrollment_code_issued", workspace_id=workspace_id,
            detail=f"ttl_seconds={ttl_seconds}")
    return code


def _too_many_attempts(home: str | Path) -> bool:
    """Count, then decide. The attempt is recorded before the verdict so a caller cannot
    avoid being counted by sending a request that fails early."""
    cutoff = _iso(_now() - timedelta(seconds=ATTEMPT_WINDOW_SECONDS))
    conn = _connect(home)
    try:
        conn.execute("INSERT INTO enrollment_attempts(attempted_at) VALUES(?)", (_iso(_now()),))
        conn.commit()
        recent = conn.execute(
            "SELECT COUNT(*) FROM enrollment_attempts WHERE attempted_at >= ?", (cutoff,),
        ).fetchone()[0]
    finally:
        conn.close()
    return bool(recent > MAX_ATTEMPTS_PER_WINDOW)


def _refuse(home: str | Path, reason: str, *, did: str | None = None,
            workspace_id: str | None = None) -> EnrollmentRefused:
    """Audit the real reason; return the one message the caller is allowed to see."""
    _record(home, event_type="enrollment_code_refused", did=did,
            workspace_id=workspace_id, detail=reason)
    return EnrollmentRefused(_REFUSED)


def redeem_code(code: str, *, did: str, device_id: str, public_key: bytes,
                signature: bytes, home: str | Path | None = None) -> dict[str, Any]:
    """Redeem `code`, binding `did` to the code's workspace. Raises `EnrollmentRefused`
    for every failure, with one message; the cause goes to the audit trail."""
    if home is None:
        raise ValueError("home is required")
    _ensure_schema(home)

    if _too_many_attempts(home):
        raise _refuse(home, "rate_limited", did=did)

    row = _connect(home).execute(
        "SELECT code_hash, workspace_id, expires_at, redeemed_at FROM enrollment_codes"
        " WHERE code_hash = ?", (_code_hash(code),),
    ).fetchone()
    if row is None:
        raise _refuse(home, "unknown_code", did=did)
    workspace_id = str(row["workspace_id"])
    if row["redeemed_at"] is not None:
        raise _refuse(home, "already_redeemed", did=did, workspace_id=workspace_id)
    if datetime.fromisoformat(str(row["expires_at"])) <= _now():
        raise _refuse(home, "expired", did=did, workspace_id=workspace_id)

    # The key must be the key the DID names, not merely *a* key. See property 1.
    expected = did.rsplit(":", 1)[-1]
    if not did.startswith("did:integrity:") or fingerprint_for_pubkey(public_key) != expected:
        raise _refuse(home, "key_does_not_match_did", did=did, workspace_id=workspace_id)
    if not verify_signature(public_key, code.encode(), signature):
        raise _refuse(home, "bad_signature", did=did, workspace_id=workspace_id)

    now = _iso(_now())
    conn = _connect(home)
    try:
        # Single use is enforced here, not by the read above: `redeemed_at IS NULL` in the
        # WHERE clause means two concurrent redemptions cannot both see an unused row and
        # both proceed. A check-then-write would race.
        changed = conn.execute(
            "UPDATE enrollment_codes SET redeemed_at=?, redeemed_did=?, redeemed_device_id=?"
            " WHERE code_hash=? AND redeemed_at IS NULL",
            (now, did, device_id, _code_hash(code)),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    if changed != 1:
        raise _refuse(home, "already_redeemed_concurrently", did=did, workspace_id=workspace_id)

    _record(home, event_type="enrollment_code_redeemed", workspace_id=workspace_id,
            did=did, device_id=device_id)
    return {"did": did, "workspace_id": workspace_id, "device_id": device_id,
            "redeemed_at": now}
