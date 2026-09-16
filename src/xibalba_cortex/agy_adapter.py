"""Agy wrapper and native-hook adapters.

The CLI/plugin and Python SDK can be configured with lifecycle callbacks, but the exact callback
payload is integration-defined. ``AgyNativeHookAdapter`` therefore accepts a generic hook name and
mapping, while preserving the important boundary: it reports observed callbacks without claiming
that every Agy installation has the same hook coverage.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from .runtime_bridge_contract import RuntimeEvent
from .runtime_controller import XibalbaRuntimeController
from integrity_sdk import normalize_hook


def _hash(value: Any) -> str | None:
    if value is None:
        return None
    try:
        encoded = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    except Exception:
        encoded = str(value).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _value(event: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if event.get(key) is not None:
            return event[key]
    return None


@dataclass(slots=True)
class AgyWrapperShim:
    controller: XibalbaRuntimeController
    runtime: Literal["agy"] = "agy"
    provenance: dict[str, Any] = field(default_factory=dict)

    def start(
        self,
        *,
        session_id: str | None = None,
        traceparent: str | None = None,
        agent_id: str | None = None,
        command: str | None = None,
        cwd: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"opened": False, "reason": "missing session_id"}
        opened = self.controller.open_session(
            self.runtime,
            session_id=session_id,
            traceparent=traceparent,
            agent_id=agent_id,
            provenance={**self.provenance, **kwargs, "command": command, "cwd": cwd},
        )
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                traceparent=traceparent,
                agent_id=agent_id,
                tool_name="agy.wrapper.start",
                tool_outcome="success",
                provenance={**self.provenance, **kwargs},
                metadata={"command": command, "cwd": cwd, "hook": "start"},
            )
        )
        return {"opened": True, **opened}

    def end(
        self,
        *,
        session_id: str | None = None,
        exit_code: int | None = None,
        summary: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"closed": False, "reason": "missing session_id"}
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                tool_name="agy.wrapper.end",
                tool_outcome="success" if (exit_code or 0) == 0 else "error",
                provenance={**self.provenance, **kwargs},
                metadata={"exit_code": exit_code, "hook": "end"},
            )
        )
        closed = self.controller.close_session(
            self.runtime,
            session_id=session_id,
            summary=summary,
            provenance={**self.provenance, **kwargs, "exit_code": exit_code},
        )
        return {"closed": True, **closed}

    def record_observation(self, *, session_id: str | None = None, note: str | None = None,
                           event_name: str = "agy.wrapper.observation",
                           turn_id: str | None = None, invocation_id: str | None = None,
                           tool_name: str | None = None, status: str | None = None,
                           duration_ms: float | None = None, **kwargs: Any) -> dict[str, Any]:
        """Record an explicitly forwarded wrapper observation.

        Antigravity's SDK has lifecycle/policy hooks, but this adapter has not been connected
        to an in-process SDK Agent. It therefore never claims native tool coverage.
        """
        if not session_id:
            return {"recorded": 0, "reason": "missing session_id"}
        if not note:
            return {"recorded": 0, "reason": "missing note"}
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                invocation_id=invocation_id,
                turn_id=turn_id,
                tool_name=tool_name or event_name,
                tool_outcome=("success" if status in {"ok", "success", "completed"}
                              else "error" if status in {"error", "failed"} else "unknown"),
                provenance={**self.provenance, **kwargs},
                assistant_response=note,
                metadata={"hook": event_name, "status": status, "duration_ms": duration_ms},
            )
        )
        return {"recorded": 1, "session_id": session_id}


@dataclass(slots=True)
class AgyNativeHookAdapter:
    """Normalize callbacks from an Agy plugin or SDK ``hooks`` configuration.

    Hook names are intentionally normalized rather than hard-coded to one release. Agy's
    documented SDK has multiple hook families, and plugin installations may expose aliases.
    Unknown callbacks are still recorded as observations when they carry a session identifier.
    """

    controller: XibalbaRuntimeController
    runtime: Literal["agy"] = "agy"
    provenance: dict[str, Any] = field(default_factory=dict)

    def ingest_hook(self, hook_name: str, event: dict[str, Any] | None = None) -> dict[str, Any]:
        event = dict(event or {})
        normalized = normalize_hook(hook_name, event)
        hook = normalized["hook"].strip().lower()
        if hook == "posttooluse":
            hook = "post_tool_use"
        elif hook == "pretooluse":
            hook = "pre_tool_use"
        elif hook == "preinvocation":
            hook = "pre_invocation"
        elif hook == "postinvocation":
            hook = "post_invocation"
        session_id = normalized["session_id"]
        if not session_id:
            return {"recorded": 0, "reason": "missing session_id"}
        session_id = str(session_id)
        turn_id = normalized["turn_id"]
        invocation_id = normalized["invocation_id"] or normalized["tool_call_id"]
        agent_id = _value(event, "agent_id", "agentId")
        source_hook = hook_name.strip()
        provenance = {**self.provenance, "source_hook": source_hook, "hook_surface": "native"}

        if hook in {"session_start", "on_session_start", "start"}:
            opened = self.controller.open_session(
                self.runtime, session_id=session_id, traceparent=_value(event, "traceparent"),
                agent_id=agent_id, provenance=provenance,
            )
            return {"recorded": 1, "opened": True, "session_id": session_id, **opened}
        if hook in {"session_end", "on_session_end", "end"}:
            closed = self.controller.close_session(
                self.runtime, session_id=session_id,
                summary=None, provenance=provenance,
            )
            return {"recorded": 1, "closed": True, **closed}

        status = str(_value(event, "status", "outcome") or "").lower()
        if hook in {"on_tool_error", "tool_error", "error", "on_error"}:
            outcome = "error"
        elif status in {"ok", "success", "completed", "complete"}:
            outcome = "success"
        elif status in {"error", "failed", "failure", "timeout"}:
            outcome = "error"
        elif status in {"blocked", "denied", "rejected"}:
            outcome = "blocked"
        else:
            outcome = "unknown"

        tool_name = normalized["tool_name"] or _value(event, "name")
        tool_input = _value(event, "tool_input", "toolInput", "input", "args", "arguments")
        result = _value(event, "tool_output", "toolOutput", "output", "result")
        metadata = {
            "hook": source_hook,
            "status": outcome,
            "duration_ms": _value(event, "duration_ms", "durationMs"),
            "tool_input_hash": _hash(tool_input),
            "result_hash": _hash(result),
            "result_chars": len(result) if isinstance(result, str) else None,
            "error_present": hook in {"on_tool_error", "tool_error", "error", "on_error"},
        }
        source_event_id = normalized["event_id"]
        # Hook phase is part of event identity: before/after share invocation IDs.
        # Without an upstream ID, preserve each observed delivery independently.
        event_id = "agy:" + (_hash([session_id, source_hook, source_event_id])
                              if source_event_id is not None else uuid.uuid4().hex)
        recorded = self.controller.ingest_event(RuntimeEvent(
            runtime=self.runtime, session_id=session_id,
            event_id=event_id,
            idempotency_key=event_id if source_event_id is not None else None,
            traceparent=_value(event, "traceparent"),
            turn_id=str(turn_id) if turn_id is not None else None,
            invocation_id=str(invocation_id) if invocation_id is not None else None,
            agent_id=str(agent_id) if agent_id is not None else None,
            tool_name=str(tool_name) if tool_name is not None else None,
            tool_input_hash=metadata["tool_input_hash"], tool_outcome=outcome,
            provenance=provenance, metadata=metadata,
        ))
        return {"recorded": recorded["recorded"], "session_id": session_id, "hook": source_hook}


__all__ = ["AgyNativeHookAdapter", "AgyWrapperShim"]
