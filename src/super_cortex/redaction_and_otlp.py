"""Deterministic secret/PII redaction and OpenTelemetry (OTLP/HTTP) trace & log ingestion for Super-Cortex."""
from __future__ import annotations

import re
from typing import Any

# Ordered deterministic secret & PII scrubbing patterns
_REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # PEM private keys
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.MULTILINE,
        ),
        "[REDACTED:PRIVATE_KEY]",
    ),
    # Anthropic keys (must run before generic sk-)
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{12,}\b"), "[REDACTED:ANTHROPIC_KEY]"),
    # Stripe live/test secret & restricted keys
    (re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}\b"), "[REDACTED:STRIPE_KEY]"),
    # Stripe webhook signing secrets
    (re.compile(r"\bwhsec_[A-Za-z0-9]{12,}\b"), "[REDACTED:STRIPE_WEBHOOK_SECRET]"),
    # OpenAI project/service/standard keys
    (re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{16,}\b"), "[REDACTED:OPENAI_KEY]"),
    # GitHub personal/fine-grained/oauth tokens
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), "[REDACTED:GITHUB_TOKEN]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED:GITHUB_PAT]"),
    # AWS Access Key IDs
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED:AWS_ACCESS_KEY]"),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"), "[REDACTED:SLACK_TOKEN]"),
    # Google API keys
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[REDACTED:GOOGLE_API_KEY]"),
    # Authorization Bearer tokens in headers/logs
    (
        re.compile(r"(?i)\b(Authorization\s*:\s*Bearer\s+)[A-Za-z0-9._\-+/=]{12,}"),
        r"\1[REDACTED:BEARER_TOKEN]",
    ),
    # US Social Security Numbers (XXX-XX-XXXX, excluding obvious 000/666/9xx prefixes)
    (
        re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
        "[REDACTED:SSN]",
    ),
]


def redact_secrets(text: str) -> str:
    """Deterministically scrub API keys, bearer tokens, private keys, and SSNs prior to persistence."""
    if not text:
        return text
    scrubbed = text
    for pattern, replacement in _REDACTION_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


def _extract_otlp_attr_value(val_obj: dict[str, Any] | Any) -> Any:
    if not isinstance(val_obj, dict):
        return val_obj
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in val_obj:
            return val_obj[key]
    if "arrayValue" in val_obj and isinstance(val_obj["arrayValue"], dict):
        values = val_obj["arrayValue"].get("values") or []
        return [_extract_otlp_attr_value(v) for v in values]
    return str(val_obj)


def _otlp_attributes_to_dict(attrs: list[dict[str, Any]] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in attrs or []:
        if isinstance(item, dict) and "key" in item:
            result[str(item["key"])] = _extract_otlp_attr_value(item.get("value", {}))
    return result


async def ingest_otlp_traces(
    cortex: Any,
    payload: dict[str, Any],
    *,
    default_scope: str = "shared",
) -> dict[str, Any]:
    """Ingest OpenTelemetry OTLP/JSON `resourceSpans` into Super-Cortex memories and provenance chains."""
    resource_spans = payload.get("resourceSpans") or payload.get("resource_spans") or []
    ingested_count = 0
    memory_ids: list[str] = []

    for rs in resource_spans:
        res_attrs = _otlp_attributes_to_dict((rs.get("resource") or {}).get("attributes"))
        service_name = str(res_attrs.get("service.name") or res_attrs.get("agent.id") or "otlp-service")
        scope = str(res_attrs.get("cortex.scope") or default_scope)
        scope_spans = rs.get("scopeSpans") or rs.get("scope_spans") or []

        for ss in scope_spans:
            spans = ss.get("spans") or []
            for span in spans:
                span_name = str(span.get("name") or "unnamed_span")
                trace_id = str(span.get("traceId") or span.get("trace_id") or "")
                span_id = str(span.get("spanId") or span.get("span_id") or "")
                span_attrs = _otlp_attributes_to_dict(span.get("attributes"))
                status_obj = span.get("status") or {}
                status_msg = str(status_obj.get("message") or status_obj.get("code") or "OK")

                summary_parts = [
                    f"[OTLP Span] {service_name} :: {span_name} (status={status_msg})",
                ]
                for k, v in list(span_attrs.items())[:12]:
                    summary_parts.append(f"{k}={v}")
                summary_text = redact_secrets(" | ".join(summary_parts))

                res = await cortex.remember(
                    text=summary_text,
                    epistemic_class="fact",
                    scope=scope,
                    agent_id=service_name,
                    session_id=f"otlp_trace_{trace_id[:16]}" if trace_id else None,
                    source_origin="otlp:traces",
                    metadata={
                        "otlp_type": "span",
                        "service_name": service_name,
                        "span_name": span_name,
                        "trace_id": trace_id,
                        "span_id": span_id,
                        "attributes": span_attrs,
                    },
                )
                ingested_count += 1
                if res.get("memory_id"):
                    memory_ids.append(res["memory_id"])

    return {
        "status": "ok",
        "ingested_spans": ingested_count,
        "memory_ids": memory_ids,
    }


async def ingest_otlp_logs(
    cortex: Any,
    payload: dict[str, Any],
    *,
    default_scope: str = "shared",
) -> dict[str, Any]:
    """Ingest OpenTelemetry OTLP/JSON `resourceLogs` into Super-Cortex memories and provenance chains."""
    resource_logs = payload.get("resourceLogs") or payload.get("resource_logs") or []
    ingested_count = 0
    memory_ids: list[str] = []

    for rl in resource_logs:
        res_attrs = _otlp_attributes_to_dict((rl.get("resource") or {}).get("attributes"))
        service_name = str(res_attrs.get("service.name") or res_attrs.get("agent.id") or "otlp-logger")
        scope = str(res_attrs.get("cortex.scope") or default_scope)
        scope_logs = rl.get("scopeLogs") or rl.get("scope_logs") or []

        for sl in scope_logs:
            log_records = sl.get("logRecords") or sl.get("log_records") or []
            for lr in log_records:
                severity = str(lr.get("severityText") or lr.get("severity_text") or "INFO")
                body_raw = _extract_otlp_attr_value(lr.get("body") or {})
                body_str = str(body_raw or "").strip()
                if not body_str:
                    continue
                log_attrs = _otlp_attributes_to_dict(lr.get("attributes"))
                trace_id = str(lr.get("traceId") or lr.get("trace_id") or "")

                text = redact_secrets(f"[OTLP Log:{severity}] {service_name}: {body_str}")
                res = await cortex.remember(
                    text=text,
                    epistemic_class="fact",
                    scope=scope,
                    agent_id=service_name,
                    session_id=f"otlp_trace_{trace_id[:16]}" if trace_id else None,
                    source_origin="otlp:logs",
                    metadata={
                        "otlp_type": "log",
                        "service_name": service_name,
                        "severity": severity,
                        "trace_id": trace_id,
                        "attributes": log_attrs,
                    },
                )
                ingested_count += 1
                if res.get("memory_id"):
                    memory_ids.append(res["memory_id"])

    return {
        "status": "ok",
        "ingested_logs": ingested_count,
        "memory_ids": memory_ids,
    }
