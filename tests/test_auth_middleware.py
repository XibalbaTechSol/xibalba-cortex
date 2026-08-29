import asyncio

from xibalba_cortex.auth_middleware import BearerTokenAuth
from xibalba_cortex.ingest_tokens import issue_token, revoke_token, list_tokens


async def _inner_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _run(home, headers):
    app = BearerTokenAuth(_inner_app, home=home)
    scope = {"type": "http", "headers": headers}
    events = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        events.append(message)

    await app(scope, receive, send)
    return events


def test_valid_token_reaches_the_wrapped_app(tmp_path):
    token = issue_token(tmp_path, "test-harness")
    events = asyncio.run(_run(tmp_path, [(b"authorization", f"Bearer {token}".encode())]))
    assert events[0]["status"] == 200
    assert events[1]["body"] == b"ok"


def test_missing_authorization_header_is_rejected(tmp_path):
    issue_token(tmp_path, "test-harness")
    events = asyncio.run(_run(tmp_path, []))
    assert events[0]["status"] == 401


def test_non_bearer_scheme_is_rejected(tmp_path):
    issue_token(tmp_path, "test-harness")
    events = asyncio.run(_run(tmp_path, [(b"authorization", b"Basic dXNlcjpwYXNz")]))
    assert events[0]["status"] == 401


def test_invalid_token_is_rejected(tmp_path):
    issue_token(tmp_path, "test-harness")
    events = asyncio.run(_run(tmp_path, [(b"authorization", b"Bearer not-a-real-token")]))
    assert events[0]["status"] == 401


def test_revoked_token_is_rejected(tmp_path):
    token = issue_token(tmp_path, "test-harness")
    [row] = list_tokens(tmp_path)
    revoke_token(tmp_path, row["id"])
    events = asyncio.run(_run(tmp_path, [(b"authorization", f"Bearer {token}".encode())]))
    assert events[0]["status"] == 401


def test_non_http_scopes_pass_through_without_auth_check():
    """lifespan events have no request to authenticate -- they must reach the app unchanged,
    or the server could never start up/shut down cleanly."""
    calls = []

    async def inner(scope, receive, send):
        calls.append(scope["type"])

    async def go():
        app = BearerTokenAuth(inner, home="/nonexistent/does/not/matter")
        await app({"type": "lifespan"}, lambda: None, lambda msg: None)

    asyncio.run(go())
    assert calls == ["lifespan"]


async def _run_with_app(app, headers):
    events = []
    async def receive():
        return {"type": "http.request"}
    async def send(message):
        events.append(message)
    await app({"type": "http", "headers": headers}, receive, send)
    return events


def test_profile_binding_rejects_other_tenant(tmp_path):
    token = issue_token(tmp_path, "tenant-a", profile_id="tenant-a")
    async def run():
        app = BearerTokenAuth(_inner_app, home=tmp_path, profile_id="tenant-b")
        return await _run_with_app(app, [(b"authorization", f"Bearer {token}".encode())])
    events = asyncio.run(run())
    assert events[0]["status"] == 403


def test_required_scope_is_enforced(tmp_path):
    token = issue_token(tmp_path, "reader", scopes=("memory:read",))
    async def run():
        app = BearerTokenAuth(_inner_app, home=tmp_path, required_scopes=("memory:write",))
        return await _run_with_app(app, [(b"authorization", f"Bearer {token}".encode())])
    events = asyncio.run(run())
    assert events[0]["status"] == 403
