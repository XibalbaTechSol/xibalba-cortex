"""Path B: a local OTLP/HTTP-JSON log receiver for Claude Code's structured telemetry.

Closes the attribution gap Path A (raw_body_ingest.py) states honestly it can't close alone:
claude_code.user_prompt / claude_code.assistant_response / claude_code.api_request /
claude_code.tool_result all carry prompt.id, message.uuid, and session.id -- the real
correlation and session attribution Path A's raw request/response files structurally lack.

Enable on the Claude Code side with:

    CLAUDE_CODE_ENABLE_TELEMETRY=1
    OTEL_LOGS_EXPORTER=otlp
    OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/json
    OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:<port>/v1/logs
    OTEL_LOG_USER_PROMPTS=1            # to get actual prompt text, not just prompt_length
    OTEL_LOG_ASSISTANT_RESPONSES=1     # to get actual response text

http/json (not grpc, not http/protobuf) is deliberate: stdlib http.server + json is enough,
no opentelemetry-proto/grpc dependency needed for this.

Scope, stated plainly: this receiver only implements the /v1/logs endpoint. Claude Code's
claude_code.token.usage / claude_code.cost.usage are METRICS, a different OTLP signal
(/v1/metrics, a different payload shape -- resourceMetrics/scopeMetrics/dataPoints, not
logRecords) -- not handled here. session_otel_summary's token/cost totals still require
piping those through memory_record_otel_batch separately, same as before this module existed.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .store import GraphStore

logger = logging.getLogger("xibalba_graph.otlp_receiver")

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
    """
    stored_memories: list[str] = []
    stored_otel_events = 0
    redacted_skipped = 0
    unrecognized_events: list[str] = []

    for record in records:
        event_name = record["event_name"]
        attrs = record["attributes"]
        session_id = attrs.get("session.id") or UNATTRIBUTED_SESSION_ID
        agent_id = attrs.get("user.account_uuid") or attrs.get("user.id")

        if event_name in _TEXT_EVENTS:
            text_key, role = _TEXT_EVENTS[event_name]
            text = attrs.get(text_key)
            if not text or text == _REDACTED_SENTINEL:
                redacted_skipped += 1
                continue
            store.start_session(session_id, retention_tier="verbatim")
            memory = store.store_memory(
                text,
                source={
                    "kind": "direct_user",
                    "session_id": session_id,
                    "role": role,
                    "message_id": attrs.get("message.uuid"),
                    "prompt_id": attrs.get("prompt.id"),
                    "agent_id": agent_id,
                    "observed_at": record.get("time_unix_nano"),
                },
                status="candidate",
                evidence_class="observed_event",
            )
            stored_memories.append(memory["id"])

        elif event_name in _TELEMETRY_EVENTS:
            store.start_session(session_id, retention_tier="verbatim")
            store.record_otel_batch(session_id, [{
                "kind": "log",
                "name": event_name,
                "prompt_id": attrs.get("prompt.id"),
                "attributes": attrs,
            }])
            stored_otel_events += 1

        elif event_name:
            unrecognized_events.append(event_name)

    return {
        "stored_memories": stored_memories,
        "stored_otel_events": stored_otel_events,
        "redacted_skipped": redacted_skipped,
        "unrecognized_events": unrecognized_events,
    }


def _make_handler(store: GraphStore, path: str):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming convention
            if self.path != path:
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
                records = parse_otlp_logs_json(body)
                result = ingest_log_records(store, records)
                logger.info("ingested batch: %s", result)
            except Exception:
                logger.exception("failed to ingest OTLP log batch")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": "ingestion failed"}).encode())
                return
            # OTLP/HTTP success response for ExportLogsServiceResponse is an empty JSON object.
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            logger.debug(format, *args)

    return Handler


def serve(store: GraphStore, *, host: str = "localhost", port: int = 4318, path: str = "/v1/logs") -> None:
    server = ThreadingHTTPServer((host, port), _make_handler(store, path))
    logger.info("OTLP log receiver listening on http://%s:%d%s", host, port, path)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, help="xibalba-graph-memory profile home")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--path", default="/v1/logs")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    store = GraphStore(args.home)
    try:
        serve(store, host=args.host, port=args.port, path=args.path)
    finally:
        store.close()


if __name__ == "__main__":
    main()
