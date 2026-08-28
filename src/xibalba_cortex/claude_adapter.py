"""Claude Code adapter for the runtime controller.

This adapter keeps Claude's richer hook surface as the reference runtime. It converts Claude
hook callbacks into normalized controller events and canonical memory writes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

from .runtime_bridge_contract import RuntimeEvent
from .runtime_controller import XibalbaRuntimeController

# Opt-in only (~/.claude/plans/iridescent-stirring-kettle.md, Phase C): submitting a real
# UserOp through the kernel-bridge testbed adds real on-chain latency and requires the local
# anvil devnet to be up, so this must never fire on a normal tool call unless explicitly asked
# for. Unset/false is the default and costs nothing beyond one os.environ.get.
_KERNEL_BRIDGE_ENV = "XIBALBA_KERNEL_BRIDGE_ENABLED"
_KERNEL_BRIDGE_TEST_VALUE_WEI = int(0.01 * 10**18)
_KERNEL_BRIDGE_TEST_RECIPIENT = "0x" + "0" * 38 + "ff"


def _kernel_bridge_enabled() -> bool:
    return os.environ.get(_KERNEL_BRIDGE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _maybe_submit_kernel_intent(*, intent_rationale: str | None, tool_name: str | None) -> dict[str, Any] | None:
    """Best-effort, opt-in only. Never raises -- a devnet that's down or misconfigured must not
    break the real tool call this is annotating. Returns None whenever the bridge is disabled,
    there's no intent_rationale to gate, or the submission itself failed."""
    if not _kernel_bridge_enabled() or not intent_rationale:
        return None
    try:
        from .kernel_bridge import submit_kernel_intent

        decision = submit_kernel_intent(
            recipient=_KERNEL_BRIDGE_TEST_RECIPIENT,
            value_wei=_KERNEL_BRIDGE_TEST_VALUE_WEI,
        )
        return {"tool_name": tool_name, **decision.to_dict()}
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see docstring
        return {"tool_name": tool_name, "error": str(exc)}


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
        kernel_decision = _maybe_submit_kernel_intent(intent_rationale=intent_rationale, tool_name=tool_name)
        metadata = {
            "hook": "pre_tool_call",
            "tool_call_id": tool_call_id,
            "policy_reason": decision["reason"],
        }
        if kernel_decision is not None:
            metadata["kernel_decision"] = kernel_decision
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
                metadata=metadata,
            )
        )
        result = dict(decision)
        if kernel_decision is not None:
            result["kernel_decision"] = kernel_decision
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
