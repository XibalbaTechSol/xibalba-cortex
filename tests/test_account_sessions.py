"""Characterisation of account-session auth, recorded before Phase 1 changes it.

These tests assert what the code does *today*. They exist so that narrowing a session's
scopes, shortening its lifetime and adding rotation cannot silently break expiry or
revocation — the one code path that can sign out every pilot user.

A passing first run is correct here, and is the point: see Phase 1 Task 1 Step 1.
"""
from xibalba_cortex.accounts import issue_account_session, revoke_account_session
from xibalba_cortex.ingest_tokens import verify_token_record

from conftest import ACCOUNT_EMAIL as EMAIL, ACCOUNT_PASSWORD as PW


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


def test_a_session_today_carries_every_known_scope(tmp_home):
    """Characterises the gap Task 2 closes: `accounts.py` issues every scope any role grants,
    so a viewer-role session holds `memory:write`. When Task 2 lands, this test is REPLACED
    by test_a_session_carries_only_its_roles_scopes -- not deleted silently."""
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW)
    record = verify_token_record(tmp_home, token)
    assert "memory:write" in record["scopes"] and len(record["scopes"]) > 2
