"""A local HTTP API for browser-based tooling (e.g. the graph viewer in viewer/).

MCP is stdio-only -- a browser can't call it directly. This mirrors otlp_receiver.py's stdlib
http.server.ThreadingHTTPServer pattern (no new framework dependency) rather than introducing
Flask/FastAPI for a small local operator UI. It intentionally omits destructive operations such
as restore or hard purge.

Despite the module's original "localhost-bound" framing, the shipped Dockerfile binds this to
0.0.0.0 -- so every route except the liveness probes (/healthz, /readyz, /metrics) is
authenticated: a `memory:read`-scoped credential for GET, `memory:write` for most POST routes, and
`proposal:decide` for the two decision endpoints. There is no unauthenticated fallback -- a
deployment with no credentials issued simply has no working API, which is the fail-closed default.

Two credential types, by caller kind:

  * Browsers get an HttpOnly, Secure, SameSite=Strict session cookie (`cortex_session`) set by
    /api/auth/login and /api/auth/signup. The raw token is never returned in a response body and
    is never readable from JavaScript, so an XSS bug cannot exfiltrate it -- which the previous
    sessionStorage-held bearer token could not prevent. `SameSite=Strict` is what makes this safe
    without a separate CSRF token. Because the cookie is `Secure`, this path requires TLS; the
    packaged Caddyfile terminates it and serves the viewer and API on one origin, so no CORS
    credentials dance is needed. Set XIBALBA_CORTEX_INSECURE_COOKIES=1 to drop `Secure` for a
    plain-HTTP loopback dev server.
  * Machine callers (the streamable-HTTP MCP transport, CLI, workers) continue to present
    `Authorization: Bearer <token>` against the same ingest-token store (auth_middleware.py /
    ingest_tokens.py). Issue tokens with `xibalba-cortex-ingest-tokens issue`. These callers have
    no cookie jar, so removing bearer support entirely would break them.

Cookie is checked first so a stale header cannot shadow a live browser session.

Every route is a thin wrapper around one public GraphStore method -- all the actual query logic
(graph_payload, memory_entity_relations, counts, etc.) lives in store.py where it's unit-tested
independent of HTTP, the same division server.py already uses for its MCP tools.

Routes:
  GET /metrics                        -> Prometheus-compatible request/status counters
  GET /healthz                         -> process/store liveness
  GET /readyz                         -> full integrity and backup readiness (503 when not ready)
  GET /api/stats                          -> GraphStore.counts()
  GET /api/status                         -> GraphStore.status()
  GET /api/operations                     -> unified dashboard operations snapshot
  GET /api/integrity-links?limit=          -> GraphStore.integrity_links_status()
  GET /api/sessions?limit=                 -> GraphStore.list_sessions()
  GET /api/session/{id}/replay             -> GraphStore.session_replay()
  GET /api/search?q=&limit=                -> GraphStore.search() (lexical-only; no embedding
                                               model runs in a browser, so query_vector is never
                                               supplied here -- vector search stays MCP/tool-side)
  GET /api/memory/{id}                     -> GraphStore.get_memory()
  GET /api/memory/{id}/events              -> GraphStore.memory_events()
  GET /api/memory/{id}/otel                -> GraphStore.memory_otel_events()
  GET /api/memory/{id}/attachments         -> GraphStore.list_attachments()
  GET /api/memory/{id}/contradictions      -> GraphStore.contradictions()
  GET /api/memory/{id}/similar?limit=      -> GraphStore.similar_memories()
  GET /api/memory/{id}/neighbors           -> GraphStore.memory_entity_relations()
  GET /api/entity/{name}/neighbors?max_depth= -> GraphStore.neighbors()
  GET /api/entity/path?from=&to=&max_depth=   -> GraphStore.find_path()
  GET /api/session/{id}/exchanges          -> GraphStore.session_exchanges()
  GET /api/session/{id}/otel               -> GraphStore.session_otel_events()
  GET /api/session/{id}/merkle-root        -> GraphStore.session_merkle_root()
  GET /api/session/{id}/merkle-proof?index= -> GraphStore.session_merkle_evidence()
  GET /api/inference/manifest              -> MEMORY_INFERENCE_SUBAGENT_MANIFEST
  GET /api/inference/tasks?status=&limit=  -> GraphStore.list_inference_tasks()
  GET /api/extraction-proposals?status=&task_id=&source_memory_id=&limit= -> GraphStore.list_extraction_proposals()
  GET /api/retrieval/trace/{id}            -> GraphStore.get_retrieval_trace()
  GET /api/retrieval/trace/{id}/evidence?rank= -> GraphStore.retrieval_trace_evidence()
  GET /api/projections/{id}/checkpoints?limit= -> GraphStore.list_projection_checkpoints()
  GET /api/projections/{id}/checkpoints/latest -> GraphStore.get_latest_projection_checkpoint()
  GET /api/embedding/models                -> GraphStore.list_embedding_models()
  POST /api/exchanges/model                -> GraphStore.record_model_exchange()
  POST /api/memory/propositions            -> GraphStore.store_memory()
  POST /api/memory/link-entities           -> GraphStore.link_entities()
  POST /api/memory/contradictions          -> GraphStore.mark_contradiction()
  POST /api/memory/{id}/supersede          -> GraphStore.supersede_memory()
  POST /api/memory/{id}/forget             -> GraphStore.forget_memory()
  POST /api/inference/tasks                -> GraphStore.request_inference_task()
  POST /api/inference/tasks/{id}/claim     -> GraphStore.claim_inference_task()
  POST /api/inference/tasks/{id}/complete  -> GraphStore.complete_inference_task()
  POST /api/extraction-proposals/{id}/decision -> GraphStore.decide_extraction_proposal()
  POST /api/retrieval/hybrid               -> GraphStore.hybrid_retrieve()
  POST /api/projections/{id}/checkpoint    -> GraphStore.create_projection_checkpoint()
  POST /api/projections/{id}/reconcile     -> GraphStore.reconcile_projection_checkpoint()
  POST /api/projections/{id}/rebuild       -> GraphStore.rebuild_projection_checkpoint()
  GET /api/graph?limit=&similarity_threshold= -> GraphStore.graph_payload()
  GET /api/session/{id}/kernel-intents     -> GraphStore.kernel_bridge_intents()
  GET /api/invocations?limit=              -> GraphStore.invocation_correlations()
  POST /api/kernel-bridge/self-test        -> _run_kernel_bridge_self_test() (Guided System Test;
                                               optional {"session_id": ...} also records both cases
                                               as real pre/post_tool_call otel events so
                                               GraphStore.kernel_bridge_intents() -- and the
                                               dashboard's Kernel Intent page -- has real data to show)
  POST /api/otel/batch                     -> GraphStore.record_otel_batch() (browser-reachable write path)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
import threading
import time
import tempfile
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse
from pathlib import Path

import requests
import yaml

from .config import load_config
from .connector_policy import ConnectorRateLimiter
from .ingest_tokens import _connect, list_tokens, verify_token_record
from .accounts import account_for_token, approve_account, change_account_password, create_account, issue_account_session, request_password_reset, reset_password, revoke_account_session, revoke_account_session_by_id
from .providers import InferenceTaskContract, connector_manifest
from integrity_sdk.agent_identity import resolve_agent_identities
from .store import MEMORY_INFERENCE_SUBAGENT_MANIFEST, GraphStore, _INFERENCE_TASK_TYPES


def _principal_agent_ids(principal: dict[str, object]) -> list[str]:
    """Return all agent identities authorized for this credential.

    ``agent_id`` remains the compatibility field for older single-agent tokens. New
    credentials carry ``agent_ids`` populated by the trusted registration/indexer path;
    request payloads are never used to expand this set.
    """
    values = principal.get("agent_ids")
    if isinstance(values, (list, tuple, set)):
        normalized = sorted({str(value).strip() for value in values if str(value).strip()})
        if normalized:
            return normalized
    value = principal.get("agent_id")
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    # Backward-compatible migration for tokens issued before the explicit agent_id column:
    # only canonical DIDs are safe to infer from a legacy label.
    label = principal.get("label")
    return [label.strip()] if isinstance(label, str) and label.startswith("did:") else []


def _principal_agent_id(principal: dict[str, object]) -> str | None:
    """Compatibility helper for routes that require exactly one agent."""
    values = _principal_agent_ids(principal)
    return values[0] if len(values) == 1 else None


def _agent_filter(store: GraphStore, principal: dict[str, object], requested: str | None) -> str | None:
    """Return the persisted agent partition for a principal-bound read."""
    authorized = _principal_agent_ids(principal)
    if authorized:
        requested_value = requested.strip() if isinstance(requested, str) else None
        if requested_value and requested_value not in authorized:
            raise PermissionError("credential is not authorized for this agent")
        selected = requested_value or authorized[0]
        persisted = store.storage_agent_id(selected)
        if persisted is None:
            raise PermissionError("agent-scoped access is unavailable while identity attribution is disabled")
        return persisted
    if requested:
        # Operator/admin credentials may explicitly select a persisted partition; runtime
        # credentials without a binding cannot manufacture one.
        return requested
    return None


def _assert_session_access(store: GraphStore, principal: dict[str, object], session_id: str) -> dict[str, object]:
    session = store.get_session(session_id)
    authorized = _principal_agent_ids(principal)
    if authorized and session.get("agent_id") not in {
        persisted for agent in authorized if (persisted := store.storage_agent_id(agent))
    } | set(authorized):
        raise PermissionError("session is outside the authenticated agent namespace")
    return session


def _assert_memory_scope(memory: dict[str, object], principal: dict[str, object], store: GraphStore) -> dict[str, object]:
    authorized = _principal_agent_ids(principal)
    source = memory.get("source") if isinstance(memory.get("source"), dict) else {}
    persisted = {value for agent in authorized if (value := store.storage_agent_id(agent))}
    if authorized and source.get("agent_id") not in persisted | set(authorized):
        raise PermissionError("memory is outside the authenticated agent namespace")
    return memory


def _assert_trace_scope(store: GraphStore, principal: dict[str, object], trace: dict[str, object]) -> dict[str, object]:
    authorized = _principal_agent_ids(principal)
    filters = trace.get("filters") if isinstance(trace.get("filters"), dict) else {}
    persisted = {value for agent in authorized if (value := store.storage_agent_id(agent))}
    if authorized and filters.get("agent_id") not in persisted | set(authorized):
        raise PermissionError("retrieval trace is outside the authenticated agent namespace")
    return trace


def _write_agent(store: GraphStore, principal: dict[str, object], requested: str | None = None) -> str | None:
    """Resolve a write identity from the authenticated principal, never from free payload data."""
    authorized = _principal_agent_ids(principal)
    if authorized:
        if len(authorized) > 1 and not requested:
            raise PermissionError("an explicitly selected registered agent is required")
        bound = requested.strip() if isinstance(requested, str) and requested.strip() else authorized[0]
        if bound not in authorized:
            raise PermissionError("credential is not authorized for this agent")
        persisted = store.storage_agent_id(bound)
        if persisted is None:
            raise PermissionError("agent-scoped access is unavailable while identity attribution is disabled")
        return bound
    if requested:
        raise PermissionError("credential is not bound to an agent")
    return None


def _scoped_source(store: GraphStore, principal: dict[str, object], source: dict[str, object] | None) -> dict[str, object]:
    value = dict(source or {})
    requested = value.get("agent_id") if isinstance(value.get("agent_id"), str) else None
    bound = _write_agent(store, principal, requested)
    if bound:
        value["agent_id"] = bound
    else:
        value.pop("agent_id", None)
    return value


def _assert_pair_manager(principal: dict[str, object]) -> None:
    roles = set(principal.get("roles") or [])
    if not roles.intersection({"operator", "admin"}):
        raise PermissionError("operator or admin role is required to manage agent/device pairs")

logger = logging.getLogger("xibalba_cortex.local_api")
_MAX_JSON_BODY_BYTES = 512 * 1024
_REQUEST_METRICS: Counter[str] = Counter()
_REQUEST_METRICS_LOCK = threading.Lock()

# Guided System Test wizard (integrity-dashboard's Developer page): a one-click kernel-bridge
# check that doesn't require a live Claude session with XIBALBA_KERNEL_BRIDGE_ENABLED=1 set.
# Same test recipient/values as claude_adapter.py's opt-in pre_tool_call path and
# contracts/script/SubmitKernelBridgeUserOp.s.sol's own case selection -- a matched case
# (well within both the kernel's and adapter's budgets) and a kernel-exceeding case (proves
# real denial, since the registered adapter itself has a known gap -- see kernel_bridge.py's
# module docstring -- and would otherwise always ALLOW).
_SELF_TEST_RECIPIENT = "0x" + "0" * 38 + "ff"
_SELF_TEST_MATCHED_VALUE_WEI = int(0.1 * 10**18)
_SELF_TEST_KERNEL_EXCEEDING_VALUE_WEI = int(1.5 * 10**18)


def _record_kernel_bridge_intent(
    store: GraphStore, *, session_id: str, tool_call_id: str, tool_name: str, decision: dict[str, object]
) -> None:
    # Same (pre_tool_call, post_tool_call) otel-event shape claude_adapter.py's real,
    # opt-in XIBALBA_KERNEL_BRIDGE_ENABLED hook path writes -- see runtime_bridge_contract.py's
    # RuntimeEvent.to_record() and GraphStore.kernel_bridge_intents(), which joins the two by
    # metadata.tool_call_id. Without this, the self-test route (unlike the real hook path) never
    # gave the Kernel Intent page (/kernel-intent) anything to show -- the wizard's "Kernel /
    # adapter bridge" step and the intent-vs-outcome page looked related but were entirely
    # disconnected. This makes the wizard's real, already-verified on-chain result the page's
    # data source too, instead of requiring a live hook-driven session to ever populate it.
    store.start_session(session_id, retention_tier="verbatim")
    success = bool(decision.get("success"))
    store.record_otel_batch(
        session_id,
        [
            {
                "kind": "log",
                "name": "xibalba.runtime.event",
                "span_id": tool_name,
                "attributes": {
                    "tool_name": tool_name,
                    "tool_input_hash": None,
                    "intent_rationale": f"Guided System Test self-test: {tool_name}",
                    "tool_outcome": "success" if success else "blocked",
                    "metadata": {
                        "hook": "pre_tool_call",
                        "tool_call_id": tool_call_id,
                        "policy_reason": "kernel-bridge self-test",
                        "kernel_decision": decision,
                    },
                },
            },
            {
                "kind": "log",
                "name": "xibalba.runtime.event",
                "span_id": tool_name,
                "attributes": {
                    "tool_name": tool_name,
                    "tool_outcome": "success" if success else "blocked",
                    "metadata": {
                        "hook": "post_tool_call",
                        "tool_call_id": tool_call_id,
                        "result": decision.get("user_op_hash"),
                        "duration_ms": None,
                    },
                },
            },
        ],
    )


def _run_kernel_bridge_self_test(store: GraphStore, *, session_id: str | None) -> dict[str, object]:
    from .kernel_bridge import submit_kernel_intent

    try:
        matched = submit_kernel_intent(recipient=_SELF_TEST_RECIPIENT, value_wei=_SELF_TEST_MATCHED_VALUE_WEI)
        kernel_exceeding = submit_kernel_intent(
            recipient=_SELF_TEST_RECIPIENT, value_wei=_SELF_TEST_KERNEL_EXCEEDING_VALUE_WEI
        )
    except Exception as exc:  # noqa: BLE001 -- surfaced as a clean test-failure result, not a 500
        return {"ok": False, "error": str(exc)}

    matched_dict = matched.to_dict()
    kernel_exceeding_dict = kernel_exceeding.to_dict()

    if session_id:
        _record_kernel_bridge_intent(
            store,
            session_id=session_id,
            tool_call_id=f"kernel-bridge-self-test-matched-{matched_dict['user_op_hash']}",
            tool_name="kernel_bridge_self_test_matched",
            decision=matched_dict,
        )
        _record_kernel_bridge_intent(
            store,
            session_id=session_id,
            tool_call_id=f"kernel-bridge-self-test-kernel-exceeding-{kernel_exceeding_dict['user_op_hash']}",
            tool_name="kernel_bridge_self_test_kernel_exceeding",
            decision=kernel_exceeding_dict,
        )

    return {
        "ok": True,
        "matched": matched_dict,
        "kernel_exceeding": kernel_exceeding_dict,
        "passed": matched.success is True and kernel_exceeding.success is False,
    }


SESSION_COOKIE_NAME = "cortex_session"

# Must track `accounts.issue_account_session`'s ttl_hours default so the cookie does not
# outlive the server-side session record it points at.
_SESSION_TTL_HOURS = 24

# `Secure` is omitted only when the operator explicitly opts out for a plain-HTTP loopback
# dev server; the deployed path runs behind Caddy TLS, where `Secure` must be set or the
# browser will refuse to store the cookie on an HTTPS origin.
_INSECURE_COOKIES = os.environ.get("XIBALBA_CORTEX_INSECURE_COOKIES") == "1"


def _session_cookie(token: str, *, max_age: int) -> str:
    """Serialize the session cookie.

    `HttpOnly` keeps the token out of JavaScript (so XSS cannot exfiltrate it, which the
    previous sessionStorage bearer token could not prevent).

    `SameSite=None` (2026-09-15, was `Strict`): a cross-origin browser caller (e.g. the
    integrity-dashboard app, served over a different scheme/port) needs this cookie attached to
    its `credentials: 'include'` fetches. Under schemeful same-site, the comparison that governs
    SameSite is against the *calling page's* own site, not the fetch target's -- so no choice of
    target origin/port here can make `Strict` (or `Lax`) cookies reach a caller on a different
    scheme. `SameSite=None` requires `Secure` and drops the free CSRF protection `Strict` gave;
    see `_csrf_token_for`/`/api/auth/csrf` for the explicit CSRF check that replaces it.
    """
    parts = [
        f"{SESSION_COOKIE_NAME}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=None",
        f"Max-Age={max_age}",
    ]
    if not _INSECURE_COOKIES:
        parts.append("Secure")
    return "; ".join(parts)


_CSRF_SECRET_FILENAME = "local_api_csrf_secret"


def _load_or_create_csrf_secret(home: str | Path) -> bytes:
    """Per-profile secret for deriving CSRF tokens from session tokens. Same pattern as
    GraphStore._load_or_create_identity_salt: local file, 0600, generated once."""
    secret_path = Path(home) / _CSRF_SECRET_FILENAME
    if secret_path.is_file():
        return secret_path.read_bytes()
    secret = os.urandom(32)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_bytes(secret)
    os.chmod(secret_path, 0o600)
    return secret


def _csrf_token_for(secret: bytes, session_token: str) -> str:
    """Derive the CSRF token a legitimate same-session caller must echo back.

    Deliberately stateless (HMAC of the session token itself, not a separately stored value):
    a forged cross-site request carries the SameSite=None session cookie automatically (the
    browser attaches it), but the attacker's page cannot read this cookie's value (HttpOnly)
    or a same-origin response naming it (CORS blocks reading a response from an origin not on
    the operator's --allowed-origins list) -- so it cannot compute or observe this header,
    even though it can trigger the request.
    """
    return hmac.new(secret, session_token.encode("utf-8"), hashlib.sha256).hexdigest()


def _make_handler(store: GraphStore, *, allowed_origins: frozenset[str]):
    csrf_secret = _load_or_create_csrf_secret(store.home)
    # The authenticated webhook/operator surface is profile-local. Keep a bounded
    # per-profile request budget so one connector or tenant cannot starve the store.
    request_limiter = ConnectorRateLimiter(rate_per_second=20.0, burst=40)
    auth_attempts: dict[str, list[float]] = {}
    auth_attempt_lock = threading.Lock()

    def auth_allowed(identity: str) -> bool:
        now = time.monotonic()
        with auth_attempt_lock:
            recent = [stamp for stamp in auth_attempts.get(identity, []) if now - stamp < 60.0]
            if len(recent) >= 8:
                auth_attempts[identity] = recent
                return False
            recent.append(now)
            auth_attempts[identity] = recent
            return True

    class Handler(BaseHTTPRequestHandler):
        # Without a socket timeout, a client that opens a connection and never completes a
        # valid HTTP request blocks that handler thread in a raw socket read forever --
        # permanently consuming one of _BoundedThreadingHTTPServer's fixed thread-pool slots.
        # Ported alongside the identical fix in xibalba-shield's backend/api.py, 2026-09-14.
        # Lowered 30s -> 10s (2026-09-15): HTTP/1.1 keep-alive means this timeout also bounds
        # how long a connection the *client* already walked away from (browser tab closed,
        # script exited) sits in CLOSE-WAIT still holding a thread-pool slot -- observed up to
        # 23/32 slots stuck this way at once under repeated headless-browser test cycles,
        # which is what made the viewer intermittently hang on "Connecting..." despite the
        # backend itself responding in milliseconds. 10s still comfortably covers any real
        # in-flight request (the slowest observed endpoint before the 2026-09-15 fixes was
        # ~19s, and that was the pathological unindexed-query case, now fixed).
        timeout = 10

        def _cors_origin(self) -> str:
            # "*" in allowed_origins is the wildcard/no-restriction config (the CLI default):
            # always reflect "*" and never claim credentials support, matching a browser's own
            # rule that a credentialed request can't be satisfied by a wildcard origin. Once an
            # operator configures an explicit allow-list, an allowed request's own Origin is
            # reflected back (required for Access-Control-Allow-Credentials to be honored at
            # all) and anything else falls back to the non-credentialed "*" response.
            if "*" in allowed_origins:
                return "*"
            origin = self.headers.get("Origin")
            return origin if origin and origin in allowed_origins else "*"

        def _send_json(self, status: int, payload: object, *, extra_headers: tuple[tuple[str, str], ...] = ()) -> None:
            body = json.dumps(payload).encode()
            with _REQUEST_METRICS_LOCK:
                _REQUEST_METRICS["requests_total"] += 1
                _REQUEST_METRICS[f"responses_{status}"] += 1
            origin = self._cors_origin()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Cortex-CSRF-Token")
            if origin != "*":
                self.send_header("Access-Control-Allow-Credentials", "true")
            for name, value in extra_headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _cookie_session_token(self) -> str:
            """Read the session token from the HttpOnly cookie.

            The browser never handles this value in JavaScript, which is the whole point of
            moving off `Authorization: Bearer` for interactive callers.
            """
            raw = self.headers.get("Cookie")
            if not raw:
                return ""
            morsel = SimpleCookie(raw).get(SESSION_COOKIE_NAME)
            return morsel.value if morsel else ""

        def _current_token(self) -> str:
            """The caller's credential, cookie first then bearer.

            Used where a route needs the token itself to identify the session record, not just
            to authorize the request.
            """
            token = self._cookie_session_token()
            if token:
                return token
            auth = self.headers.get("Authorization", "")
            return auth.split(" ", 1)[-1] if " " in auth else ""

        def _send_metrics(self) -> None:
            with _REQUEST_METRICS_LOCK:
                snapshot = dict(_REQUEST_METRICS)
            lines = ["# HELP xibalba_cortex_requests_total Total local API responses.", "# TYPE xibalba_cortex_requests_total counter", f"xibalba_cortex_requests_total {snapshot.get("requests_total", 0)}"]
            for key, value in sorted(snapshot.items()):
                if key.startswith("responses_"):
                    lines.append(f"xibalba_cortex_responses_total{{status=\"{key.removeprefix("responses_")}\"}} {value}")
            body = ("\n".join(lines) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authenticate(self, *, required_scope: str) -> dict[str, object] | None:
            # Interactive callers present an HttpOnly cookie; machine callers (MCP over
            # streamable-HTTP, CLI, workers) still present a bearer token. The cookie wins so a
            # stale header cannot shadow a live browser session.
            token = self._cookie_session_token()
            if not token:
                auth = self.headers.get("Authorization", "")
                scheme, _, credentials = auth.partition(" ")
                token = credentials.strip() if scheme.lower() == "bearer" else ""
            if not token:
                self._send_json(401, {"error": "authentication required: session cookie or Authorization: Bearer <token>"})
                return None
            principal = verify_token_record(store.home, token)
            if principal is None:
                self._send_json(401, {"error": "invalid or revoked token"})
                return None
            if principal["profile_id"] != store.profile_id:
                self._send_json(403, {"error": "credential is not authorized for this profile"})
                return None
            if required_scope not in principal["scopes"]:
                self._send_json(403, {"error": f"credential lacks required scope: {required_scope}"})
                return None
            return principal

        def _verify_csrf(self) -> bool:
            """Call after a successful _authenticate() on every state-changing (POST) route.

            Only cookie-authenticated requests need this: a bearer-token caller (MCP, CLI,
            workers) has no cookie jar for a malicious page to ride, so it isn't a CSRF target.
            See _csrf_token_for's docstring for why the header can't be forged cross-site even
            though the SameSite=None cookie itself is attached automatically.
            """
            cookie_token = self._cookie_session_token()
            if not cookie_token:
                return True
            expected = _csrf_token_for(csrf_secret, cookie_token)
            provided = self.headers.get("X-Cortex-CSRF-Token", "")
            if not provided or not hmac.compare_digest(provided, expected):
                self._send_json(403, {"error": "missing or invalid CSRF token; GET /api/auth/csrf first"})
                return False
            return True

        def do_OPTIONS(self) -> None:  # noqa: N802 -- CORS preflight
            origin = self._cors_origin()
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Cortex-CSRF-Token")
            if origin != "*":
                self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()

        def _read_json_body(self) -> dict[str, object]:
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                raise ValueError("invalid Content-Length")
            if length <= 0:
                return {}
            if length > _MAX_JSON_BODY_BYTES:
                raise ValueError("request body too large")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON body: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming convention
            request_limiter.wait()
            parsed = urlparse(self.path)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            parts = [p for p in parsed.path.split("/") if p]

            if parts == ["api", "auth", "me"]:
                principal = self._authenticate(required_scope="memory:read")
                if principal is None:
                    return
                token = self._current_token()
                account = account_for_token(store.home, token)
                self._send_json(200, {"account": account, "session_expires_at": principal.get("expires_at")} if account else {"error": "account session not found"})
                return
            if parts == ["api", "auth", "csrf"]:
                # Cross-origin browser callers (SameSite=None session cookie) can't read this
                # cookie's own value to derive the CSRF token themselves -- HttpOnly, and even
                # if it weren't, cross-origin `document.cookie` reads are blocked regardless of
                # SameSite. Handing the token back in a CORS-mediated JSON body works because
                # CORS gates *response reading* by origin (the --allowed-origins allow-list),
                # independent of the SameSite cookie policy that gates *request sending*.
                principal = self._authenticate(required_scope="memory:read")
                if principal is None:
                    return
                if not self._cookie_session_token():
                    self._send_json(400, {"error": "csrf token requires cookie-based session auth"})
                    return
                self._send_json(200, {"csrf_token": _csrf_token_for(csrf_secret, self._cookie_session_token())})
                return
            if parts == ["api", "auth", "sessions"]:
                principal = self._authenticate(required_scope="memory:read")
                if principal is None:
                    return
                token = self._current_token()
                account = account_for_token(store.home, token)
                email = str(account.get("email")) if account else ""
                sessions = [item for item in list_tokens(store.home) if item["label"] == f"account:{email}"]
                self._send_json(200, {"sessions": sessions})
                return
            if parts == ["api", "auth", "events"]:
                principal = self._authenticate(required_scope="memory:read")
                if principal is None:
                    return
                token = self._current_token()
                account = account_for_token(store.home, token)
                conn = _connect(store.home)
                try:
                    rows = conn.execute("SELECT event_type,detail,created_at FROM auth_events WHERE email=? ORDER BY id DESC LIMIT 100", (account["email"] if account else "",)).fetchall()
                    self._send_json(200, {"events": [dict(row) for row in rows]})
                finally:
                    conn.close()
                return
            if parts not in (["metrics"], ["healthz"], ["readyz"]):
                principal = self._authenticate(required_scope="memory:read")
                if principal is None:
                    return

            try:
                if parts == ["metrics"]:
                    self._send_metrics()
                elif parts == ["healthz"]:
                    self._send_json(200, {"schema_version": "xibalba.health.v1", "status": "ok", "profile_id": store.profile_id})
                elif parts == ["readyz"]:
                    status = store.status()
                    ready = status["integrity_check"] == "ok" and status["foreign_keys"] is True and status["fts5"] is True and status["backup_ready"] is True
                    self._send_json(200 if ready else 503, {"schema_version": "xibalba.readiness.v1", "ready": ready, "profile_id": store.profile_id, "checks": {"integrity_check": status["integrity_check"], "foreign_keys": status["foreign_keys"], "fts5": status["fts5"], "backup_ready": status["backup_ready"]}})
                elif parts == ["api", "stats"]:
                    self._send_json(200, store.counts())
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "agent" and parts[3] == "summary":
                    limit = int(params.get("limit", 8))
                    agent_filter = _agent_filter(store, principal, unquote(parts[2]))
                    if agent_filter is None:
                        raise PermissionError("credential is not bound to an agent")
                    self._send_json(200, store.agent_summary(agent_filter, limit=limit))
                elif parts == ["api", "agents"]:
                    # agent_workspaces() scans sources/memories for every agent_id and
                    # overlays agent_devices pairing metadata where it exists -- it must
                    # not be replaced with a pairs-only projection here, or any agent
                    # with real memories but no device pairing silently disappears from
                    # the header selector (the common case, not an edge case).
                    workspaces = store.agent_workspaces(limit=int(params.get("limit", 100)))
                    authorized = _principal_agent_ids(principal)
                    if authorized:
                        persisted = {value for agent in authorized if (value := store.storage_agent_id(agent))}
                        allowed = persisted | set(authorized)
                        workspaces = [item for item in workspaces if item.get("agent_id") in allowed]
                        # A chain-registered agent is visible even before its first
                        # exchange.  This keeps the header selector a registration
                        # directory, rather than silently hiding an authorized
                        # namespace until memory ingestion happens.
                        present = {str(item.get("agent_id")) for item in workspaces}
                        for agent_id in authorized:
                            storage_id = store.storage_agent_id(agent_id) or agent_id
                            if storage_id in present:
                                continue
                            workspaces.append({
                                "agent_id": storage_id,
                                "device_id": None,
                                "agent_name": None,
                                "device_name": None,
                                "pair_status": None,
                                "pair_updated_at": None,
                                "memories": 0,
                                "sessions": 0,
                                "last_seen_at": None,
                            })
                        workspaces = workspaces[:max(1, min(int(params.get("limit", 100)), 500))]
                    # Standardized 2026-09-13 identity resolution (see integrity_sdk's own
                    # docstring): on-chain status + XNS handle/DID-doc name/local label, the
                    # same contract Shield and the dashboard use for the same three questions
                    # ("what do I call this agent", "is it real", "is it on-chain").
                    #
                    # `import os` here (module already imported at file scope) works around
                    # this same do_GET method's own local `import os` further down (elif
                    # branch handling a different route) -- that local import makes `os` a
                    # function-local name for this entire method under Python's scoping
                    # rules, which would otherwise make this earlier reference raise
                    # UnboundLocalError.
                    import os
                    oracle_url = os.environ.get("XIBALBA_ORACLE_URL", "http://localhost:8080")
                    identities = resolve_agent_identities(
                        [str(item["agent_id"]) for item in workspaces if item.get("agent_id")],
                        oracle_url,
                    )
                    # resolve_agent_identities() fails open by design (its own docstring: "any
                    # oracle-reachability problem resolves every requested DID to 'unknown,
                    # off-chain, no name'") -- correct for a naming lookup that must never break
                    # this page, but it makes "confirmed off-chain" and "couldn't check, oracle
                    # down" indistinguishable to a caller reading only on_chain/seen. Probe the
                    # oracle independently so the viewer can render an honest "unverified" state
                    # instead of a confident, possibly-false "off-chain" badge.
                    oracle_reachable = True
                    try:
                        requests.get(f"{oracle_url.rstrip('/')}/v1/agents", timeout=2.0).raise_for_status()
                    except requests.RequestException:
                        oracle_reachable = False
                    for item in workspaces:
                        identity = identities.get(str(item.get("agent_id")))
                        if identity:
                            item.update(identity)
                            # The viewer's existing card rendering
                            # (`workspace.device_name || workspace.agent_name`) already reads
                            # this exact field -- set it from the resolved display name so no
                            # viewer change is needed, instead of leaving it permanently null.
                            item["agent_name"] = identity["display_name"]
                        item["identity_verified"] = oracle_reachable
                    self._send_json(200, {"agents": workspaces, "oracle_reachable": oracle_reachable})
                elif parts == ["api", "agent-devices"]:
                    _assert_pair_manager(principal)
                    self._send_json(200, {"pairs": store.list_agent_devices(limit=int(params.get("limit", 500)))})
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "agent" and parts[3] == "memories":
                    agent_id = _agent_filter(store, principal, unquote(parts[2]))
                    if agent_id is None:
                        raise PermissionError("credential is not bound to an agent")
                    self._send_json(200, {"agent_id": agent_id, "memories": store.agent_memories(agent_id, device_id=params.get("device_id"), limit=int(params.get("limit", 100)))})
                elif parts == ["api", "status"]:
                    self._send_json(200, store.status(fast=True))
                elif parts == ["api", "operations"]:
                    status = store.status(fast=True)
                    try:
                        audit = store.audit_report(limit=25)
                    except RuntimeError as exc:
                        audit = {"disabled": True, "error": str(exc)}
                    self._send_json(200, {"schema_version": "xibalba.dashboard_operations.v1", "profile_id": store.profile_id, "health": {"state": "healthy", "status": status}, "readiness": {"state": "healthy" if status["integrity_check"] == "skipped (fast mode)" and status["foreign_keys"] and status["fts5"] and status["backup_ready"] else "degraded", "checks": {"foreign_keys": status["foreign_keys"], "fts5": status["fts5"], "backup_ready": status["backup_ready"]}}, "features": status.get("features", {}), "quotas": status.get("quotas", {}), "embedding_coverage": store.embedding_coverage(), "audit": audit, "connectors": connector_manifest(), "production": {"state": "local_only", "active_tokens": sum(1 for row in list_tokens(store.home) if not row["revoked_at"] and (not row["expires_at"] or row["expires_at"] > datetime.now(timezone.utc).isoformat())), "token_lifecycle": "implemented", "tenant_onboarding": "implemented", "isolation_model": "one profile home and SQLite store per tenant", "open_gates": ["external pilot deployment", "published integrity-sdk", "HA/PITR", "real-tenant evaluation", "burn-in SLA"]}, "disclaimer": "Local dashboard operations evidence; not deployment, SLA, compliance, or pilot-readiness evidence."})
                elif parts == ["api", "settings", "inference"]:
                    self._send_json(200, load_config(home=store.home).redacted_dict()["inference"])
                elif parts == ["api", "integrity-links"]:
                    limit = int(params.get("limit", 50))
                    self._send_json(200, store.integrity_links_status(limit=limit))
                elif parts == ["api", "sessions"]:
                    limit = int(params.get("limit", 100))
                    requested_agent = params.get("agent_id")
                    agent_filter = _agent_filter(store, principal, requested_agent)
                    self._send_json(200, store.list_sessions(limit=limit, agent_id=agent_filter))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "replay":
                    _assert_session_access(store, principal, parts[2])
                    self._send_json(200, store.session_replay(parts[2]))
                elif parts == ["api", "invocations"]:
                    limit = int(params.get("limit", 100))
                    self._send_json(200, store.invocation_correlations(limit=limit, agent_id=_principal_agent_id(principal)))
                elif parts == ["api", "search"]:
                    query = params.get("q", "")
                    limit = int(params.get("limit", 10))
                    requested_agent = params.get("agent_id")
                    agent_filter = _agent_filter(store, principal, requested_agent)
                    self._send_json(200, store.search(query, limit=limit, agent_id=agent_filter))
                elif parts == ["api", "memories"]:
                    limit = int(params.get("limit", 50))
                    offset = int(params.get("offset", 0))
                    raw_status = params.get("status")
                    statuses = tuple(s.strip() for s in raw_status.split(",") if s.strip()) if raw_status else (
                        "candidate", "active", "confirmed", "superseded", "forgotten",
                    )
                    requested_agent = params.get("agent_id")
                    agent_filter = _agent_filter(store, principal, requested_agent)
                    page = store.list_memories(limit=limit + 1, offset=offset, statuses=statuses, agent_id=agent_filter)
                    self._send_json(200, {"memories": page[:limit], "has_more": len(page) > limit, "offset": offset, "limit": limit})
                elif parts == ["api", "graph"]:
                    limit = int(params.get("limit", 500))
                    threshold = float(params.get("similarity_threshold", 0.75))
                    requested_agent = params.get("agent_id")
                    agent_filter = _agent_filter(store, principal, requested_agent)
                    self._send_json(200, store.graph_payload(limit=limit, similarity_threshold=threshold, agent_id=agent_filter))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "entity" and parts[3] == "neighbors":
                    max_depth = int(params.get("max_depth", 1))
                    self._send_json(200, store.neighbors(unquote(parts[2]), max_depth=max_depth, agent_id=_agent_filter(store, principal, None)))
                elif parts == ["api", "entity", "path"]:
                    max_depth = int(params.get("max_depth", 3))
                    self._send_json(200, store.find_path(params.get("from", ""), params.get("to", ""), max_depth=max_depth, agent_id=_agent_filter(store, principal, None)))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "exchanges":
                    _assert_session_access(store, principal, parts[2])
                    self._send_json(200, store.session_exchanges(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "otel":
                    _assert_session_access(store, principal, parts[2])
                    self._send_json(200, store.session_otel_events(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "merkle-root":
                    _assert_session_access(store, principal, parts[2])
                    self._send_json(200, store.session_merkle_root(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "merkle-proof":
                    _assert_session_access(store, principal, parts[2])
                    self._send_json(200, store.session_merkle_evidence(parts[2], exchange_index=int(params.get("index", "0"))))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "kernel-intents":
                    _assert_session_access(store, principal, parts[2])
                    self._send_json(200, store.kernel_bridge_intents(parts[2]))
                elif parts == ["api", "inference", "manifest"]:
                    self._send_json(200, MEMORY_INFERENCE_SUBAGENT_MANIFEST)
                elif parts == ["api", "inference", "tasks"]:
                    status = params.get("status", "pending")
                    limit = int(params.get("limit", 50))
                    tasks = store.list_inference_tasks(status=status, limit=limit)
                    visible = []
                    for task in tasks:
                        if task.get("subject_type") == "memory":
                            try:
                                _assert_memory_scope(store.get_memory(str(task.get("subject_id"))), principal, store)
                            except (KeyError, PermissionError):
                                continue
                        visible.append(task)
                    self._send_json(200, visible)
                elif parts == ["api", "para", "classifications"]:
                    status = params.get("status", "proposed")
                    limit = int(params.get("limit", 50))
                    self._send_json(200, store.list_para_classifications(status=status, limit=limit))
                elif parts == ["api", "extraction-proposals"]:
                    status = params.get("status", "proposed")
                    limit = int(params.get("limit", 50))
                    task_id = params.get("task_id")
                    source_memory_id = params.get("source_memory_id")
                    self._send_json(200, store.list_extraction_proposals(status=status, task_id=task_id, source_memory_id=source_memory_id, limit=limit))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "retrieval" and parts[2] == "trace":
                    self._send_json(200, _assert_trace_scope(store, principal, store.get_retrieval_trace(parts[3])))
                elif len(parts) == 5 and parts[0] == "api" and parts[1] == "retrieval" and parts[2] == "trace" and parts[4] == "evidence":
                    rank = int(params.get("rank", 1))
                    _assert_trace_scope(store, principal, store.get_retrieval_trace(parts[3]))
                    self._send_json(200, store.retrieval_trace_evidence(parts[3], rank=rank))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "projections" and parts[3] == "checkpoints":
                    limit = int(params.get("limit", 50))
                    self._send_json(200, store.list_projection_checkpoints(parts[2], limit=limit))
                elif len(parts) == 5 and parts[0] == "api" and parts[1] == "projections" and parts[3] == "checkpoints" and parts[4] == "latest":
                    latest = store.get_latest_projection_checkpoint(parts[2])
                    if latest is None:
                        self._send_json(404, {"error": "no checkpoint exists for this projection yet"})
                    else:
                        self._send_json(200, latest)
                elif parts == ["api", "embedding", "models"]:
                    self._send_json(200, store.list_embedding_models())
                elif len(parts) == 3 and parts[0] == "api" and parts[1] == "memory" and parts[2]:
                    self._send_json(200, _assert_memory_scope(store.get_memory(parts[2]), principal, store))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "similar":
                    limit = int(params.get("limit", 10))
                    _assert_memory_scope(store.get_memory(parts[2]), principal, store)
                    self._send_json(200, store.similar_memories(parts[2], limit=limit))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "neighbors":
                    _assert_memory_scope(store.get_memory(parts[2]), principal, store)
                    self._send_json(200, store.memory_entity_relations(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "events":
                    _assert_memory_scope(store.get_memory(parts[2]), principal, store)
                    self._send_json(200, store.memory_events(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "otel":
                    _assert_memory_scope(store.get_memory(parts[2]), principal, store)
                    self._send_json(200, store.memory_otel_events(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "attachments":
                    _assert_memory_scope(store.get_memory(parts[2]), principal, store)
                    self._send_json(200, store.list_attachments(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "attachment" and parts[3] == "file":
                    attachment = store.get_attachment(parts[2])
                    if not attachment:
                        self._send_json(404, {"error": "attachment not found"})
                    else:
                        locator = attachment["storage_locator"]
                        file_path = locator[7:] if locator.startswith("file://") else locator
                        import os
                        if not os.path.exists(file_path):
                            self._send_json(404, {"error": f"file not found at {file_path}"})
                        else:
                            origin = self._cors_origin()
                            self.send_response(200)
                            self.send_header("Content-Type", attachment.get("media_type") or "application/octet-stream")
                            self.send_header("Access-Control-Allow-Origin", origin)
                            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Cortex-CSRF-Token")
                            if origin != "*":
                                self.send_header("Access-Control-Allow-Credentials", "true")
                            self.send_header("Content-Length", str(os.path.getsize(file_path)))
                            self.end_headers()
                            with open(file_path, "rb") as f:
                                self.wfile.write(f.read())
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "contradictions":
                    _assert_memory_scope(store.get_memory(parts[2]), principal, store)
                    self._send_json(200, [_assert_memory_scope(memory, principal, store) for memory in store.contradictions(parts[2])])
                else:
                    self._send_json(404, {"error": "not found"})
            except KeyError:
                self._send_json(404, {"error": "not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except PermissionError as exc:
                self._send_json(403, {"error": str(exc)})
            except Exception:
                logger.exception("local_api request failed: %s", self.path)
                self._send_json(500, {"error": "internal error"})

        def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming convention
            request_limiter.wait()
            parsed = urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]

            is_decision_route = (
                (len(parts) == 5 and parts[:3] == ["api", "para", "classifications"] and parts[4] == "decision")
                or (len(parts) == 4 and parts[:2] == ["api", "extraction-proposals"] and parts[3] == "decision")
            )
            is_read_route = parts == ["api", "retrieval", "hybrid"]
            required_scope = "proposal:decide" if is_decision_route else "memory:read" if is_read_route else "memory:write"
            if parts == ["api", "settings", "inference"]:
                try:
                    body = self._read_json_body()
                    allowed = {"enabled", "provider", "harness", "profile_name", "allow_fallback", "task_types", "batch_size", "interval_seconds", "max_attempts", "timeout_seconds", "max_parallel_families", "combined_batching", "max_evidence_chars_per_memory", "max_items_per_type", "human_review_confidence_threshold", "task_confidence_thresholds", "promotion_policy", "contradictions_require_review"}
                    unknown = set(body) - allowed
                    if unknown:
                        raise ValueError(f"unsupported inference settings: {sorted(unknown)}")
                    config_path = Path(store.home) / "config.yaml"
                    raw = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
                    if raw is None:
                        raw = {}
                    if not isinstance(raw, dict):
                        raise ValueError("config.yaml must contain a mapping")
                    raw["inference"] = {**(raw.get("inference") or {}), **body}
                    config_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = config_path.with_suffix(".yaml.tmp")
                    temporary.write_text(yaml.safe_dump(raw, sort_keys=False))
                    try:
                        with tempfile.TemporaryDirectory(prefix="cortex-config-") as validation_home:
                            Path(validation_home, "config.yaml").write_text(temporary.read_text())
                            validated_inference = load_config(home=validation_home).redacted_dict()["inference"]
                    except Exception:
                        temporary.unlink(missing_ok=True)
                        raise
                    os.replace(temporary, config_path)
                    self._send_json(200, {"ok": True, "inference": validated_inference, "message": "Inference policy saved; the daemon reloads it on its next cycle."})
                    return
                except ValueError as e:
                    self._send_json(400, {"error": str(e)})
                    return
                except Exception as e:
                    logger.exception("could not update inference settings")
                    self._send_json(500, {"error": str(e)})
                    return

            if parts in (["api", "auth", "signup"], ["api", "auth", "login"], ["api", "auth", "logout"], ["api", "auth", "password"], ["api", "auth", "sessions", "revoke"], ["api", "auth", "password-reset", "request"], ["api", "auth", "password-reset", "confirm"], ["api", "auth", "admin", "approve"]):
                try:
                    payload = self._read_json_body()
                    if parts[-1] in ("signup", "login", "request"):
                        identity = f"{parts[-1]}:{str(payload.get('email') or '').strip().lower()}:{self.client_address[0]}"
                        if not auth_allowed(identity):
                            self._send_json(429, {"error": "too many authentication attempts; try again later"})
                            return
                    if parts[-2:] == ["admin", "approve"]:
                        principal = self._authenticate(required_scope="*")
                        if principal is None:
                            return
                        if not self._verify_csrf():
                            return
                        approved = approve_account(store.home, email=str(payload.get("email") or ""), verified=bool(payload.get("verified", True)))
                        self._send_json(200 if approved else 404, {"ok": approved} if approved else {"error": "account not found"})
                    elif parts[-2:] == ["password-reset", "request"]:
                        email = str(payload.get("email") or "")
                        try:
                            request_password_reset(store.home, email=email)
                        except RuntimeError:
                            self._send_json(503, {"error": "password reset delivery is unavailable"})
                            return
                        self._send_json(200, {"ok": True, "delivery": "email"})
                    elif parts[-2:] == ["password-reset", "confirm"]:
                        changed = reset_password(store.home, reset_token=str(payload.get("reset_token") or ""), new_password=str(payload.get("new_password") or ""))
                        self._send_json(200 if changed else 400, {"ok": changed} if changed else {"error": "reset token is invalid or expired"})
                    elif parts[-2:] == ["sessions", "revoke"]:
                        token = self._current_token()
                        principal = self._authenticate(required_scope="memory:read")
                        if principal is None:
                            return
                        if not self._verify_csrf():
                            return
                        revoked = revoke_account_session_by_id(store.home, current_token=token, session_id=str(payload.get("session_id") or ""))
                        self._send_json(200 if revoked else 404, {"ok": revoked} if revoked else {"error": "session not found"})
                    elif parts[-1] == "password":
                        token = self._current_token()
                        principal = self._authenticate(required_scope="memory:read")
                        if principal is None:
                            return
                        if not self._verify_csrf():
                            return
                        changed = change_account_password(store.home, token=token, current_password=str(payload.get("current_password") or ""), new_password=str(payload.get("new_password") or ""))
                        self._send_json(200 if changed else 401, {"ok": changed} if changed else {"error": "current password is incorrect"})
                    elif parts[-1] == "signup":
                        create_account(store.home, email=str(payload.get("email") or ""), password=str(payload.get("password") or ""), display_name=str(payload.get("display_name") or ""), profile_id=store.profile_id)
                        token, account = issue_account_session(store.home, email=str(payload.get("email") or ""), password=str(payload.get("password") or ""))
                        self._send_json(201, {"account": account}, extra_headers=(("Set-Cookie", _session_cookie(token, max_age=_SESSION_TTL_HOURS * 3600)),))
                    elif parts[-1] == "login":
                        token, account = issue_account_session(store.home, email=str(payload.get("email") or ""), password=str(payload.get("password") or ""))
                        self._send_json(200, {"account": account}, extra_headers=(("Set-Cookie", _session_cookie(token, max_age=_SESSION_TTL_HOURS * 3600)),))
                    else:
                        token = self._cookie_session_token()
                        if not token:
                            token = self._current_token()
                        revoked = revoke_account_session(store.home, token)
                        # Clear the cookie regardless of whether the record was still live, so a
                        # browser holding an already-expired session is not left presenting it.
                        self._send_json(200, {"ok": revoked}, extra_headers=(("Set-Cookie", _session_cookie("", max_age=0)),))
                except ValueError as exc:
                    self._send_json(400, {"error": str(exc)})
                return
            principal = self._authenticate(required_scope=required_scope)
            if principal is None:
                return
            if not self._verify_csrf():
                return

            try:
                payload = self._read_json_body()
                if parts == ["api", "agent-devices", "associate"]:
                    _assert_pair_manager(principal)
                    agent_id = str(payload.get("agent_id") or "").strip()
                    persisted_agent = store.storage_agent_id(agent_id)
                    if persisted_agent is None:
                        raise ValueError("agent identity attribution is disabled")
                    self._send_json(200, store.associate_agent_device(
                        persisted_agent,
                        str(payload.get("device_id") or ""),
                        display_name=str(payload.get("display_name") or "") or None,
                    ))
                elif len(parts) == 4 and parts[:2] == ["api", "agent-devices"] and parts[3] == "rename":
                    _assert_pair_manager(principal)
                    self._send_json(200, store.rename_agent_device(unquote(parts[2]), str(payload.get("display_name") or "")))
                elif len(parts) == 4 and parts[:2] == ["api", "agent-devices"] and parts[3] in {"detach", "revoke"}:
                    _assert_pair_manager(principal)
                    self._send_json(200, store.set_agent_device_status(unquote(parts[2]), parts[3] + "ed" if parts[3] == "detach" else "revoked"))
                elif len(parts) == 5 and parts[0] == "api" and parts[1] == "session" and parts[3] == "exchanges" and parts[4] == "build":
                    from .exchange_builder import build_session_exchanges
                    _assert_session_access(store, principal, unquote(parts[2]))
                    self._send_json(200, build_session_exchanges(store, unquote(parts[2])))
                elif parts == ["api", "otel", "batch"]:
                    # Browser-reachable write path for record_otel_batch (~/.claude/plans/
                    # velvet-giggling-quill.md's cross-system test log) -- previously only
                    # callable in-process via runtime_controller.ingest_event; the dashboard
                    # needs its own POST route since it isn't an MCP client. Same
                    # idempotent start_session-then-insert pattern ingest_event already uses,
                    # since otel_events.session_id has a NOT NULL FK to sessions.
                    session_id = str(payload.get("session_id") or "")
                    events = payload.get("events")
                    if not session_id:
                        raise ValueError("session_id is required")
                    if not isinstance(events, list):
                        raise ValueError("events must be a list")
                    store.start_session(session_id, retention_tier="digest", agent_id=_write_agent(store, principal))
                    _assert_session_access(store, principal, session_id)
                    self._send_json(200, store.record_otel_batch(session_id, events))
                elif parts == ["api", "exchanges", "model"]:
                    requested_agent = payload.get("agent_id") if isinstance(payload.get("agent_id"), str) else None
                    bound_agent = _write_agent(store, principal, requested_agent)
                    self._send_json(
                        200,
                        store.record_model_exchange(
                            str(payload.get("external_session_id") or ""),
                            user_prompt=str(payload.get("user_prompt") or ""),
                            model_response=str(payload.get("model_response") or ""),
                            context=list(payload.get("context") or []),
                            runtime=payload.get("runtime") if isinstance(payload.get("runtime"), str) else None,
                            agent_id=bound_agent,
                            prompt_id=payload.get("prompt_id") if isinstance(payload.get("prompt_id"), str) else None,
                            prompt_time=payload.get("prompt_time") if isinstance(payload.get("prompt_time"), str) else None,
                            response_time=payload.get("response_time") if isinstance(payload.get("response_time"), str) else None,
                            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
                            idempotency_key=payload.get("idempotency_key")
                            if isinstance(payload.get("idempotency_key"), str)
                            else None,
                        ),
                    )
                elif parts == ["api", "inference", "tasks"]:
                    input_payload = payload.get("input_payload")
                    if not isinstance(input_payload, dict):
                        raise ValueError("input_payload must be an object")
                    subject_type = str(payload.get("subject_type") or "")
                    subject_id = str(payload.get("subject_id") or "")
                    if subject_type == "memory" and str(payload.get("task_type") or "") in _INFERENCE_TASK_TYPES:
                        _assert_memory_scope(store.get_memory(subject_id), principal, store)
                    contract_raw = payload.get("contract")
                    contract = None
                    if contract_raw is not None:
                        if not isinstance(contract_raw, dict):
                            raise ValueError("contract must be an object")
                        contract = InferenceTaskContract(
                            schema_version=str(contract_raw.get("schema_version", "xibalba.inference.task.v1")),
                            evidence_scope=tuple(str(item) for item in contract_raw.get("evidence_scope", [])),
                            input_snapshot_hash=contract_raw.get("input_snapshot_hash") if isinstance(contract_raw.get("input_snapshot_hash"), str) else None,
                            output_schema=str(contract_raw.get("output_schema", "xibalba.inference.output.v1")),
                            promotion_policy=str(contract_raw.get("promotion_policy", "review_required")),
                            worker_runtime=contract_raw.get("worker_runtime") if isinstance(contract_raw.get("worker_runtime"), str) else None,
                        )
                    self._send_json(
                        200,
                        store.request_inference_task(
                            str(payload.get("task_type") or ""),
                            subject_type=subject_type,
                            subject_id=subject_id,
                            input_payload=input_payload,
                            requested_by=payload.get("requested_by")
                            if isinstance(payload.get("requested_by"), str)
                            else None,
                            idempotency_key=payload.get("idempotency_key")
                            if isinstance(payload.get("idempotency_key"), str)
                            else None,
                            contract=contract,
                        ),
                    )
                elif parts == ["api", "memory", "propositions"]:
                    source = payload.get("source")
                    if source is not None and not isinstance(source, dict):
                        raise ValueError("source must be an object")
                    source = _scoped_source(store, principal, source if isinstance(source, dict) else None)
                    self._send_json(
                        200,
                        store.store_memory(
                            str(payload.get("content") or ""),
                            source=source,
                            status=str(payload.get("status") or "candidate"),
                            evidence_class=str(payload.get("evidence_class") or "extracted_proposition"),
                            idempotency_key=payload.get("idempotency_key")
                            if isinstance(payload.get("idempotency_key"), str)
                            else None,
                        ),
                    )
                elif parts == ["api", "memory", "link-entities"]:
                    _assert_memory_scope(store.get_memory(str(payload.get("evidence_memory_id") or "")), principal, store)
                    self._send_json(
                        200,
                        store.link_entities(
                            str(payload.get("subject") or ""),
                            str(payload.get("predicate") or ""),
                            str(payload.get("object") or ""),
                            evidence_memory_id=str(payload.get("evidence_memory_id") or ""),
                            confidence=float(payload.get("confidence", 1.0)),
                        ),
                    )
                elif parts == ["api", "memory", "contradictions"]:
                    _assert_memory_scope(store.get_memory(str(payload.get("memory_id_a") or "")), principal, store)
                    _assert_memory_scope(store.get_memory(str(payload.get("memory_id_b") or "")), principal, store)
                    self._send_json(
                        200,
                        store.mark_contradiction(
                            str(payload.get("memory_id_a") or ""),
                            str(payload.get("memory_id_b") or ""),
                            str(payload.get("reason") or ""),
                        ),
                    )
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "supersede":
                    source = payload.get("source")
                    if source is not None and not isinstance(source, dict):
                        raise ValueError("source must be an object")
                    _assert_memory_scope(store.get_memory(unquote(parts[2])), principal, store)
                    self._send_json(
                        200,
                        store.supersede_memory(
                            unquote(parts[2]),
                            str(payload.get("new_content") or ""),
                            source=_scoped_source(store, principal, source if isinstance(source, dict) else None),
                            status=str(payload.get("status") or "confirmed"),
                            evidence_class=str(payload.get("evidence_class") or "extracted_proposition"),
                            idempotency_key=payload.get("idempotency_key")
                            if isinstance(payload.get("idempotency_key"), str)
                            else None,
                        ),
                    )
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "forget":
                    _assert_memory_scope(store.get_memory(unquote(parts[2])), principal, store)
                    self._send_json(200, store.forget_memory(unquote(parts[2])))
                elif len(parts) == 5 and parts[:3] == ["api", "para", "classifications"] and parts[4] == "decision":
                    decision = str(payload.get("decision") or "")
                    note = payload.get("note") if isinstance(payload.get("note"), str) else None
                    self._send_json(200, store.accept_para_classification(unquote(parts[3]), decision=decision, note=note))
                elif len(parts) == 4 and parts[:2] == ["api", "extraction-proposals"] and parts[3] == "decision":
                    decision = str(payload.get("decision") or "")
                    note = payload.get("note") if isinstance(payload.get("note"), str) else None
                    decided_by = str(principal["label"])
                    self._send_json(200, store.decide_extraction_proposal(unquote(parts[2]), decision=decision, decided_by=decided_by, note=note))
                elif parts == ["api", "retrieval", "hybrid"]:
                    query_vector = payload.get("query_vector")
                    if query_vector is not None and not isinstance(query_vector, list):
                        raise ValueError("query_vector must be a list")
                    filters = payload.get("filters")
                    if filters is not None and not isinstance(filters, dict):
                        raise ValueError("filters must be an object")
                    filters = dict(filters or {})
                    requested_agent = filters.get("agent_id")
                    filters["agent_id"] = _agent_filter(store, principal, requested_agent)
                    self._send_json(
                        200,
                        store.hybrid_retrieve(
                            str(payload.get("query") or ""),
                            query_vector=[float(v) for v in query_vector] if query_vector is not None else None,
                            limit=int(payload.get("limit", 10)),
                            temporal_at=payload.get("temporal_at") if isinstance(payload.get("temporal_at"), str) else None,
                            filters=filters,
                            max_per_source=payload.get("max_per_source") if isinstance(payload.get("max_per_source"), int) else None,
                            max_total_chars=payload.get("max_total_chars") if isinstance(payload.get("max_total_chars"), int) else None,
                        ),
                    )
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "projections" and parts[3] == "checkpoint":
                    metadata = payload.get("metadata")
                    if metadata is not None and not isinstance(metadata, dict):
                        raise ValueError("metadata must be an object")
                    self._send_json(200, store.create_projection_checkpoint(unquote(parts[2]), metadata=metadata))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "projections" and parts[3] == "reconcile":
                    self._send_json(200, store.reconcile_projection_checkpoint(unquote(parts[2])))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "projections" and parts[3] == "rebuild":
                    self._send_json(200, store.rebuild_projection_checkpoint(unquote(parts[2])))
                elif len(parts) == 5 and parts[:3] == ["api", "inference", "tasks"] and parts[4] == "claim":
                    task = store.get_inference_task(unquote(parts[3]))
                    if task.get("subject_type") == "memory":
                        _assert_memory_scope(store.get_memory(str(task.get("subject_id"))), principal, store)
                    self._send_json(
                        200,
                        store.claim_inference_task(
                            unquote(parts[3]),
                            claimed_by=payload.get("claimed_by")
                            if isinstance(payload.get("claimed_by"), str)
                            else None,
                        ),
                    )
                elif parts == ["api", "kernel-bridge", "self-test"]:
                    session_id = payload.get("session_id")
                    self._send_json(
                        200,
                        _run_kernel_bridge_self_test(
                            store, session_id=session_id if isinstance(session_id, str) and session_id else None
                        ),
                    )
                elif len(parts) == 5 and parts[:3] == ["api", "inference", "tasks"] and parts[4] == "complete":
                    task = store.get_inference_task(unquote(parts[3]))
                    if task.get("subject_type") == "memory":
                        _assert_memory_scope(store.get_memory(str(task.get("subject_id"))), principal, store)
                    output_payload = payload.get("output_payload")
                    if output_payload is not None and not isinstance(output_payload, dict):
                        raise ValueError("output_payload must be an object")
                    self._send_json(
                        200,
                        store.complete_inference_task(
                            unquote(parts[3]),
                            output_payload=output_payload,
                            error=payload.get("error") if isinstance(payload.get("error"), str) else None,
                            claimed_by=payload.get("claimed_by") if isinstance(payload.get("claimed_by"), str) else None,
                            claim_token=payload.get("claim_token") if isinstance(payload.get("claim_token"), str) else None,
                        ),
                    )
                else:
                    self._send_json(404, {"error": "not found"})
            except KeyError:
                self._send_json(404, {"error": "not found"})
            except (sqlite3.IntegrityError, TypeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
            except PermissionError as exc:
                self._send_json(403, {"error": str(exc)})
            except RuntimeError as exc:
                self._send_json(409, {"error": str(exc)})
            except Exception:
                logger.exception("local_api request failed: %s", self.path)
                self._send_json(500, {"error": "internal error"})

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            logger.debug(format, *args)

    return Handler


class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer capped at a fixed number of concurrent request threads.

    Unbounded per-connection threading, combined with GraphStore's lock-held scans (see
    agent_workspaces()'s docstring), let concurrent polling outpace drain rate and run away to
    hundreds of threads within minutes (588 observed 2026-09-14) -- the same failure class
    documented for xibalba-shield's per-device identity resolution. Acquiring the semaphore in
    process_request (which runs in the single accept-loop thread) blocks new connections from
    spawning a thread once the cap is hit, turning an unbounded explosion into bounded queuing.
    """

    daemon_threads = True
    max_concurrent_requests = 32
    # socketserver.TCPServer's default listen() backlog is 5. process_request() below blocks
    # the single accept-loop thread on a semaphore once max_concurrent_requests is in flight --
    # while blocked, it isn't calling accept() at all, so new TCP connections just pile up in
    # the kernel's backlog. At the default of 5, a handful of concurrently slow requests (e.g.
    # under memory-pressure-induced disk contention) fills that backlog, and Caddy's proxy
    # dial fails outright -- a 502 for a request the backend would have served fine once a
    # semaphore slot freed up (reproduced 2026-09-15: direct curl to this port succeeded in
    # ~3s while the same request through Caddy 502'd). A larger backlog buys queuing room
    # instead of an outright connection failure.
    request_queue_size = 128

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._request_semaphore = threading.BoundedSemaphore(self.max_concurrent_requests)

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_semaphore.release()

    def process_request(self, request, client_address) -> None:
        self._request_semaphore.acquire()
        threading.Thread(
            target=self.process_request_thread,
            args=(request, client_address),
            daemon=self.daemon_threads,
        ).start()


def _run_retention_sweep_once(store: GraphStore) -> None:
    """One bounded pass of session/telemetry retention pruning; never raises."""
    try:
        tier_days = {
            "digest": int(os.environ.get("XIBALBA_CORTEX_RETENTION_DIGEST_DAYS", "14")),
            "synopsis": int(os.environ.get("XIBALBA_CORTEX_RETENTION_SYNOPSIS_DAYS", "30")),
            "verbatim": int(os.environ.get("XIBALBA_CORTEX_RETENTION_VERBATIM_DAYS", "180")),
        }
        result = store.retention_sweep(max_age_days=tier_days, apply=True, limit=500)
        if result["candidate_count"]:
            logger.info("retention sweep: forgot %d memory/memories (tiers=%s)", result["candidate_count"], tier_days)
    except Exception:
        logger.exception("session retention sweep failed")
    try:
        otel_days = int(os.environ.get("XIBALBA_CORTEX_OTEL_RETENTION_DAYS", "60"))
        result = store.prune_old_otel_events(max_age_days=otel_days, apply=True, limit=2000)
        if result["count"]:
            logger.info("retention sweep: pruned %d otel_events older than %d days", result["count"], otel_days)
    except Exception:
        logger.exception("otel_events retention sweep failed")


def _retention_sweep_loop(store: GraphStore) -> None:
    # Nothing in this codebase called GraphStore.retention_sweep() automatically before this --
    # every session-starting call site defaults retention_tier="verbatim" (full fidelity, no
    # sweep window), and otel_events (verbatim tool-call attributes_json, up to ~40KB/row) had no
    # pruning path at all. Left alone that grew graph-memory.sqlite3 to 8.7GB over ~6 weeks and
    # contributed to the 2026-09-15 thread-pileup/D-state stall incident (see PRODUCTION_GAPS.md
    # and store.py's `_configure` docstring). This loop is the automatic side of that fix -- the
    # bounded, non-destructive-by-default primitives (`retention_sweep`, `prune_old_otel_events`)
    # already existed but were operator-invoked only.
    interval_hours = max(1, int(os.environ.get("XIBALBA_CORTEX_RETENTION_SWEEP_INTERVAL_HOURS", "6")))
    # Run one pass shortly after startup (not immediately -- let the server finish coming up
    # under load) rather than waiting a full interval for the first sweep.
    time.sleep(300)
    while True:
        _run_retention_sweep_once(store)
        time.sleep(interval_hours * 3600)


def serve(store: GraphStore, *, host: str = "localhost", port: int = 8420, allowed_origins: frozenset[str] = frozenset({"*"})) -> None:
    server = _BoundedThreadingHTTPServer((host, port), _make_handler(store, allowed_origins=allowed_origins))
    if os.environ.get("XIBALBA_CORTEX_DISABLE_RETENTION_SWEEP") != "1":
        threading.Thread(target=_retention_sweep_loop, args=(store,), daemon=True).start()
    logger.info("local_api listening on http://%s:%d (local operator API)", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, help="xibalba-cortex profile home")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument(
        "--allowed-origins", default="*",
        help="Comma-separated CORS origins for browser viewers (e.g. http://localhost:5173,http://localhost:9443). "
        "'*' (default) allows any origin but never sends Access-Control-Allow-Credentials, so cookie-based "
        "auth (fetch with credentials: 'include') will fail cross-origin -- pass explicit origins instead.",
    )
    args = parser.parse_args()
    allowed_origins = frozenset(origin.strip() for origin in args.allowed_origins.split(",") if origin.strip())

    logging.basicConfig(level=logging.INFO)
    config = load_config(home=args.home)
    store = GraphStore(
        config.storage.home,
        profile_id=config.profile_id,
        identity_mode=os.environ.get("XIBALBA_CORTEX_IDENTITY_MODE", "pseudonymous"),
        quotas=config.quotas.as_dict(),
    )
    try:
        serve(store, host=args.host, port=args.port, allowed_origins=allowed_origins)
    finally:
        store.close()


if __name__ == "__main__":
    main()
