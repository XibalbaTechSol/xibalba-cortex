import json
import threading
import urllib.request

import pytest

from xibalba_cortex.otlp_receiver import (
    UNATTRIBUTED_SESSION_ID,
    ingest_gen_ai_spans,
    ingest_log_records,
    parse_otlp_logs_json,
    parse_otlp_spans_json,
    serve,
)
from xibalba_cortex.store import GraphStore


def _sval(v):
    return {"stringValue": v}


def _ival(v):
    return {"intValue": v}


def _aval(items):
    return {"arrayValue": {"values": items}}


def _kval(pairs):
    return {"kvlistValue": {"values": [{"key": k, "value": v} for k, v in pairs]}}


def _gen_ai_message(role, *parts):
    return _kval([("role", _sval(role)), ("parts", _aval(list(parts)))])


def _text_part(content):
    return _kval([("type", _sval("text")), ("content", _sval(content))])


def _tool_call_part(call_id, name, arguments=None):
    pairs = [("type", _sval("tool_call")), ("id", _sval(call_id)), ("name", _sval(name))]
    if arguments is not None:
        pairs.append(("arguments", _kval([(k, _sval(v)) for k, v in arguments.items()])))
    return _kval(pairs)


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


def test_ingest_dedupes_against_content_already_captured_by_raw_body_ingest(tmp_path):
    """The actual cross-path scenario: raw_body_ingest (Path A) captures a turn first
    (synchronous file write), otlp_receiver (Path B) sees the same text later (batched OTLP
    export) with real attribution -- must not duplicate, must link instead.
    """
    from xibalba_cortex.raw_body_ingest import UNATTRIBUTED_SESSION_ID as RAW_UNATTRIBUTED

    store = GraphStore(tmp_path / "graph")
    store.start_session(RAW_UNATTRIBUTED, retention_tier="verbatim")
    unattributed = store.store_memory(
        "fix the login page css",
        source={"kind": "direct_user", "session_id": RAW_UNATTRIBUTED, "message_id": "uuid-1"},
        status="candidate",
        evidence_class="observed_event",
    )

    payload = _payload(
        {"eventName": "claude_code.user_prompt",
         "attributes": [_attr("prompt", "fix the login page css"), _attr("prompt.id", "prompt-77")]},
        {"eventName": "claude_code.api_request",
         "attributes": [_attr("model", "claude-sonnet-5"), _attr("prompt.id", "prompt-77"), _attr("duration_ms", 500)]},
        resource_attrs=[("session.id", "real-session-99"), ("user.account_uuid", "acct-1")],
    )
    result = ingest_log_records(store, parse_otlp_logs_json(payload))

    assert result["stored_memories"] == []  # no duplicate
    assert result["reused_memories"] == [unattributed["id"]]

    # The original memory's own provenance is honestly unchanged -- still says what was true
    # when Path A first captured it, not silently rewritten.
    reloaded = store.get_memory(unattributed["id"])
    assert reloaded["source"]["session_id"] == RAW_UNATTRIBUTED

    # But the real attribution and telemetry ARE discoverable via the link.
    correlated = store.memory_otel_events(unattributed["id"])
    assert len(correlated) == 1
    assert correlated[0]["session_id"] == "real-session-99"
    assert correlated[0]["attributes"]["duration_ms"] == 500
    store.close()


def test_telemetry_event_links_via_memory_id_even_when_text_event_arrives_second_in_the_batch(tmp_path):
    """Two-pass processing exists specifically so ordering within one batch doesn't matter --
    put api_request BEFORE user_prompt in the record list and confirm linkage still works.
    """
    store = GraphStore(tmp_path / "graph")
    payload = _payload(
        {"eventName": "claude_code.api_request",
         "attributes": [_attr("model", "claude-sonnet-5"), _attr("prompt.id", "p1")]},
        {"eventName": "claude_code.user_prompt",
         "attributes": [_attr("prompt", "out of order test"), _attr("prompt.id", "p1")]},
        resource_attrs=[("session.id", "s1")],
    )
    result = ingest_log_records(store, parse_otlp_logs_json(payload))
    memory_id = result["stored_memories"][0]
    correlated = store.memory_otel_events(memory_id)
    assert len(correlated) == 1
    assert correlated[0]["name"] == "claude_code.api_request"
    store.close()


def _gen_ai_payload(*, provider="gcp.gemini", model="gemini-2.5-pro", session_id="s1",
                     trace_id="trace-1", span_id="span-1", input_messages=None, output_messages=None):
    attrs = [
        {"key": "gen_ai.provider.name", "value": _sval(provider)},
        {"key": "gen_ai.request.model", "value": _sval(model)},
        {"key": "gen_ai.usage.input_tokens", "value": _ival(120)},
        {"key": "gen_ai.usage.output_tokens", "value": _ival(45)},
        {"key": "gen_ai.response.finish_reasons", "value": _aval([_sval("stop")])},
    ]
    if input_messages is not None:
        attrs.append({"key": "gen_ai.input.messages", "value": _aval(input_messages)})
    if output_messages is not None:
        attrs.append({"key": "gen_ai.output.messages", "value": _aval(output_messages)})
    return {
        "resourceSpans": [{
            "resource": {"attributes": [{"key": "session.id", "value": _sval(session_id)}]},
            "scopeSpans": [{
                "spans": [{
                    "name": f"chat {model}",
                    "traceId": trace_id,
                    "spanId": span_id,
                    "attributes": attrs,
                }],
            }],
        }],
    }


