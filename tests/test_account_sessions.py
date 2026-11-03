"""Characterisation of account-session auth, recorded before Phase 1 changes it.

These tests assert what the code does *today*. They exist so that narrowing a session's
scopes, shortening its lifetime and adding rotation cannot silently break expiry or
revocation — the one code path that can sign out every pilot user.

A passing first run is correct here, and is the point: see Phase 1 Task 1 Step 1.
"""
import json

from xibalba_cortex import accounts
from xibalba_cortex.accounts import SESSION_TTL_HOURS, issue_account_session, revoke_account_session, rotate_account_session
from xibalba_cortex.ingest_tokens import ROLE_SCOPES, _connect, _hash, verify_token_record


def stored_scopes(home, token):
    """The scopes as written to the row, before any reader narrows them by role."""
    conn = _connect(home)
    try:
        row = conn.execute("SELECT scopes_json FROM ingest_tokens WHERE token_hash=?", (_hash(token),)).fetchone()
    finally:
        conn.close()
    return json.loads(row["scopes_json"])

from conftest import ACCOUNT_EMAIL as EMAIL, ACCOUNT_PASSWORD as PW, MANAGED_PASSWORD, READER_EMAIL


def test_a_session_expires_at_its_ttl_today(tmp_home, frozen_clock):
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW, ttl_hours=1)
    assert verify_token_record(tmp_home, token) is not None
    frozen_clock.advance(hours=1, seconds=1)
    assert verify_token_record(tmp_home, token) is None


def test_revocation_is_consulted_on_the_next_request_today(tmp_home):
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW)
    assert verify_token_record(tmp_home, token) is not None   # passes BEFORE
    assert revoke_account_session(tmp_home, token) is True
    assert verify_token_record(tmp_home, token) is None       # fails AFTER


def test_a_session_carries_only_its_roles_scopes(tmp_home):
    """Replaces test_a_session_today_carries_every_known_scope, the characterisation of the
    gap this closes: a read-only account's session used to hold `memory:write` because
    `accounts.py` issued every scope any role grants."""
    token, _ = issue_account_session(tmp_home, email=READER_EMAIL, password=PW)
    record = verify_token_record(tmp_home, token)
    assert "memory:read" in record["scopes"]
    assert "memory:write" not in record["scopes"]


def test_a_session_stores_only_its_roles_scopes(tmp_home):
    """The stored grant must match the role, not merely be narrowed on the way out.

    Both of today's read paths call `effective_scopes`, so an over-broad row grants nothing
    extra *yet* — which is exactly why this is worth asserting. Least privilege currently
    depends on every present and future reader of `scopes_json` remembering to narrow; a row
    that claims `memory:write` for a read-only account is one forgetful reader away from
    being true.
    """
    token, _ = issue_account_session(tmp_home, email=READER_EMAIL, password=PW)
    assert stored_scopes(tmp_home, token) == ["memory:read"]


def test_an_admin_session_still_stores_the_concrete_scope_set(tmp_home):
    """`ROLE_SCOPES["admin"]` is the literal `{"*"}`, and storing `"*"` would never match a
    concrete required scope like `memory:read` at auth time. An admin therefore keeps the
    expanded set -- narrowing must not turn an admin into a no-scope account."""
    conn = _connect(tmp_home)
    try:
        conn.execute("UPDATE accounts SET role='admin' WHERE email=?", (EMAIL,))
        conn.commit()
    finally:
        conn.close()
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW)
    stored = stored_scopes(tmp_home, token)
    assert "*" not in stored
    assert {"memory:read", "memory:write", "memory:delete", "proposal:decide", "agent0:write"} <= set(stored)


