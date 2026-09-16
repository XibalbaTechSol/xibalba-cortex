"""Provider-facing telemetry adapters with explicit consent and retention policy.

These adapters intentionally sit above the shared ``RuntimeEvent`` contract. They never infer a
DID, never retain raw provider payloads by default, and refuse collection unless the caller has
explicitly enabled telemetry for the named provider and supplied a session-bound Integrity DID.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import hashlib
import hmac
import json
import time
from typing import Any, Callable, Literal
from urllib.request import Request, urlopen

from .redaction import redact
from .config import CortexConfig
from .runtime_bridge_contract import RuntimeEvent
from .runtime_controller import XibalbaRuntimeController
from .otel_core import token_usage_metric_events

TelemetryRuntime = Literal["perplexity", "mcp", "cloud_run"]
_RETENTION_TIERS = {"digest", "synopsis", "verbatim"}


@dataclass(frozen=True, slots=True)
class ProviderTelemetryPolicy:
    provider: str
    consent_granted: bool
    retention_tier: str = "digest"
    allow_raw_payloads: bool = False

    def authorize(self, *, session_id: str | None, agent_id: str | None) -> None:
        if not self.provider.strip():
            raise ValueError("provider must be non-empty")
        if not self.consent_granted:
            raise PermissionError(f"telemetry consent is required for provider {self.provider!r}")
        if self.retention_tier not in _RETENTION_TIERS:
            raise ValueError(f"unsupported retention tier: {self.retention_tier!r}")
        if not session_id:
            raise ValueError("session_id is required for provider telemetry")
        if not agent_id or not agent_id.startswith("did:integrity:"):
            raise ValueError("a session-bound did:integrity agent_id is required")


def policy_from_config(config: CortexConfig, provider: str) -> ProviderTelemetryPolicy:
    """Build the provider policy from persisted Cortex config; disabled is fail-closed."""
    settings = config.telemetry
    return ProviderTelemetryPolicy(
        provider=provider,
        consent_granted=settings.enabled and provider in settings.consented_providers,
        retention_tier=settings.retention_tier,
        allow_raw_payloads=settings.allow_raw_payloads,
    )


def create_runtime_adapter(name: str, *, controller: XibalbaRuntimeController,
                           config: CortexConfig, **kwargs: Any) -> Any:
    """Create a provider adapter only after persisted consent has authorized it."""
    policy = policy_from_config(config, name)
    if not policy.consent_granted:
        raise PermissionError(f"telemetry is not enabled/consented for provider {name!r}")
    adapters = {"perplexity": PerplexityAdapter, "mcp": MCPAdapter, "cloud_run": CloudRunAdapter}
    try:
        adapter_type = adapters[name]
    except KeyError as exc:
        raise ValueError(f"unsupported provider adapter: {name!r}") from exc
    return adapter_type(controller, policy, **kwargs)


def _hash(value: Any) -> str | None:
    if value is None:
        return None
    raw = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    output: dict[str, int] = {}
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
        "cached_input_tokens": ("cached_input_tokens", "cache_read_tokens"),
        "cache_read_tokens": ("cache_read_tokens",),
        "cache_write_tokens": ("cache_write_tokens",),
        "reasoning_tokens": ("reasoning_tokens", "reasoning_output_tokens"),
        "reasoning_output_tokens": ("reasoning_output_tokens",),
    }
    for canonical, keys in aliases.items():
        for key in keys:
            if key not in value:
                continue
            try:
                output[canonical] = int(value[key])
            except (TypeError, ValueError):
                pass
            break
    return output or None


def _usage_metadata(value: Any) -> dict[str, Any]:
    """Return normalized usage plus optional provider cost fields.

    Token counts stay in ``RuntimeEvent.token_usage``. Costs are metadata because
    they are monetary values, not tokens, and different providers report them with
    different precision and accounting rules.
    """
    usage = _usage(value)
    result: dict[str, Any] = {"present": bool(usage), "tokens": usage or {}}
    if isinstance(value, dict):
        for key in ("cost_usd", "input_cost_usd", "output_cost_usd", "cached_cost_usd"):
            if key in value:
                try:
                    result[key] = float(value[key])
                except (TypeError, ValueError):
                    continue
    return result


def _payload_metadata(value: Any, *, allow_raw: bool) -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    result: dict[str, Any] = {"hash": _hash(value), "chars": len(text)}
    if allow_raw:
        result["redacted"] = redact(value)
    return result


@dataclass(slots=True)
class _BaseProviderAdapter:
    controller: XibalbaRuntimeController
    policy: ProviderTelemetryPolicy
    runtime: TelemetryRuntime
    provenance: dict[str, Any] = field(default_factory=dict)

    def _event(self, *, session_id: str | None, agent_id: str | None,
               turn_id: str | None = None, invocation_id: str | None = None,
               tool_name: str | None = None, outcome: str = "unknown",
               assistant_response: str | None = None, usage: Any = None,
               metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            self.policy.authorize(session_id=session_id, agent_id=agent_id)
        except Exception as exc:
            self.controller.store.record_telemetry_health(
                self.policy.provider, rejected=1, error=type(exc).__name__
            )
            raise
        normalized_usage = _usage(usage)
        standard_attributes: dict[str, Any] = {
            "gen_ai.provider.name": self.policy.provider,
            "integrity.agent.did": agent_id,
            "integrity.consent.granted": True,
            "integrity.retention.tier": self.policy.retention_tier,
        }
        if normalized_usage:
            standard_attributes.update({
                f"gen_ai.usage.{key}": value for key, value in normalized_usage.items()
            })
            if "cached_input_tokens" in normalized_usage:
                standard_attributes["gen_ai.usage.cache_read.input_tokens"] = normalized_usage["cached_input_tokens"]
            if "cache_write_tokens" in normalized_usage:
                standard_attributes["gen_ai.usage.cache_creation.input_tokens"] = normalized_usage["cache_write_tokens"]
            if "reasoning_tokens" in normalized_usage:
                standard_attributes["gen_ai.usage.reasoning.output_tokens"] = normalized_usage["reasoning_tokens"]
        if metadata:
            if metadata.get("model"):
                standard_attributes["gen_ai.request.model"] = metadata["model"]
            if metadata.get("operation_name"):
                standard_attributes["gen_ai.operation.name"] = metadata["operation_name"]
            if metadata.get("tool_name"):
                standard_attributes["gen_ai.tool.name"] = metadata["tool_name"]
        event_metadata = {"consent_granted": True, "retention_tier": self.policy.retention_tier,
                          "usage": _usage_metadata(usage), **(metadata or {})}
        idempotency_key = "sha256:" + hashlib.sha256(json.dumps({
            "runtime": self.runtime, "provider": self.policy.provider, "session_id": session_id,
            "turn_id": turn_id, "invocation_id": invocation_id, "tool_name": tool_name,
            "metadata": event_metadata,
        }, sort_keys=True, default=str).encode()).hexdigest()
        event = RuntimeEvent(
            runtime=self.runtime, session_id=session_id or "", idempotency_key=idempotency_key,
            trace_id=turn_id, span_id=invocation_id or tool_name,
            status_code="ERROR" if outcome == "error" else "OK" if outcome == "success" else None,
            agent_id=agent_id,
            turn_id=turn_id, invocation_id=invocation_id, tool_name=tool_name,
            tool_outcome=outcome, token_usage=normalized_usage,
            assistant_response=assistant_response if self.policy.allow_raw_payloads else None,
            attributes=standard_attributes,
            provenance={**self.provenance, "provider": self.policy.provider},
            metadata=event_metadata,
        )
        self.controller.open_session(self.runtime, session_id=event.session_id,
                                     agent_id=agent_id, retention_tier=self.policy.retention_tier,
                                     provenance={"provider": self.policy.provider})
        result = self.controller.ingest_event(event)
        metric_result = {"recorded": 0, "duplicates": 0}
        if normalized_usage:
            metric_result = self.controller.store.record_otel_batch(
                event.session_id,
                token_usage_metric_events(
                    session_id=event.session_id, provider=self.policy.provider,
                    usage=normalized_usage, trace_id=turn_id,
                    span_id=invocation_id or tool_name,
                    model=event_metadata.get("model"),
                    integrity_attributes={"integrity.agent.did": agent_id,
                                           "integrity.retention.tier": self.policy.retention_tier},
                ),
            )
        self.controller.store.record_telemetry_health(
            self.policy.provider,
            accepted=int(result.get("recorded", 0)) + int(metric_result.get("recorded", 0)),
            duplicates=int(result.get("duplicates", 0)) + int(metric_result.get("duplicates", 0)),
        )
        return {"recorded": int(result.get("recorded", 0)), "duplicates": int(result.get("duplicates", 0)),
                "metric_recorded": int(metric_result.get("recorded", 0)),
                "metric_duplicates": int(metric_result.get("duplicates", 0)),
                "session_id": event.session_id}


@dataclass(slots=True)
class PerplexityAdapter(_BaseProviderAdapter):
    """Direct Perplexity Agent API adapter using an injectable HTTP transport."""

    runtime: Literal["perplexity"] = "perplexity"
    endpoint: str = "https://api.perplexity.ai/v1/agent"
    request_fn: Callable[..., Any] | None = None
    request_async_fn: Callable[..., Any] | None = None

    def run(self, *, session_id: str, agent_id: str, api_key: str, payload: dict[str, Any],
            turn_id: str | None = None) -> dict[str, Any]:
        safe_request = _payload_metadata(payload, allow_raw=self.policy.allow_raw_payloads)
        self._event(session_id=session_id, agent_id=agent_id, turn_id=turn_id,
                    metadata={"phase": "request", "operation_name": "chat", "request": safe_request})
        try:
            body = json.dumps(payload).encode()
            if self.request_fn:
                response = self.request_fn(self.endpoint, api_key, payload)
            else:
                request = Request(self.endpoint, data=body, method="POST", headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                })
                with urlopen(request, timeout=120) as raw:
                    response = json.loads(raw.read().decode())
            if not isinstance(response, dict):
                response = {"output": response}
            output = response.get("output") or response.get("text") or response.get("content")
            self._event(session_id=session_id, agent_id=agent_id, turn_id=turn_id,
                        outcome="success", assistant_response=output if isinstance(output, str) else None,
                        usage=response.get("usage"), metadata={
                            "phase": "response", "operation_name": "chat", "model": response.get("model"), "response": _payload_metadata(response, allow_raw=self.policy.allow_raw_payloads),
                            "citations": _payload_metadata(response.get("citations"), allow_raw=self.policy.allow_raw_payloads),
                            "request_id": response.get("id") or response.get("request_id"),
                        })
            return response
        except Exception as exc:
            self._event(session_id=session_id, agent_id=agent_id, turn_id=turn_id,
                        outcome="error", metadata={"phase": "error", "error_type": type(exc).__name__,
                                                   "error_hash": _hash(str(exc))})
            raise

    async def async_run(self, *, session_id: str, agent_id: str, api_key: str,
                        payload: dict[str, Any], turn_id: str | None = None) -> dict[str, Any]:
        if self.request_async_fn:
            self.policy.authorize(session_id=session_id, agent_id=agent_id)
            self._event(session_id=session_id, agent_id=agent_id, turn_id=turn_id,
                        metadata={"phase": "request", "operation_name": "chat", "request": _payload_metadata(
                            payload, allow_raw=self.policy.allow_raw_payloads)})
            try:
                response = await self.request_async_fn(self.endpoint, api_key, payload)
                return await asyncio.to_thread(
                    self._record_response, session_id=session_id, agent_id=agent_id,
                    response=response, turn_id=turn_id,
                )
            except Exception as exc:
                self._event(session_id=session_id, agent_id=agent_id, turn_id=turn_id,
                            outcome="error", metadata={"phase": "error",
                            "error_type": type(exc).__name__, "error_hash": _hash(str(exc))})
                raise
        return await asyncio.to_thread(self.run, session_id=session_id, agent_id=agent_id,
                                       api_key=api_key, payload=payload, turn_id=turn_id)

    def _record_response(self, *, session_id: str, agent_id: str, response: Any,
                         turn_id: str | None) -> dict[str, Any]:
        if not isinstance(response, dict):
            response = {"output": response}
        output = response.get("output") or response.get("text") or response.get("content")
        self._event(session_id=session_id, agent_id=agent_id, turn_id=turn_id,
                    outcome="success", assistant_response=output if isinstance(output, str) else None,
                    usage=response.get("usage"), metadata={
                        "phase": "response", "operation_name": "chat", "model": response.get("model"), "response": _payload_metadata(response, allow_raw=self.policy.allow_raw_payloads),
                        "citations": _payload_metadata(response.get("citations"), allow_raw=self.policy.allow_raw_payloads),
                        "request_id": response.get("id") or response.get("request_id"),
                    })
        return response


@dataclass(slots=True)
class MCPAdapter(_BaseProviderAdapter):
    """MCP tool-boundary adapter; arguments/results are hashed unless raw capture is consented."""

    runtime: Literal["mcp"] = "mcp"

    def tool_started(self, *, session_id: str, agent_id: str, tool_name: str,
                     arguments: Any = None, turn_id: str | None = None,
                     invocation_id: str | None = None) -> dict[str, Any]:
        return self._event(session_id=session_id, agent_id=agent_id, turn_id=turn_id,
                           invocation_id=invocation_id, tool_name=tool_name,
                           metadata={"phase": "start", "operation_name": "execute_tool", "tool_name": tool_name,
                                     "arguments": _payload_metadata(arguments, allow_raw=self.policy.allow_raw_payloads)})

    def tool_finished(self, *, session_id: str, agent_id: str, tool_name: str,
                      result: Any = None, status: str = "success", turn_id: str | None = None,
                      invocation_id: str | None = None, duration_ms: float | None = None) -> dict[str, Any]:
        outcome = "success" if status in {"success", "ok", "completed"} else "error" if status in {"error", "failed"} else "blocked" if status in {"blocked", "denied"} else "unknown"
        return self._event(session_id=session_id, agent_id=agent_id, turn_id=turn_id,
                           invocation_id=invocation_id, tool_name=tool_name, outcome=outcome,
                           metadata={"phase": "finish", "operation_name": "execute_tool", "tool_name": tool_name, "duration_ms": duration_ms,
                                     "result": _payload_metadata(result, allow_raw=self.policy.allow_raw_payloads)})


@dataclass(slots=True)
class CloudRunAdapter(_BaseProviderAdapter):
    """Generic cloud-agent lifecycle adapter for provider events/webhook payloads."""

    runtime: Literal["cloud_run"] = "cloud_run"
    signature_secret: bytes | None = None
    max_clock_skew_seconds: int = 300

    def ingest(self, *, session_id: str, agent_id: str, event_name: str,
               payload: dict[str, Any] | None = None, turn_id: str | None = None,
               invocation_id: str | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        status = str(payload.get("status") or payload.get("outcome") or "").lower()
        outcome = "success" if status in {"success", "completed", "ok"} else "error" if status in {"error", "failed", "timeout"} else "blocked" if status in {"blocked", "denied"} else "unknown"
        output = payload.get("final_output") or payload.get("output") or payload.get("text")
        return self._event(session_id=session_id, agent_id=agent_id, turn_id=turn_id,
                           invocation_id=invocation_id, outcome=outcome,
                           assistant_response=output if isinstance(output, str) else None,
                           usage=payload.get("usage"), metadata={
                               "event_name": event_name, "operation_name": "invoke_agent", "phase": payload.get("phase"),
                               "model": payload.get("model"), "provider": payload.get("provider"),
                               "request_id": payload.get("request_id") or payload.get("id"),
                               "latency_ms": payload.get("latency_ms") or payload.get("duration_ms"),
                               "retry_count": payload.get("retry_count"),
                               "citations": _payload_metadata(payload.get("citations"), allow_raw=self.policy.allow_raw_payloads),
                               "payload": _payload_metadata(payload, allow_raw=self.policy.allow_raw_payloads),
                           })

    def ingest_signed(self, *, raw_body: bytes, signature: str, timestamp: str,
                      session_id: str, agent_id: str, event_name: str,
                      turn_id: str | None = None, invocation_id: str | None = None) -> dict[str, Any]:
        if self.signature_secret is None:
            raise PermissionError("CloudRun signature verification is not configured")
        try:
            timestamp_int = int(timestamp)
        except ValueError as exc:
            raise ValueError("invalid CloudRun signature timestamp") from exc
        if abs(time.time() - timestamp_int) > self.max_clock_skew_seconds:
            raise PermissionError("CloudRun webhook timestamp is outside the replay window")
        expected = "sha256=" + hmac.new(
            self.signature_secret, timestamp.encode() + b"." + raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise PermissionError("invalid CloudRun webhook signature")
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("CloudRun webhook body must be a JSON object")
        return self.ingest(session_id=session_id, agent_id=agent_id, event_name=event_name,
                           payload=payload, turn_id=turn_id, invocation_id=invocation_id)


@dataclass(slots=True)
class MCPTelemetryMiddleware:
    """Framework-neutral wrapper usable around any MCP server's tool dispatcher."""

    adapter: MCPAdapter

    async def call(self, handler: Callable[..., Any], *, session_id: str, agent_id: str,
                   tool_name: str, arguments: Any = None, turn_id: str | None = None,
                   invocation_id: str | None = None, **kwargs: Any) -> Any:
        started = time.perf_counter()
        self.adapter.tool_started(session_id=session_id, agent_id=agent_id, tool_name=tool_name,
                                  arguments=arguments, turn_id=turn_id, invocation_id=invocation_id)
        try:
            result = handler(arguments, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            self.adapter.tool_finished(session_id=session_id, agent_id=agent_id, tool_name=tool_name,
                                       result=result, status="success", turn_id=turn_id,
                                       invocation_id=invocation_id, duration_ms=(time.perf_counter() - started) * 1000)
            return result
        except Exception:
            self.adapter.tool_finished(session_id=session_id, agent_id=agent_id, tool_name=tool_name,
                                       result=None, status="error", turn_id=turn_id,
                                       invocation_id=invocation_id, duration_ms=(time.perf_counter() - started) * 1000)
            raise


def export_provider_telemetry(controller: XibalbaRuntimeController, provider: str, *, limit: int = 500) -> dict[str, object]:
    return controller.store.export_provider_telemetry(provider, limit=limit)


def delete_provider_telemetry(controller: XibalbaRuntimeController, provider: str, *, before: str,
                              apply: bool = False, limit: int = 500) -> dict[str, object]:
    return controller.store.delete_provider_telemetry(provider, before=before, apply=apply, limit=limit)


__all__ = ["ProviderTelemetryPolicy", "policy_from_config", "create_runtime_adapter",
           "PerplexityAdapter", "MCPAdapter", "MCPTelemetryMiddleware", "CloudRunAdapter",
           "export_provider_telemetry", "delete_provider_telemetry"]
