"""Local account and session model for the Cortex operator API.

This is intentionally local-first: passwords are scrypt-hashed and bearer session
tokens are stored only as SHA-256 hashes. Existing issued ingest tokens remain
supported; account sessions are represented in the same credential table so every
authenticated Cortex route keeps one authorization path.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .ingest_tokens import _connect, _hash, effective_scopes, ROLE_SCOPES

_ACCOUNT_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    profile_id TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL DEFAULT 'active',
    role TEXT NOT NULL DEFAULT 'operator',
    email_verified INTEGER NOT NULL DEFAULT 1,
    approval_status TEXT NOT NULL DEFAULT 'approved',
    controller_address TEXT,
    agent_ids_json TEXT NOT NULL DEFAULT '[]',
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email);
CREATE TABLE IF NOT EXISTS user_agent_registrations (
    account_id TEXT NOT NULL,
    agent_did TEXT NOT NULL,
    chain_id INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    tx_hash TEXT NOT NULL,
    log_index INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    finalized INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL,
    revoked_at TEXT,
    PRIMARY KEY (account_id, agent_did)
    -- A directory snapshot cursor may cover several agents; uniqueness is enforced
    -- by the account/DID primary key while the cursor remains auditable metadata.
);
CREATE INDEX IF NOT EXISTS idx_user_agent_registrations_account ON user_agent_registrations(account_id, status, finalized);
CREATE TABLE IF NOT EXISTS core_registration_cursors (
    account_id TEXT NOT NULL,
    chain_id INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    snapshot_id TEXT NOT NULL,
    log_index INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (account_id, chain_id)
);
CREATE TABLE IF NOT EXISTS auth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT,
    email TEXT,
    event_type TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);
"""

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _normalize_email(email: str) -> str:
    return email.strip().lower()

def _password_hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode()

def _password_matches(password: str, salt_text: str, digest_text: str) -> bool:
    try:
        salt = base64.urlsafe_b64decode(salt_text.encode())
        _, candidate = _password_hash(password, salt)
        return hmac.compare_digest(candidate, digest_text)
    except (ValueError, TypeError):
        return False

def _ensure_schema(home: str | Path) -> None:
    conn = _connect(home)
    try:
        conn.executescript(_ACCOUNT_SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)")}
        if "role" not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN role TEXT NOT NULL DEFAULT 'operator'")
        if "failed_attempts" not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0")
        if "locked_until" not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN locked_until TEXT")
        if "email_verified" not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1")
        if "approval_status" not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'approved'")
        if "agent_ids_json" not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN agent_ids_json TEXT NOT NULL DEFAULT '[]'")
        if "controller_address" not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN controller_address TEXT")
        conn.commit()
    finally:
        conn.close()

