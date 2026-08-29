"""Cursor wrapper shim.

Cursor is editor-embedded and has no verified native hook surface in this codebase, so this
adapter is lifecycle-only, mirroring AgyWrapperShim: it binds identity, opens/closes sessions
around the wrapper invocation, and emits best-effort telemetry. Session start/end boundaries
are approximated from the wrapper, not a native Cursor lifecycle event -- see
CURSOR_ADAPTER.limitations in runtime_bridge_contract.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .runtime_bridge_contract import RuntimeEvent
from .runtime_controller import XibalbaRuntimeController


@dataclass(slots=True)
class CursorAdapter:
    controller: XibalbaRuntimeController
    runtime: Literal["cursor"] = "cursor"
    provenance: dict[str, Any] = field(default_factory=dict)

    def start(
        self,
        *,
        session_id: str | None = None,
        traceparent: str | None = None,
        agent_id: str | None = None,
        workspace: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"opened": False, "reason": "missing session_id"}
        opened = self.controller.open_session(
            self.runtime,
            session_id=session_id,
            traceparent=traceparent,
            agent_id=agent_id,
            provenance={**self.provenance, **kwargs, "workspace": workspace},
        )
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                traceparent=traceparent,
                agent_id=agent_id,
                tool_name="cursor.wrapper.start",
                tool_outcome="success",
                provenance={**self.provenance, **kwargs},
                metadata={"workspace": workspace, "hook": "start"},
            )
        )
        return {"opened": True, **opened}

    def end(
        self,
        *,
        session_id: str | None = None,
        summary: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"closed": False, "reason": "missing session_id"}
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                tool_name="cursor.wrapper.end",
                tool_outcome="success",
                provenance={**self.provenance, **kwargs},
                metadata={"hook": "end"},
            )
        )
        closed = self.controller.close_session(
            self.runtime,
            session_id=session_id,
            summary=summary,
            provenance={**self.provenance, **kwargs},
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
                tool_name="cursor.wrapper.observation",
                tool_outcome="unknown",
                provenance={**self.provenance, **kwargs},
                assistant_response=note,
                metadata={"hook": "observation"},
            )
        )
        return {"recorded": 1, "session_id": session_id}


__all__ = ["CursorAdapter"]
