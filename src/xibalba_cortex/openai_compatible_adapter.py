"""Reference adapter for any OpenAI-compatible-tool-call harness with no dedicated adapter yet.

This is the template to copy when wiring up a new runtime: the minimal lifecycle-only shape
(start/end/record_observation) shared by every wrapper-transport adapter in this layer, with no
runtime-specific fields beyond what OPENAI_COMPATIBLE_ADAPTER in runtime_bridge_contract.py
already declares. Do not add vendor-specific guarantees here -- copy this file and extend the
copy instead, so this one stays the honest floor of what a brand-new integration can claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .runtime_bridge_contract import RuntimeEvent
from .runtime_controller import XibalbaRuntimeController


@dataclass(slots=True)
class OpenAICompatibleAdapter:
    controller: XibalbaRuntimeController
    runtime: Literal["openai_compatible"] = "openai_compatible"
    provenance: dict[str, Any] = field(default_factory=dict)

    def start(
        self,
        *,
        session_id: str | None = None,
        traceparent: str | None = None,
        agent_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"opened": False, "reason": "missing session_id"}
        opened = self.controller.open_session(
            self.runtime,
            session_id=session_id,
            traceparent=traceparent,
            agent_id=agent_id,
            provenance={**self.provenance, **kwargs},
        )
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                traceparent=traceparent,
                agent_id=agent_id,
                tool_name="openai_compatible.wrapper.start",
                tool_outcome="success",
                provenance={**self.provenance, **kwargs},
                metadata={"hook": "start"},
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
                tool_name="openai_compatible.wrapper.end",
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
                tool_name="openai_compatible.wrapper.observation",
                tool_outcome="unknown",
                provenance={**self.provenance, **kwargs},
                assistant_response=note,
                metadata={"hook": "observation"},
            )
        )
        return {"recorded": 1, "session_id": session_id}


__all__ = ["OpenAICompatibleAdapter"]
