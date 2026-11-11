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
from .supabase_auth import SupabaseAuthVerifier
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
    auth_verifier = (SupabaseAuthVerifier(config.supabase_url, audience=config.supabase_jwt_audience)
                     if config.identity_backend == "supabase_auth" else None)

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
        if auth_verifier is not None and cookie_auth:
            try:
                claims = auth_verifier.verify(token)
                account = service.account_for_auth_subject(claims["sub"])
            except Exception:
                log.info("Supabase Auth access token rejected")
                account = None
            if account is None:
                raise ApiError(401, "Sign in to your managed workspace")
            principal = {"label": "account:" + account["id"], "profile_id": account["profile_id"],
                         "scopes": ["memory:read", "memory:write"], "auth_subject": claims["sub"]}
        else:
            service.sync_identity_from_supabase()
            principal = verify_token_record(service.identity_home, token) if token else None
        if principal is None:
            raise ApiError(401, "Sign in to your managed workspace")
        if auth_verifier is not None and not cookie_auth and str(principal["label"]).startswith("account:"):
            raise ApiError(401, "Use Supabase Auth to sign in to your managed workspace")
        if auth_verifier is None or not cookie_auth:
            account = accounts.account_for_token(service.identity_home, token)
        if account is None:
            # API keys are looked up through their profile, never through an email supplied by
            # the caller. Their scopes are enforced separately for each memory operation.
            with service.db() as db:
                tenant = db.execute("SELECT owner_account_id FROM tenants WHERE id=?", (principal["profile_id"],)).fetchone()
            if tenant is None:
                raise ApiError(403, "Unknown managed workspace")
            account = service.account_for_owner_id(tenant["owner_account_id"])
            if account is None:
                raise ApiError(403, 'Workspace owner is unavailable')
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
        database_ready = None
        if service.config.storage_backend == "supabase":
            def probe_managed_database():
                with service.db() as db:
                    db.execute("SELECT 1").fetchone()
            try:
                await run_in_threadpool(probe_managed_database)
                database_ready = True
            except Exception:
                database_ready = False
                log.warning("Managed readiness database probe failed")
        result = service.config.pilot_readiness(managed_database_ready=database_ready)
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
        if auth_verifier is not None:
            raise ApiError(410, "Use Supabase Auth sign-in and submit its access token as the managed session")
        token, account = await auth_work(accounts.issue_account_session, service.identity_home,
            email=str(data.get("email", "")), password=str(data.get("password", "")))
        service.tenant(account)
        response = JSONResponse({"account": account, "csrf_token": csrf(token)})
        response.set_cookie(COOKIE, token, max_age=accounts.SESSION_TTL_HOURS * 3600, httponly=True, secure=config.public_url.startswith("https:"), samesite="lax", path="/")
        return response

    async def supabase_session(request):
        rate_limit(request, auth=True)
        origin_guard(request)
        if auth_verifier is None:
            raise ApiError(404, "Supabase Auth session exchange is disabled")
        data = await payload(request)
        token = str(data.get("access_token", ""))
        try:
            claims = auth_verifier.verify(token)
        except Exception:
            raise ApiError(401, "Supabase access token is invalid") from None
        account = service.account_for_auth_subject(claims["sub"])
        if account is None and config.allow_signup:
            try:
                account = await run_in_threadpool(service.provision_auth_subject, claims["sub"])
            except LimitExceeded as exc:
                raise ApiError(429, str(exc)) from None
            except PermissionError as exc:
                raise ApiError(403, str(exc)) from None
        if account is None:
            raise ApiError(403, "Supabase identity is not linked to a managed workspace")
        response = JSONResponse({"account": account, "csrf_token": csrf(token)})
        response.set_cookie(COOKIE, token, max_age=max(0, int(claims["exp"]) - int(time.time())),
                            httponly=True, secure=config.public_url.startswith("https:"), samesite="lax", path="/")
        return response

    def get_tenant_workspaces(tenant, account, limit=100):
        with service.store(tenant) as store:
            workspaces = store.agent_workspaces(limit=limit)
            conn = store._read_connection()
            agent_stats = {
                str(r["agent_id"]): {
                    "memories": int(r["memories"] or 0),
                    "sessions": int(r["sessions"] or 0),
                    "last_seen_at": r["last_seen_at"],
                }
                for r in conn.execute(
                    """SELECT sources.agent_id AS agent_id,
                              COUNT(DISTINCT memories.id) AS memories,
                              COUNT(DISTINCT sources.session_id) AS sessions,
                              MAX(memories.created_at) AS last_seen_at
                       FROM memories JOIN sources ON sources.id = memories.source_id
                       WHERE sources.agent_id IS NOT NULL
                       GROUP BY sources.agent_id"""
                ).fetchall()
            }
            for w in workspaces:
                w["store_id"] = tenant["id"]
                w["profile_id"] = tenant["id"]
                w["store_access"] = "writable"
                w["writable"] = True
                w["memories_counted"] = True
                stats = agent_stats.get(str(w.get("agent_id") or ""))
                if stats is not None:
                    w["memories"] = max(int(w.get("memories") or 0), stats["memories"])
                    w["sessions"] = max(int(w.get("sessions") or 0), stats["sessions"])
                    w["sessions_counted"] = True
                    if not w.get("last_seen_at"):
                        w["last_seen_at"] = stats["last_seen_at"]

            service.sync_identity_from_supabase()
            with closing(identity_connection(service.identity_home)) as db:
                token_rows = db.execute(
                    "SELECT label, agent_id, agent_ids_json FROM ingest_tokens WHERE profile_id=? AND label LIKE 'managed-api:%' AND revoked_at IS NULL",
                    (account["profile_id"],),
                ).fetchall()

            matched_dids = set()
            for tr in token_rows:
                raw_label = str(tr["label"]).replace("managed-api:", "")
                agent_name = raw_label.split("@")[0] if "@" in raw_label else raw_label
                agent_ids = []
                if tr["agent_ids_json"]:
                    try:
                        agent_ids = json.loads(tr["agent_ids_json"])
                    except Exception:
                        pass
                if not agent_ids and tr["agent_id"]:
                    agent_ids = [tr["agent_id"]]

                for did in agent_ids:
                    did_str = str(did).strip()
                    if not did_str:
                        continue
                    persisted = store.storage_agent_id(did_str) or did_str
                    found = False
                    for w in workspaces:
                        if w.get("agent_id") in (did_str, persisted):
                            w["agent_id"] = did_str
                            w["agent_name"] = agent_name
                            found = True
                            matched_dids.add(did_str)
                            break
                    if not found and did_str not in matched_dids:
                        matched_dids.add(did_str)
                        stats = agent_stats.get(did_str) or agent_stats.get(persisted) or {}
                        workspaces.append({
                            "agent_id": did_str,
                            "store_id": tenant["id"],
                            "profile_id": tenant["id"],
                            "agent_name": agent_name,
                            "store_access": "writable",
                            "writable": True,
                            "memories": int(stats.get("memories") or 0),
                            "memories_counted": True,
                            "sessions": int(stats.get("sessions") or 0),
                            "sessions_counted": True,
                            "last_seen_at": stats.get("last_seen_at"),
                        })
            return workspaces

    async def me(request):
        rate_limit(request)
        account, _, token = await run_in_threadpool(owner, request)
        def read_state():
            tenant = service.tenant(account)
            with service.store(tenant) as store:
                counts = store.counts()
            return {"account": account, "entitlement": service.entitlement(tenant),
                "usage": service.usage(tenant), "counts": counts, "csrf_token": csrf(token),
                "destinations": list(MANAGED_DESTINATIONS),
                "agents": get_tenant_workspaces(tenant, account)}
        return JSONResponse(await run_in_threadpool(read_state))

    async def logout(request):
        _, _, token = await run_in_threadpool(owner, request, mutate=True)
        if auth_verifier is None:
            await run_in_threadpool(accounts.revoke_account_session, service.identity_home, token)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/", secure=config.public_url.startswith("https:"), httponly=True, samesite="lax")
        return response

    def configured_oauth_providers() -> list[dict[str, str]]:
        providers = []
        if config.identity_backend == "supabase_auth" and config.supabase_url:
            providers.append({"id": "google", "name": "Google"})
            providers.append({"id": "github", "name": "GitHub"})
            return providers
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
        if provider_name not in {"google", "github"}:
            raise ApiError(404, f"Unsupported OAuth provider: {provider_name}")

        if config.identity_backend == "supabase_auth" and config.supabase_url:
            redirect_to = str(request.query_params.get("redirect_to") or f"{config.public_url.rstrip('/')}/managed")
            auth_url = f"{config.supabase_url.rstrip('/')}/auth/v1/authorize?provider={provider_name}&redirect_to={redirect_to}"
            return RedirectResponse(auth_url, status_code=303)

        client_id = ""
        client_secret = ""
        if provider_name == "google":
            client_id, client_secret = config.google_client_id, config.google_client_secret
        elif provider_name == "github":
            client_id, client_secret = config.github_client_id, config.github_client_secret

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
            await run_in_threadpool(service.checkpoint_identity_to_supabase, trigger="device_pair_approve")
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
        service.sync_identity_from_supabase()
        with closing(identity_connection(service.identity_home)) as db:
            changed = db.execute("UPDATE ingest_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE id=? AND profile_id=? AND label LIKE 'managed-api:%' AND revoked_at IS NULL", (str(data.get('id', '')), account['profile_id'])).rowcount
            db.commit()
        if changed:
            await run_in_threadpool(service.checkpoint_identity_to_supabase, trigger="revoke_key")
        return JSONResponse({'revoked': bool(changed)})

    async def keys(request):
        rate_limit(request)
        account, _, _ = await run_in_threadpool(owner, request, mutate=request.method == 'POST')
        service.sync_identity_from_supabase()
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
        await run_in_threadpool(service.checkpoint_identity_to_supabase, trigger="issue_key")
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
            incoming_source = data.get("source") if isinstance(data.get("source"), dict) else {}
            authorized_agents = principal.get("agent_ids") or ()
            agent_id = incoming_source.get("agent_id") or (authorized_agents[0] if authorized_agents else principal["id"])
            source_payload = {
                "kind": incoming_source.get("kind", "agent_mcp" if authorized_agents else "direct_user"),
                "agent_id": agent_id,
                **{k: v for k, v in incoming_source.items() if k not in ("kind", "agent_id")},
            }
            with service.write_guard(tenant):
                service.consume(tenant, "writes", request_key=request_key, fingerprint=fingerprint)
                with service.store(tenant) as store:
                    try:
                        return store.store_memory(content, source=source_payload,
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
            agent_id = request.query_params.get("agent_id", "").strip() or None
            if agent_id in ("demo-healthcare-researcher", "did:integrity:healthcare-researcher-latent-space-01", "healthcare-researcher-latent-space-01"):
                agent_id = "demo-healthcare-researcher"
            elif agent_id in (tenant["id"], account.get("profile_id")):
                agent_id = None
            elif agent_id:
                if not store.has_agent_partition(agent_id):
                    resolved = store.storage_agent_id(agent_id)
                    if resolved:
                        agent_id = resolved
            try:
                limit = max(1, min(int(request.query_params.get("limit", "50")), 200))
            except ValueError:
                limit = 50
            try:
                offset = max(0, int(request.query_params.get("offset", "0")))
            except ValueError:
                offset = 0
            statuses_raw = request.query_params.get("status") or request.query_params.get("statuses")
            statuses = tuple(s.strip() for s in statuses_raw.split(",") if s.strip()) if statuses_raw else ("active", "confirmed")
            if query:
                rows = store.search(query, limit=limit, agent_id=agent_id, statuses=statuses)
                return {"memories": rows, "has_more": False, "offset": 0, "limit": len(rows)}
            rows = store.list_memories(limit=limit, offset=offset, statuses=statuses, agent_id=agent_id)
            return {"memories": rows, "has_more": len(rows) == limit, "offset": offset, "limit": limit}

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
                    if isinstance(data, dict) and (data.get("bundle_schema") == "xibalba.structured_memory_bundle.v1" or data.get("schema_version") == "xibalba.structured_memory_bundle.v1"):
                        inserted = store.import_structured_bundle(data)
                        return {"schema_version": "xibalba.managed_import.v1", "inserted": inserted}
                    elif isinstance(data, dict) and ("content" in data or "document" in data or data.get("format") == "markdown"):
                        from ..console_actions import import_document
                        text = str(data.get("content") or data.get("document") or "")
                        title = str(data.get("title") or "imported_document.md")
                        res = import_document(store, filename=title, data=text.encode("utf-8"))
                        return {"schema_version": "xibalba.managed_import.v1", "inserted": res}
                    else:
                        inserted = store.import_structured_bundle(data)
                        return {"schema_version": "xibalba.managed_import.v1", "inserted": inserted}
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
        agent_id = request.query_params.get("agent_id", "").strip() or None
        if agent_id in ("demo-healthcare-researcher", "did:integrity:healthcare-researcher-latent-space-01", "healthcare-researcher-latent-space-01"):
            agent_id = "demo-healthcare-researcher"
        elif agent_id in (tenant["id"], account.get("profile_id")):
            agent_id = None
        with service.store(tenant) as store:
            if agent_id and not store.has_agent_partition(agent_id):
                resolved = store.storage_agent_id(agent_id)
                if resolved:
                    agent_id = resolved
            if agent_id == "demo-healthcare-researcher" and not store.has_agent_partition(agent_id):
                try:
                    store.seed_sample_knowledge_graph(force=True, dataset="healthcare_researcher", agent_id="demo-healthcare-researcher")
                except Exception:
                    pass
            graph = store.graph_payload(limit=limit, similarity_threshold=0.75, agent_id=agent_id)
            if timeline:
                return {"sessions": store.list_sessions(limit=limit, agent_id=agent_id), "nodes": graph["nodes"]}
            return graph

    async def graph(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(graph_operation, request))

    async def timeline(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(graph_operation, request, timeline=True))

    def graph_math_operation(request, custom_body=None):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        service.consume(tenant, "retrievals")
        try:
            limit = max(1, min(int(request.query_params.get("limit", "100")), 500))
            threshold = float(request.query_params.get("similarity_threshold", "0.6"))
        except ValueError:
            raise ApiError(400, "limit and similarity_threshold must be numbers") from None
        agent_id = request.query_params.get("agent_id", "").strip() or None
        if agent_id in ("demo-healthcare-researcher", "did:integrity:healthcare-researcher-latent-space-01", "healthcare-researcher-latent-space-01"):
            agent_id = "demo-healthcare-researcher"
        if custom_body and isinstance(custom_body, dict):
            nodes = custom_body.get("nodes")
            edges = custom_body.get("edges")
            if nodes is not None and edges is not None:
                from ..graph_math import compute_formal_graph_math
                return compute_formal_graph_math(nodes, edges, max_nodes=limit)
        with service.store(tenant) as store:
            return store.compute_graph_mathematics(limit=limit, similarity_threshold=threshold, agent_id=agent_id)

    async def graph_math_get(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(graph_math_operation, request))

    async def graph_math_post(request):
        rate_limit(request)
        try:
            payload = await request.json()
        except Exception:
            payload = None
        return JSONResponse(await run_in_threadpool(graph_math_operation, request, payload))

    def seed_sample_operation(request, payload):
        account, principal, _ = owner(request, mutate=True)
        tenant = service.tenant(account)
        force = bool(payload.get("force", False))
        dataset = str(payload.get("dataset", "healthcare_researcher"))
        agent_id = payload.get("agent_id")
        with service.store(tenant) as store:
            return store.seed_sample_knowledge_graph(force=force, dataset=dataset, agent_id=agent_id)

    async def seed_sample(request):
        rate_limit(request)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return JSONResponse(await run_in_threadpool(seed_sample_operation, request, payload))

    def connectors_triples_operation(request, payload):
        account, principal, _ = authenticate(request, mutate=True)
        require_scope(principal, "memory:write")
        tenant = service.tenant(account)
        triples = payload.get("triples")
        if not isinstance(triples, list):
            raise ApiError(400, "triples must be a list")
        source_name = str(payload.get("source_name", "managed_triples_ingest"))
        with service.store(tenant) as store:
            return store.ingest_triples(triples, source_name=source_name)

    async def connectors_triples(request):
        rate_limit(request)
        payload = await request.json()
        return JSONResponse(await run_in_threadpool(connectors_triples_operation, request, payload))

    def connectors_biomedical_operation(request, payload):
        account, principal, _ = authenticate(request, mutate=True)
        require_scope(principal, "memory:write")
        tenant = service.tenant(account)
        title = str(payload.get("title", ""))
        abstract = str(payload.get("abstract", ""))
        pmid = str(payload.get("pmid", ""))
        with service.store(tenant) as store:
            return store.ingest_biomedical_article(title=title, abstract=abstract, pmid=pmid)

    async def connectors_biomedical(request):
        rate_limit(request)
        payload = await request.json()
        return JSONResponse(await run_in_threadpool(connectors_biomedical_operation, request, payload))

    def connectors_fhir_operation(request, payload):
        account, principal, _ = authenticate(request, mutate=True)
        require_scope(principal, "memory:write")
        tenant = service.tenant(account)
        bundle = payload.get("bundle") or payload
        if not isinstance(bundle, dict):
            raise ApiError(400, "FHIR bundle must be an object")
        with service.store(tenant) as store:
            return store.ingest_fhir_bundle(bundle)

    async def connectors_fhir(request):
        rate_limit(request)
        payload = await request.json()
        return JSONResponse(await run_in_threadpool(connectors_fhir_operation, request, payload))

    def connectors_csv_operation(request, payload):
        account, principal, _ = authenticate(request, mutate=True)
        require_scope(principal, "memory:write")
        tenant = service.tenant(account)
        csv_text = str(payload.get("csv_text", ""))
        delimiter = str(payload.get("delimiter", ","))
        has_header = bool(payload.get("has_header", True))
        source_name = str(payload.get("source_name", "managed_csv_ingest"))
        from ..connectors.triples import TriplesConnector
        with service.store(tenant) as store:
            conn = TriplesConnector(store)
            res = conn.ingest_csv(csv_text, delimiter=delimiter, has_header=has_header, source_name=source_name)
            return {"success": True, "entities_created": res.entities_created, "relations_created": res.relations_created}

    async def connectors_csv(request):
        rate_limit(request)
        payload = await request.json()
        return JSONResponse(await run_in_threadpool(connectors_csv_operation, request, payload))

    def discovery_mechanisms_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        src = str(request.query_params.get("source", "")).strip()
        tgt = str(request.query_params.get("target", "")).strip()
        try:
            depth = max(1, min(int(request.query_params.get("max_depth", "4")), 6))
        except ValueError:
            depth = 4
        with service.store(tenant) as store:
            return store.trace_mechanisms(src, tgt, max_depth=depth)

    async def discovery_mechanisms(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(discovery_mechanisms_operation, request))

    def discovery_predict_links_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        src = str(request.query_params.get("source", "")).strip()
        tgt = str(request.query_params.get("target", "")).strip()
        rel = str(request.query_params.get("relation", "relates_to")).strip()
        with service.store(tenant) as store:
            return store.predict_links(src, tgt, relation=rel)

    async def discovery_predict_links(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(discovery_predict_links_operation, request))

    def discovery_repurposing_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        disease = str(request.query_params.get("disease", "")).strip()
        try:
            top_k = max(1, min(int(request.query_params.get("top_k", "5")), 20))
        except ValueError:
            top_k = 5
        with service.store(tenant) as store:
            return store.suggest_drug_repurposing(disease, top_k=top_k)

    async def discovery_repurposing(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(discovery_repurposing_operation, request))

    def discovery_ego_subgraph_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        entity = str(request.query_params.get("entity", "")).strip()
        try:
            radius = max(1, min(int(request.query_params.get("radius", "2")), 4))
        except ValueError:
            radius = 2
        with service.store(tenant) as store:
            return store.ego_subgraph(entity, radius=radius)

    async def discovery_ego_subgraph(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(discovery_ego_subgraph_operation, request))

    def discovery_reward_step_operation(request, payload):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        with service.store(tenant) as store:
            return store.evaluate_step_reward(
                source=str(payload.get("source", "")),
                relation=str(payload.get("relation", "")),
                target=str(payload.get("target", "")),
                task_reward=float(payload.get("task_reward", 1.0)),
                cost=float(payload.get("cost", 0.0)),
                bonded_stake=float(payload.get("bonded_stake", 100.0)),
            )

    async def discovery_reward_step(request):
        rate_limit(request)
        payload = await request.json()
        return JSONResponse(await run_in_threadpool(discovery_reward_step_operation, request, payload))

    def discovery_reward_trajectory_operation(request, payload):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        steps = payload.get("steps")
        if not isinstance(steps, list):
            raise ApiError(400, "steps must be a list")
        discount = float(payload.get("discount_factor", 0.99))
        stake = float(payload.get("initial_stake", 100.0))
        with service.store(tenant) as store:
            return store.evaluate_trajectory_reward(steps, discount_factor=discount, initial_stake=stake)

    async def discovery_reward_trajectory(request):
        rate_limit(request)
        payload = await request.json()
        return JSONResponse(await run_in_threadpool(discovery_reward_trajectory_operation, request, payload))

    def ais_closed_loop_reward_evaluate_operation(request, payload):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        from ..ais_trajectory_reward import (
            DEFAULT_REWARD_PROFILE,
            REWARD_PROFILES,
            TrajectoryStepInput,
            build_dpo_preference_pair,
            compute_grpo_advantages,
            evaluate_trajectory_rewards,
        )

        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ApiError(400, "steps must be a non-empty list")
        reward_profile = payload.get("reward_profile", DEFAULT_REWARD_PROFILE)
        if not isinstance(reward_profile, str) or reward_profile not in REWARD_PROFILES:
            raise ApiError(400, "reward_profile must be one of: " + ", ".join(REWARD_PROFILES))
        agent_did = str(payload.get("agent_did") or principal["profile_id"])

        def _parse_steps(step_list: list[dict]) -> list[TrajectoryStepInput]:
            return [
                TrajectoryStepInput(
                    event_id=str(s.get("event_id", f"evt_{idx}")),
                    receipt_hash=str(s.get("receipt_hash", "sha256:oracle_receipt")),
                    r_task=float(s.get("r_task", 1.0)),
                    ais_score_1000=float(s.get("ais_score_1000", 1000.0)),
                    s_compliance=float(s.get("s_compliance", 1000.0)),
                    policy_denied=bool(s.get("policy_denied", False)),
                    cost_usd=float(s.get("cost_usd", 0.0)),
                )
                for idx, s in enumerate(step_list)
            ]

        primary = evaluate_trajectory_rewards(
            session_id=str(payload.get("session_id", "session_primary")),
            agent_did=agent_did,
            steps=_parse_steps(raw_steps),
            initial_ais_1000=float(payload.get("initial_ais_1000", 1000.0)),
            lambda_ais=float(payload.get("lambda_ais", 0.50)),
            gamma=float(payload.get("gamma", 0.99)),
            shaping_weight=float(payload.get("shaping_weight", 0.25)),
            lambda_cost=float(payload.get("lambda_cost", 0.10)),
            deny_penalty=float(payload.get("deny_penalty", 1.0)),
            reward_profile=reward_profile,
        )
        result = {"reward_profile": reward_profile, "trajectory": primary.to_dict()}

        alt_steps = payload.get("comparison_steps")
        if isinstance(alt_steps, list) and alt_steps:
            secondary = evaluate_trajectory_rewards(
                session_id=str(payload.get("comparison_session_id", "session_comparison")),
                agent_did=agent_did,
                steps=_parse_steps(alt_steps),
                initial_ais_1000=float(payload.get("initial_ais_1000", 1000.0)),
                reward_profile=reward_profile,
            )
            result["grpo_advantages"] = compute_grpo_advantages([primary, secondary])
            result["dpo_preference_pair"] = build_dpo_preference_pair(primary, secondary)
        return result

    async def ais_closed_loop_reward_evaluate(request):
        rate_limit(request)
        payload = await request.json()
        return JSONResponse(await run_in_threadpool(ais_closed_loop_reward_evaluate_operation, request, payload))

    def session_summarize_subagent_operation(request, payload):
        account, principal, _ = authenticate(request, mutate=True)
        require_scope(principal, "memory:write")
        tenant = service.tenant(account)
        sess_id = str(payload.get("session_id")) if payload.get("session_id") else None
        auto_ingest = bool(payload.get("auto_ingest_triples", True))
        with service.store(tenant) as store:
            return store.summarize_session_with_inference_subagent(external_session_id=sess_id, auto_ingest_triples=auto_ingest)

    async def session_summarize_subagent(request):
        rate_limit(request)
        payload = await request.json()
        return JSONResponse(await run_in_threadpool(session_summarize_subagent_operation, request, payload))

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

    def memory_similar_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        memory_id = request.path_params["memory_id"]
        try:
            limit = max(1, min(int(request.query_params.get("limit", "10")), 100))
        except ValueError:
            limit = 10
        with service.store(tenant) as store:
            store.get_memory(memory_id)
            try:
                return store.similar_memories(memory_id, limit=limit)
            except Exception:
                return []

    async def memory_similar(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(memory_similar_operation, request))

    def memory_neighbors_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        memory_id = request.path_params["memory_id"]
        with service.store(tenant) as store:
            store.get_memory(memory_id)
            return store.memory_entity_relations(memory_id)

    async def memory_neighbors(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(memory_neighbors_operation, request))

    def memory_events_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        memory_id = request.path_params["memory_id"]
        with service.store(tenant) as store:
            store.get_memory(memory_id)
            return store.memory_events(memory_id)

    async def memory_events(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(memory_events_operation, request))

    def memory_otel_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        memory_id = request.path_params["memory_id"]
        with service.store(tenant) as store:
            store.get_memory(memory_id)
            return store.memory_otel_events(memory_id)

    async def memory_otel(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(memory_otel_operation, request))

    def memory_attachments_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        memory_id = request.path_params["memory_id"]
        with service.store(tenant) as store:
            store.get_memory(memory_id)
            return [{k: v for k, v in item.items() if k != "storage_locator"} for item in store.list_attachments(memory_id)]

    async def memory_attachments(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(memory_attachments_operation, request))

    def attachment_file_operation(request):
        from starlette.responses import FileResponse
        import os
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        attachment_id = request.path_params["attachment_id"]
        with service.store(tenant) as store:
            attachment = store.get_attachment(attachment_id)
            if not attachment:
                raise ApiError(404, "Attachment not found")
            locator = attachment.get("storage_locator", "")
            file_path = locator[7:] if locator.startswith("file://") else locator
            if not os.path.exists(file_path):
                raise ApiError(404, "Attachment file not found on disk")
            return FileResponse(file_path, media_type=attachment.get("media_type") or "application/octet-stream")

    async def attachment_file(request):
        rate_limit(request)
        return await run_in_threadpool(attachment_file_operation, request)

    def memory_contradictions_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        memory_id = request.path_params["memory_id"]
        with service.store(tenant) as store:
            store.get_memory(memory_id)
            return store.contradictions(memory_id)

    async def memory_contradictions(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(memory_contradictions_operation, request))

    def entity_neighbors_operation(request):
        from urllib.parse import unquote
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        name = unquote(request.path_params["name"])
        try:
            max_depth = max(1, min(int(request.query_params.get("max_depth", "1")), 5))
        except ValueError:
            max_depth = 1
        agent_id = request.query_params.get("agent_id")
        if agent_id in ("demo-healthcare-researcher", "did:integrity:healthcare-researcher-latent-space-01", "healthcare-researcher-latent-space-01"):
            agent_id = "demo-healthcare-researcher"
        with service.store(tenant) as store:
            return store.neighbors(name, max_depth=max_depth, agent_id=agent_id)

    async def entity_neighbors(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(entity_neighbors_operation, request))

    def entity_path_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        from_name = request.query_params.get("from", "")
        to_name = request.query_params.get("to", "")
        try:
            max_depth = max(1, min(int(request.query_params.get("max_depth", "4")), 10))
        except ValueError:
            max_depth = 4
        agent_id = request.query_params.get("agent_id")
        if agent_id in ("demo-healthcare-researcher", "did:integrity:healthcare-researcher-latent-space-01", "healthcare-researcher-latent-space-01"):
            agent_id = "demo-healthcare-researcher"
        with service.store(tenant) as store:
            return store.find_path(from_name, to_name, max_depth=max_depth, agent_id=agent_id)

    async def entity_path(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(entity_path_operation, request))

    def session_merkle_root_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        session_id = request.path_params["session_id"]
        with service.store(tenant) as store:
            return store.session_merkle_root(session_id)

    async def session_merkle_root_route(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(session_merkle_root_operation, request))

    def session_replay_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        session_id = request.path_params["session_id"]
        with service.store(tenant) as store:
            return store.session_replay(session_id)

    async def session_replay(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(session_replay_operation, request))

    def session_otel_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        session_id = request.path_params["session_id"]
        with service.store(tenant) as store:
            return store.session_otel_events(session_id)

    async def session_otel(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(session_otel_operation, request))

    def session_memories_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        session_id = request.path_params["session_id"]
        with service.store(tenant) as store:
            return store.session_memories(session_id)

    async def session_memories(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(session_memories_operation, request))

    def store_status_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        with service.store(tenant) as store:
            return store.status(fast=True)

    async def store_status(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(store_status_operation, request))

    def store_stats_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        with service.store(tenant) as store:
            return store.counts()

    async def store_stats(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(store_stats_operation, request))

    def integrity_links_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        try:
            limit = max(1, min(int(request.query_params.get("limit", "50")), 500))
        except ValueError:
            limit = 50
        with service.store(tenant) as store:
            return store.integrity_links_status(limit=limit)

    async def integrity_links_route(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(integrity_links_operation, request))

    def agent_devices_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        try:
            limit = max(1, min(int(request.query_params.get("limit", "500")), 1000))
        except ValueError:
            limit = 500
        with service.store(tenant) as store:
            return {"pairs": store.list_agent_devices(limit=limit)}

    async def agent_devices_route(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(agent_devices_operation, request))

    def agents_operation(request):
        account, principal, _ = authenticate(request)
        require_scope(principal, "memory:read")
        tenant = service.tenant(account)
        try:
            limit = max(1, min(int(request.query_params.get("limit", "100")), 500))
        except ValueError:
            limit = 100
        workspaces = get_tenant_workspaces(tenant, account, limit=limit)
        return {
            "agents": workspaces,
            "oracle_reachable": True,
            "primary_profile_id": tenant["id"],
        }

    async def agents_list(request):
        rate_limit(request)
        return JSONResponse(await run_in_threadpool(agents_operation, request))

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
        Route("/api/managed/auth/session", supabase_session, methods=["POST"]),
        Route("/api/auth/supabase/session", supabase_session, methods=["POST"]),
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
        Route("/api/managed/graph/math", graph_math_get, methods=["GET"]),
        Route("/api/managed/graph/math", graph_math_post, methods=["POST"]),
        Route("/api/managed/graph/seed-sample", seed_sample, methods=["POST"]),
        Route("/api/managed/connectors/triples", connectors_triples, methods=["POST"]),
        Route("/api/managed/connectors/biomedical", connectors_biomedical, methods=["POST"]),
        Route("/api/managed/connectors/fhir", connectors_fhir, methods=["POST"]),
        Route("/api/managed/connectors/csv", connectors_csv, methods=["POST"]),
        Route("/api/managed/discovery/mechanisms", discovery_mechanisms, methods=["GET"]),
        Route("/api/managed/discovery/predict-links", discovery_predict_links, methods=["GET"]),
        Route("/api/managed/discovery/repurposing", discovery_repurposing, methods=["GET"]),
        Route("/api/managed/discovery/ego-subgraph", discovery_ego_subgraph, methods=["GET"]),
        Route("/api/managed/discovery/reward/step", discovery_reward_step, methods=["POST"]),
        Route("/api/managed/discovery/reward/trajectory", discovery_reward_trajectory, methods=["POST"]),
        Route("/api/managed/discovery/reward/ais-closed-loop", ais_closed_loop_reward_evaluate, methods=["POST"]),
        Route("/api/managed/session/summarize-with-subagent", session_summarize_subagent, methods=["POST"]),
        Route("/api/managed/timeline", timeline, methods=["GET"]),
        Route("/api/managed/agent0/search", agent0_search, methods=["GET"]),
        Route("/api/managed/agent0/agent/{agent_id}", agent0_agent, methods=["GET"]),
        Route("/api/managed/agent0/reputation/{agent_id}", agent0_reputation, methods=["GET"]),
        Route("/api/managed/memories/{memory_id}/similar", memory_similar, methods=["GET"]),
        Route("/api/managed/memories/{memory_id}/neighbors", memory_neighbors, methods=["GET"]),
        Route("/api/managed/memories/{memory_id}/events", memory_events, methods=["GET"]),
        Route("/api/managed/memories/{memory_id}/otel", memory_otel, methods=["GET"]),
        Route("/api/managed/memories/{memory_id}/attachments", memory_attachments, methods=["GET"]),
        Route("/api/managed/attachment/{attachment_id}/file", attachment_file, methods=["GET"]),
        Route("/api/managed/memories/{memory_id}/contradictions", memory_contradictions, methods=["GET"]),
        Route("/api/managed/entity/path", entity_path, methods=["GET"]),
        Route("/api/managed/entity/{name}/neighbors", entity_neighbors, methods=["GET"]),
        Route("/api/managed/session/{session_id}/merkle-root", session_merkle_root_route, methods=["GET"]),
        Route("/api/managed/session/{session_id}/replay", session_replay, methods=["GET"]),
        Route("/api/managed/session/{session_id}/otel", session_otel, methods=["GET"]),
        Route("/api/managed/session/{session_id}/memories", session_memories, methods=["GET"]),
        Route("/api/managed/status", store_status, methods=["GET"]),
        Route("/api/managed/stats", store_stats, methods=["GET"]),
        Route("/api/managed/integrity-links", integrity_links_route, methods=["GET"]),
        Route("/api/managed/agent-devices", agent_devices_route, methods=["GET"]),
        Route("/api/managed/memories/{memory_id}", memories),
        Route("/api/managed/memories/{memory_id}/verify", memories),
        Route("/api/managed/export", export),
        Route("/api/managed/export-download", export_download),
        Route("/api/managed/agents", agents_list, methods=["GET"]),
        Route("/api/auth/agents", agents_list, methods=["GET"]),
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
