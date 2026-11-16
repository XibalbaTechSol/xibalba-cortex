"""Claude Code adapter for the runtime controller.

This adapter keeps Claude's richer hook surface as the reference runtime. It converts Claude
hook callbacks into normalized controller events and canonical memory writes.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from integrity_sdk import normalize_hook

from .runtime_bridge_contract import RuntimeEvent
from .runtime_controller import XibalbaRuntimeController

_INVOCATION_NAMESPACE = uuid.UUID("9f7df4b9-8538-4c58-9044-b34d56454f13")


def _normalized_hook(hook: str, *, session_id: str | None = None,
                     turn_id: str | None = None, invocation_id: str | None = None,
                     tool_call_id: str | None = None, tool_name: str | None = None,
                     traceparent: str | None = None, status: str | None = None,
                     **payload: Any) -> dict[str, Any]:
    """Use the SDK correlation vocabulary at the Claude adapter boundary."""
    return normalize_hook(hook, {
        **payload, "session_id": session_id, "turn_id": turn_id,
        "invocation_id": invocation_id, "tool_call_id": tool_call_id,
        "tool_name": tool_name, "traceparent": traceparent, "status": status,
    })


def _invocation_id(session_id: str, tool_call_id: str | None, supplied: str | None) -> str:
    """Use a caller-supplied UUID, or derive a stable UUIDv5 from the runtime hook scope."""
    if supplied is not None:
        parsed = uuid.UUID(supplied)
        canonical = str(parsed)
        if supplied != canonical or parsed.int == 0:
            raise ValueError("invocation_id must be a non-nil lowercase canonical UUID")
        return canonical
    if tool_call_id:
        return str(uuid.uuid5(_INVOCATION_NAMESPACE, f"claude:{session_id}:{tool_call_id}"))
    return str(uuid.uuid4())


@dataclass(slots=True)
class ClaudeAdapter:
    controller: XibalbaRuntimeController
    runtime: Literal["claude"] = "claude"
    provenance: dict[str, Any] = field(default_factory=dict)

    def _observer_event(self, *, session_id: str | None, hook: str,
                        turn_id: str | None = None, invocation_id: str | None = None,
                        tool_name: str | None = None, tool_outcome: str = "unknown",
                        assistant_response: str | None = None, agent_id: str | None = None,
                        **metadata: Any) -> dict[str, Any]:
        normalized = _normalized_hook(
            hook, session_id=session_id, turn_id=turn_id, invocation_id=invocation_id,
            tool_name=tool_name, **metadata,
        )
        session_id = normalized["session_id"]
        if not session_id:
            return {"recorded": 0, "reason": "missing session_id"}
        self.controller.ingest_event(RuntimeEvent(
            runtime=self.runtime, session_id=session_id, invocation_id=normalized["invocation_id"],
            turn_id=normalized["turn_id"], agent_id=agent_id,
            tool_name=normalized["tool_name"],
            tool_outcome=tool_outcome, assistant_response=assistant_response,
            provenance={**self.provenance},
            metadata={"hook": hook, "event_id": normalized["event_id"], **metadata},
        ))
        return {"recorded": 1, "session_id": session_id}

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

    def pre_llm_call(self, *, session_id: str | None = None, turn_id: str | None = None,
                     model: str | None = None, provider: str | None = None,
                     messages: Any = None, **kwargs: Any) -> dict[str, Any]:
        return self._observer_event(session_id=session_id, hook="pre_llm_call", turn_id=turn_id,
                                    model=model, provider=provider,
                                    message_count=len(messages) if isinstance(messages, list) else None)

    def pre_api_request(self, *, session_id: str | None = None, turn_id: str | None = None,
                        api_request_id: str | None = None, model: str | None = None,
                        provider: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self._observer_event(session_id=session_id, hook="pre_api_request", turn_id=turn_id,
                                    api_request_id=api_request_id, model=model, provider=provider)

    def post_api_request(self, *, session_id: str | None = None, turn_id: str | None = None,
                         api_request_id: str | None = None, usage: dict | None = None,
                         api_duration: float | None = None, model: str | None = None,
                         provider: str | None = None, finish_reason: str | None = None,
                         **kwargs: Any) -> dict[str, Any]:
        return self._observer_event(session_id=session_id, hook="post_api_request", turn_id=turn_id,
                                    api_request_id=api_request_id, model=model, provider=provider,
                                    usage=usage, duration_ms=api_duration, finish_reason=finish_reason)

    def on_stream_start(self, *, session_id: str | None = None, turn_id: str | None = None,
                        api_request_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self._observer_event(session_id=session_id, hook="on_stream_start", turn_id=turn_id,
                                    api_request_id=api_request_id)

    def on_stream_end(self, *, session_id: str | None = None, turn_id: str | None = None,
                      api_request_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self._observer_event(session_id=session_id, hook="on_stream_end", turn_id=turn_id,
                                    api_request_id=api_request_id,
                                    delta_count=kwargs.get("delta_count"),
                                    text_chars=kwargs.get("text_chars"),
                                    duration_ms=kwargs.get("duration_ms"),
                                    finish_reason=kwargs.get("finish_reason"))

    def on_session_finalize(self, *, session_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self._observer_event(session_id=session_id, hook="on_session_finalize",
                                    reason=kwargs.get("reason"))

    def on_session_reset(self, *, session_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self._observer_event(session_id=session_id, hook="on_session_reset",
                                    reason=kwargs.get("reason"))

    def post_tool_call(
        self,
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        invocation_id: str | None = None,
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
        invocation_id = _invocation_id(session_id, tool_call_id, invocation_id)
        normalized = _normalized_hook(
            "post_tool_call", session_id=session_id, turn_id=turn_id,
            invocation_id=invocation_id, tool_call_id=tool_call_id, tool_name=tool_name,
            status=status, traceparent=traceparent,
        )
        session_id = normalized["session_id"]
        turn_id = normalized["turn_id"]
        invocation_id = normalized["invocation_id"]
        tool_name = normalized["tool_name"]
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
            invocation_id=invocation_id,
            turn_id=turn_id,
            traceparent=normalized["traceparent"],
            agent_id=agent_id,
            intent_rationale=intent_rationale,
            tool_name=tool_name,
            tool_outcome=outcome,
            assistant_response=None,
            provenance={**self.provenance, **kwargs},
            metadata={
                "hook": "post_tool_call",
                "tool_call_id": normalized["tool_call_id"],
                "result": result,
                "duration_ms": duration_ms,
                "error_type": error_type,
                "error_message": error_message,
                "event_id": normalized["event_id"],
            },
        )
        self.controller.ingest_event(event)
        return {"recorded": 1, "session_id": session_id, "tool_name": tool_name, "invocation_id": invocation_id}

    def pre_tool_call(
        self,
        *,
        session_id: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        invocation_id: str | None = None,
        turn_id: str | None = None,
        tool_input_hash: str | None = None,
        intent_rationale: str | None = None,
        traceparent: str | None = None,
        agent_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not session_id:
            return {"allowed": False, "reason": "missing session_id"}
        invocation_id = _invocation_id(session_id, tool_call_id, invocation_id)
        normalized = _normalized_hook(
            "pre_tool_call", session_id=session_id, turn_id=turn_id,
            invocation_id=invocation_id, tool_call_id=tool_call_id, tool_name=tool_name,
            traceparent=traceparent,
        )
        session_id = normalized["session_id"]
        turn_id = normalized["turn_id"]
        invocation_id = normalized["invocation_id"]
        tool_name = normalized["tool_name"]
        decision = self.controller.evaluate_policy(
            runtime=self.runtime,
            session_id=session_id,
            intent_rationale=intent_rationale,
            tool_name=tool_name,
            tool_input_hash=tool_input_hash,
        )
        metadata = {
            "hook": "pre_tool_call",
            "tool_call_id": normalized["tool_call_id"],
            "policy_reason": decision["reason"],
            "event_id": normalized["event_id"],
        }
        self.controller.ingest_event(
            RuntimeEvent(
                runtime=self.runtime,
                session_id=session_id,
                invocation_id=invocation_id,
                turn_id=turn_id,
                traceparent=normalized["traceparent"],
                agent_id=agent_id,
                intent_rationale=intent_rationale,
                tool_name=tool_name,
                tool_input_hash=tool_input_hash,
                tool_outcome="success" if decision["allowed"] else "blocked",
                provenance={**self.provenance, **kwargs},
                metadata=metadata,
            )
        )
        result = dict(decision)
        result["invocation_id"] = invocation_id
        return result

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
