"""Characterisation of account-session auth, recorded before Phase 1 changes it.

These tests assert what the code does *today*. They exist so that narrowing a session's
scopes, shortening its lifetime and adding rotation cannot silently break expiry or
revocation — the one code path that can sign out every pilot user.

A passing first run is correct here, and is the point: see Phase 1 Task 1 Step 1.
"""
import json

from xibalba_cortex.accounts import issue_account_session, revoke_account_session
from xibalba_cortex.ingest_tokens import _connect, _hash, verify_token_record


def stored_scopes(home, token):
    """The scopes as written to the row, before any reader narrows them by role."""
    conn = _connect(home)
    try:
        row = conn.execute("SELECT scopes_json FROM ingest_tokens WHERE token_hash=?", (_hash(token),)).fetchone()
    finally:
        conn.close()
    return json.loads(row["scopes_json"])

from conftest import ACCOUNT_EMAIL as EMAIL, ACCOUNT_PASSWORD as PW, READER_EMAIL


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
