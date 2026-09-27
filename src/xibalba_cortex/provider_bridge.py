"""Bounded request/response bridge for the Hermes native memory provider.

This bridge is intentionally narrower than model-visible Model Context Protocol dispatch.
It accepts explicit operations over standard input and returns one JSON response. The
Hermes provider runs in Hermes' virtual environment; this module runs in Cortex' virtual
environment and owns the GraphStore boundary.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from .server import (
    get_store,
    memory_hybrid_retrieve,
    memory_ingest_agent_turn,
    memory_session_end,
    memory_session_start,
)
from .store import GraphStore


_LEGACY_PROFILE_ALIASES = {
    # These namespaces were used by the default Hermes provider before its DID
    # binding was made canonical. Source metadata was verified as profile=default,
    # runtime=hermes; keep it queryable without rewriting its original provenance.
    "default": ("xibalba.agent",),
    "custom": ("xibalba.agent",),
}


def _legacy_agent_ids(store: GraphStore, profile: str, agent_id: str) -> list[str]:
    aliases = _LEGACY_PROFILE_ALIASES.get(profile, ())
    if not aliases:
        return []
    resolved: list[str] = []
    for alias in aliases:
        if store.has_agent_partition(alias):
            resolved.append(alias)
        # Older records were written with Cortex's profile-local HMAC namespace.
        # Derive only the exact alias pseudonym from the same store salt and add it
        # only if rows under that persisted ID exist.
        legacy_store = GraphStore(
            store.home,
            profile_id=getattr(store, "profile_id", "default"),
            identity_mode="pseudonymous",
            readonly=True,
        )
        try:
            pseudonym = legacy_store.storage_agent_id(alias)
        finally:
            legacy_store.close()
        if pseudonym and pseudonym != agent_id and store.has_agent_partition(pseudonym):
            resolved.append(pseudonym)
    return list(dict.fromkeys(resolved))

def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    operation = str(request.get("operation") or "")
    requested_agent = str(request.get("agent_id") or "").strip()
    bound_agent = str(os.environ.get("XIBALBA_AGENT_ID") or "").strip()
    if not bound_agent or requested_agent != bound_agent:
        raise PermissionError("provider bridge identity does not match its bound agent")
    store = get_store()
    if store.identity_mode != "full":
        raise PermissionError("provider bridge requires full identity attribution")
    if store.storage_agent_id(requested_agent) != requested_agent:
        raise PermissionError("provider bridge identity does not resolve to its bound agent namespace")
    requested_profile = str(request.get("profile") or "").strip()
    bound_profile = str(os.environ.get("XIBALBA_AGENT_PROFILE") or "").strip()
    if bound_profile and requested_profile and requested_profile != bound_profile:
        raise PermissionError("provider bridge profile does not match its bound profile")
    if operation == "session_start":
        return memory_session_start(
            str(request["session_id"]), request.get("retention_tier"),
            agent_id=str(request["agent_id"]),
        )
    if operation == "session_end":
        return memory_session_end(
            str(request["session_id"]),
            summary_content=request.get("summary_content"),
            source={**dict(request.get("source") or {}), "agent_id": requested_agent},
        )
    if operation == "recall":
        query = str(request.get("query") or "")
        limit = max(1, min(int(request.get("limit", 8)), 20))
        max_total_chars = max(1000, min(int(request.get("max_total_chars", 12000)), 32000))
        identities = [requested_agent]
        if requested_profile:
            identities.extend(_legacy_agent_ids(store, requested_profile, requested_agent))
        recalls = [
            memory_hybrid_retrieve(
                query,
                limit=limit,
                max_total_chars=max_total_chars,
                filters={"agent_id": identity},
            )
            for identity in identities
        ]
        primary = recalls[0] if recalls else {"results": []}
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        # Interleave namespaces by rank so legacy rows remain eligible even when
        # the canonical DID partition alone fills the result limit.
        for rank in range(max((len(item.get("results", [])) for item in recalls), default=0)):
            for recall in recalls:
                rows = recall.get("results", [])
                if rank >= len(rows):
                    continue
                row = rows[rank]
                memory_id = str(row.get("id") or "")
                if memory_id and memory_id not in seen:
                    seen.add(memory_id)
                    merged.append(row)
                    if len(merged) >= limit:
                        break
            if len(merged) >= limit:
                break
        primary["results"] = merged
        primary["compatibility_trace_ids"] = [
            trace_id for recall in recalls[1:]
            if isinstance((trace_id := recall.get("trace_id")), str)
        ]
        return primary
    if operation == "sync_turn":
        return memory_ingest_agent_turn(
            str(request["session_id"]),
            runtime="hermes",
            prompt=str(request.get("prompt") or ""),
            response=str(request.get("response") or ""),
            tool_calls=list(request.get("tool_calls") or []),
            agent_id=request.get("agent_id"),
            prompt_id=request.get("turn_id"),
            metadata=dict(request.get("metadata") or {}),
            idempotency_key=str(request["idempotency_key"]),
        )
    raise ValueError(f"unsupported provider operation: {operation!r}")


def main() -> int:
    try:
        request = json.loads(sys.stdin.read() or "{}")
        result = dispatch(request)
        print(json.dumps({"ok": True, "result": result}, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
