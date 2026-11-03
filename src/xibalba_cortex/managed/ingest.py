"""Transport-neutral ingestion for the managed edition.

Resolves a bearer token to the workspace it was issued for, applies the managed write
contract (scope, metering, per-tenant serialisation, plan quota) and hands the turn to
`GraphStore.ingest_agent_turn`. That method owns every session, exchange and otel decision;
nothing here may grow any. REST and MCP are both thin callers of `ingest_turn`.
"""
from __future__ import annotations

import hashlib
import json

from ..ingest_tokens import verify_token_record
from .control import LimitExceeded, ManagedControl

MAX_TOOL_CALLS = 100
MAX_IDENTIFIER = 256
# Keys `ingest_agent_turn` stamps into every memory's source; caller metadata must not shadow them.
_RESERVED_METADATA = frozenset({"session_id", "prompt_id", "agent_id", "runtime", "kind", "role", "observed_at", "locator"})


def _text(data: dict, key: str, *, limit: int, required: bool = True) -> str | None:
    value = data.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{key} must be a non-empty string")
    if len(value.encode()) > limit:
        raise ValueError(f"{key} exceeds the {limit} byte limit")
    return value


def _agent_id(principal: dict, requested: str | None) -> str | None:
    bound = list(principal.get("agent_ids") or [])
    if requested is not None:
        # A key speaks only for the identities it was issued for.
        if requested not in bound:
            raise PermissionError("This API key is not bound to that agent_id")
        return requested
    return bound[0] if len(bound) == 1 else None


def ingest_turn(service: ManagedControl, token: str, payload: dict, *, request_key: str) -> dict:
    principal = verify_token_record(service.identity_home, token) if token else None
    if principal is None:
        raise PermissionError("Sign in to your managed workspace")
    if "memory:write" not in principal["scopes"]:
        raise PermissionError("This API key lacks memory:write")
    # The workspace is the one the token was issued for. Nothing in the payload can select it.
    with service.db() as db:
        row = db.execute("SELECT * FROM tenants WHERE id=?", (principal["profile_id"],)).fetchone()
    if row is None:
        raise PermissionError("Unknown managed workspace")
    tenant = dict(row)

    limit = service.config.max_content_bytes
    session_id = _text(payload, "external_session_id", limit=MAX_IDENTIFIER)
    runtime = _text(payload, "runtime", limit=MAX_IDENTIFIER)
    prompt = _text(payload, "prompt", limit=limit)
    response = _text(payload, "response", limit=limit)
    prompt_id = _text(payload, "prompt_id", limit=MAX_IDENTIFIER, required=False)
    prompt_time = _text(payload, "prompt_time", limit=MAX_IDENTIFIER, required=False)
    response_time = _text(payload, "response_time", limit=MAX_IDENTIFIER, required=False)
    tool_calls = payload.get("tool_calls") or []
    if not isinstance(tool_calls, list) or len(tool_calls) > MAX_TOOL_CALLS or not all(isinstance(c, dict) for c in tool_calls):
        raise ValueError(f"tool_calls must be a list of at most {MAX_TOOL_CALLS} objects")
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    metadata = {k: v for k, v in (metadata or {}).items() if k not in _RESERVED_METADATA}
    agent_id = _agent_id(principal, _text(payload, "agent_id", limit=MAX_IDENTIFIER, required=False))

    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with service.write_guard(tenant):
        service.consume(tenant, "writes", request_key=request_key, fingerprint=fingerprint)
        with service.store(tenant) as store:
            try:
                return store.ingest_agent_turn(session_id, runtime=runtime, prompt=prompt, response=response,
                    tool_calls=tool_calls, agent_id=agent_id, prompt_id=prompt_id, prompt_time=prompt_time,
                    response_time=response_time, metadata=metadata, idempotency_key=request_key)
            except RuntimeError as exc:
                if str(exc).startswith("memory quota exceeded:"):
                    raise LimitExceeded("Stored-memory capacity reached; export data or choose a larger plan") from None
                raise
