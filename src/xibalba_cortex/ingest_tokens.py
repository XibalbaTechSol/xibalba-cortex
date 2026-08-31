"""Per-harness API-key auth store for the network-reachable generic ingestion path
(streamable-HTTP MCP transport, see `server.py --transport streamable-http` and
`auth_middleware.py`).

Deliberately a **separate** SQLite file (`<home>/ingest_tokens.sqlite3`), not a table inside
`graph-memory.sqlite3`: this is security-sensitive credential state with a different lifecycle
(issued/revoked by an operator, never touched by normal memory-write traffic) than memory
content, and keeping it in its own file means a memory-store backup/restore never accidentally
carries live credentials along with it, and a credential rotation never touches the memory
schema/migrations.

Only a token's SHA-256 hash is ever stored -- the raw token is generated with `secrets.token_urlsafe`
(cryptographically random) and shown to the caller exactly once, at issuance. There is no way to
recover a lost raw token from this store; issuing a new one and revoking the old is the only path,
matching how every real API-key system works (GitHub, Stripe, etc.) -- this is deliberate, not a
missing feature.

A single shared-token deployment is just one row (e.g. `label="default"`) -- there is no separate
"shared mode"; every deployment uses the same per-harness-named-token mechanism.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import hmac
import secrets
import sqlite3
import uuid
from pathlib import Path

_DB_FILENAME = "ingest_tokens.sqlite3"

ROLE_SCOPES: dict[str, frozenset[str]] = {
    "reader": frozenset({"memory:read"}),
    "writer": frozenset({"memory:read", "memory:write"}),
    "operator": frozenset({"memory:read", "memory:write", "memory:delete", "proposal:decide"}),
    "reviewer": frozenset({"memory:read", "proposal:decide"}),
    "admin": frozenset({"*" }),
}

def effective_scopes(roles: list[str], requested: list[str]) -> list[str]:
    grants = set()
    for role in roles:
        grants.update(ROLE_SCOPES.get(role, ()))
    if "*" in grants:
        return sorted(set(requested))
    return sorted(set(requested) & grants)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_tokens (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT,
    revoked_at TEXT,
    profile_id TEXT NOT NULL DEFAULT 'default',
    roles_json TEXT NOT NULL DEFAULT '["reader"]',
    scopes_json TEXT NOT NULL DEFAULT '["memory:read"]'
);
"""


def _db_path(home: str | Path) -> Path:
    home = Path(home).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    return home / _DB_FILENAME


def _connect(home: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(home))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(ingest_tokens)")}
    for name, definition in (("profile_id", "TEXT NOT NULL DEFAULT 'default'"), ("roles_json", "TEXT NOT NULL DEFAULT '[\"reader\"]'"), ("scopes_json", "TEXT NOT NULL DEFAULT '[\"memory:read\"]'")):
        if name not in columns:
            conn.execute(f"ALTER TABLE ingest_tokens ADD COLUMN {name} {definition}")
    return conn


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_token(home: str | Path, label: str, *, profile_id: str = "default", roles: tuple[str, ...] = ("writer",), scopes: tuple[str, ...] = ("memory:read",)) -> str:
    """Generate a new random token for `label`, store only its hash, and return the raw
    token. This is the only moment the raw value exists outside the caller's own hands --
    it is never logged, never stored, and cannot be recovered later."""
    if not label or not label.strip():
        raise ValueError("label must be a non-empty string")
    if not profile_id or not profile_id.strip():
        raise ValueError("profile_id must be a non-empty string")
    if not roles or any(not item.strip() for item in roles):
        raise ValueError("roles must contain non-empty strings")
    if not scopes or any(not item.strip() for item in scopes):
        raise ValueError("scopes must contain non-empty strings")
    raw_token = secrets.token_urlsafe(32)
    conn = _connect(home)
    try:
        conn.execute(
            "INSERT INTO ingest_tokens(id, label, token_hash, profile_id, roles_json, scopes_json) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), label.strip(), _hash(raw_token), profile_id.strip(), json.dumps(list(roles)), json.dumps(list(scopes))),
        )
        conn.commit()
    finally:
        conn.close()
    return raw_token


