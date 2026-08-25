"""Runtime bridge contract for Claude Code, agy, and Codex.

This module is intentionally small and importable without any runtime-specific dependencies.
It defines the shared event schema, the controller interface shape, and the adapter
responsibility records that the architecture uses as its first implementation pass.

The contract is explicit about one thing: Hermes Model Context Protocol is the shared tool
bus, but the controller owns identity binding, session state, memory access, and normalized
telemetry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

RuntimeName = Literal["claude", "agy", "codex", "gemini", "cursor", "openai_compatible"]
TransportMode = Literal["hooks", "wrapper", "launcher"]
AdapterStatus = Literal["implemented", "partial", "unknown"]
ToolOutcome = Literal["success", "error", "blocked", "unknown"]

CONTROLLER_EVENT_SCHEMA_VERSION = "xibalba.runtime.bridge.v1"
CONTROLLER_REQUIRED_EVENT_FIELDS = (
    "schema_version",
    "runtime",
    "session_id",
    "turn_id",
    "traceparent",
    "agent_id",
    "intent_rationale",
    "tool_name",
    "tool_input_hash",
    "tool_outcome",
    "token_usage",
    "assistant_response",
    "observed_at_utc",
    "provenance",
    "metadata",
)
CONTROLLER_METHODS = (
    "register_runtime",
    "bind_identity",
    "open_session",
    "close_session",
    "ingest_event",
    "ingest_events",
    "read_memory",
    "write_memory",
    "evaluate_policy",
    "record_model_exchange",
    "request_memory_inference",
)


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Normalized telemetry from a runtime adapter.

    The controller accepts one of these records per observable event. Missing fields are
    permitted and must be represented explicitly as nulls rather than invented values.
    """

    runtime: RuntimeName
    session_id: str
    turn_id: str | None = None
    traceparent: str | None = None
    agent_id: str | None = None
    intent_rationale: str | None = None
    tool_name: str | None = None
    tool_input_hash: str | None = None
    tool_outcome: ToolOutcome = "unknown"
    token_usage: dict[str, int] | None = None
    assistant_response: str | None = None
    observed_at_utc: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        record = {"schema_version": CONTROLLER_EVENT_SCHEMA_VERSION}
        record.update(asdict(self))
        return record


@dataclass(frozen=True, slots=True)
class RuntimeAdapterResponsibilities:
    """Human-readable responsibility bundle for a runtime-specific adapter."""

    runtime: RuntimeName
    transport: TransportMode
    status: AdapterStatus
    responsibilities: tuple[str, ...]
    guarantees: tuple[str, ...]
    limitations: tuple[str, ...] = ()
    notes: str = ""

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


CLAUDE_ADAPTER = RuntimeAdapterResponsibilities(
    runtime="claude",
    transport="hooks",
    status="implemented",
    responsibilities=(
        "bind_identity",
        "session_start",
        "session_end",
        "pre_tool_gating",
        "post_tool_reporting",
        "trace_continuity",
        "memory_bus_access",
    ),
    guarantees=(
        "per_tool_policy_enforcement",
        "session_trace_propagation",
        "normalized_event_ingest",
    ),
    notes="Claude Code has the richest native hook surface and should be treated as the reference adapter.",
)

AGY_ADAPTER = RuntimeAdapterResponsibilities(
    runtime="agy",
    transport="wrapper",
    status="partial",
    responsibilities=(
        "bind_identity",
        "wrapper_session_start",
        "wrapper_session_end",
        "memory_bus_access",
        "best_effort_telemetry",
    ),
    guarantees=(
        "shared_identity_binding",
        "lifecycle_telemetry",
    ),
    limitations=(
        "no_native_hook_surface",
        "no_pre_tool_or_post_tool_hooks",
        "trace_continuity_is_best_effort_only",
    ),
    notes="agy is wrapper-only today; it must not claim Claude-equivalent tool-level parity.",
)

