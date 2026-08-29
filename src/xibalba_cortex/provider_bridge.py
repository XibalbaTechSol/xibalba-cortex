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
    memory_hybrid_retrieve,
    memory_ingest_agent_turn,
    memory_session_end,
    memory_session_start,
)


def dispatch(request: dict[str, Any]) -> dict[str, Any]:
    operation = str(request.get("operation") or "")
    if operation == "session_start":
        return memory_session_start(
            str(request["session_id"]), request.get("retention_tier")
        )
    if operation == "session_end":
        return memory_session_end(
            str(request["session_id"]),
            summary_content=request.get("summary_content"),
            source=request.get("source"),
        )
    if operation == "recall":
        return memory_hybrid_retrieve(
            str(request.get("query") or ""),
            limit=max(1, min(int(request.get("limit", 8)), 20)),
            max_total_chars=max(1000, min(int(request.get("max_total_chars", 12000)), 32000)),
            filters={"status": "active"},
        )
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
