import json
import threading
import urllib.request

import pytest

from xibalba_graph.otlp_receiver import (
    UNATTRIBUTED_SESSION_ID,
    ingest_log_records,
    parse_otlp_logs_json,
    serve,
)
from xibalba_graph.store import GraphStore


def _attr(key, value):
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, str):
        return {"key": key, "value": {"stringValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": value}}
    raise TypeError(value)


def _payload(*log_records, resource_attrs=()):
    return {
        "resourceLogs": [{
            "resource": {"attributes": [_attr(k, v) for k, v in resource_attrs]},
            "scopeLogs": [{"logRecords": list(log_records)}],
        }]
    }


def test_parse_merges_resource_and_record_attributes_record_wins():
    payload = _payload(
        {"eventName": "claude_code.user_prompt", "attributes": [_attr("session.id", "record-level")]},
        resource_attrs=[("session.id", "resource-level"), ("user.account_uuid", "acct-1")],
    )
    records = parse_otlp_logs_json(payload)
    assert records[0]["attributes"]["session.id"] == "record-level"  # record wins
    assert records[0]["attributes"]["user.account_uuid"] == "acct-1"  # resource passes through


def test_parse_falls_back_to_otel_event_name_attribute_when_eventname_field_absent():
    payload = _payload({"attributes": [_attr("otel.event.name", "claude_code.tool_result")]})
    records = parse_otlp_logs_json(payload)
    assert records[0]["event_name"] == "claude_code.tool_result"


def test_ingest_stores_text_events_as_memories_with_real_attribution(tmp_path):
    store = GraphStore(tmp_path / "graph")
    payload = _payload(
        {
            "eventName": "claude_code.user_prompt",
            "attributes": [
                _attr("prompt", "fix the login page css"),
                _attr("prompt.id", "prompt-9"),
                _attr("message.uuid", "msg-9"),
            ],
        },
        resource_attrs=[("session.id", "real-session"), ("user.account_uuid", "acct-1")],
    )
    result = ingest_log_records(store, parse_otlp_logs_json(payload))
    assert len(result["stored_memories"]) == 1

    memory = store.get_memory(result["stored_memories"][0])
    assert memory["content"] == "fix the login page css"
    assert memory["source"]["session_id"] == "real-session"
    assert memory["source"]["prompt_id"] == "prompt-9"
    assert memory["source"]["message_id"] == "msg-9"
    assert memory["source"]["agent_id"] is not None  # pseudonymized, but present
    store.close()


def test_ingest_skips_redacted_prompts_without_storing_empty_memory(tmp_path):
    store = GraphStore(tmp_path / "graph")
    payload = _payload(
        {"eventName": "claude_code.user_prompt", "attributes": [_attr("prompt_length", 40)]},  # no "prompt"
        resource_attrs=[("session.id", "s1")],
    )
    result = ingest_log_records(store, parse_otlp_logs_json(payload))
    assert result["stored_memories"] == []
    assert result["redacted_skipped"] == 1
    store.close()


def test_ingest_routes_telemetry_events_to_otel_events_not_memories(tmp_path):
    store = GraphStore(tmp_path / "graph")
    payload = _payload(
        {
            "eventName": "claude_code.api_request",
            "attributes": [_attr("model", "claude-sonnet-5"), _attr("prompt.id", "prompt-9")],
        },
        resource_attrs=[("session.id", "s1")],
    )
    result = ingest_log_records(store, parse_otlp_logs_json(payload))
    assert result["stored_memories"] == []
    assert result["stored_otel_events"] == 1
    summary = store.session_otel_summary("s1")
    assert summary["counts_by_kind"]["log"] == 1
    store.close()


def test_ingest_closes_the_correlation_gap_prompt_and_response_and_telemetry_linked(tmp_path):
    """The actual point of Path B: a user_prompt, its assistant_response, and its
    api_request telemetry all correlate through the same memory via prompt_id.
    """
    store = GraphStore(tmp_path / "graph")
    payload = _payload(
        {"eventName": "claude_code.user_prompt",
         "attributes": [_attr("prompt", "fix the css"), _attr("prompt.id", "p1")]},
        {"eventName": "claude_code.assistant_response",
         "attributes": [_attr("response", "fixed it"), _attr("prompt.id", "p1")]},
        {"eventName": "claude_code.api_request",
         "attributes": [_attr("model", "claude-sonnet-5"), _attr("prompt.id", "p1"), _attr("duration_ms", 900)]},
        resource_attrs=[("session.id", "s1")],
    )
    result = ingest_log_records(store, parse_otlp_logs_json(payload))
    assert len(result["stored_memories"]) == 2

    prompt_memory_id = result["stored_memories"][0]
    correlated = store.memory_otel_events(prompt_memory_id)
    assert len(correlated) == 1
    assert correlated[0]["name"] == "claude_code.api_request"
    assert correlated[0]["attributes"]["duration_ms"] == 900
    store.close()


def test_unattributed_session_id_used_when_session_id_attribute_missing(tmp_path):
    store = GraphStore(tmp_path / "graph")
    payload = _payload({"eventName": "claude_code.user_prompt", "attributes": [_attr("prompt", "hi")]})
    result = ingest_log_records(store, parse_otlp_logs_json(payload))
    memory = store.get_memory(result["stored_memories"][0])
    assert memory["source"]["session_id"] == UNATTRIBUTED_SESSION_ID
    store.close()


def test_serve_accepts_a_real_http_post_end_to_end(tmp_path):
    """Integration test: an actual HTTP request against a running receiver, not just the
    parsing functions in isolation -- confirms the server wiring itself works.
    """
    store = GraphStore(tmp_path / "graph")
    port = 14318  # fixed test port; not 4318, to avoid colliding with a real deployment
    thread = threading.Thread(target=serve, kwargs={"store": store, "port": port}, daemon=True)
    thread.start()
    import time
    time.sleep(0.3)  # let the server bind

    payload = _payload(
        {"eventName": "claude_code.user_prompt",
         "attributes": [_attr("prompt", "hello from a real http request")]},
        resource_attrs=[("session.id", "http-session")],
    )
    request = urllib.request.Request(
        f"http://localhost:{port}/v1/logs",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200
        assert json.loads(response.read()) == {}

    results = store.search("hello from a real http request", limit=10)
    # status defaults to candidate, excluded from search -- confirm via session query instead.
    memories = store.session_memories("http-session")
    assert len(memories) == 1
    assert memories[0]["content"] == "hello from a real http request"
    store.close()


def test_serve_returns_404_for_unconfigured_path(tmp_path):
    store = GraphStore(tmp_path / "graph")
    port = 14319
    thread = threading.Thread(target=serve, kwargs={"store": store, "port": port}, daemon=True)
    thread.start()
    import time
    time.sleep(0.3)

    request = urllib.request.Request(
        f"http://localhost:{port}/v1/metrics", data=b"{}", method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=5)
    assert exc_info.value.code == 404
    store.close()
