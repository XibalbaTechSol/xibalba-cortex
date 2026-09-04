"""A local OTLP/HTTP-JSON receiver, two signals, two conventions:

**/v1/logs -- Path B, Claude-Code-specific.** claude_code.user_prompt / assistant_response /
api_request / tool_result, all carrying prompt.id, message.uuid, session.id -- closes the
attribution gap Path A (raw_body_ingest.py) states honestly it can't close alone.

    CLAUDE_CODE_ENABLE_TELEMETRY=1
    OTEL_LOGS_EXPORTER=otlp
    OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/json
    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4318/v1/logs
    OTEL_LOG_USER_PROMPTS=1            # to get actual prompt text, not just prompt_length
    OTEL_LOG_ASSISTANT_RESPONSES=1     # to get actual response text

**/v1/traces -- the universal path.** The OpenTelemetry GenAI semantic convention
(gen_ai.* attributes, CNCF-backed, verified against the live spec registry before building
this, not assumed) is vendor-neutral -- the same convention Gemini CLI, OpenAI's Codex CLI,
and any other gen_ai-instrumented harness emit over OTLP. One receiver, many vendors, instead
of a bespoke adapter per harness. gen_ai.provider.name identifies which one produced a given
span (openai, anthropic, gcp.gemini, ...). This data rides on SPANS, not logs -- a different
OTLP signal/endpoint/payload shape (resourceSpans/scopeSpans/spans, not
resourceLogs/scopeLogs/logRecords) -- confirmed against the spec, not guessed.

    OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
    # exact enablement flags are per-harness -- see that harness's own OTel docs.

http/json (not grpc, not http/protobuf) throughout, deliberate: stdlib http.server + json is
enough, no opentelemetry-proto/grpc dependency needed.

Scope, stated plainly: /v1/metrics (a third OTLP signal, different payload shape again --
resourceMetrics/dataPoints) is not handled by either endpoint. Claude Code's
claude_code.token.usage / claude_code.cost.usage still require memory_record_otel_batch
directly, same as before this module existed.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .connector_policy import ConnectorRateLimiter
from .store import GraphStore

logger = logging.getLogger("xibalba_cortex.otlp_receiver")

UNATTRIBUTED_SESSION_ID = "otlp-unattributed"
_REDACTED_SENTINEL = "<REDACTED>"

# event_name -> (text attribute key, role). Only these two events carry LLM text.
_TEXT_EVENTS = {
    "claude_code.user_prompt": ("prompt", "user"),
    "claude_code.assistant_response": ("response", "assistant"),
}
# Structured telemetry events with no text content -- go to otel_events, not memories.
_TELEMETRY_EVENTS = {"claude_code.api_request", "claude_code.tool_result"}


def _decode_attribute_value(value: dict[str, Any]) -> Any:
    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return value["doubleValue"]
    if "boolValue" in value:
        return value["boolValue"]
    if "arrayValue" in value:
        return [_decode_attribute_value(v) for v in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        # Structured object values (e.g. gen_ai.input.messages recorded in structured form,
        # per the spec, rather than as a JSON string) arrive this way.
        return _decode_attributes(value["kvlistValue"].get("values", []))
    return None


def _decode_attributes(attr_list: list[dict[str, Any]]) -> dict[str, Any]:
    return {item["key"]: _decode_attribute_value(item.get("value", {})) for item in attr_list if "key" in item}


def parse_otlp_logs_json(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten an OTLP ExportLogsServiceRequest JSON body into one dict per log record:
    {event_name, attributes, time_unix_nano}. Resource-level attributes (session.id,
    user.account_uuid, etc. -- Claude Code's docs: "standard attributes... included on ALL
    metrics and events") are merged in, with per-record attributes taking precedence on
    conflict.
    """
    records = []
    for resource_log in body.get("resourceLogs", []):
        resource_attrs = _decode_attributes(resource_log.get("resource", {}).get("attributes", []))
        for scope_log in resource_log.get("scopeLogs", []):
            for log_record in scope_log.get("logRecords", []):
                record_attrs = _decode_attributes(log_record.get("attributes", []))
                event_name = log_record.get("eventName") or record_attrs.get("otel.event.name")
                records.append({
                    "event_name": event_name,
                    "attributes": {**resource_attrs, **record_attrs},
                    "time_unix_nano": log_record.get("timeUnixNano"),
                })
    return records


