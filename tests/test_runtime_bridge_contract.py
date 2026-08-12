from xibalba_cortex.runtime_bridge_contract import (
    AGY_ADAPTER,
    CLAUDE_ADAPTER,
    CODEX_ADAPTER,
    CONTROLLER_EVENT_SCHEMA_VERSION,
    CONTROLLER_METHODS,
    CONTROLLER_REQUIRED_EVENT_FIELDS,
    RuntimeEvent,
)


def test_runtime_event_serializes_with_schema_version_and_required_fields():
    event = RuntimeEvent(
        runtime="claude",
        session_id="session-1",
        turn_id="turn-1",
        traceparent="00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
        agent_id="did:integrity:123",
        intent_rationale="Explain the architecture boundary.",
        tool_name="memory_recall",
        tool_input_hash="sha256:abc123",
        tool_outcome="success",
        token_usage={"input": 10, "output": 4},
        assistant_response="Hermes MCP is necessary, not sufficient.",
        observed_at_utc="2026-08-05T11:45:00Z",
        provenance={"source": "hook"},
        metadata={"profile": "default"},
    )

    record = event.to_record()
    assert record["schema_version"] == CONTROLLER_EVENT_SCHEMA_VERSION
    assert tuple(record) == CONTROLLER_REQUIRED_EVENT_FIELDS
    assert record["runtime"] == "claude"
    assert record["session_id"] == "session-1"
    assert record["intent_rationale"] == "Explain the architecture boundary."
    assert record["tool_outcome"] == "success"
    assert record["token_usage"] == {"input": 10, "output": 4}


def test_adapter_responsibility_records_keep_runtime_specific_limits_explicit():
    assert CLAUDE_ADAPTER.status == "implemented"
    assert "pre_tool_gating" in CLAUDE_ADAPTER.responsibilities
    assert AGY_ADAPTER.status == "partial"
    assert "no_native_hook_surface" in AGY_ADAPTER.limitations
    assert "trace_continuity_is_best_effort_only" in AGY_ADAPTER.limitations
    assert CODEX_ADAPTER.status == "unknown"
    assert "hook_surface_must_be_discovered" in CODEX_ADAPTER.limitations


def test_controller_method_surface_is_explicit():
    assert CONTROLLER_METHODS == (
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
