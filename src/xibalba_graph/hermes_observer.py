"""Path D: a native Hermes Agent observer plugin adapter.

Not built on OTel, because Hermes has none -- checked directly against
~/.hermes/hermes-agent's own codebase before assuming otherwise, not guessed. Hermes has its
own hook contract instead: docs/observability/README.md's "Observer Hooks"
(telemetry_schema_version = "hermes.observer.v1"), the same contract the bundled NeMo Relay and
Langfuse plugins already use (verified against nemo_relay/__init__.py's actual register(ctx)
call and plugin.yaml before building against this shape).

This is arguably a better integration than an OTLP receiver, not a fallback: Hermes plugins run
in-process and call Python functions directly with real correlation IDs already attached
(session_id, turn_id, api_request_id, tool_call_id) -- no HTTP server, no OTLP JSON decoding,
no redaction flags to enable upstream.

## Hooks mapped, and why each pre_*/post_* pair collapses to one call

Only the *_end/post_* member of each pair is handled -- the corresponding pre_* hook fires
before the same data exists (a tool hasn't run yet, a response hasn't arrived yet), so it adds
framing but no additional capturable content; instrumenting both would double-count nothing new.

  on_session_start / on_session_end  -> start_session / end_session
  post_llm_call                      -> user_message + assistant_response as memories
                                         (turn_id doubles as prompt_id, same reuse-not-invent
                                         pattern as otlp_receiver's trace_id)
  post_api_request                   -> otel_events, kind=log, name="hermes.api_request"
  api_request_error                  -> otel_events, kind=log, name="hermes.api_request_error"
  post_tool_call                     -> otel_events, kind=span, name=f"tool_call.{tool_name}"
  post_approval_response             -> otel_events, kind=log, name="hermes.approval"
                                         (a security-relevant decision, part of a session's
                                         complete memory, not just LLM output; keyed by
                                         session_key, the field name approval hooks actually
                                         carry -- checked against tools/approval.py's real
                                         invoke_hook() call sites, not the field name assumed
                                         from the docs table alone)
  subagent_start / subagent_stop     -> otel_events on the PARENT session (kind=log) --
                                         simplification, stated plainly: this does not build a
                                         parent/child session schema, it records the
                                         delegation as an event on the parent instead.

Same content-hash dedup as every other path (find_memory_id_by_content) and the same
prompt_id-based correlation exchange_builder already understands -- no new grouping logic
needed for Hermes-sourced sessions to walk the same way Claude-Code-sourced ones do.

## Wiring this into a running Hermes agent

Building the adapter here (testable, no dependency on Hermes) is deliberately separate from
installing it as a Hermes plugin, which means writing into a different project's codebase.
That wiring is done: the plugin lives at ~/.hermes/plugins/xibalba_graph_memory/ (a flat user
plugin, not nested under hermes-agent's own plugins/observability/), registered via
`plugins.enabled` in ~/.hermes/config.yaml. It does not import this adapter in-process --
hermes-agent's venv doesn't have xibalba_graph installed -- it instead shells out per hook call
to this project's own venv via `python -m xibalba_graph.hermes_bridge <hook_name>` (see
hermes_bridge.py), which constructs this same HermesObserverAdapter and dispatches to it. See
~/.hermes/plugins/xibalba_graph_memory/__init__.py and plugin.yaml for the deployed shim.

Hook callbacks are fail-open per Hermes's own contract (exceptions are caught and logged, the
agent loop keeps running) -- this adapter does not need its own try/except for that reason, but
does not raise on missing/None fields either, consistent with "additive fields stay
backward-compatible" from the observer contract itself.
"""
from __future__ import annotations

from typing import Any
import os

from .store import GraphStore


