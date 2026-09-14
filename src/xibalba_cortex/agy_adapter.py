"""agy wrapper shim.

agy does not have a native hook surface in the current harness, so this adapter is intentionally
lifecycle-only. It binds identity, opens/closes sessions, and emits best-effort telemetry around
wrapper entry/exit. It does not pretend to provide Claude-equivalent tool hooks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .runtime_bridge_contract import RuntimeEvent
from .runtime_controller import XibalbaRuntimeController


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


__all__ = ["AgyWrapperShim"]