def ingest_log_records(store: GraphStore, records: list[dict[str, Any]]) -> dict[str, object]:
    """Route decoded log records to memories (text-bearing events) or otel_events
    (structured telemetry), using session.id/prompt_id/message.uuid/user.account_uuid
    attributes for real attribution -- what Path A structurally couldn't provide alone.

    Two passes, deliberately, not one: text events (user_prompt/assistant_response) are
    resolved first, building a prompt_id -> memory_id map; telemetry events
    (api_request/tool_result) are resolved second, so they can link via that map regardless
    of which order the two kinds actually arrive in within a batch (OTel export ordering is
    not a documented guarantee to rely on here).

    Content-hash deduplication, not blind insertion: if a memory with the exact same content
    already exists -- most commonly because raw_body_ingest (Path A) already captured this
    same turn from the raw API body file, arriving independently and typically first, since
    Path A writes synchronously while OTLP export batches on a timer -- this does NOT create a
    duplicate memory. `sources` rows are immutable by design (append-only, same as every other
    provenance record in this system), so an already-stored memory's own session_id/prompt_id
    can't be rewritten in place even though this event has better attribution. Instead: the
    existing memory is reused, and the richer/correctly-attributed telemetry for that turn is
    linked to it via otel_events.memory_id -- so memory_otel_events() surfaces the real
    session/prompt context even though the memory's own source record still honestly reflects
    what was known when Path A first captured it.
    """
    prompt_id_to_memory_id: dict[str, str] = {}
    stored_memories: list[str] = []
    reused_memories: list[str] = []
    stored_otel_events = 0
    redacted_skipped = 0
    unrecognized_events: list[str] = []

    text_records = [r for r in records if r["event_name"] in _TEXT_EVENTS]
    telemetry_records = [r for r in records if r["event_name"] in _TELEMETRY_EVENTS]
    for record in records:
        if record["event_name"] not in _TEXT_EVENTS and record["event_name"] not in _TELEMETRY_EVENTS:
            if record["event_name"]:
                unrecognized_events.append(record["event_name"])

    for record in text_records:
        text_key, role = _TEXT_EVENTS[record["event_name"]]
        attrs = record["attributes"]
        text = attrs.get(text_key)
        if not text or text == _REDACTED_SENTINEL:
            redacted_skipped += 1
            continue

        prompt_id = attrs.get("prompt.id")
        existing_id = store.find_memory_id_by_content(text)
        if existing_id:
            reused_memories.append(existing_id)
            memory_id = existing_id
        else:
            session_id = attrs.get("session.id") or UNATTRIBUTED_SESSION_ID
            store.start_session(session_id, retention_tier="verbatim")
            memory = store.store_memory(
                text,
                source={
                    "kind": "direct_user",
                    "session_id": session_id,
                    "role": role,
                    "message_id": attrs.get("message.uuid"),
                    "prompt_id": prompt_id,
                    "agent_id": attrs.get("user.account_uuid") or attrs.get("user.id"),
                    "observed_at": record.get("time_unix_nano"),
                },
                status="candidate",
                evidence_class="observed_event",
            )
            memory_id = memory["id"]
            stored_memories.append(memory_id)

        if prompt_id:
            prompt_id_to_memory_id[prompt_id] = memory_id

    for record in telemetry_records:
        attrs = record["attributes"]
        session_id = attrs.get("session.id") or UNATTRIBUTED_SESSION_ID
        prompt_id = attrs.get("prompt.id")
        store.start_session(session_id, retention_tier="verbatim")
        event: dict[str, Any] = {
            "kind": "log",
            "name": record["event_name"],
            "prompt_id": prompt_id,
            "attributes": attrs,
        }
        linked_memory_id = prompt_id_to_memory_id.get(prompt_id) if prompt_id else None
        if linked_memory_id:
            event["memory_id"] = linked_memory_id
        store.record_otel_batch(session_id, [event])
        stored_otel_events += 1

    return {
        "stored_memories": stored_memories,
        "reused_memories": reused_memories,
        "stored_otel_events": stored_otel_events,
        "redacted_skipped": redacted_skipped,
        "unrecognized_events": unrecognized_events,
    }