def test_parse_otlp_spans_extracts_trace_span_ids_and_merges_resource_attributes():
    payload = _gen_ai_payload()
    records = parse_otlp_spans_json(payload)
    assert len(records) == 1
    assert records[0]["trace_id"] == "trace-1"
    assert records[0]["span_id"] == "span-1"
    assert records[0]["attributes"]["session.id"] == "s1"  # merged from resource
    assert records[0]["attributes"]["gen_ai.provider.name"] == "gcp.gemini"


def test_ingest_gen_ai_spans_ignores_non_gen_ai_spans():
    payload = {
        "resourceSpans": [{
            "resource": {"attributes": []},
            "scopeSpans": [{"spans": [{"name": "http.request", "traceId": "t", "spanId": "s", "attributes": []}]}],
        }],
    }
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        store = GraphStore(Path(d) / "graph")
        result = ingest_gen_ai_spans(store, parse_otlp_spans_json(payload))
        assert result == {
            "stored_memories": [], "reused_memories": [], "stored_otel_events": 0, "skipped_spans": 1,
        }
        store.close()


def test_ingest_gen_ai_spans_stores_messages_as_memories_and_tool_calls_as_otel_events(tmp_path):
    """The actual universal-ingest scenario: a Gemini-CLI-shaped span (gen_ai.provider.name
    identifies the vendor), decoded with no Claude-Code-specific knowledge at all.
    """
    store = GraphStore(tmp_path / "graph")
    payload = _gen_ai_payload(
        input_messages=[_gen_ai_message("user", _text_part("What is 2+2 and write it to a file?"))],
        output_messages=[_gen_ai_message(
            "assistant",
            _text_part("It's 4. Writing it now."),
            _tool_call_part("call_1", "write_file", {"path": "answer.txt", "content": "4"}),
        )],
    )
    result = ingest_gen_ai_spans(store, parse_otlp_spans_json(payload))

    assert len(result["stored_memories"]) == 2
    assert result["stored_otel_events"] == 2  # tool_call span + gen_ai.chat log

    memories = {store.get_memory(mid)["source"]["role"]: store.get_memory(mid)["content"] for mid in result["stored_memories"]}
    assert memories["user"] == "What is 2+2 and write it to a file?"
    assert memories["assistant"] == "It's 4. Writing it now."

    user_memory_id = next(mid for mid in result["stored_memories"] if store.get_memory(mid)["source"]["role"] == "user")
    linked = store.memory_otel_events(user_memory_id)
    linked_names = {e["name"] for e in linked}
    assert linked_names == {"tool_call.write_file", "gen_ai.chat"}

    chat_event = next(e for e in linked if e["name"] == "gen_ai.chat")
    assert chat_event["attributes"]["provider"] == "gcp.gemini"
    assert chat_event["attributes"]["model"] == "gemini-2.5-pro"
    assert chat_event["attributes"]["input_tokens"] == 120
    store.close()


def test_ingest_gen_ai_spans_dedupes_against_content_from_other_paths(tmp_path):
    """Provider-agnostic dedup: an OpenAI Codex CLI span describing text already captured by
    Path A/B/C (or a different provider's gen_ai span) reuses the memory, doesn't duplicate.
    """
    store = GraphStore(tmp_path / "graph")
    store.start_session("s1", retention_tier="verbatim")
    existing = store.store_memory(
        "What is 2+2 and write it to a file?",
        source={"kind": "direct_user", "session_id": "s1"}, status="confirmed",
    )

    payload = _gen_ai_payload(
        provider="openai", model="gpt-5.1", session_id="s1",
        input_messages=[_gen_ai_message("user", _text_part("What is 2+2 and write it to a file?"))],
    )
    result = ingest_gen_ai_spans(store, parse_otlp_spans_json(payload))
    assert result["stored_memories"] == []
    assert result["reused_memories"] == [existing["id"]]
    store.close()


def test_ingest_gen_ai_spans_handles_json_string_fallback_for_messages(tmp_path):
    """Per spec: messages MAY be a JSON string when structured form isn't supported."""
    store = GraphStore(tmp_path / "graph")
    payload = _gen_ai_payload()
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"].append({
        "key": "gen_ai.input.messages",
        "value": _sval(json.dumps([{"role": "user", "parts": [{"type": "text", "content": "hello via JSON string"}]}])),
    })
    result = ingest_gen_ai_spans(store, parse_otlp_spans_json(payload))
    assert len(result["stored_memories"]) == 1
    assert store.get_memory(result["stored_memories"][0])["content"] == "hello via JSON string"
    store.close()


def test_traces_endpoint_accepts_a_real_http_post_end_to_end(tmp_path):
    store = GraphStore(tmp_path / "graph")
    port = 14320
    thread = threading.Thread(target=serve, kwargs={"store": store, "port": port}, daemon=True)
    thread.start()
    import time
    time.sleep(0.3)

    payload = _gen_ai_payload(
        session_id="http-gen-ai-session",
        input_messages=[_gen_ai_message("user", _text_part("hello from a real gen_ai http request"))],
    )
    request = urllib.request.Request(
        f"http://localhost:{port}/v1/traces",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200
        assert json.loads(response.read()) == {}

    memories = store.session_memories("http-gen-ai-session")
    assert any(m["content"] == "hello from a real gen_ai http request" for m in memories)
    store.close()
