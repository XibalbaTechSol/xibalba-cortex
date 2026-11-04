"""Device authorization and browser-mediated pairing for Cortex agents (RFC 8628 & Loopback)."""
from __future__ import annotations

import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ingest_tokens import _connect, issue_token
from .accounts import record_auth_event

_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS device_pairing_requests (
    id TEXT PRIMARY KEY,
    user_code TEXT NOT NULL UNIQUE,
    device_id TEXT NOT NULL,
    device_name TEXT NOT NULL,
    agent_did TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    callback_url TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    approved_account_id TEXT,
    approved_tenant_id TEXT,
    issued_token TEXT,
    redeemed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pairing_user_code ON device_pairing_requests(user_code);
CREATE INDEX IF NOT EXISTS idx_pairing_status ON device_pairing_requests(status);
"""


def _ensure_pairing_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _random_user_code() -> str:
    part1 = "".join(secrets.choice(_CODE_CHARS) for _ in range(4))
    part2 = "".join(secrets.choice(_CODE_CHARS) for _ in range(4))
    return f"{part1}-{part2}"


def create_pairing_request(
    home: str | Path,
    *,
    device_id: str,
    device_name: str,
    agent_did: str,
    agent_name: str = "default",
    callback_url: str | None = None,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    """Create a pending device pairing session for browser authorization."""
    device_code = secrets.token_urlsafe(32)
    user_code = _random_user_code()
    now_epoch = int(time.time())
    expires_epoch = now_epoch + ttl_seconds
    now_iso = datetime.now(timezone.utc).isoformat()
    expires_iso = datetime.fromtimestamp(expires_epoch, timezone.utc).isoformat()

    conn = _connect(home)
    try:
        _ensure_pairing_schema(conn)
        conn.execute(
            """INSERT INTO device_pairing_requests (
                id, user_code, device_id, device_name, agent_did, agent_name,
                callback_url, created_at, expires_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                device_code,
                user_code,
                device_id.strip(),
                device_name.strip() or device_id.strip(),
                agent_did.strip(),
                agent_name.strip() or "default",
                callback_url.strip() if callback_url else None,
                now_iso,
                expires_iso,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "device_code": device_code,
        "user_code": user_code,
        "expires_in": ttl_seconds,
        "interval": 2,
    }


def get_pairing_request(home: str | Path, code: str) -> dict[str, Any] | None:
    """Look up a pairing request by device_code or user_code."""
    code_clean = code.strip()
    conn = _connect(home)
    try:
        _ensure_pairing_schema(conn)
        row = conn.execute(
            "SELECT * FROM device_pairing_requests WHERE id=? OR user_code=?",
            (code_clean, code_clean.upper()),
        ).fetchone()
        if not row:
            return None

        data = dict(row)
        expires_at = datetime.fromisoformat(data["expires_at"])
        if datetime.now(timezone.utc) > expires_at and data["status"] == "pending":
            conn.execute(
                "UPDATE device_pairing_requests SET status='expired' WHERE id=?",
                (data["id"],),
            )
            conn.commit()
            data["status"] = "expired"

        expires_in = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
        data["expires_in"] = expires_in
        return data
    finally:
        conn.close()


def approve_pairing_request(
    home: str | Path,
    code: str,
    *,
    account_id: str,
    tenant_id: str,
    service_control: Any | None = None,
) -> dict[str, Any]:
    """Approve a device pairing request, issue an agent API token, and register the device."""
    conn = _connect(home)
    try:
        _ensure_pairing_schema(conn)
        row = conn.execute(
            "SELECT * FROM device_pairing_requests WHERE id=? OR user_code=?",
            (code.strip(), code.strip().upper()),
        ).fetchone()
        if not row:
            raise ValueError("Pairing request not found")
        data = dict(row)
        if data["status"] != "pending":
            raise ValueError(f"Pairing request is already {data['status']}")

        expires_at = datetime.fromisoformat(data["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            conn.execute(
                "UPDATE device_pairing_requests SET status='expired' WHERE id=?",
                (data["id"],),
            )
            conn.commit()
            raise ValueError("Pairing request has expired")

        # Mint a scoped API token bound to this tenant and agent DID
        label = f"managed-api:{data['agent_name']}@{data['device_name']}"
        token = issue_token(
            home,
            label,
            profile_id=tenant_id,
            roles=("writer",),
            scopes=("memory:read", "memory:write"),
            ttl_hours=720,  # 30 days
            agent_ids=(data["agent_did"],),
        )

        conn.execute(
            """UPDATE device_pairing_requests 
               SET status='approved', approved_account_id=?, approved_tenant_id=?, issued_token=? 
               WHERE id=?""",
            (account_id, tenant_id, token, data["id"]),
        )
        conn.commit()

        # If managed control is present, record device association in tenant's store
        if service_control is not None:
            try:
                tenant = service_control.tenant({"profile_id": tenant_id, "id": account_id})
                with service_control.store(tenant) as store:
                    store.associate_agent_device(
                        data["agent_did"],
                        data["device_id"],
                        display_name=data["device_name"],
                    )
            except Exception:
                pass  # store-level association is best-effort projection

        record_auth_event(
            home,
            event_type="device_paired",
            profile_id=tenant_id,
            detail=f"{data['agent_name']} on {data['device_name']} ({data['device_id']})",
        )

        return {
            "token": token,
            "callback_url": data["callback_url"],
            "device_id": data["device_id"],
            "agent_did": data["agent_did"],
            "device_name": data["device_name"],
            "tenant_id": tenant_id,
        }
    finally:
        conn.close()


def poll_pairing_status(home: str | Path, device_code: str) -> dict[str, Any]:
    """Poll pairing status with device_code (RFC 8628)."""
    req = get_pairing_request(home, device_code)
    if not req:
        return {"status": "not_found"}

    if req["status"] == "approved":
        conn = _connect(home)
        try:
            conn.execute(
                "UPDATE device_pairing_requests SET redeemed_at=? WHERE id=? AND redeemed_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), req["id"]),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "status": "approved",
            "token": req["issued_token"],
            "tenant_id": req["approved_tenant_id"],
            "agent_did": req["agent_did"],
            "device_id": req["device_id"],
        }

    return {"status": req["status"], "expires_in": req["expires_in"]}
