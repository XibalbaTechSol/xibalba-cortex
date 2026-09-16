"""OpenTelemetry compatibility helpers and optional OTLP exporters.

The Integrity layer deliberately extends, rather than replaces, OpenTelemetry.  This module
contains the small amount of translation needed at the boundary: canonical GenAI attributes,
protobuf decoding, metric datapoint flattening, and provider-neutral exporter construction.
The exporter imports are lazy so the local JSON receiver remains usable without installing an
OTel exporter implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
from typing import Any, Literal

from google.protobuf.json_format import MessageToDict

_SIGNALS = {"traces", "metrics", "logs"}


def normalize_trace_identifier(value: Any, byte_length: int) -> Any:
    """Normalize protobuf base64 trace/span IDs to OTLP's canonical lowercase hex form."""
    if not isinstance(value, str):
        return value
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception:
        return value
    return decoded.hex() if len(decoded) == byte_length else value


def canonical_gen_ai_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Return standard ``gen_ai.*`` names while retaining vendor attributes.

    Older Claude/vendor payloads use short names such as ``model`` and ``input_tokens``.
    Those are copied into the current semantic namespace; the source mapping is not deleted,
    which preserves provider evidence and keeps existing Cortex queries compatible.
    """
    result = dict(attributes)
    provider = result.get("gen_ai.provider.name") or result.get("gen_ai.system") or result.get("provider")
    model = result.get("gen_ai.request.model") or result.get("model")
    if provider is not None:
        result.setdefault("gen_ai.provider.name", provider)
    if model is not None:
        result.setdefault("gen_ai.request.model", model)
    if result.get("operation") and not result.get("gen_ai.operation.name"):
        result["gen_ai.operation.name"] = result["operation"]
    mappings = {
        "input_tokens": "gen_ai.usage.input_tokens",
        "prompt_tokens": "gen_ai.usage.input_tokens",
        "output_tokens": "gen_ai.usage.output_tokens",
        "completion_tokens": "gen_ai.usage.output_tokens",
        "total_tokens": "gen_ai.usage.total_tokens",
        "cached_input_tokens": "gen_ai.usage.cache_read.input_tokens",
        "cache_read_tokens": "gen_ai.usage.cache_read.input_tokens",
        "cache_write_tokens": "gen_ai.usage.cache_creation.input_tokens",
        "reasoning_tokens": "gen_ai.usage.reasoning.output_tokens",
        "reasoning_output_tokens": "gen_ai.usage.reasoning.output_tokens",
    }
    for source, target in mappings.items():
        if source in result and target not in result:
            result[target] = result[source]
    return result


def protobuf_json(body: bytes, signal: Literal["traces", "metrics", "logs"]) -> dict[str, Any]:
    """Decode an OTLP protobuf Export request to the same dict shape as OTLP/JSON."""
    if signal not in _SIGNALS:
        raise ValueError(f"unsupported OTLP signal: {signal}")
    if signal == "traces":
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
        message = ExportTraceServiceRequest()
    elif signal == "metrics":
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
        message = ExportMetricsServiceRequest()
    else:
        from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
        message = ExportLogsServiceRequest()
    message.ParseFromString(body)
    return MessageToDict(message, preserving_proto_field_name=False)


def _any_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    for key in ("stringValue", "intValue", "doubleValue", "boolValue", "bytesValue"):
        if key in value:
            return value[key]
    if "arrayValue" in value:
        return [_any_value(item) for item in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        return {item.get("key"): _any_value(item.get("value"))
                for item in value["kvlistValue"].get("values", [])}
    return None


def decode_attributes(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {item["key"]: _any_value(item.get("value", {}))
            for item in items or [] if item.get("key")}


def parse_otlp_metrics_json(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten OTLP metrics datapoints, retaining native metric identity and timestamps."""
    records: list[dict[str, Any]] = []
    for resource_metric in body.get("resourceMetrics", []):
        resource_attrs = decode_attributes((resource_metric.get("resource") or {}).get("attributes"))
        for scope_metric in resource_metric.get("scopeMetrics", []):
            for metric in scope_metric.get("metrics", []):
                name = metric.get("name")
                description = metric.get("description")
                unit = metric.get("unit")
                for kind in ("gauge", "sum", "histogram", "exponentialHistogram", "summary"):
                    payload = metric.get(kind)
                    if not payload:
                        continue
                    points = payload.get("dataPoints", [])
                    for point in points:
                        attrs = canonical_gen_ai_attributes({**resource_attrs, **decode_attributes(point.get("attributes"))})
                        value = point.get("asDouble", point.get("asInt"))
                        if value is None and kind in {"histogram", "exponentialHistogram", "summary"}:
                            value = point.get("sum")
                        records.append({
                            "name": name, "description": description, "unit": unit,
                            "metric_type": kind, "value": value,
                            "start_time_unix_nano": point.get("startTimeUnixNano"),
                            "time_unix_nano": point.get("timeUnixNano"),
                            "attributes": attrs,
                        })
    return records


