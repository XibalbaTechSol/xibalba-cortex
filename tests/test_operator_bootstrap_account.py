"""The first-run operator account.

A fresh deployment has no account, and both editions gate sign-in behind one:
managed demotes a freshly registered account to email_verified=0 /
approval_status='pending' (managed/control.py), and email delivery is
fail-closed, so nobody can verify. This command is the way in that does not
need mail: it creates the account, approves it, and sets its role, writing the
identity database directly.

The password is never a command-line argument, never echoed, never printed,
and never recorded in an auth event.
"""

from argparse import Namespace

import pytest

from xibalba_cortex import accounts
from xibalba_cortex.operator import run_command

EMAIL = "operator@example.test"
PASSWORD = "a-password-the-operator-supplies"


def _args(home, **kwargs):
    base = {
        "command": "bootstrap-account",
        "home": str(home),
        "email": EMAIL,
        "display_name": "First Operator",
        "profile_id": "default",
        "role": "operator",
    }
    base.update(kwargs)
    return Namespace(**base)


def test_bootstrap_creates_an_account_that_can_sign_in_with_no_email_step(tmp_path, monkeypatch):
    home = tmp_path / "identity"
    monkeypatch.setenv("CORTEX_BOOTSTRAP_PASSWORD", PASSWORD)

    result = run_command(_args(home))

    assert result["email"] == EMAIL
    assert result["approval_status"] == "approved"
    assert result["email_verified"] is True
    # The one thing that matters: the account can actually authenticate.
    token, record = accounts.issue_account_session(home, email=EMAIL, password=PASSWORD)
    assert token
    assert record["email"] == EMAIL


def test_bootstrap_never_reveals_the_password(tmp_path, monkeypatch):
    home = tmp_path / "identity"
    monkeypatch.setenv("CORTEX_BOOTSTRAP_PASSWORD", PASSWORD)

    result = run_command(_args(home))

    assert PASSWORD not in repr(result)
    # Nor in the auth trail, which an operator may well paste into a ticket.
    events = accounts.recent_auth_events(home) if hasattr(accounts, "recent_auth_events") else []
    assert PASSWORD not in repr(events)


def test_bootstrap_refuses_to_take_the_password_on_the_command_line(tmp_path):
    """A password in argv lands in shell history and in `ps`."""
    from xibalba_cortex.operator import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["bootstrap-account", "--email", EMAIL, "--password", PASSWORD])


def test_bootstrap_refuses_when_no_password_is_supplied(tmp_path, monkeypatch):
    home = tmp_path / "identity"
    monkeypatch.delenv("CORTEX_BOOTSTRAP_PASSWORD", raising=False)
    # Non-interactive: no tty to prompt on, so it must refuse rather than
    # invent a password or create an account nobody can sign in to.
    monkeypatch.setattr("xibalba_cortex.operator.sys.stdin.isatty", lambda: False, raising=False)

    with pytest.raises(ValueError, match="password"):
        run_command(_args(home))

    assert accounts.active_account_by_email(home, email=EMAIL) is None


def test_bootstrap_is_idempotent_and_repairs_a_pending_account(tmp_path, monkeypatch):
    """The managed path leaves accounts pending. Re-running must rescue one,
    not fail on the unique-email constraint and not reset the password."""
    home = tmp_path / "identity"
    accounts.create_account(home, email=EMAIL, password=PASSWORD, display_name="First Operator")
    import sqlite3

    from xibalba_cortex.ingest_tokens import _connect

    conn = _connect(home)
    conn.execute("UPDATE accounts SET email_verified=0, approval_status='pending' WHERE email=?", (EMAIL,))
    conn.commit()
    conn.close()
    del sqlite3

    monkeypatch.setenv("CORTEX_BOOTSTRAP_PASSWORD", "a-different-password")
    result = run_command(_args(home))

    assert result["created"] is False
    assert result["approval_status"] == "approved"
    # The existing password still works: bootstrap approves, it does not reset.
    assert accounts.verify_account_password(home, email=EMAIL, password=PASSWORD) is True


def test_bootstrap_sets_the_requested_role(tmp_path, monkeypatch):
    home = tmp_path / "identity"
    monkeypatch.setenv("CORTEX_BOOTSTRAP_PASSWORD", PASSWORD)

    result = run_command(_args(home, role="admin"))

    assert result["role"] == "admin"
    token, _ = accounts.issue_account_session(home, email=EMAIL, password=PASSWORD)
    principal = accounts.account_for_token(home, token)
    assert principal is not None
    assert principal["role"] == "admin"


def test_bootstrap_rejects_a_role_outside_the_known_set(tmp_path, monkeypatch):
    home = tmp_path / "identity"
    monkeypatch.setenv("CORTEX_BOOTSTRAP_PASSWORD", PASSWORD)

    with pytest.raises(ValueError, match="role"):
        run_command(_args(home, role="superuser"))

    assert accounts.active_account_by_email(home, email=EMAIL) is None
