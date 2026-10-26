"""ASGI entry point for the managed edition. Run separately from the local operator API."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timezone
from collections import defaultdict, deque
from contextlib import closing
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.middleware import Middleware
from starlette.staticfiles import StaticFiles

from .. import accounts
from ..contact import ContactInbox, ContactError
from ..email_delivery import EmailDeliveryError
from ..ingest_tokens import issue_token, verify_token_record, _connect as identity_connection
from .config import ManagedConfig
from .control import LimitExceeded, ManagedControl
from .plans import PLANS
from .stripe_gateway import BillingUnavailable

log = logging.getLogger(__name__)
COOKIE = "cortex_managed_session"


class ResponseHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def with_headers(message):
            if message['type'] == 'http.response.start':
                message['headers'] = list(message.get('headers', [])) + [
                    (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff'),
                    (b'x-frame-options', b'DENY'), (b'referrer-policy', b'no-referrer')]
            await send(message)
        await self.app(scope, receive, with_headers)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def create_app(config: ManagedConfig, *, control: ManagedControl | None = None, viewer_dist: Path | None = None):
    service = control or ManagedControl(config)
    csrf_path = config.home / "csrf.secret"
    try:
        with csrf_path.open("xb") as stream:
            stream.write(secrets.token_bytes(32))
        csrf_path.chmod(0o600)
    except FileExistsError:
        pass
    csrf_secret = csrf_path.read_bytes()
    rate_windows = defaultdict(deque)
    rate_lock = threading.Lock()
    export_slots = asyncio.Semaphore(2)
    auth_slots = asyncio.Semaphore(4)

    async def auth_work(function, *args, **kwargs):
        async with auth_slots:
            return await run_in_threadpool(function, *args, **kwargs)

    def rate_limit(request: Request, *, auth=False):
        # Trust forwarded addresses only through uvicorn's explicit proxy allow-list.
        identity = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with rate_lock:
            if len(rate_windows) > 10000:
                stale = [key for key, stamps in rate_windows.items() if not stamps or stamps[-1] < now - 60]
                for key in stale:
                    del rate_windows[key]
                if len(rate_windows) > 10000:
                    raise ApiError(429, "Service request capacity reached")
            window = rate_windows[(identity, auth)]
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= (8 if auth else 120):
                raise ApiError(429, "Too many requests; retry in one minute")
            window.append(now)

    def csrf(token: str) -> str:
        return hmac.new(csrf_secret, token.encode(), hashlib.sha256).hexdigest()

    def authenticate(request: Request, *, mutate=False):
        token = request.cookies.get(COOKIE, "")
        cookie_auth = bool(token)
        if not token:
            scheme, _, candidate = request.headers.get("authorization", "").partition(" ")
            token = candidate if scheme.lower() == "bearer" else ""
        principal = verify_token_record(service.identity_home, token) if token else None
        if principal is None:
            raise ApiError(401, "Sign in to your managed workspace")
        account = accounts.account_for_token(service.identity_home, token)
        if account is None:
            # API keys are looked up through their profile, never through an email supplied by
            # the caller. Their scopes are enforced separately for each memory operation.
            with service.db() as db:
                tenant = db.execute("SELECT owner_account_id FROM tenants WHERE id=?", (principal["profile_id"],)).fetchone()
            if tenant is None:
                raise ApiError(403, "Unknown managed workspace")
            with closing(identity_connection(service.identity_home)) as db:
                record = db.execute("SELECT id,profile_id,status,email_verified,approval_status FROM accounts WHERE id=?", (tenant['owner_account_id'],)).fetchone()
            if record is None:
                raise ApiError(403, 'Workspace owner is unavailable')
            account = dict(record)
        if account.get('status') != 'active' or not account.get('email_verified') or account.get('approval_status') != 'approved':
            raise ApiError(403, 'Account verification is required')
        if mutate and cookie_auth:
            if request.headers.get("origin") != config.public_url.rstrip("/"):
                raise ApiError(403, "Request origin does not match this service")
            if not hmac.compare_digest(request.headers.get("x-cortex-csrf-token", ""), csrf(token)):
                raise ApiError(403, "Missing or invalid CSRF token")
        return account, principal, token

    def owner(request: Request, *, mutate=False):
        account, principal, token = authenticate(request, mutate=mutate)
        if not str(principal["label"]).startswith("account:") or "email" not in account:
            raise ApiError(403, "Billing and API-key management require an account session")
        return account, principal, token

    def require_scope(principal, scope):
        if scope not in principal["scopes"]:
            raise ApiError(403, "This API key lacks " + scope)

    async def body_bytes(request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > config.max_body_bytes:
                raise ApiError(413, "Request body is too large")
        return bytes(data)

    async def payload(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise ApiError(415, "Use application/json")
        try:
            result = json.loads(await body_bytes(request))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Invalid JSON") from None
        if not isinstance(result, dict):
            raise ApiError(400, "Expected a JSON object")
        return result

    def origin_guard(request):
        origin = request.headers.get("origin")
        if origin and origin != config.public_url.rstrip("/"):
            raise ApiError(403, "Request origin does not match this service")

    async def plans(request):
        return JSONResponse({"edition": "managed", "plans": [p.public() for p in PLANS.values()],
            "billing_configured": config.billing_ready, "signup_enabled": config.allow_signup,
            "hosted_inference_enabled": False})

    async def ready(request):
        result = service.config.pilot_readiness()
        return JSONResponse(result, status_code=200 if result["ready"] else 503)

    async def signup(request):
        rate_limit(request, auth=True)
        origin_guard(request)
        data = await payload(request)
        try:
            await auth_work(service.register, email=str(data.get("email", "")),
                password=str(data.get("password", "")), display_name=str(data.get("display_name", "")))
        except ValueError as exc:
            if "already exists" not in str(exc):
                raise
            # No account enumeration. A separate resend endpoint can use the same generic result.
        return JSONResponse({"message": "Check your email to verify your account before signing in."}, status_code=202)

    async def verify(request):
        rate_limit(request, auth=True)
        if not await run_in_threadpool(service.verify_email, request.query_params.get("token", "")):
            raise ApiError(400, "Verification link is invalid or expired")
        return RedirectResponse("/managed?verified=1", status_code=303)

    async def login(request):
        rate_limit(request, auth=True)
        origin_guard(request)
        data = await payload(request)
        token, account = await auth_work(accounts.issue_account_session, service.identity_home,
            email=str(data.get("email", "")), password=str(data.get("password", "")))
        service.tenant(account)
        response = JSONResponse({"account": account, "csrf_token": csrf(token)})
        response.set_cookie(COOKIE, token, max_age=86400, httponly=True, secure=config.public_url.startswith("https:"), samesite="lax", path="/")
        return response

    async def me(request):
        rate_limit(request)
        account, _, token = await run_in_threadpool(owner, request)
        def read_state():
            tenant = service.tenant(account)
            with service.store(tenant) as store:
                counts = store.counts()
            return {"account": account, "entitlement": service.entitlement(tenant),
                "usage": service.usage(tenant), "counts": counts, "csrf_token": csrf(token)}
        return JSONResponse(await run_in_threadpool(read_state))

    async def logout(request):
        _, _, token = await run_in_threadpool(owner, request, mutate=True)
        await run_in_threadpool(accounts.revoke_account_session, service.identity_home, token)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/", secure=config.public_url.startswith("https:"), httponly=True, samesite="lax")
        return response

    async def checkout(request):
        rate_limit(request)
        account, _, _ = await run_in_threadpool(owner, request, mutate=True)
        data = await payload(request)
        return JSONResponse(await run_in_threadpool(service.checkout, account, str(data.get("plan", ""))))

    async def portal(request):
        rate_limit(request)
        account, _, _ = await run_in_threadpool(owner, request, mutate=True)
        return JSONResponse(await run_in_threadpool(service.portal, account))

    async def webhook(request):
        raw = await body_bytes(request)
        event = service.stripe.verify_event(raw, request.headers.get("stripe-signature", ""))
        return JSONResponse(await run_in_threadpool(service.apply_event, event))

    contact_inbox = ContactInbox()

    async def contact(request):
        rate_limit(request, auth=True)
        origin_guard(request)
        body = await payload(request)
        try:
            result = await run_in_threadpool(contact_inbox.submit, body, request.client.host if request.client else 'unknown')
        except ContactError as exc:
            raise ApiError(exc.status, str(exc)) from None
        return JSONResponse(result, status_code=202)

    async def recovery(request):
        rate_limit(request, auth=True)
        origin_guard(request)
        data = await payload(request)
        action = request.path_params['action']
        if action == 'reset':
            changed = await auth_work(service.reset_password, str(data.get('token', '')), str(data.get('password', '')))
            if not changed:
                raise ApiError(400, 'Reset link is invalid or expired')
            return JSONResponse({'message': 'Password reset. Sign in with your new password.'})
        if action not in {'forgot-password', 'resend-verification'}:
            raise ApiError(404, 'Unknown account recovery action')
        function = service.request_reset if action == 'forgot-password' else service.resend_verification
        try:
            await auth_work(function, str(data.get('email', '')))
        except EmailDeliveryError:
            # Keep delivery outages from revealing whether this email has an account.
            log.warning('Managed account recovery email delivery failed')
        return JSONResponse({'message': 'If this account needs this action, an email has been sent.'}, status_code=202)

    async def revoke_key(request):
        account, _, _ = await run_in_threadpool(owner, request, mutate=True)
        data = await payload(request)
        with closing(identity_connection(service.identity_home)) as db:
            changed = db.execute("UPDATE ingest_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE id=? AND profile_id=? AND label LIKE 'managed-api:%' AND revoked_at IS NULL", (str(data.get('id', '')), account['profile_id'])).rowcount
            db.commit()
        return JSONResponse({'revoked': bool(changed)})

    async def keys(request):
        rate_limit(request)
        account, _, _ = await run_in_threadpool(owner, request, mutate=request.method == 'POST')
        with closing(identity_connection(service.identity_home)) as db:
            existing = db.execute("SELECT id,label,created_at,expires_at,revoked_at FROM ingest_tokens WHERE profile_id=? AND label LIKE 'managed-api:%' AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 100", (account['profile_id'],)).fetchall()
        if request.method == 'GET':
            return JSONResponse({'keys': [dict(row) for row in existing]})
        with closing(identity_connection(service.identity_home)) as db:
            active_count = db.execute("SELECT COUNT(*) FROM ingest_tokens WHERE profile_id=? AND label LIKE 'managed-api:%' AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)", (account['profile_id'], datetime.now(timezone.utc).isoformat())).fetchone()[0]
        if active_count >= 100:
            raise ApiError(429, 'Revoke an unused API key before creating another')
        data = await payload(request)
        label = str(data.get("label", "")).strip()
        if not label or len(label) > 80:
            raise ApiError(400, "API key label must contain 1–80 characters")
        # Managed keys may read and write their own tenant; they cannot manage billing, mint
        # other keys, administer accounts, or select another profile.
        token = await run_in_threadpool(issue_token, service.identity_home, "managed-api:" + label,
            profile_id=account["profile_id"], roles=("writer",), scopes=("memory:read", "memory:write"), ttl_hours=720)
        return JSONResponse({"token": token, "expires_in_days": 30}, status_code=201)

    def memory_operation(request, data):
        account, principal, _ = authenticate(request, mutate=request.method == "POST")
        tenant = service.tenant(account)
        require_scope(principal, "memory:write" if request.method == "POST" else "memory:read")
        if request.method == "POST":
            content = data.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ApiError(400, "Memory content is required")
            if len(content.encode()) > config.max_content_bytes:
                raise ApiError(413, "Memory exceeds the 16 KiB content limit")
            request_key = request.headers.get("idempotency-key", "")
            if not 8 <= len(request_key) <= 128:
                raise ApiError(400, "Supply an Idempotency-Key containing 8–128 characters")
            fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            with service.write_guard(tenant):
                service.consume(tenant, "writes", request_key=request_key, fingerprint=fingerprint)
                with service.store(tenant) as store:
                    try:
                        return store.store_memory(content, source={"kind": "direct_user", "agent_id": principal["id"]},
                            status="active", idempotency_key=request_key)
                    except RuntimeError as exc:
                        if str(exc).startswith('memory quota exceeded:'):
                            raise LimitExceeded('Stored-memory capacity reached; export data or choose a larger plan') from None
                        raise
        service.consume(tenant, "retrievals")
        with service.store(tenant) as store:
            if request.path_params.get("memory_id"):
                if request.url.path.endswith('/verify'):
                    store.get_memory(request.path_params['memory_id'])
                    return store.verify_chain(request.path_params['memory_id'])
                return {"memory": store.get_memory(request.path_params["memory_id"])}
            query = request.query_params.get("q", "").strip()
            if len(query) > 500:
                raise ApiError(400, "Search query is too long")
            return {"memories": store.search(query, limit=50) if query else store.list_memories(limit=50)}

    async def memories(request):
        rate_limit(request)
        data = await payload(request) if request.method == "POST" else None
        result = await run_in_threadpool(memory_operation, request, data)
        return JSONResponse(result, status_code=201 if request.method == "POST" else 200)

    def export_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        # Export is paged and retained even after nonpayment or a downgrade. No data deletion
        # or forced upgrade is used to recover memories exceeding a downgraded storage quota.
        try:
            offset = int(request.query_params.get("offset", "0"))
            if offset < 0:
                raise ValueError()
        except ValueError:
            raise ApiError(400, "Export offset must be a nonnegative integer") from None
        with service.store(tenant) as store:
            rows = store.list_memories(limit=100, offset=offset, statuses=("candidate", "active", "confirmed", "superseded", "forgotten", "quarantined", "disputed"))
        return {"memories": rows, "offset": offset, "next_offset": offset + len(rows) if len(rows) == 100 else None}

    async def export(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(export_operation, request))

    async def export_download(request):
        rate_limit(request)
        account, principal, _ = await run_in_threadpool(authenticate, request)
        require_scope(principal, 'memory:read')
        tenant = service.tenant(account)
        def read_page(offset):
            with service.store(tenant) as store:
                return store.list_memories(limit=200, offset=offset, statuses=('candidate', 'active', 'confirmed', 'superseded', 'forgotten', 'quarantined', 'disputed'))
        async def stream():
            async with export_slots:
                yield b'{"schema_version":"cortex.managed.export.v1","memories":['
                offset, first = 0, True
                while True:
                    rows = await run_in_threadpool(read_page, offset)
                    for row in rows:
                        yield (('' if first else ',') + json.dumps(row)).encode()
                        first = False
                    offset += len(rows)
                    if len(rows) < 200:
                        break
                yield b']}'
        return StreamingResponse(stream(), media_type='application/json', headers={'Content-Disposition': 'attachment; filename="cortex-memories.json"'})

    async def error(request, exc):
        if isinstance(exc, ApiError):
            return JSONResponse({"error": exc.message}, status_code=exc.status)
        if isinstance(exc, LimitExceeded):
            return JSONResponse({"error": str(exc)}, status_code=429)
        if isinstance(exc, BillingUnavailable):
            return JSONResponse({"error": str(exc)}, status_code=503)
        if isinstance(exc, PermissionError):
            return JSONResponse({"error": str(exc)}, status_code=403)
        if isinstance(exc, KeyError):
            return JSONResponse({"error": "Memory not found"}, status_code=404)
        if isinstance(exc, ValueError):
            return JSONResponse({"error": str(exc)}, status_code=400)
        log.error("Managed request failed: %s", type(exc).__name__)
        return JSONResponse({"error": "Managed service temporarily unavailable"}, status_code=503)

    routes = [
        Route("/healthz", lambda request: JSONResponse({"ok": True, "edition": "managed"})),
        Route("/readyz", ready),
        Route("/api/managed/plans", plans),
        Route("/api/contact", contact, methods=["POST"]),
        Route("/api/managed/signup", signup, methods=["POST"]),
        Route("/api/managed/verify", verify),
        Route("/api/managed/login", login, methods=["POST"]),
        Route("/api/managed/me", me),
        Route("/api/managed/logout", logout, methods=["POST"]),
        Route("/api/managed/keys", keys, methods=["GET", "POST"]),
        Route("/api/managed/keys/revoke", revoke_key, methods=["POST"]),
        Route("/api/managed/recovery/{action}", recovery, methods=["POST"]),
        Route("/api/managed/checkout", checkout, methods=["POST"]),
        Route("/api/managed/portal", portal, methods=["POST"]),
        Route("/api/managed/stripe/webhook", webhook, methods=["POST"]),
        Route("/api/managed/memories", memories, methods=["GET", "POST"]),
        Route("/api/managed/memories/{memory_id}", memories),
        Route("/api/managed/memories/{memory_id}/verify", memories),
        Route("/api/managed/export", export),
        Route("/api/managed/export-download", export_download),
    ]
    app = Starlette(routes=routes, middleware=[Middleware(ResponseHeaders)], exception_handlers={kind: error for kind in (ApiError, LimitExceeded, BillingUnavailable, PermissionError, ValueError, KeyError, Exception)})

    if viewer_dist:
        from starlette.responses import FileResponse
        # The API routes are registered first; unknown API URLs must not receive SPA HTML.
        async def spa(request):
            if request.url.path.startswith("/api/"):
                return JSONResponse({"error": "Unknown managed API route"}, status_code=404)
            return FileResponse(viewer_dist / "index.html")
        app.router.routes.append(Mount("/assets", app=StaticFiles(directory=viewer_dist / "assets"), name="assets"))
        for image in viewer_dist.glob("*.png"):
            async def asset(request, path=image):
                return FileResponse(path)
            app.router.routes.append(Route("/" + image.name, asset))
        app.router.routes.append(Route("/", lambda request: RedirectResponse("/managed")))
        app.router.routes.append(Route("/{path:path}", spa))
    app.state.control = service
    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8430)
    parser.add_argument("--viewer-dist", type=Path)
    args = parser.parse_args()
    # SQLite tenant volumes require one service replica with persistent storage. Multiple
    # workers or ephemeral/serverless filesystems are deliberately not enabled here.
    uvicorn.run(create_app(ManagedConfig.from_env(), viewer_dist=args.viewer_dist), host=args.host, port=args.port, workers=1, access_log=False, limit_concurrency=64, timeout_keep_alive=10)


if __name__ == "__main__":
    main()