CODEX_ADAPTER = RuntimeAdapterResponsibilities(
    runtime="codex",
    transport="launcher",
    status="partial",
    responsibilities=(
        "bind_identity",
        "launcher_session_context",
        "wrapper_session_start",
        "wrapper_session_end",
        "memory_bus_access",
        "telemetry_normalization",
        "best_effort_telemetry",
    ),
    guarantees=(
        "shared_identity_binding",
        "shared_memory_access",
        "lifecycle_telemetry",
    ),
    limitations=(
        "hook_surface_must_be_discovered",
        "tool_level_parity_is_unverified",
        "no_native_pre_tool_or_post_tool_hooks",
    ),
    notes=(
        "Codex now has a lifecycle-only adapter (CodexAdapter) plus the CodexLauncher subprocess "
        "wrapper, so identity binding and session telemetry are real. Pre-tool/post-tool hook "
        "parity with Claude is still unverified and must be measured in the live environment "
        "before a stronger claim is made."
    ),
)

GEMINI_ADAPTER = RuntimeAdapterResponsibilities(
    runtime="gemini",
    transport="wrapper",
    status="partial",
    responsibilities=(
        "bind_identity",
        "wrapper_session_start",
        "wrapper_session_end",
        "memory_bus_access",
        "best_effort_telemetry",
    ),
    guarantees=(
        "shared_identity_binding",
        "lifecycle_telemetry",
    ),
    limitations=(
        "no_native_hook_surface",
        "no_pre_tool_or_post_tool_hooks",
        "trace_continuity_is_best_effort_only",
    ),
    notes="Gemini CLI is wrapper-only today; it must not claim Claude-equivalent tool-level parity.",
)

CURSOR_ADAPTER = RuntimeAdapterResponsibilities(
    runtime="cursor",
    transport="wrapper",
    status="partial",
    responsibilities=(
        "bind_identity",
        "wrapper_session_start",
        "wrapper_session_end",
        "memory_bus_access",
        "best_effort_telemetry",
    ),
    guarantees=(
        "shared_identity_binding",
        "lifecycle_telemetry",
    ),
    limitations=(
        "no_native_hook_surface",
        "no_pre_tool_or_post_tool_hooks",
        "trace_continuity_is_best_effort_only",
        "editor_embedded_lifecycle_boundaries_are_approximate",
    ),
    notes=(
        "Cursor is editor-embedded and wrapper-only today; session start/end boundaries are "
        "approximated from the wrapper invocation, not a native Cursor lifecycle hook."
    ),
)

OPENAI_COMPATIBLE_ADAPTER = RuntimeAdapterResponsibilities(
    runtime="openai_compatible",
    transport="wrapper",
    status="partial",
    responsibilities=(
        "bind_identity",
        "wrapper_session_start",
        "wrapper_session_end",
        "memory_bus_access",
        "best_effort_telemetry",
    ),
    guarantees=(
        "shared_identity_binding",
        "lifecycle_telemetry",
    ),
    limitations=(
        "no_native_hook_surface",
        "no_pre_tool_or_post_tool_hooks",
        "trace_continuity_is_best_effort_only",
        "no_vendor_specific_guarantees",
    ),
    notes=(
        "Reference/template adapter for any harness that speaks an OpenAI-compatible tool-call "
        "shape but has no dedicated adapter yet. Intentionally the thinnest adapter in the "
        "layer -- copy this one when wiring up a new runtime."
    ),
)


class RuntimeController(Protocol):
    """Abstract controller boundary for Xibalba runtime adapters."""

    def register_runtime(
        self,
        adapter: RuntimeAdapterResponsibilities,
        *,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def bind_identity(
        self,
        runtime: RuntimeName,
        *,
        session_id: str,
        agent_id: str,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def open_session(
        self,
        runtime: RuntimeName,
        *,
        session_id: str,
        traceparent: str | None = None,
        retention_tier: str | None = None,
        agent_id: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def close_session(
        self,
        runtime: RuntimeName,
        *,
        session_id: str,
        summary: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def ingest_event(self, event: RuntimeEvent) -> dict[str, Any]: ...

    def ingest_events(self, events: list[RuntimeEvent]) -> list[dict[str, Any]]: ...

    def read_memory(
        self,
        query: str,
        *,
        runtime: RuntimeName | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...

    def write_memory(
        self,
        content: str,
        *,
        source: dict[str, Any],
        status: str = "candidate",
        evidence_class: str = "observed_event",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...

    def evaluate_policy(
        self,
        *,
        runtime: RuntimeName,
        session_id: str,
        intent_rationale: str | None = None,
        tool_name: str | None = None,
        tool_input_hash: str | None = None,
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

    def request_memory_inference(
        self,
        task_type: str,
        *,
        subject_type: str,
        subject_id: str,
        input_payload: dict[str, Any],
        requested_by: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...