def legacy_issued_session(home, email=EMAIL):
    """A session row in the pre-Phase-1 format: 24h TTL and every known scope.

    Built through the real issuer with the old arguments rather than by hand -- a hand-built
    row would prove only that the test author understood the old format.
    """
    token, _ = issue_account_session(home, email=email, password=PW, ttl_hours=24)
    conn = _connect(home)
    try:
        every = sorted({s for grants in ROLE_SCOPES.values() for s in grants if s != "*"})
        conn.execute("UPDATE ingest_tokens SET scopes_json=? WHERE token_hash=?", (json.dumps(every), _hash(token)))
        conn.commit()
    finally:
        conn.close()
    return token


def test_rotation_replaces_the_credential_without_signing_the_holder_out(tmp_home):
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW)
    fresh, account = rotate_account_session(tmp_home, token)
    assert fresh != token
    assert verify_token_record(tmp_home, fresh) is not None
    assert verify_token_record(tmp_home, token) is None
    assert account["email"] == EMAIL


def test_rotating_a_revoked_session_is_refused(tmp_home):
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW)
    revoke_account_session(tmp_home, token)
    assert rotate_account_session(tmp_home, token) is None


def test_rotating_an_expired_session_is_refused(tmp_home, frozen_clock):
    """Rotation must not resurrect a session that already lapsed -- otherwise a stolen cookie
    stays useful forever, and the TTL means nothing."""
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW, ttl_hours=1)
    frozen_clock.advance(hours=1, seconds=1)
    assert rotate_account_session(tmp_home, token) is None


def test_a_session_issued_before_the_change_still_authenticates(tmp_home):
    """The binding constraint: no pilot user is signed out by a migration.

    Uses the READ-ONLY account deliberately. An operator's pre-change row stored every known
    scope, which is exactly what an operator's correct row stores -- indistinguishable, so an
    operator version of this test could not fail. Only a reader's row is over-broad enough for
    a narrowing-at-verify-time implementation to reject.
    """
    token = legacy_issued_session(tmp_home, email=READER_EMAIL)
    assert "memory:write" in stored_scopes(tmp_home, token)   # genuinely the old, broad format
    assert verify_token_record(tmp_home, token) is not None


def test_rotating_a_legacy_session_narrows_its_stored_scopes(tmp_home):
    """Rotation is also the migration path: an over-broad row issued before Phase 1 Task 2
    stores only its role's scopes once rotated, without its holder re-authenticating."""
    token = legacy_issued_session(tmp_home, email=READER_EMAIL)
    assert "memory:write" in stored_scopes(tmp_home, token)
    fresh, _ = rotate_account_session(tmp_home, token)
    assert stored_scopes(tmp_home, fresh) == ["memory:read"]


def test_the_managed_cookie_does_not_outlive_the_session_it_points_at(managed_app, monkeypatch):
    """A cookie that lives longer than its server-side session presents to the user as a silent
    random logout.

    Asserting `Max-Age == SESSION_TTL_HOURS * 3600` against today's values would pass on the
    coincidence that the hardcoded 86400 equals the default -- it would measure nothing. So the
    constant is moved and the cookie must follow it.
    """
    managed_app.register("acct-1")
    monkeypatch.setattr(accounts, "SESSION_TTL_HOURS", 3)
    r = managed_app.owner.post("/api/managed/login", json={"email": "acct-1@example.com", "password": MANAGED_PASSWORD})
    assert r.status_code == 200, r.text
    assert "Max-Age=10800" in r.headers["set-cookie"]


def test_the_self_hosted_cookie_lifetime_is_not_a_second_copy_of_the_number():
    """`local_api.py` carried its own `_SESSION_TTL_HOURS = 24` with a comment asking a reader to
    keep two numbers in step by hand. It is now derived, so there is no second number.

    This asserts the derivation rather than the value: it imports the module and compares the
    object to the source constant, which is the only thing that can drift.
    """
    import xibalba_cortex.local_api as local_api

    assert local_api._SESSION_TTL_HOURS is local_api._ACCOUNT_SESSION_TTL_HOURS is accounts.SESSION_TTL_HOURS
