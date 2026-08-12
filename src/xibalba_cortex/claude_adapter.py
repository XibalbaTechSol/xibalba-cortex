"""Claude Code adapter for the runtime controller.

This adapter keeps Claude's richer hook surface as the reference runtime. It converts Claude
hook callbacks into normalized controller events and canonical memory writes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .runtime_bridge_contract import RuntimeEvent
from .runtime_controller import XibalbaRuntimeController


@dataclass(slots=True)
class ClaudeAdapter:
    controller: XibalbaRuntimeController
    runtime: Literal["claude"] = "claude"
    provenance: dict[str, Any] = field(default_factory=dict)

    def on_session_start(
        self,
        *,
        session_id: str | None = None,
        traceparent: str | None = None,
        agent_id: str | None = None,
        retention_tier: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"opened": False, "reason": "missing session_id"}
        return self.controller.open_session(
            self.runtime,
            session_id=session_id,
            traceparent=traceparent,
            retention_tier=retention_tier,
            agent_id=agent_id,
            provenance={**self.provenance, **kwargs},
        )

    def on_session_end(
        self,
        *,
        session_id: str | None = None,
        summary: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"closed": False, "reason": "missing session_id"}
        return self.controller.close_session(
            self.runtime,
            session_id=session_id,
            summary=summary,
            provenance={**self.provenance, **kwargs},
        )

    def post_llm_call(
        self,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        user_message: str | None = None,
        assistant_response: str | None = None,
        intent_rationale: str | None = None,
        traceparent: str | None = None,
        agent_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"recorded": 0, "reason": "missing session_id"}
        self.controller.open_session(
            self.runtime,
            session_id=session_id,
            traceparent=traceparent,
            agent_id=agent_id,
            provenance={**self.provenance, **kwargs},
        )
        recorded = 0
        if isinstance(user_message, str) and user_message.strip():
            self.controller.write_memory(
                user_message,
                source={
                    "kind": "direct_user",
                    "session_id": session_id,
                    "role": "user",
                    "prompt_id": turn_id,
                    "agent_id": agent_id,
                },
                status="candidate",
                evidence_class="observed_event",
            )
            recorded += 1
        if isinstance(assistant_response, str) and assistant_response.strip():
            self.controller.write_memory(
                assistant_response,
                source={
                    "kind": "direct_user",
                    "session_id": session_id,
                    "role": "assistant",
                    "prompt_id": turn_id,
                    "agent_id": agent_id,
                },
                status="candidate",
                evidence_class="observed_event",
            )
            recorded += 1
        event = RuntimeEvent(
            runtime=self.runtime,
            session_id=session_id,
            turn_id=turn_id,
            traceparent=traceparent,
            agent_id=agent_id,
            intent_rationale=intent_rationale,
            tool_outcome="success",
            assistant_response=assistant_response,
            provenance={**self.provenance, **kwargs},
            metadata={"hook": "post_llm_call"},
        )
        self.controller.ingest_event(event)
        return {"recorded": recorded + 1, "session_id": session_id}

    def post_tool_call(
        self,
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        turn_id: str | None = None,
        result: Any = None,
        duration_ms: float | None = None,
        status: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        intent_rationale: str | None = None,
        traceparent: str | None = None,
        agent_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"recorded": 0, "reason": "missing session_id"}
        outcome = "unknown"
        if status:
            status_lower = status.lower()
            if status_lower in {"ok", "success", "completed", "done"}:
                outcome = "success"
            elif status_lower in {"blocked", "denied", "rejected"}:
                outcome = "blocked"
            else:
                outcome = "error"
        event = RuntimeEvent(
            runtime=self.runtime,
            session_id=session_id,
            turn_id=turn_id,
            traceparent=traceparent,
            agent_id=agent_id,
            intent_rationale=intent_rationale,
            tool_name=tool_name,
            tool_outcome=outcome,
            assistant_response=None,
            provenance={**self.provenance, **kwargs},
            metadata={
                "hook": "post_tool_call",
                "tool_call_id": tool_call_id,
                "result": result,
                "duration_ms": duration_ms,
                "error_type": error_type,
                "error_message": error_message,
            },
        )
        self.controller.ingest_event(event)
        return {"recorded": 1, "session_id": session_id, "tool_name": tool_name}

    def pre_tool_call(
        self,
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        turn_id: str | None = None,
        tool_input_hash: str | None = None,
        intent_rationale: str | None = None,
        traceparent: str | None = None,
        agent_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"allowed": False, "reason": "missing session_id"}
        decision = self.controller.evaluate_policy(
            runtime=self.runtime,
            session_id=session_id,
            intent_rationale=intent_rationale,
            tool_name=tool_name,
            tool_input_hash=tool_input_hash,
        )
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                turn_id=turn_id,
                traceparent=traceparent,
                agent_id=agent_id,
                intent_rationale=intent_rationale,
                tool_name=tool_name,
                tool_input_hash=tool_input_hash,
                tool_outcome="success" if decision["allowed"] else "blocked",
                provenance={**self.provenance, **kwargs},
                metadata={
                    "hook": "pre_tool_call",
                    "tool_call_id": tool_call_id,
                    "policy_reason": decision["reason"],
                },
            )
        )
        return dict(decision)

    def api_request_error(self, *, session_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        if not session_id:
            return {"recorded": 0, "reason": "missing session_id"}
        event = RuntimeEvent(
            runtime=self.runtime,
            session_id=session_id,
            tool_outcome="error",
            provenance={**self.provenance, **kwargs},
            metadata={"hook": "api_request_error", **kwargs},
        )
        self.controller.ingest_event(event)
        return {"recorded": 1, "session_id": session_id}


__all__ = ["ClaudeAdapter"]
