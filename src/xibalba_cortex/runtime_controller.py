"""Controller façade for runtime adapters.

This layer owns the boundary between runtime adapters and GraphStore.
Adapters never write directly to the store in production code; they call this
service, which can normalize identity, session, policy, and telemetry before
handing anything to the canonical memory layer.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .runtime_bridge_contract import (
    CONTROLLER_EVENT_SCHEMA_VERSION,
    AGY_ADAPTER,
    CLAUDE_ADAPTER,
    CODEX_ADAPTER,
    CURSOR_ADAPTER,
    GEMINI_ADAPTER,
    OPENAI_COMPATIBLE_ADAPTER,
    RuntimeAdapterResponsibilities,
    RuntimeEvent,
    RuntimeName,
)
from .store import GraphStore


@dataclass(slots=True)
class RuntimeRegistration:
    adapter: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)


class XibalbaRuntimeController:
    """Thin controller façade around GraphStore."""

    def __init__(
        self,
        store: GraphStore,
        *,
        auto_anchor_on_session_end: bool | None = None,
    ):
        self.store = store
        self.auto_anchor_on_session_end = (
            _env_flag("XIBALBA_AUTO_ANCHOR_ON_SESSION_END")
            if auto_anchor_on_session_end is None
            else bool(auto_anchor_on_session_end)
        )
        self._registrations: dict[str, RuntimeRegistration] = {}
        self._bindings: dict[str, dict[str, Any]] = {}

    def register_runtime(
        self,
        adapter: RuntimeAdapterResponsibilities | dict[str, Any],
        *,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(adapter, RuntimeAdapterResponsibilities):
            record = adapter.to_record()
        else:
            record = dict(adapter)
        runtime = str(record.get("runtime") or "unknown")
        entry = RuntimeRegistration(adapter=record, provenance=dict(provenance or {}))
        self._registrations[runtime] = entry
        return {
            "runtime": runtime,
            "registered": True,
            "adapter": record,
            "provenance": entry.provenance,
        }

    def bind_identity(
        self,
        runtime: RuntimeName,
        *,
        session_id: str,
        agent_id: str,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.open_session(runtime, session_id=session_id, agent_id=agent_id, provenance=provenance)
        binding = {
            "runtime": runtime,
            "session_id": session_id,
            "agent_id": agent_id,
            "provenance": dict(provenance or {}),
        }
        self._bindings[session_id] = binding
        return {"bound": True, **binding}

    def open_session(
        self,
        runtime: RuntimeName,
        *,
        session_id: str,
        traceparent: str | None = None,
        retention_tier: str | None = None,
        agent_id: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self.store.start_session(session_id, retention_tier=retention_tier)
        self._bindings.setdefault(session_id, {})
        self._bindings[session_id].update(
            {
                "runtime": runtime,
                "session_id": session_id,
                "traceparent": traceparent,
                "agent_id": agent_id,
                "provenance": dict(provenance or {}),
            }
        )
        return {
            "runtime": runtime,
            "session": session,
            "traceparent": traceparent,
            "agent_id": agent_id,
            "opened": True,
        }

    def close_session(
        self,
        runtime: RuntimeName,
        *,
        session_id: str,
        summary: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self.store.end_session(session_id, summary_content=summary)
        binding = self._bindings.get(session_id, {})
        anchor: dict[str, Any] | None = None
        if self.auto_anchor_on_session_end:
            try:
                anchor = self.store.anchor_session_root(session_id)
            except Exception as exc:  # anchoring must not prevent lifecycle close
                anchor = {
                    "anchored": False,
                    "session_id": session_id,
                    "error": str(exc),
                }
        return {
            "runtime": runtime,
            "session": session,
            "binding": binding,
            "closed": True,
            "provenance": dict(provenance or {}),
            "anchor": anchor,
        }

    def ingest_event(self, event: RuntimeEvent) -> dict[str, Any]:
        self.store.start_session(event.session_id, retention_tier="verbatim")
        result = self.store.record_otel_batch(
            event.session_id,
            [
                {
                    "kind": "log",
                    "name": "xibalba.runtime.event",
                    "trace_id": event.turn_id,
                    "span_id": event.tool_name,
                    "parent_span_id": event.turn_id,
                    "prompt_id": event.turn_id,
                    "attributes": event.to_record(),
                }
            ],
        )
        return {"recorded": 1, "session_id": event.session_id, "store_result": result}

    def ingest_events(self, events: list[RuntimeEvent]) -> list[dict[str, Any]]:
        return [self.ingest_event(event) for event in events]

    def read_memory(
        self,
        query: str,
        *,
        runtime: RuntimeName | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return self.store.search(query, limit=limit)

    def write_memory(
        self,
        content: str,
        *,
        source: dict[str, Any],
        status: str = "candidate",
        evidence_class: str = "observed_event",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self.store.store_memory(
            content,
            source=source,
            status=status,
            evidence_class=evidence_class,
            idempotency_key=idempotency_key,
        )

    def record_model_exchange(
        self,
        runtime: RuntimeName,
        *,
        session_id: str,
        user_prompt: str,
        model_response: str,
        context: list[dict[str, Any]] | None = None,
        agent_id: str | None = None,
        prompt_id: str | None = None,
        prompt_time: str | None = None,
        response_time: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self.open_session(runtime, session_id=session_id, agent_id=agent_id, retention_tier="verbatim")
        return self.store.record_model_exchange(
            session_id,
            user_prompt=user_prompt,
            model_response=model_response,
            context=list(context or []),
            runtime=runtime,
            agent_id=agent_id,
            prompt_id=prompt_id,
            prompt_time=prompt_time,
            response_time=response_time,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

    def request_memory_inference(
        self,
        task_type: str,
        *,
        subject_type: str,
        subject_id: str,
        input_payload: dict[str, Any],
        requested_by: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self.store.request_inference_task(
            task_type,
            subject_type=subject_type,
            subject_id=subject_id,
            input_payload=input_payload,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
        )

    def evaluate_policy(
        self,
        *,
        runtime: RuntimeName,
        session_id: str,
        intent_rationale: str | None = None,
        tool_name: str | None = None,
        tool_input_hash: str | None = None,
    ) -> dict[str, Any]:
        if tool_name and not (intent_rationale or "").strip():
            return {
                "allowed": False,
                "reason": "missing intent_rationale for tool-bearing action",
                "runtime": runtime,
                "session_id": session_id,
                "tool_name": tool_name,
                "tool_input_hash": tool_input_hash,
            }
        return {
            "allowed": True,
            "reason": "policy passed",
            "runtime": runtime,
            "session_id": session_id,
            "tool_name": tool_name,
            "tool_input_hash": tool_input_hash,
        }


__all__ = [
    "XibalbaRuntimeController",
    "RuntimeRegistration",
    "CONTROLLER_EVENT_SCHEMA_VERSION",
    "AGY_ADAPTER",
    "CLAUDE_ADAPTER",
    "CODEX_ADAPTER",
    "CURSOR_ADAPTER",
    "GEMINI_ADAPTER",
    "OPENAI_COMPATIBLE_ADAPTER",
]


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