# Presence of any one of these on a span identifies it as GenAI-convention telemetry --
# gen_ai.system is the older/fallback attribute name, gen_ai.provider.name the current one.
_GEN_AI_MARKER_ATTRS = ("gen_ai.provider.name", "gen_ai.system", "gen_ai.request.model")


def parse_otlp_spans_json(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten an OTLP ExportTraceServiceRequest JSON body into one dict per span:
    {name, trace_id, span_id, parent_span_id, attributes, start_time_unix_nano,
    end_time_unix_nano}. traceId/spanId/parentSpanId are native OTLP span fields (hex
    strings), not AnyValue-wrapped attributes -- read directly, not through
    _decode_attribute_value.
    """
    records = []
    for resource_span in body.get("resourceSpans", []):
        resource_attrs = _decode_attributes(resource_span.get("resource", {}).get("attributes", []))
        for scope_span in resource_span.get("scopeSpans", []):
            for span in scope_span.get("spans", []):
                span_attrs = _decode_attributes(span.get("attributes", []))
                records.append({
                    "name": span.get("name"),
                    "trace_id": span.get("traceId"),
                    "span_id": span.get("spanId"),
                    "parent_span_id": span.get("parentSpanId"),
                    "attributes": {**resource_attrs, **span_attrs},
                    "start_time_unix_nano": span.get("startTimeUnixNano"),
                    "end_time_unix_nano": span.get("endTimeUnixNano"),
                })
    return records


def _parse_gen_ai_message_list(value: Any) -> list[dict[str, Any]]:
    """gen_ai.input.messages / output.messages / system_instructions: per the spec, "MAY be
    recorded as a JSON string if structured format is not supported and SHOULD be recorded in
    structured form otherwise" -- handle both. Structure: [{"role": ..., "parts": [{"type":
    "text", "content": ...} | {"type": "tool_call", ...}]}].
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    messages = []
    for item in value:
        if not isinstance(item, dict):
            continue
        parts = item.get("parts")
        if not isinstance(parts, list):
            continue
        text_parts = [
            p.get("content", "") for p in parts
            if isinstance(p, dict) and p.get("type") == "text" and p.get("content")
        ]
        tool_calls = [p for p in parts if isinstance(p, dict) and p.get("type") == "tool_call"]
        messages.append({
            "role": item.get("role") or "unknown",
            "text": "\n".join(text_parts),
            "tool_calls": tool_calls,
        })
    return messages