def create_account(home: str | Path, *, email: str, password: str, display_name: str, profile_id: str = "default") -> dict[str, object]:
    email = _normalize_email(email)
    display_name = display_name.strip()
    if "@" not in email or len(email) > 320:
        raise ValueError("a valid email is required")
    if not display_name or len(display_name) > 120:
        raise ValueError("display name is required")
    _ensure_schema(home)
    salt, digest = _password_hash(password)
    account_id = str(uuid.uuid4())
    now = _now()
    conn = _connect(home)
    try:
        conn.execute("INSERT INTO accounts(id,email,display_name,password_hash,password_salt,profile_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (account_id, email, display_name, digest, salt, profile_id, now, now))
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("an account with that email already exists") from exc
    finally:
        conn.close()
    record_auth_event(home, event_type="account_created", email=email, profile_id=profile_id)
    return {"id": account_id, "email": email, "display_name": display_name, "profile_id": profile_id, "role": "operator", "status": "active", "email_verified": True, "approval_status": "approved", "controller_address": None, "agent_ids": [], "created_at": now}

def _account(home: str | Path, email: str) -> sqlite3.Row | None:
    _ensure_schema(home)
    conn = _connect(home)
    try:
        return conn.execute("SELECT * FROM accounts WHERE email=? AND status='active'", (_normalize_email(email),)).fetchone()
    finally:
        conn.close()


def _registered_agent_ids(conn: sqlite3.Connection, account_id: str) -> list[str]:
    """Read only active, finalized registrations; legacy JSON is a fallback projection."""
    rows = conn.execute(
        "SELECT agent_did FROM user_agent_registrations WHERE account_id=? AND status='active' AND finalized=1 ORDER BY agent_did",
        (account_id,),
    ).fetchall()
    return [str(row["agent_did"]) for row in rows]

def record_auth_event(home: str | Path, *, event_type: str, email: str | None = None, profile_id: str | None = None, detail: str | None = None) -> None:
    conn = _connect(home)
    try:
        conn.execute("INSERT INTO auth_events(profile_id,email,event_type,detail,created_at) VALUES(?,?,?,?,?)", (profile_id, _normalize_email(email) if email else None, event_type, detail, _now()))
        conn.commit()
    finally:
        conn.close()

def issue_account_session(home: str | Path, *, email: str, password: str, ttl_hours: int = 24) -> tuple[str, dict[str, object]]:
    row = _account(home, email)
    normalized = _normalize_email(email)
    now = datetime.now(timezone.utc)
    if row is None:
        record_auth_event(home, event_type="login_failed", email=normalized, detail="unknown account")
        raise ValueError("invalid email or password")
    if not row["email_verified"] or row["approval_status"] != "approved":
        record_auth_event(home, event_type="login_blocked", email=normalized, profile_id=row["profile_id"], detail="verification or administrator approval required")
        raise ValueError("account requires email verification or administrator approval")
    locked_until = row["locked_until"]
    if locked_until:
        try:
            if datetime.fromisoformat(locked_until.replace("Z", "+00:00")) > now:
                record_auth_event(home, event_type="login_blocked", email=normalized, profile_id=row["profile_id"], detail="account lockout")
                raise ValueError("account temporarily locked; try again later")
        except ValueError as exc:
            if str(exc).startswith("account temporarily locked"):
                raise
    if not _password_matches(password, row["password_salt"], row["password_hash"]):
        attempts = int(row["failed_attempts"] or 0) + 1
        locked = (now + timedelta(minutes=15)).isoformat() if attempts >= 5 else None
        conn = _connect(home)
        try:
            conn.execute("UPDATE accounts SET failed_attempts=?, locked_until=? WHERE id=?", (attempts, locked, row["id"]))
            conn.commit()
        finally:
            conn.close()
        record_auth_event(home, event_type="login_failed", email=normalized, profile_id=row["profile_id"], detail="locked" if locked else "invalid password")
        raise ValueError("invalid email or password")
    conn = _connect(home)
    try:
        registered_ids = _registered_agent_ids(conn, str(row["id"]))
        effective_ids = registered_ids or json.loads(row["agent_ids_json"] or "[]")
        conn.execute("UPDATE accounts SET failed_attempts=0, locked_until=NULL WHERE id=?", (row["id"],))
        token = secrets.token_urlsafe(32)
        expires = (now + timedelta(hours=ttl_hours)).isoformat()
        conn.execute("INSERT INTO ingest_tokens(id,label,token_hash,profile_id,roles_json,scopes_json,expires_at,agent_id,agent_ids_json) VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), f"account:{row['email']}", _hash(token), row["profile_id"], json.dumps(["operator"]), json.dumps(sorted(ROLE_SCOPES["operator"])), expires, None, json.dumps(effective_ids)))
        conn.commit()
    finally:
        conn.close()
    record_auth_event(home, event_type="login_succeeded", email=normalized, profile_id=row["profile_id"])
    return token, {"id": row["id"], "email": row["email"], "display_name": row["display_name"], "profile_id": row["profile_id"], "role": row["role"], "status": row["status"], "email_verified": bool(row["email_verified"]), "approval_status": row["approval_status"], "controller_address": row["controller_address"], "agent_ids": effective_ids, "created_at": row["created_at"]}

def account_for_token(home: str | Path, token: str) -> dict[str, object] | None:
    record = None
    candidate = _hash(token)
    conn = _connect(home)
    try:
        row = conn.execute("SELECT label FROM ingest_tokens WHERE token_hash=? AND revoked_at IS NULL", (candidate,)).fetchone()
        if not row or not str(row["label"]).startswith("account:"):
            return None
        email = str(row["label"])[8:]
    finally:
        conn.close()
    row = _account(home, email)
    if row is None:
        return None
    conn = _connect(home)
    try:
        agent_ids = _registered_agent_ids(conn, str(row["id"])) or json.loads(row["agent_ids_json"] or "[]")
    finally:
        conn.close()
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"], "profile_id": row["profile_id"], "role": row["role"], "status": row["status"], "email_verified": bool(row["email_verified"]), "approval_status": row["approval_status"], "controller_address": row["controller_address"], "agent_ids": agent_ids, "created_at": row["created_at"]}


def set_account_agent_ids(home: str | Path, *, account_id: str, agent_ids: list[str]) -> bool:
    """Synchronize an account's agent access from a trusted CORE indexer.

    This is intentionally a service-layer operation, not a browser-facing self-grant.
    The caller must have already verified controller ownership and chain finality.
    """
    normalized = sorted({str(value).strip() for value in agent_ids if str(value).strip()})
    _ensure_schema(home)
    conn = _connect(home)
    try:
        changed = conn.execute("UPDATE accounts SET agent_ids_json=?, updated_at=? WHERE id=? AND status='active'", (json.dumps(normalized), _now(), account_id)).rowcount
        conn.commit()
    finally:
        conn.close()
    if changed:
        record_auth_event(home, event_type="agent_registrations_synced", detail=f"account={account_id};count={len(normalized)}")
    return bool(changed)


def set_account_controller(home: str | Path, *, account_id: str, controller_address: str) -> bool:
    """Bind an account to a normalized EVM controller from a trusted auth/indexer flow."""
    normalized = str(controller_address).strip().lower()
    if len(normalized) != 42 or not normalized.startswith("0x"):
        raise ValueError("controller_address must be a 20-byte EVM address")
    _ensure_schema(home)
    conn = _connect(home)
    try:
        changed = conn.execute("UPDATE accounts SET controller_address=?, updated_at=? WHERE id=? AND status='active'", (normalized, _now(), account_id)).rowcount
        conn.commit()
    finally:
        conn.close()
    if changed:
        record_auth_event(home, event_type="controller_bound", detail=f"account={account_id};controller={normalized}")
    return bool(changed)


def sync_account_registrations(home: str | Path, *, account_id: str, chain_id: int, block_number: int, tx_hash: str, log_index: int, agent_ids: list[str], finalized: bool) -> bool:
    """Replace the active finalized registration projection from a CORE snapshot."""
    normalized = sorted({str(value).strip() for value in agent_ids if str(value).startswith("did:integrity:")})
    if not tx_hash or block_number < 0 or chain_id < 0 or log_index < 0:
        raise ValueError("invalid CORE registration cursor")
    _ensure_schema(home)
    now = _now()
    conn = _connect(home)
    try:
        account_row = conn.execute("SELECT email FROM accounts WHERE id=? AND status='active'", (account_id,)).fetchone()
        if account_row is None:
            return False
        cursor = conn.execute("SELECT block_number,snapshot_id FROM core_registration_cursors WHERE account_id=? AND chain_id=?", (account_id, chain_id)).fetchone()
        if cursor is not None:
            previous_block = int(cursor["block_number"])
            previous_snapshot = str(cursor["snapshot_id"])
            if block_number < previous_block:
                raise ValueError("CORE registration snapshot is older than the applied cursor")
            if block_number == previous_block and tx_hash != previous_snapshot:
                raise ValueError("CORE registration snapshot conflicts at the applied cursor")
        conn.execute("UPDATE user_agent_registrations SET status='revoked', revoked_at=? WHERE account_id=? AND status='active'", (now, account_id))
        for agent_id in normalized:
            conn.execute(
                "INSERT INTO user_agent_registrations(account_id,agent_did,chain_id,block_number,tx_hash,log_index,status,finalized,observed_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,agent_did) DO UPDATE SET chain_id=excluded.chain_id,block_number=excluded.block_number,tx_hash=excluded.tx_hash,log_index=excluded.log_index,status='active',finalized=excluded.finalized,observed_at=excluded.observed_at,revoked_at=NULL",
                (account_id, agent_id, chain_id, block_number, tx_hash, log_index, "active", 1 if finalized else 0, now),
            )
        conn.execute(
            "INSERT INTO core_registration_cursors(account_id,chain_id,block_number,snapshot_id,log_index,observed_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(account_id,chain_id) DO UPDATE SET block_number=excluded.block_number,snapshot_id=excluded.snapshot_id,log_index=excluded.log_index,observed_at=excluded.observed_at",
            (account_id, chain_id, block_number, tx_hash, log_index, now),
        )
        conn.commit()
    finally:
        conn.close()
    effective_ids = normalized if finalized else []
    conn = _connect(home)
    try:
        conn.execute("UPDATE ingest_tokens SET agent_ids_json=? WHERE label=? AND revoked_at IS NULL", (json.dumps(effective_ids), f"account:{account_row['email']}"))
        conn.commit()
    finally:
        conn.close()
    return set_account_agent_ids(home, account_id=account_id, agent_ids=effective_ids)

def approve_account(home: str | Path, *, email: str, verified: bool = True) -> bool:
    row = _account(home, email)
    if row is None:
        return False
    conn = _connect(home)
    try:
        conn.execute("UPDATE accounts SET email_verified=?, approval_status='approved', updated_at=? WHERE id=?", (1 if verified else 0, _now(), row["id"]))
        conn.commit()
    finally:
        conn.close()
    record_auth_event(home, event_type="account_approved", email=row["email"], profile_id=row["profile_id"])
    return True

def change_account_password(home: str | Path, *, token: str, current_password: str, new_password: str) -> bool:
    account = account_for_token(home, token)
    if account is None:
        return False
    row = _account(home, str(account["email"]))
    if row is None or not _password_matches(current_password, row["password_salt"], row["password_hash"]):
        record_auth_event(home, event_type="password_change_failed", email=str(account["email"]), profile_id=str(account["profile_id"]), detail="invalid current password")
        return False
    salt, digest = _password_hash(new_password)
    conn = _connect(home)
    try:
        conn.execute("UPDATE accounts SET password_hash=?, password_salt=?, failed_attempts=0, locked_until=NULL, updated_at=? WHERE id=?", (digest, salt, _now(), row["id"]))
        conn.commit()
    finally:
        conn.close()
    record_auth_event(home, event_type="password_changed", email=str(account["email"]), profile_id=str(account["profile_id"]))
    return True

def request_password_reset(home: str | Path, *, email: str, ttl_minutes: int = 30) -> str | None:
    row = _account(home, email)
    if row is None:
        record_auth_event(home, event_type="password_reset_requested", email=_normalize_email(email), detail="unknown account")
        return None
    raw = secrets.token_urlsafe(32)
    token_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    conn = _connect(home)
    try:
        conn.execute("INSERT INTO password_reset_tokens(id,account_id,token_hash,expires_at,created_at) VALUES(?,?,?,?,?)", (token_id, row["id"], _hash(raw), (now + timedelta(minutes=ttl_minutes)).isoformat(), _now()))
        conn.commit()
    finally:
        conn.close()
    reset_url = os.environ.get("CORTEX_PASSWORD_RESET_URL", "").strip()
    if not reset_url:
        conn = _connect(home)
        try:
            conn.execute("DELETE FROM password_reset_tokens WHERE id=?", (token_id,))
            conn.commit()
        finally:
            conn.close()
        raise RuntimeError("CORTEX_PASSWORD_RESET_URL is required for password reset delivery")
    separator = "&" if "?" in reset_url else "?"
    try:
        from .email_delivery import send_email
        send_email(row["email"], "Reset your Xibalba Cortex password", f"Use this time-limited link to reset your password:\n\n{reset_url}{separator}token={raw}\n")
    except Exception as exc:
        conn = _connect(home)
        try:
            conn.execute("DELETE FROM password_reset_tokens WHERE id=?", (token_id,))
            conn.commit()
        finally:
            conn.close()
        raise RuntimeError("password reset email delivery failed") from exc
    record_auth_event(home, event_type="password_reset_requested", email=row["email"], profile_id=row["profile_id"], detail="email delivered")
    return raw

def reset_password(home: str | Path, *, reset_token: str, new_password: str) -> bool:
    now = datetime.now(timezone.utc)
    conn = _connect(home)
    try:
        row = conn.execute("SELECT id,account_id,expires_at FROM password_reset_tokens WHERE token_hash=? AND used_at IS NULL", (_hash(reset_token),)).fetchone()
        if row is None or datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")) <= now:
            return False
        salt, digest = _password_hash(new_password)
        conn.execute("UPDATE accounts SET password_hash=?,password_salt=?,failed_attempts=0,locked_until=NULL,updated_at=? WHERE id=?", (digest, salt, _now(), row["account_id"]))
        conn.execute("UPDATE password_reset_tokens SET used_at=? WHERE id=?", (_now(), row["id"]))
        conn.commit()
        email_row = conn.execute("SELECT email,profile_id FROM accounts WHERE id=?", (row["account_id"],)).fetchone()
    finally:
        conn.close()
    record_auth_event(home, event_type="password_reset_completed", email=email_row["email"] if email_row else None, profile_id=email_row["profile_id"] if email_row else None)
    return True

def revoke_account_session(home: str | Path, token: str) -> bool:
    conn = _connect(home)
    try:
        cur = conn.execute("UPDATE ingest_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE token_hash=? AND label LIKE 'account:%' AND revoked_at IS NULL", (_hash(token),))
        conn.commit()
        revoked = cur.rowcount > 0
    finally:
        conn.close()
    record_auth_event(home, event_type="logout", detail="revoked" if revoked else "already revoked")
    return revoked

def revoke_account_session_by_id(home: str | Path, *, current_token: str, session_id: str) -> bool:
    account = account_for_token(home, current_token)
    if account is None:
        return False
    conn = _connect(home)
    try:
        cur = conn.execute("UPDATE ingest_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE id=? AND label=? AND revoked_at IS NULL", (session_id, f"account:{account['email']}"))
        conn.commit()
        revoked = cur.rowcount > 0
    finally:
        conn.close()
    record_auth_event(home, event_type="session_revoked", email=str(account["email"]), profile_id=str(account["profile_id"]), detail=session_id)
    return revoked
