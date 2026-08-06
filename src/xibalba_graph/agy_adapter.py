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

    def record_observation(self, *, session_id: str | None = None, note: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Optional best-effort helper for external wrapper observations.

        This is not a tool hook and should only be used for wrapper-level facts.
        """
        if not session_id:
            return {"recorded": 0, "reason": "missing session_id"}
        if not note:
            return {"recorded": 0, "reason": "missing note"}
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                tool_name="agy.wrapper.observation",
                tool_outcome="unknown",
                provenance={**self.provenance, **kwargs},
                assistant_response=note,
                metadata={"hook": "observation"},
            )
        )
        return {"recorded": 1, "session_id": session_id}


__all__ = ["AgyWrapperShim"]