class HermesObserverAdapter:
    """Stateless w.r.t. Hermes -- holds only a GraphStore. Every method accepts **kwargs so
    new fields Hermes adds to its observer payloads over time don't break this adapter,
    matching the observer contract's own "additive fields remain backward-compatible" rule.
    """

    def __init__(self, store: GraphStore):
        self.store = store

    def _store_text(self, session_id: str, text: Any, *, role: str, prompt_id: str | None) -> str | None:
        if not isinstance(text, str) or not text.strip():
            return None
        existing = self.store.find_memory_id_by_content(text)
        if existing:
            return existing
        self.store.start_session(session_id, retention_tier="verbatim")
        memory = self.store.store_memory(
            text,
            source={
                "kind": "direct_user",
                "session_id": session_id,
                "role": role,
                "prompt_id": prompt_id,
                "agent_id": os.environ.get("XIBALBA_AGENT_ID", "xibalba.agent"),
            },
            status="candidate",
            evidence_class="observed_event",
        )
        return memory["id"]

    def on_session_start(self, *, session_id: str | None = None, **kwargs: Any) -> None:
        if not session_id:
            return
        self.store.start_session(session_id, retention_tier="verbatim")

    def on_session_end(
        self, *, session_id: str | None = None, completed: bool | None = None,
        interrupted: bool | None = None, reason: str | None = None, **kwargs: Any,
    ) -> None:
        if not session_id:
            return
        try:
            self.store.get_session(session_id)
        except KeyError:
            return  # on_session_end can fire for a session this adapter never saw start
        summary = None
        if interrupted:
            summary = f"Session interrupted: {reason or 'no reason given'}"
        elif reason:
            summary = f"Session ended: {reason}"
        self.store.end_session(session_id, summary_content=summary)

    def post_llm_call(
        self, *, session_id: str | None = None, turn_id: str | None = None,
        user_message: Any = None, assistant_response: Any = None, **kwargs: Any,
    ) -> None:
        if not session_id:
            return
        self._store_text(session_id, user_message, role="user", prompt_id=turn_id)
        self._store_text(session_id, assistant_response, role="assistant", prompt_id=turn_id)

    def post_api_request(
        self, *, session_id: str | None = None, turn_id: str | None = None,
        api_request_id: str | None = None, model: str | None = None, provider: str | None = None,
        api_duration: float | None = None, usage: dict | None = None,
        finish_reason: str | None = None, response_model: str | None = None, **kwargs: Any,
    ) -> None:
        if not session_id:
            return
        self.store.start_session(session_id, retention_tier="verbatim")
        self.store.record_otel_batch(session_id, [{
            "kind": "log",
            "name": "hermes.api_request",
            "trace_id": turn_id,
            "span_id": api_request_id,
            "prompt_id": turn_id,
            "attributes": {
                "model": model, "provider": provider, "duration_ms": api_duration,
                "usage": usage, "finish_reason": finish_reason, "response_model": response_model,
            },
        }])

    def api_request_error(
        self, *, session_id: str | None = None, turn_id: str | None = None,
        api_request_id: str | None = None, error: dict | None = None,
        status_code: int | None = None, retryable: bool | None = None, **kwargs: Any,
    ) -> None:
        if not session_id:
            return
        self.store.start_session(session_id, retention_tier="verbatim")
        self.store.record_otel_batch(session_id, [{
            "kind": "log",
            "name": "hermes.api_request_error",
            "trace_id": turn_id,
            "span_id": api_request_id,
            "prompt_id": turn_id,
            "attributes": {"error": error, "status_code": status_code, "retryable": retryable},
        }])

    def post_tool_call(
        self, *, session_id: str | None = None, tool_name: str | None = None,
        tool_call_id: str | None = None, turn_id: str | None = None, result: Any = None,
        duration_ms: float | None = None, status: str | None = None,
        error_type: str | None = None, error_message: str | None = None, **kwargs: Any,
    ) -> None:
        if not session_id:
            return
        self.store.start_session(session_id, retention_tier="verbatim")
        self.store.record_otel_batch(session_id, [{
            "kind": "span",
            "name": f"tool_call.{tool_name or 'unknown'}",
            "trace_id": turn_id,
            "span_id": tool_call_id,
            "parent_span_id": turn_id,
            "prompt_id": turn_id,
            "attributes": {
                "status": status, "duration_ms": duration_ms, "error_type": error_type,
                "error_message": error_message, "result": result,
            },
        }])

    def post_approval_response(
        self, *, session_key: str | None = None, command: str | None = None,
        description: str | None = None, choice: str | None = None, **kwargs: Any,
    ) -> None:
        # Approval hooks carry session_key, not session_id -- verified against the real
        # invoke_hook("post_approval_response", ...) call sites in tools/approval.py, which
        # never pass session_id at all. session_key is the same per-session identity, just
        # under approval.py's own name for it.
        if not session_key:
            return
        session_id = session_key
        self.store.start_session(session_id, retention_tier="verbatim")
        self.store.record_otel_batch(session_id, [{
            "kind": "log",
            "name": "hermes.approval",
            "attributes": {"command": command, "description": description, "choice": choice},
        }])

    def subagent_start(
        self, *, parent_session_id: str | None = None, child_session_id: str | None = None,
        child_subagent_id: str | None = None, child_role: str | None = None,
        child_goal: str | None = None, **kwargs: Any,
    ) -> None:
        if not parent_session_id:
            return
        self.store.start_session(parent_session_id, retention_tier="verbatim")
        self.store.record_otel_batch(parent_session_id, [{
            "kind": "log",
            "name": "hermes.subagent_start",
            "attributes": {
                "child_session_id": child_session_id, "child_subagent_id": child_subagent_id,
                "child_role": child_role, "child_goal": child_goal,
            },
        }])

    def subagent_stop(
        self, *, parent_session_id: str | None = None, child_session_id: str | None = None,
        child_status: str | None = None,
        child_summary: str | None = None, duration_ms: float | None = None, **kwargs: Any,
    ) -> None:
        # child_status, not status -- verified against the real _invoke_hook("subagent_stop", ...)
        # call site in tools/delegate_tool.py, which also never passes child_subagent_id here
        # (only subagent_start does).
        if not parent_session_id:
            return
        self.store.start_session(parent_session_id, retention_tier="verbatim")
        self.store.record_otel_batch(parent_session_id, [{
            "kind": "log",
            "name": "hermes.subagent_stop",
            "attributes": {
                "child_session_id": child_session_id,
                "child_status": child_status, "child_summary": child_summary, "duration_ms": duration_ms,
            },
        }])