def ingest_metric_records(store: Any, records: list[dict[str, Any]]) -> dict[str, int]:
    """Persist metric datapoints without turning them into memories."""
    stored = 0
    skipped = 0
    by_session: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        attrs = canonical_gen_ai_attributes(record.get("attributes") or {})
        session_id = str(attrs.get("session.id") or "otlp-unattributed")
        if not record.get("name"):
            skipped += 1
            continue
        by_session.setdefault(session_id, []).append({
            "kind": "metric", "name": record["name"],
            "trace_id": attrs.get("trace.id"), "span_id": attrs.get("span.id"),
            "value": record.get("value"), "unit": record.get("unit"),
            "start_time": record.get("start_time_unix_nano") or record.get("time_unix_nano"),
            "end_time": record.get("time_unix_nano"), "attributes": {
                **attrs, "otel.metric.type": record.get("metric_type"),
                "otel.metric.description": record.get("description"),
            },
        })
    for session_id, events in by_session.items():
        store.start_session(session_id, retention_tier="verbatim")
        stored += int(store.record_otel_batch(session_id, events).get("recorded", 0))
    return {"stored_metrics": stored, "skipped_metrics": skipped}


def token_usage_metric_events(*, session_id: str, provider: str, usage: dict[str, int],
                              trace_id: str | None = None, span_id: str | None = None,
                              model: str | None = None, integrity_attributes: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Create standard GenAI token-usage histogram datapoints for adapter-owned calls."""
    token_types = {
        "input_tokens": "input",
        "output_tokens": "output",
        "cached_input_tokens": "cache_read",
        "cache_write_tokens": "cache_creation",
        "reasoning_tokens": "reasoning",
        "reasoning_output_tokens": "reasoning",
    }
    events: list[dict[str, Any]] = []
    for field, token_type in token_types.items():
        if field not in usage:
            continue
        attrs: dict[str, Any] = {
            "gen_ai.provider.name": provider,
            "provider": provider,
            "gen_ai.token.type": token_type,
            "otel.metric.type": "histogram",
        }
        if model:
            attrs["gen_ai.request.model"] = model
        attrs.update(integrity_attributes or {})
        key = json.dumps({"session": session_id, "trace": trace_id, "span": span_id,
                          "provider": provider, "field": field, "value": usage[field]},
                         sort_keys=True, separators=(",", ":"), default=str).encode()
        events.append({
            "kind": "metric", "name": "gen_ai.client.token.usage", "trace_id": trace_id,
            "span_id": span_id, "value": usage[field], "unit": "{token}",
            "attributes": attrs,
            "idempotency_key": "sha256:" + hashlib.sha256(key).hexdigest(),
        })
    return events


@dataclass(frozen=True, slots=True)
class OtlpExporterConfig:
    """Configuration shared by HTTP/protobuf and gRPC OTLP exporters."""

    endpoint: str
    protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"
    headers: dict[str, str] | None = None
    timeout_seconds: float = 10.0


def build_otlp_exporters(config: OtlpExporterConfig) -> dict[str, Any]:
    """Build official OpenTelemetry exporters for traces, metrics, and logs.

    ``opentelemetry-exporter-otlp-proto-http`` and/or ``...-grpc`` are optional dependencies.
    A clear installation error is preferable to silently falling back to a non-standard wire
    format.
    """
    headers = config.headers or {}
    try:
        if config.protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    except ImportError as exc:
        raise RuntimeError(
            "OTLP exporters require the optional 'otel' dependency group; install with "
            "uv sync --extra otel"
        ) from exc
    def signal_endpoint(signal: str) -> str:
        if config.protocol == "grpc":
            return config.endpoint
        base = config.endpoint.rstrip("/")
        for existing in ("traces", "metrics", "logs"):
            suffix = f"/v1/{existing}"
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        return f"{base}/v1/{signal}"

    def exporter_kwargs(signal: str) -> dict[str, Any]:
        return {"endpoint": signal_endpoint(signal), "headers": headers,
                "timeout": config.timeout_seconds}
    return {
        "traces": OTLPSpanExporter(**exporter_kwargs("traces")),
        "metrics": OTLPMetricExporter(**exporter_kwargs("metrics")),
        "logs": OTLPLogExporter(**exporter_kwargs("logs")),
    }


__all__ = [
    "OtlpExporterConfig", "build_otlp_exporters", "canonical_gen_ai_attributes",
    "decode_attributes", "ingest_metric_records", "parse_otlp_metrics_json", "protobuf_json",
    "normalize_trace_identifier", "token_usage_metric_events",
]