def ingest_gen_ai_spans(store: GraphStore, records: list[dict[str, Any]]) -> dict[str, object]:
    """Route OTel GenAI-semantic-convention spans (any vendor honoring gen_ai.* -- verified
    conventions, not this project's own naming) to memories (message text) and otel_events
    (model/token/finish-reason telemetry, tool calls). Same content-hash dedup as
    ingest_log_records -- a span describing content Path A/B/C already captured reuses that
    memory rather than duplicating it.

    A span's own trace_id doubles as this exchange's prompt_id -- gen_ai spans don't carry a
    separate Claude-Code-style prompt.id, and trace_id is the natural per-invocation
    correlation key the convention already provides, so reusing it (rather than inventing a
    second identifier scheme) keeps this compatible with the same exchange-building logic
    Path A/B/C already use.
    """
    stored_memories: list[str] = []
    reused_memories: list[str] = []
    stored_otel_events = 0
    skipped_spans = 0

    for record in records:
        attrs = record["attributes"]
        if not any(key in attrs for key in _GEN_AI_MARKER_ATTRS):
            skipped_spans += 1
            continue

        session_id = attrs.get("session.id") or UNATTRIBUTED_SESSION_ID
        trace_id = record.get("trace_id")
        span_id = record.get("span_id")
        provider = attrs.get("gen_ai.provider.name") or attrs.get("gen_ai.system")
        agent_id = attrs.get("user.account_uuid") or attrs.get("user.id")
        store.start_session(session_id, retention_tier="verbatim")

        def _store_text(text: str, role: str) -> None:
            if not text.strip():
                return
            existing = store.find_memory_id_by_content(text)
            if existing:
                reused_memories.append(existing)
                return
            memory = store.store_memory(
                text,
                source={
                    "kind": "direct_user",
                    "session_id": session_id,
                    "role": role,
                    "prompt_id": trace_id,
                    "agent_id": agent_id,
                },
                status="candidate",
                evidence_class="observed_event",
            )
            stored_memories.append(memory["id"])

        for message in _parse_gen_ai_message_list(attrs.get("gen_ai.system_instructions")):
            _store_text(message["text"], "system")
        for message in _parse_gen_ai_message_list(attrs.get("gen_ai.input.messages")):
            _store_text(message["text"], message["role"] if message["role"] != "unknown" else "user")
        for message in _parse_gen_ai_message_list(attrs.get("gen_ai.output.messages")):
            _store_text(message["text"], message["role"] if message["role"] != "unknown" else "assistant")
            for tool_call in message["tool_calls"]:
                store.record_otel_batch(session_id, [{
                    "kind": "span",
                    "name": f"tool_call.{tool_call.get('name', 'unknown')}",
                    "trace_id": trace_id,
                    "span_id": tool_call.get("id"),
                    "parent_span_id": span_id,
                    "prompt_id": trace_id,
                    "attributes": {"provider": provider, "tool_call": tool_call},
                }])
                stored_otel_events += 1

        store.record_otel_batch(session_id, [{
            "kind": "log",
            "name": "gen_ai.chat",
            "trace_id": trace_id,
            "span_id": span_id,
            "prompt_id": trace_id,
            "attributes": {
                "provider": provider,
                "model": attrs.get("gen_ai.request.model"),
                "input_tokens": attrs.get("gen_ai.usage.input_tokens"),
                "output_tokens": attrs.get("gen_ai.usage.output_tokens"),
                "finish_reasons": attrs.get("gen_ai.response.finish_reasons"),
            },
        }])
        stored_otel_events += 1

    return {
        "stored_memories": stored_memories,
        "reused_memories": reused_memories,
        "stored_otel_events": stored_otel_events,
        "skipped_spans": skipped_spans,
    }


# Fixed, matching OTLP's own conventional well-known paths -- not made configurable, since
# every OTel exporter targeting this receiver already expects these exact paths by default.
_LOGS_PATH = "/v1/logs"
_TRACES_PATH = "/v1/traces"


def _make_handler(store: GraphStore):
    request_limiter = ConnectorRateLimiter(rate_per_second=20.0, burst=40)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming convention
            request_limiter.wait()
            if self.path == _LOGS_PATH:
                parse_fn, ingest_fn, label = parse_otlp_logs_json, ingest_log_records, "log"
            elif self.path == _TRACES_PATH:
                parse_fn, ingest_fn, label = parse_otlp_spans_json, ingest_gen_ai_spans, "span"
            else:
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
                records = parse_fn(body)
                result = ingest_fn(store, records)
                logger.info("ingested %s batch: %s", label, result)
            except Exception:
                logger.exception("failed to ingest OTLP %s batch", label)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": "ingestion failed"}).encode())
                return
            # OTLP/HTTP success response for both Export*ServiceResponse shapes is an empty
            # JSON object -- same for logs and traces.
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            logger.debug(format, *args)

    return Handler


def serve(store: GraphStore, *, host: str = "localhost", port: int = 4318) -> None:
    server = ThreadingHTTPServer((host, port), _make_handler(store))
    logger.info(
        "OTLP receiver listening on http://%s:%d (%s logs, %s traces/gen_ai)",
        host, port, _LOGS_PATH, _TRACES_PATH,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, help="xibalba-cortex profile home")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4318)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    store = GraphStore(args.home)
    try:
        serve(store, host=args.host, port=args.port)
    finally:
        store.close()


if __name__ == "__main__":
    main()
