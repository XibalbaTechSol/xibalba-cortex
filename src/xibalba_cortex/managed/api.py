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
from ..device_pairing import create_pairing_request, get_pairing_request, approve_pairing_request, poll_pairing_status
from ..email_delivery import EmailDeliveryError
from ..ingest_tokens import issue_token, verify_token_record, _connect as identity_connection
from ..oauth import generate_pkce, sign_oauth_state, verify_oauth_state, get_oauth_provider, OAuthError
from .config import ManagedConfig
from .control import LimitExceeded, ManagedControl
from .ingest import ingest_turn
from .plans import PLANS
from .stripe_gateway import BillingUnavailable
from ..agent0_integration import Agent0Gateway, Agent0Unavailable

log = logging.getLogger(__name__)
COOKIE = "cortex_managed_session"
# UI destinations the hosted edition can serve; keep in step with the route table in create_app.
MANAGED_DESTINATIONS = ("graph", "timeline", "memories", "recall", "settings", "agents", "billing")


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
    agent0_gateway: Agent0Gateway | None = None

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

    def get_agent0() -> Agent0Gateway:
        nonlocal agent0_gateway
        if agent0_gateway is None:
            agent0_gateway = Agent0Gateway(config.agent0)
        return agent0_gateway

    def agent0_read_operation(request: Request, operation: str):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        service.consume(tenant, "retrievals")
        gateway = get_agent0()
        if operation == "search":
            query = str(request.query_params.get("q") or request.query_params.get("name") or "").strip()
            filters: dict[str, object] = {"name": query} if query else {}
            return {"agents": gateway.search_agents(filters=filters, options={"sort": ["updatedAt:desc"]}), "source": "agent0", "query": query}
        agent_id = str(request.path_params["agent_id"])
        if operation == "agent":
            return {"agent": gateway.agent(agent_id, full=request.query_params.get("full") == "true"), "source": "agent0"}
        return {"agent_id": agent_id, "reputation": gateway.reputation(agent_id), "source": "agent0"}

    async def agent0_search(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(agent0_read_operation, request, "search"))

    async def agent0_agent(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(agent0_read_operation, request, "agent"))

    async def agent0_reputation(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(agent0_read_operation, request, "reputation"))

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
        except EmailDeliveryError:
            log.warning("Managed account verification email delivery failed")
        except ValueError as exc:
            if "already exists" not in str(exc):
                raise
            # No account enumeration. A separate resend endpoint can use the same generic result.
        message = (
            "Check your email to verify your account before signing in."
            if config.require_email_verification
            else "Account created. You may now sign in."
        )
        return JSONResponse({"message": message}, status_code=202)

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
        response.set_cookie(COOKIE, token, max_age=accounts.SESSION_TTL_HOURS * 3600, httponly=True, secure=config.public_url.startswith("https:"), samesite="lax", path="/")
        return response

    async def me(request):
        rate_limit(request)
        account, _, token = await run_in_threadpool(owner, request)
        def read_state():
            tenant = service.tenant(account)
            with service.store(tenant) as store:
                counts = store.counts()
            return {"account": account, "entitlement": service.entitlement(tenant),
                "usage": service.usage(tenant), "counts": counts, "csrf_token": csrf(token),
                "destinations": list(MANAGED_DESTINATIONS)}
        return JSONResponse(await run_in_threadpool(read_state))

    async def logout(request):
        _, _, token = await run_in_threadpool(owner, request, mutate=True)
        await run_in_threadpool(accounts.revoke_account_session, service.identity_home, token)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/", secure=config.public_url.startswith("https:"), httponly=True, samesite="lax")
        return response

    def configured_oauth_providers() -> list[dict[str, str]]:
        providers = []
        if config.google_client_id and config.google_client_secret:
            providers.append({"id": "google", "name": "Google"})
        if config.github_client_id and config.github_client_secret:
            providers.append({"id": "github", "name": "GitHub"})
        return providers

    async def oauth_providers(request: Request):
        return JSONResponse({"providers": configured_oauth_providers()})

    async def oauth_authorize(request: Request):
        rate_limit(request, auth=True)
        provider_name = str(request.path_params.get("provider", "")).lower()
        client_id = ""
        client_secret = ""
        if provider_name == "google":
            client_id, client_secret = config.google_client_id, config.google_client_secret
        elif provider_name == "github":
            client_id, client_secret = config.github_client_id, config.github_client_secret
        else:
            raise ApiError(404, f"Unsupported OAuth provider: {provider_name}")

        if not client_id or not client_secret:
            raise ApiError(400, f"OAuth provider {provider_name} is not configured")

        verifier, challenge = generate_pkce()
        callback_uri = f"{config.public_url.rstrip('/')}/api/managed/oauth/{provider_name}/callback"
        signed_state = sign_oauth_state(csrf_secret, provider=provider_name, code_verifier=verifier, redirect_uri=callback_uri)

        try:
            provider = get_oauth_provider(provider_name, client_id, client_secret)
            auth_url = provider.authorization_url(state=signed_state, code_challenge=challenge, redirect_uri=callback_uri)
        except OAuthError as exc:
            raise ApiError(400, str(exc)) from exc

        return RedirectResponse(auth_url, status_code=303)

    async def oauth_callback(request: Request):
        rate_limit(request, auth=True)
        provider_name = str(request.path_params.get("provider", "")).lower()

        error_code = request.query_params.get("error")
        error_desc = request.query_params.get("error_description")
        if error_code:
            log.warning("OAuth provider %s returned error: %s (%s)", provider_name, error_code, error_desc)
            return RedirectResponse(f"/managed?error={error_desc or error_code}#signin", status_code=303)

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state:
            return RedirectResponse("/managed?error=missing_code_or_state#signin", status_code=303)

        try:
            verified = verify_oauth_state(csrf_secret, state, expected_provider=provider_name)
        except OAuthError as exc:
            log.warning("OAuth state verification failed: %s", exc)
            return RedirectResponse(f"/managed?error={exc}#signin", status_code=303)

        client_id = ""
        client_secret = ""
        if provider_name == "google":
            client_id, client_secret = config.google_client_id, config.google_client_secret
        elif provider_name == "github":
            client_id, client_secret = config.github_client_id, config.github_client_secret

        if not client_id or not client_secret:
            return RedirectResponse("/managed?error=provider_unconfigured#signin", status_code=303)

        callback_uri = verified.get("u") or f"{config.public_url.rstrip('/')}/api/managed/oauth/{provider_name}/callback"
        provider = get_oauth_provider(provider_name, client_id, client_secret)

        try:
            user_info = await run_in_threadpool(provider.exchange_code, code=code, code_verifier=verified.get("v", ""), redirect_uri=callback_uri)
        except OAuthError as exc:
            log.warning("OAuth token exchange failed: %s", exc)
            return RedirectResponse(f"/managed?error={exc}#signin", status_code=303)
        except Exception as exc:
            log.exception("Unexpected error during OAuth token exchange")
            return RedirectResponse("/managed?error=oauth_exchange_failed#signin", status_code=303)

        if not user_info.email_verified:
            return RedirectResponse("/managed?error=unverified_email#signin", status_code=303)

        try:
            token, account = await auth_work(service.oauth_login_or_register, user_info)
        except LimitExceeded as exc:
            return RedirectResponse(f"/managed?error={exc}#signin", status_code=303)
        except Exception as exc:
            log.exception("OAuth login or registration failed")
            return RedirectResponse("/managed?error=oauth_account_failed#signin", status_code=303)

        response = RedirectResponse("/managed", status_code=303)
        response.set_cookie(COOKIE, token, max_age=accounts.SESSION_TTL_HOURS * 3600, httponly=True, secure=config.public_url.startswith("https:"), samesite="lax", path="/")
        return response

    async def device_pair_request(request: Request):
        rate_limit(request, auth=True)
        data = await payload(request)
        device_id = str(data.get("device_id", "")).strip()
        agent_did = str(data.get("agent_did", "")).strip()
        if not device_id or not agent_did:
            raise ApiError(400, "device_id and agent_did are required")
        if not agent_did.startswith("did:integrity:") or len(agent_did) > 160:
            raise ApiError(400, "agent_did must be a valid did:integrity identifier")

        result = await run_in_threadpool(
            create_pairing_request,
            service.identity_home,
            device_id=device_id,
            device_name=str(data.get("device_name", "")).strip() or device_id,
            agent_did=agent_did,
            agent_name=str(data.get("agent_name", "")).strip() or "default",
            callback_url=str(data.get("callback_url", "")).strip() or None,
        )
        user_code = result["user_code"]
        verification_url = f"{config.public_url.rstrip('/')}/managed#pair?code={user_code}"
        return JSONResponse({
            "device_code": result["device_code"],
            "user_code": user_code,
            "verification_url": verification_url,
            "expires_in": result["expires_in"],
            "interval": result["interval"],
        }, status_code=201)

    async def device_pair_info(request: Request):
        rate_limit(request)
        code = str(request.path_params["code"]).strip()
        req = await run_in_threadpool(get_pairing_request, service.identity_home, code)
        if not req:
            raise ApiError(404, "Pairing request not found or expired")
        return JSONResponse({
            "code": req["user_code"],
            "device_id": req["device_id"],
            "device_name": req["device_name"],
            "agent_did": req["agent_did"],
            "agent_name": req["agent_name"],
            "status": req["status"],
            "expires_in": req["expires_in"],
            "callback_url": req["callback_url"],
        })

    async def device_pair_approve(request: Request):
        rate_limit(request)
        account, _, _ = await run_in_threadpool(owner, request, mutate=True)
        code = str(request.path_params["code"]).strip()
        try:
            result = await run_in_threadpool(
                approve_pairing_request,
                service.identity_home,
                code,
                account_id=account["id"],
                tenant_id=account["profile_id"],
                service_control=service,
            )
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc

        return JSONResponse({
            "ok": True,
            "token": result["token"],
            "callback_url": result["callback_url"],
            "device_id": result["device_id"],
            "agent_did": result["agent_did"],
        })

    async def device_pair_status(request: Request):
        rate_limit(request)
        code = str(request.path_params["code"]).strip()
        status = await run_in_threadpool(poll_pairing_status, service.identity_home, code)
        return JSONResponse(status)

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
            existing = db.execute("SELECT id,label,created_at,expires_at,revoked_at,agent_id,agent_ids_json FROM ingest_tokens WHERE profile_id=? AND label LIKE 'managed-api:%' AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 100", (account['profile_id'],)).fetchall()
        if request.method == 'GET':
            result = []
            for row in existing:
                item = dict(row)
                try:
                    item['agent_ids'] = sorted({str(value).strip() for value in json.loads(item.pop('agent_ids_json') or '[]') if str(value).strip()})
                except (TypeError, json.JSONDecodeError):
                    item['agent_ids'] = [item['agent_id']] if item.get('agent_id') else []
                result.append(item)
            return JSONResponse({'keys': result})
        with closing(identity_connection(service.identity_home)) as db:
            active_count = db.execute("SELECT COUNT(*) FROM ingest_tokens WHERE profile_id=? AND label LIKE 'managed-api:%' AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)", (account['profile_id'], datetime.now(timezone.utc).isoformat())).fetchone()[0]
        if active_count >= 100:
            raise ApiError(429, 'Revoke an unused API key before creating another')
        data = await payload(request)
        label = str(data.get("label", "")).strip()
        if not label or len(label) > 80:
            raise ApiError(400, "API key label must contain 1–80 characters")
        raw_agent_ids = data.get('agent_ids')
        if raw_agent_ids is None:
            raw_agent_ids = [data.get('agent_id', '')]
        if not isinstance(raw_agent_ids, list):
            raise ApiError(400, 'agent_ids must be an array of did:integrity identifiers')
        agent_ids = sorted({str(value).strip() for value in raw_agent_ids if str(value).strip()})
        if len(agent_ids) > 100:
            raise ApiError(400, 'agent_ids may contain at most 100 identities')
        if any(not value.startswith('did:integrity:') or len(value) > 160 for value in agent_ids):
            raise ApiError(400, 'agent_ids must contain valid did:integrity identifiers')
        # Managed keys may read and write their own tenant; they cannot manage billing, mint
        # other keys, administer accounts, or select another profile.
        token = await run_in_threadpool(issue_token, service.identity_home, "managed-api:" + label,
            profile_id=account["profile_id"], roles=("writer",), scopes=("memory:read", "memory:write"),
            ttl_hours=720, agent_ids=tuple(agent_ids))
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

    def ingest_operation(request, data):
        # authenticate() applies account state and, for cookie callers, Origin + CSRF; bearer keys carry neither.
        _, principal, token = authenticate(request, mutate=True)
        require_scope(principal, "memory:write")
        request_key = request.headers.get("idempotency-key", "")
        if not 8 <= len(request_key) <= 128:
            raise ApiError(400, "Supply an Idempotency-Key containing 8–128 characters")
        return ingest_turn(service, token, data, request_key=request_key)

    async def ingest(request):
        rate_limit(request)
        data = await payload(request)
        return JSONResponse(await run_in_threadpool(ingest_operation, request, data))

    def import_operation(request, data):
        account, principal, _ = authenticate(request, mutate=True)
        require_scope(principal, "memory:write")
        request_key = request.headers.get("idempotency-key", "")
        if not 8 <= len(request_key) <= 128:
            raise ApiError(400, "Supply an Idempotency-Key containing 8–128 characters")
        fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        tenant = service.tenant(account)
        with service.write_guard(tenant):
            service.consume(tenant, "writes", request_key=request_key, fingerprint=fingerprint)
            with service.store(tenant) as store:
                try:
                    inserted = store.import_structured_bundle(data)
                except ValueError as exc:
                    raise ApiError(400, str(exc)) from exc
                except RuntimeError as exc:
                    if str(exc).startswith("memory quota exceeded:"):
                        raise LimitExceeded("Stored-memory capacity reached; choose a larger plan") from None
                    raise
        return {"schema_version": "xibalba.managed_import.v1", "inserted": inserted}

    async def structured_import(request):
        rate_limit(request)
        data = await payload(request)
        return JSONResponse(await run_in_threadpool(import_operation, request, data), status_code=201)

    def graph_operation(request, *, timeline=False):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        service.consume(tenant, "retrievals")
        try:
            limit = max(1, min(int(request.query_params.get("limit", "500")), 1000))
        except ValueError:
            raise ApiError(400, "limit must be an integer") from None
        with service.store(tenant) as store:
            graph = store.graph_payload(limit=limit, similarity_threshold=0.75)
            if timeline:
                return {"sessions": store.list_sessions(limit=limit), "nodes": graph["nodes"]}
            return graph

    async def graph(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(graph_operation, request))

    async def timeline(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(graph_operation, request, timeline=True))

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
        if isinstance(exc, Agent0Unavailable):
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
        Route("/api/managed/oauth/providers", oauth_providers, methods=["GET"]),
        Route("/api/managed/oauth/{provider}/authorize", oauth_authorize, methods=["GET"]),
        Route("/api/managed/oauth/{provider}/callback", oauth_callback, methods=["GET"]),
        Route("/api/auth/oauth/providers", oauth_providers, methods=["GET"]),
        Route("/api/auth/oauth/{provider}/authorize", oauth_authorize, methods=["GET"]),
        Route("/api/auth/oauth/{provider}/callback", oauth_callback, methods=["GET"]),
        Route("/api/managed/device/pair/request", device_pair_request, methods=["POST"]),
        Route("/api/managed/device/pair/{code}", device_pair_info, methods=["GET"]),
        Route("/api/managed/device/pair/{code}/approve", device_pair_approve, methods=["POST"]),
        Route("/api/managed/device/pair/{code}/status", device_pair_status, methods=["GET"]),
        Route("/api/auth/device/pair/request", device_pair_request, methods=["POST"]),
        Route("/api/auth/device/pair/{code}", device_pair_info, methods=["GET"]),
        Route("/api/auth/device/pair/{code}/approve", device_pair_approve, methods=["POST"]),
        Route("/api/auth/device/pair/{code}/status", device_pair_status, methods=["GET"]),
        Route("/api/managed/me", me),
        Route("/api/managed/logout", logout, methods=["POST"]),
        Route("/api/managed/keys", keys, methods=["GET", "POST"]),
        Route("/api/managed/keys/revoke", revoke_key, methods=["POST"]),
        Route("/api/managed/recovery/{action}", recovery, methods=["POST"]),
        Route("/api/managed/checkout", checkout, methods=["POST"]),
        Route("/api/managed/portal", portal, methods=["POST"]),
        Route("/api/managed/stripe/webhook", webhook, methods=["POST"]),
        Route("/api/managed/memories", memories, methods=["GET", "POST"]),
        Route("/api/managed/import", structured_import, methods=["POST"]),
        Route("/api/managed/ingest", ingest, methods=["POST"]),
        Route("/api/managed/graph", graph, methods=["GET"]),
        Route("/api/managed/timeline", timeline, methods=["GET"]),
        Route("/api/managed/agent0/search", agent0_search, methods=["GET"]),
        Route("/api/managed/agent0/agent/{agent_id}", agent0_agent, methods=["GET"]),
        Route("/api/managed/agent0/reputation/{agent_id}", agent0_reputation, methods=["GET"]),
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