def verify_token_record(home: str | Path, raw_token: str) -> dict[str, object] | None:
    """Return the matching label if `raw_token` is valid and not revoked, else None.
    Updates `last_used_at` on success. Hash comparison uses `hmac.compare_digest` (constant
    time) so response timing can't be used to guess a valid hash byte-by-byte."""
    if not raw_token:
        return None
    candidate_hash = _hash(raw_token)
    conn = _connect(home)
    try:
        rows = conn.execute(
            "SELECT id, label, token_hash, profile_id, roles_json, scopes_json FROM ingest_tokens WHERE revoked_at IS NULL"
        ).fetchall()
        for row in rows:
            if hmac.compare_digest(row["token_hash"], candidate_hash):
                conn.execute(
                    "UPDATE ingest_tokens SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (row["id"],),
                )
                conn.commit()
                roles = json.loads(row["roles_json"])
                scopes = json.loads(row["scopes_json"])
                return {"id": row["id"], "label": row["label"], "profile_id": row["profile_id"], "roles": roles, "scopes": effective_scopes(roles, scopes)}
        return None
    finally:
        conn.close()


def verify_token(home: str | Path, raw_token: str) -> str | None:
    record = verify_token_record(home, raw_token)
    return str(record["label"]) if record else None


def revoke_token(home: str | Path, token_id: str) -> bool:
    """Mark a token revoked by its id (not its label -- labels aren't unique, ids are).
    Returns True if a row was actually revoked, False if the id didn't exist or was already
    revoked."""
    conn = _connect(home)
    try:
        cursor = conn.execute(
            "UPDATE ingest_tokens SET revoked_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND revoked_at IS NULL",
            (token_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_tokens(home: str | Path) -> list[dict[str, object]]:
    """List every issued token's metadata -- never the hash, so this is safe to print/log."""
    conn = _connect(home)
    try:
        rows = conn.execute(
            "SELECT id, label, profile_id, roles_json, scopes_json, created_at, last_used_at, revoked_at FROM ingest_tokens "
            "ORDER BY created_at"
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["roles"] = json.loads(item.pop("roles_json"))
            item["scopes"] = effective_scopes(item["roles"], json.loads(item.pop("scopes_json")))
            result.append(item)
        return result
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, help="xibalba-cortex profile home")
    sub = parser.add_subparsers(dest="command", required=True)

    p_issue = sub.add_parser("issue", help="issue a new token for a harness/label")
    p_issue.add_argument("--label", required=True, help='e.g. "perplexity-personal"')
    p_issue.add_argument("--profile-id", default="default")
    p_issue.add_argument("--role", action="append", dest="roles", default=None)
    p_issue.add_argument("--scope", action="append", dest="scopes", default=None)

    p_revoke = sub.add_parser("revoke", help="revoke a token by its id")
    p_revoke.add_argument("--id", required=True, dest="token_id")

    sub.add_parser("list", help="list all issued tokens (labels/timestamps only, never hashes)")

    args = parser.parse_args()

    if args.command == "issue":
        raw_token = issue_token(args.home, args.label, profile_id=args.profile_id, roles=tuple(args.roles or ("reader",)), scopes=tuple(args.scopes or ("memory:read",)))
        print(f"Issued token for {args.label!r}. Shown once, save it now:")
        print(raw_token)
    elif args.command == "revoke":
        revoked = revoke_token(args.home, args.token_id)
        print("OK   revoked" if revoked else "FAIL no matching unrevoked token id")
    elif args.command == "list":
        for row in list_tokens(args.home):
            status = "revoked" if row["revoked_at"] else "active"
            print(
                f"{row['id']}  {row['label']:24}  {status:8}  "
                f"profile={row['profile_id']} roles={','.join(row['roles'])} scopes={','.join(row['scopes'])} created={row['created_at']} last_used={row['last_used_at'] or '(never)'}"
            )


if __name__ == "__main__":
    main()
