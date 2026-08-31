"""Bearer-token auth for the streamable-HTTP MCP transport.

Deliberately NOT using the `mcp` SDK's built-in `TokenVerifier`/`AuthSettings` machinery
(`mcp.server.auth`): that path is OAuth-shaped -- `AuthSettings` mandatorily requires an
`issuer_url` (an OAuth authorization server) and wires in OAuth discovery/metadata routes. Using
it here to gate a simple static per-harness API key would misrepresent what this server actually
supports (no OAuth flow, no token endpoint, no discovery metadata) -- the same "no silent mocks"
rule this whole project follows elsewhere. This is a small, honest, raw ASGI middleware instead.

A raw ASGI class, not Starlette's `BaseHTTPMiddleware`: `BaseHTTPMiddleware` buffers the whole
response before it can inspect it, which breaks server-sent-event streaming -- and the
streamable-HTTP transport this wraps genuinely streams. Rejecting a request before it reaches the
wrapped app is cheap (no buffering needed since nothing has been read yet); passing an accepted
request through is a direct, unbuffered `await app(scope, receive, send)`.
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from functools import wraps
import logging
from collections import defaultdict, deque
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from .ingest_tokens import verify_token_record

logger = logging.getLogger("xibalba_cortex.auth_middleware")

_current_principal: ContextVar[dict[str, object] | None] = ContextVar("xibalba_cortex_principal", default=None)

def current_principal() -> dict[str, object] | None:
    return _current_principal.get()

ASGIApp = Callable[[dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]]


def _extract_bearer_token(scope: dict[str, Any]) -> str | None:
    headers = dict(scope.get("headers") or ())
    raw = headers.get(b"authorization")
    if not raw:
        return None
    value = raw.decode("latin-1")
    if not value.lower().startswith("bearer "):
        return None
    return value[len("bearer "):].strip() or None


async def _reject(send: Callable[[dict[str, Any]], Awaitable[None]], *, status: int, message: str) -> None:
    body = json.dumps({"error": message}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


class BearerTokenAuth:
    """Wraps an ASGI app; rejects any `http` request with a missing, malformed, or
    revoked/unknown bearer token before it reaches the wrapped app. Non-`http` scopes
    (`lifespan`, and `websocket` if ever added) pass through untouched -- there's nothing to
    authenticate about server lifecycle events, and this server doesn't use websockets."""

    def __init__(self, app: ASGIApp, *, home: str | Path, profile_id: str | None = None, required_scopes: tuple[str, ...] = (), rate_limit_per_minute: int | None = None) -> None:
        self._app = app
        self._home = home
        self._profile_id = profile_id
        self._required_scopes = tuple(required_scopes)
        self._rate_limit_per_minute = rate_limit_per_minute
        if rate_limit_per_minute is not None and rate_limit_per_minute < 1:
            raise ValueError("rate_limit_per_minute must be positive or None")
        self._rate_windows: defaultdict[str, deque[float]] = defaultdict(deque)
        self._rate_lock = threading.Lock()

    def _rate_allowed(self, principal_id: str) -> bool:
        if self._rate_limit_per_minute is None:
            return True
        now = time.monotonic()
        cutoff = now - 60.0
        with self._rate_lock:
            window = self._rate_windows[principal_id]
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self._rate_limit_per_minute:
                return False
            window.append(now)
            return True
    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        token = _extract_bearer_token(scope)
        if token is None:
            await _reject(send, status=401, message="missing or malformed Authorization: Bearer <token> header")
            return

        principal = verify_token_record(self._home, token)
        if principal is None:
            await _reject(send, status=401, message="invalid or revoked token")
            return

        if self._profile_id and principal["profile_id"] != self._profile_id:
            await _reject(send, status=403, message="credential is not authorized for this profile")
            return
        if any(scope not in principal["scopes"] for scope in self._required_scopes):
            await _reject(send, status=403, message="credential lacks required scope")
            return

        if not self._rate_allowed(str(principal["id"])):
            await _reject(send, status=429, message="rate limit exceeded")
            return

        logger.debug("authenticated request from harness %r", principal["label"])
        # Stash the resolved harness label on the ASGI scope so downstream tool calls could,
        # in principle, read `scope["state"]["harness_label"]` for attribution -- not consumed
        # by anything yet, but cheap to provide now rather than needing another auth-layer
        # change later if a tool wants to know which harness sent a given call.
        scope.setdefault("state", {})["principal"] = principal
        scope["state"]["harness_label"] = principal["label"]
        principal_token = _current_principal.set(principal)
        try:
            await self._app(scope, receive, send)
        finally:
            _current_principal.reset(principal_token)
