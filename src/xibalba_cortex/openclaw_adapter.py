"""OpenClaw native-plugin telemetry adapter.

OpenClaw exposes typed in-process plugin hooks (``api.on(...)``) and a separate internal
``HOOK.md`` system. This adapter models the typed hook payloads and deliberately does not treat
coarse internal hooks or Gateway RPC polling as equivalent to agent-loop observation. A thin
OpenClaw plugin can forward each typed event to ``ingest_hook`` or to a local bridge.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from .runtime_bridge_contract import RuntimeEvent
from .runtime_controller import XibalbaRuntimeController


def _hash(value: Any) -> str | None:
    if value is None:
        return None
    try:
        raw = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    except Exception:
        raw = str(value).encode()
    return hashlib.sha256(raw).hexdigest()


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            if isinstance(value.get(key), str):
                return value[key]
    return None


@dataclass(slots=True)
class OpenClawAdapter:
    """Normalize OpenClaw typed hook events into the shared Cortex event ledger."""

    controller: XibalbaRuntimeController
    runtime: Literal["openclaw"] = "openclaw"
    provenance: dict[str, Any] = field(default_factory=dict)

    def _ids(self, event: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None]:
        context = event.get("context") if isinstance(event.get("context"), dict) else {}
        session_id = (event.get("sessionId") or event.get("session_id") or
                      context.get("sessionKey") or context.get("session_id"))
        turn_id = event.get("turnId") or event.get("turn_id") or event.get("runId")
        invocation_id = event.get("toolCallId") or event.get("tool_call_id") or event.get("runId")
        agent_id = event.get("agentId") or event.get("agent_id") or context.get("agentId")
        return tuple(str(x) if x is not None else None for x in (session_id, turn_id, invocation_id, agent_id))

    def ingest_hook(self, hook_name: str, event: dict[str, Any] | None = None) -> dict[str, Any]:
        """Ingest one typed ``api.on`` event; unknown additive fields are preserved selectively."""
        event = dict(event or {})
        session_id, turn_id, invocation_id, agent_id = self._ids(event)
        if not session_id:
            return {"recorded": 0, "reason": "missing session_id"}

        if hook_name == "session_start":
            self.controller.open_session(self.runtime, session_id=session_id, agent_id=agent_id,
                                         provenance={**self.provenance, "source_hook": hook_name})
            return {"recorded": 1, "opened": True, "session_id": session_id}
        if hook_name == "session_end":
            result = self.controller.close_session(self.runtime, session_id=session_id,
                                                   summary=_text(event.get("summary")),
                                                   provenance={**self.provenance, "source_hook": hook_name})
            return {"recorded": 1, "closed": True, **result}

        tool_name = event.get("toolName") or event.get("tool_name")
        outcome = "unknown"
        status = str(event.get("status") or event.get("outcome") or "").lower()
        if status in {"ok", "success", "completed"}:
            outcome = "success"
        elif status in {"error", "failed", "timeout"}:
            outcome = "error"
        elif status in {"blocked", "denied", "rejected"}:
            outcome = "blocked"

        content = _text(event.get("assistantMessage") or event.get("message") or event.get("text"))
        metadata = {
            "hook": hook_name,
            "provider": event.get("provider"), "model": event.get("model") or event.get("resolvedModel"),
            "tool_call_id": event.get("toolCallId") or event.get("tool_call_id"),
            "tool_input_hash": _hash(event.get("params") or event.get("input") or event.get("args")),
            "result_hash": _hash(event.get("result") or event.get("output")),
            "result_chars": len(_text(event.get("result") or event.get("output")) or ""),
            "status": event.get("status") or event.get("outcome"),
            "reason": event.get("reason"), "error": event.get("error"),
            "duration_ms": event.get("durationMs") or event.get("duration_ms"),
            "target_session_key": event.get("targetSessionKey"),
            "child_session_key": event.get("childSessionKey") or event.get("child_session_id"),
        }
        self.controller.ingest_event(RuntimeEvent(
            runtime=self.runtime, session_id=session_id, invocation_id=invocation_id,
            turn_id=turn_id, agent_id=agent_id, tool_name=tool_name,
            tool_input_hash=metadata["tool_input_hash"], tool_outcome=outcome,
            assistant_response=content if hook_name in {"agent_end", "message_received", "message_sent"} else None,
            token_usage=event.get("usage") if isinstance(event.get("usage"), dict) else None,
            provenance={**self.provenance, "source_hook": hook_name}, metadata=metadata,
        ))
        return {"recorded": 1, "session_id": session_id, "hook": hook_name}


__all__ = ["OpenClawAdapter"]
