"""Operator-console administration helpers: API tokens, and the profile's redacted configuration.

The console (viewer/) lets an operator manage credentials and see how the profile is configured
without a shell. Everything here is a pure function over the profile home so it is unit-tested
independent of HTTP (local_api.py calls these from thin route branches, the division the rest of
that module already uses).

Design rules, each one a decision rather than an accident:

  * A token's secret is shown ONCE, at issue time (``issue_console_token`` returns it; nothing
    else ever can -- only a hash is stored, see ingest_tokens.issue_token).
  * A caller can only grant what it holds. An operator may issue reader/writer/reviewer/operator
    credentials; only an admin may issue another admin. A scope is never taken from the request:
    it is derived from the role, so a client cannot ask for a scope the role does not carry.
  * Account sessions (label ``account:<email>``) are NOT API tokens. They are what a signed-in
    browser holds and are managed under Settings -> Account, so they are excluded here.
  * Revoking the credential the request itself used is refused: it would lock the operator out
    of the very screen they are on. (Fail-closed would be to allow it; fail-safe for a human at a
    keyboard is to say no and name the reason.)
  * The configuration view is read-only and carries no filesystem path and no secret. Mode,
    identity and retention are ``config.yaml`` / environment settings that need a restart, so a
    web form that pretended to change them would be a silent mock.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .ingest_tokens import ROLE_SCOPES, issue_token, list_tokens, revoke_token

# Roles an operator may grant. "admin" is deliberately absent: only an admin may mint another.
_OPERATOR_GRANTABLE = ("reader", "writer", "reviewer", "operator")
_MAX_TTL_HOURS = 24 * 365
_DEFAULT_TTL_HOURS = 24 * 30


def grantable_roles(caller_roles: set[str] | list[str]) -> tuple[str, ...]:
    """The roles a credential holding `caller_roles` is allowed to issue."""
    roles = set(caller_roles)
    if "admin" in roles:
        return _OPERATOR_GRANTABLE + ("admin",)
    if "operator" in roles:
        return _OPERATOR_GRANTABLE
    return ()


def _is_account_session(token: dict[str, object]) -> bool:
    return str(token.get("label") or "").startswith("account:")


def _state(token: dict[str, object], now_iso: str) -> str:
    if token.get("revoked_at"):
        return "revoked"
    expires = token.get("expires_at")
    if expires and str(expires) <= now_iso:
        return "expired"
    return "active"


def console_tokens(home: str | Path, profile_id: str) -> list[dict[str, object]]:
    """API tokens for this profile, newest first, with a plain-word state. Never a hash or secret."""
    now_iso = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, object]] = []
    for token in list_tokens(home):
        if token.get("profile_id") != profile_id or _is_account_session(token):
            continue
        out.append({
            "id": token["id"],
            "label": token["label"],
            "roles": token["roles"],
            "scopes": token["scopes"],
            "agent_ids": token["agent_ids"],
            "created_at": token["created_at"],
            "last_used_at": token["last_used_at"],
            "expires_at": token["expires_at"],
            "revoked_at": token["revoked_at"],
            "state": _state(token, now_iso),
        })
    out.sort(key=lambda t: str(t["created_at"]), reverse=True)
    return out


def issue_console_token(
    home: str | Path,
    *,
    profile_id: str,
    caller_roles: set[str] | list[str],
    label: str,
    role: str,
    ttl_hours: int | None = None,
    agent_ids: list[str] | None = None,
) -> dict[str, object]:
    """Issue a token. Returns ``{"token": <raw secret, shown once>, "record": <metadata>}``.

    Raises ValueError (HTTP 400) for a bad request and PermissionError (HTTP 403) when the caller
    may not grant the role.
    """
    label = (label or "").strip()
    if not label:
        raise ValueError("label is required: it is how you will recognise this token in the list")
    if label.startswith("account:"):
        raise ValueError("labels starting with 'account:' are reserved for browser sessions")
    if len(label) > 80:
        raise ValueError("label must be 80 characters or fewer")
    allowed = grantable_roles(caller_roles)
    if role not in ROLE_SCOPES:
        raise ValueError(f"unknown role {role!r}; choose one of {sorted(ROLE_SCOPES)}")
    if role not in allowed:
        raise PermissionError(f"your credential may not issue the {role!r} role")
    ttl = _DEFAULT_TTL_HOURS if ttl_hours is None else int(ttl_hours)
    if ttl < 1 or ttl > _MAX_TTL_HOURS:
        raise ValueError(f"ttl_hours must be between 1 and {_MAX_TTL_HOURS}")
    cleaned_agents = sorted({str(a).strip() for a in (agent_ids or []) if str(a).strip()})
    # The scope list comes from the role, never from the request ("*" is spelled out only for admin).
    scopes = tuple(sorted(ROLE_SCOPES[role]))
    secret = issue_token(
        home, label, profile_id=profile_id, roles=(role,), scopes=scopes,
        ttl_hours=ttl, agent_ids=tuple(cleaned_agents) or None,
    )
    record = next((t for t in console_tokens(home, profile_id) if t["label"] == label and t["state"] == "active"), None)
    return {"token": secret, "record": record}


def revoke_console_token(home: str | Path, profile_id: str, token_id: str, *, current_token_id: str | None) -> bool:
    """Revoke by id. Refuses to revoke the credential making the request, or a non-API token."""
    token_id = (token_id or "").strip()
    if not token_id:
        raise ValueError("token_id is required")
    if current_token_id and token_id == current_token_id:
        raise ValueError("this is the credential you are using right now; revoking it would end this session")
    target = next((t for t in list_tokens(home) if t["id"] == token_id and t.get("profile_id") == profile_id), None)
    if target is None or _is_account_session(target):
        return False
    return revoke_token(home, token_id)


# --- redacted profile configuration ----------------------------------------------------------------------

def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def public_profile_config(home: str | Path, *, environ: dict[str, str] | None = None) -> dict[str, object]:
    """What the profile is configured to do, in words a person can read. No paths, no secrets.

    Values that name a place on disk or a network location are reduced to "configured" or "not
    configured": the browser is told that a backup destination exists, never where it is.
    """
    env = dict(os.environ if environ is None else environ)
    config = load_config(home=home, environ=env)
    data = config.redacted_dict()
    storage = data.get("storage") or {}
    remote = data.get("remote") or {}
    return {
        "profile_id": data.get("profile_id"),
        "mode": data.get("mode"),
        "identity_mode": env.get("XIBALBA_CORTEX_IDENTITY_MODE") or "pseudonymous",
        "retention_tier": env.get("XIBALBA_CORTEX_RETENTION_TIER") or "digest",
        "storage": {"backend": storage.get("backend"), "pool_size": storage.get("pool_size"), "ssl_mode": storage.get("ssl_mode")},
        "inference": {k: v for k, v in (data.get("inference") or {}).items()},
        "embeddings": data.get("embeddings"),
        "retrieval": data.get("retrieval"),
        "features": data.get("features"),
        "telemetry": data.get("telemetry"),
        "quotas": data.get("quotas"),
        "auth": data.get("auth"),
        "remote": {"configured": _present(remote)},
        # places the server uses but the browser must never be told
        "destinations": {
            "backup": _present(env.get("XIBALBA_BACKUP_DIR")),
            "vault": _present(env.get("XIBALBA_VAULT_DIR")),
            "integrity_dag": _present(env.get("XIBALBA_DAG_HOME")),
            "anchor_service": _present(env.get("XIBALBA_ANCHOR_URL")),
            "oracle": _present(env.get("XIBALBA_ORACLE_URL")),
        },
        "changed_by": "config.yaml or environment variables; a change needs a restart",
    }
