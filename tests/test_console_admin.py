"""Console administration: API tokens, accounts waiting for approval, the redacted profile config.

Two layers, like the rest of the API's tests: the pure helpers in console_admin.py / accounts.py,
and the HTTP routes in local_api.py that wrap them (role checks, status codes, CSRF-free bearer
calls). The properties worth pinning are the safety ones: a secret is shown once and never listed,
a caller cannot grant what it does not hold, the credential in use cannot be revoked from under
itself, and the configuration view carries no path and no secret.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from xibalba_cortex.accounts import approve_account, create_account, list_pending_accounts
from xibalba_cortex.console_admin import (
    console_tokens,
    grantable_roles,
    issue_console_token,
    public_profile_config,
    revoke_console_token,
)
from xibalba_cortex.ingest_tokens import issue_token, list_tokens, verify_token_record
from xibalba_cortex.local_api import serve
from xibalba_cortex.store import GraphStore


# --- helpers ---------------------------------------------------------------------------------------------

def test_only_an_admin_may_issue_an_admin():
    assert grantable_roles({"admin"}) == ("reader", "writer", "reviewer", "operator", "admin")
    assert grantable_roles({"operator"}) == ("reader", "writer", "reviewer", "operator")
    assert grantable_roles({"writer"}) == ()
    assert grantable_roles(set()) == ()


def test_a_secret_is_returned_once_and_never_listed(tmp_path):
    out = issue_console_token(tmp_path, profile_id="default", caller_roles={"operator"}, label="ci-reader", role="reader", ttl_hours=12)
    secret = out["token"]
    assert isinstance(secret, str) and len(secret) > 30
    # it authenticates...
    assert verify_token_record(tmp_path, secret)["label"] == "ci-reader"
    # ...and appears in no listing, in any field
    listed = console_tokens(tmp_path, "default")
    assert [t["label"] for t in listed] == ["ci-reader"]
    assert secret not in json.dumps(listed)
    assert all("hash" not in key for key in listed[0])
    assert listed[0]["state"] == "active" and listed[0]["scopes"] == ["memory:read"]


def test_scopes_come_from_the_role_not_from_the_request(tmp_path):
    out = issue_console_token(tmp_path, profile_id="default", caller_roles={"operator"}, label="w", role="writer")
    assert out["record"]["scopes"] == ["memory:read", "memory:write"]
    assert "*" not in out["record"]["scopes"]


def test_an_operator_cannot_grant_admin_or_an_unknown_role(tmp_path):
    with pytest.raises(PermissionError):
        issue_console_token(tmp_path, profile_id="default", caller_roles={"operator"}, label="x", role="admin")
    with pytest.raises(ValueError):
        issue_console_token(tmp_path, profile_id="default", caller_roles={"admin"}, label="x", role="superuser")
    with pytest.raises(PermissionError):
        issue_console_token(tmp_path, profile_id="default", caller_roles={"writer"}, label="x", role="reader")


@pytest.mark.parametrize("label", ["", "   ", "account:someone@example.com", "x" * 81])
def test_bad_labels_are_refused(tmp_path, label):
    with pytest.raises(ValueError):
        issue_console_token(tmp_path, profile_id="default", caller_roles={"operator"}, label=label, role="reader")


@pytest.mark.parametrize("ttl", [0, -3, 24 * 365 + 1])
def test_a_ttl_outside_the_window_is_refused(tmp_path, ttl):
    with pytest.raises(ValueError):
        issue_console_token(tmp_path, profile_id="default", caller_roles={"operator"}, label="t", role="reader", ttl_hours=ttl)


def test_account_sessions_are_not_api_tokens(tmp_path):
    issue_token(tmp_path, "account:operator@example.com", roles=("operator",), scopes=("memory:read",))
    issue_token(tmp_path, "viewer-local-dev", roles=("operator",), scopes=("memory:read",))
    assert [t["label"] for t in console_tokens(tmp_path, "default")] == ["viewer-local-dev"]


def test_tokens_of_another_profile_are_not_listed_or_revocable(tmp_path):
    issue_token(tmp_path, "other-profile", profile_id="tenant-b", roles=("reader",), scopes=("memory:read",))
    assert console_tokens(tmp_path, "default") == []
    other = next(t for t in list_tokens(tmp_path) if t["label"] == "other-profile")
    assert revoke_console_token(tmp_path, "default", other["id"], current_token_id=None) is False


def test_revoking_the_credential_in_use_is_refused_and_others_work(tmp_path):
    issue_token(tmp_path, "me", roles=("operator",), scopes=("memory:read",))
    issue_token(tmp_path, "them", roles=("reader",), scopes=("memory:read",))
    me = next(t for t in list_tokens(tmp_path) if t["label"] == "me")
    them = next(t for t in list_tokens(tmp_path) if t["label"] == "them")
    with pytest.raises(ValueError, match="using right now"):
        revoke_console_token(tmp_path, "default", me["id"], current_token_id=me["id"])
    assert revoke_console_token(tmp_path, "default", them["id"], current_token_id=me["id"]) is True
    assert revoke_console_token(tmp_path, "default", them["id"], current_token_id=me["id"]) is False  # already revoked
    states = {t["label"]: t["state"] for t in console_tokens(tmp_path, "default")}
    assert states == {"me": "active", "them": "revoked"}


def test_pending_accounts_lists_only_those_who_cannot_sign_in_yet(tmp_path):
    create_account(tmp_path, email="ready@example.com", password="a-long-enough-password", display_name="Ready")
    create_account(tmp_path, email="waiting@example.com", password="a-long-enough-password", display_name="Waiting")
    # simulate an account created under a require-approval policy
    from xibalba_cortex.ingest_tokens import _connect
    conn = _connect(tmp_path)
    conn.execute("UPDATE accounts SET approval_status='pending', email_verified=0 WHERE email='waiting@example.com'")
    conn.commit(); conn.close()
    pending = list_pending_accounts(tmp_path)
    assert [a["email"] for a in pending] == ["waiting@example.com"]
    assert "password_hash" not in pending[0] and "password_salt" not in pending[0]
    assert approve_account(tmp_path, email="waiting@example.com") is True
    assert list_pending_accounts(tmp_path) == []


def test_profile_config_names_no_path_and_no_secret(tmp_path):
    env = {
        "XIBALBA_BACKUP_DIR": "/srv/backups/secret-place",
        "XIBALBA_VAULT_DIR": "/srv/vault",
        "XIBALBA_DAG_HOME": "/srv/dag",
        "XIBALBA_ANCHOR_URL": "https://anchor.internal.example/path?key=abc123",
        "XIBALBA_CORTEX_IDENTITY_MODE": "full",
    }
    view = public_profile_config(tmp_path, environ=env)
    blob = json.dumps(view)
    for forbidden in ("/srv/", "secret-place", "anchor.internal", "abc123", str(tmp_path)):
        assert forbidden not in blob
    assert view["destinations"] == {"backup": True, "vault": True, "integrity_dag": True, "anchor_service": True, "oracle": False}
    assert view["identity_mode"] == "full"
    assert view["mode"] in {"local", "hybrid", "remote-inference"}
    assert "restart" in view["changed_by"]


def test_profile_config_reports_unset_destinations_as_unset(tmp_path):
    view = public_profile_config(tmp_path, environ={})
    assert not any(view["destinations"].values())


# --- the HTTP routes -----------------------------------------------------------------------------------------

def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


class _Api:
    def __init__(self, port: int, bearer: str) -> None:
        self.port, self.bearer = port, bearer

    def call(self, method: str, path: str, payload: dict | None = None) -> tuple[int, object]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"http://localhost:{self.port}{path}", data=data, method=method,
            headers={"Authorization": f"Bearer {self.bearer}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


def _serve(tmp_path, *, roles, scopes):
    store = GraphStore(tmp_path / "graph")
    bearer = issue_token(store.home, "harness", roles=roles, scopes=scopes)
    port = _port()
    threading.Thread(target=serve, kwargs={"store": store, "port": port}, daemon=True).start()
    time.sleep(0.3)
    return store, _Api(port, bearer)


@pytest.fixture
def operator_api(tmp_path):
    store, api = _serve(tmp_path, roles=("operator",), scopes=("memory:read", "memory:write"))
    yield store, api
    store.close()


@pytest.fixture
def admin_api(tmp_path):
    store, api = _serve(tmp_path, roles=("admin",), scopes=("*", "memory:read", "memory:write"))
    yield store, api
    store.close()


def test_route_token_lifecycle(operator_api):
    store, api = operator_api
    status, body = api.call("GET", "/api/auth/tokens")
    assert status == 200 and body["grantable_roles"] == ["reader", "writer", "reviewer", "operator"]
    status, issued = api.call("POST", "/api/auth/tokens", {"label": "ingest-bot", "role": "writer", "ttl_hours": 24})
    assert status == 201 and issued["token"] and issued["record"]["state"] == "active"
    status, body = api.call("GET", "/api/auth/tokens")
    assert issued["token"] not in json.dumps(body)
    assert "ingest-bot" in [t["label"] for t in body["tokens"]]
    status, _ = api.call("POST", "/api/auth/tokens/revoke", {"token_id": issued["record"]["id"]})
    assert status == 200
    status, _ = api.call("POST", "/api/auth/tokens/revoke", {"token_id": issued["record"]["id"]})
    assert status == 404
    # the issued secret really stopped working
    assert verify_token_record(store.home, issued["token"]) is None


def test_route_refuses_to_issue_admin_and_to_revoke_itself(operator_api):
    store, api = operator_api
    status, body = api.call("POST", "/api/auth/tokens", {"label": "sneaky", "role": "admin"})
    assert status == 403 and "admin" in body["error"]
    me = next(t for t in list_tokens(store.home) if t["label"] == "harness")
    status, body = api.call("POST", "/api/auth/tokens/revoke", {"token_id": me["id"]})
    assert status == 400 and "right now" in body["error"]
    status, body = api.call("POST", "/api/auth/tokens", {"label": "", "role": "reader"})
    assert status == 400


def test_a_reader_cannot_manage_tokens(tmp_path):
    store, api = _serve(tmp_path, roles=("reader",), scopes=("memory:read",))
    try:
        assert api.call("GET", "/api/auth/tokens")[0] == 403
        assert api.call("POST", "/api/auth/tokens", {"label": "x", "role": "reader"})[0] == 403
    finally:
        store.close()


def test_route_profile_config_is_readable_and_pathless(operator_api):
    store, api = operator_api
    status, body = api.call("GET", "/api/profile/config")
    assert status == 200 and body["profile_id"] == store.profile_id
    assert str(store.home) not in json.dumps(body)


def test_route_pending_accounts_needs_an_admin(operator_api, admin_api):
    assert operator_api[1].call("GET", "/api/auth/admin/pending")[0] == 403
    store, api = admin_api
    create_account(store.home, email="waiting@example.com", password="a-long-enough-password", display_name="W", profile_id=store.profile_id)
    from xibalba_cortex.ingest_tokens import _connect
    conn = _connect(store.home)
    conn.execute("UPDATE accounts SET approval_status='pending' WHERE email='waiting@example.com'")
    conn.commit(); conn.close()
    status, body = api.call("GET", "/api/auth/admin/pending")
    assert status == 200 and [a["email"] for a in body["accounts"]] == ["waiting@example.com"]
    status, _ = api.call("POST", "/api/auth/admin/approve", {"email": "waiting@example.com"})
    assert status == 200
    assert api.call("GET", "/api/auth/admin/pending")[1]["accounts"] == []
