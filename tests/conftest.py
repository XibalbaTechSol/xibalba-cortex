"""Shared fixtures: the managed (hosted) edition, plus the account-session primitives."""
from contextlib import ExitStack
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from xibalba_cortex import accounts, ingest_tokens
from xibalba_cortex.accounts import approve_account, create_account
from xibalba_cortex.managed.api import create_app
from xibalba_cortex.managed.config import ManagedConfig
from xibalba_cortex.managed.control import ManagedControl

_PASSWORD = "correct-test-password"
MANAGED_PASSWORD = _PASSWORD  # the password ManagedApp.register signs its accounts up with


class ManagedApp:
    """A managed service plus two clients over it: `owner` carries the account session cookie,
    `client` carries nothing, so a bearer key is the only credential it ever presents."""

    def __init__(self, config, service, mail, owner, client, stack):
        self.config, self.service, self.mail, self.owner, self.client = config, service, mail, owner, client
        self._stack = stack
        self._accounts: dict[str, tuple[dict, dict]] = {}

    def register(self, name: str):
        """Sign up, verify and log `name` in on the owner client; returns (account, headers)."""
        if name not in self._accounts:
            email = f"{name}@example.com"
            r = self.owner.post("/api/managed/signup", json={"email": email, "password": _PASSWORD, "display_name": name})
            assert r.status_code == 202, r.text
            token = parse_qs(urlsplit(self.mail[-1][2].splitlines()[-1]).query)["token"][0]
            assert self.owner.get("/api/managed/verify", params={"token": token}, follow_redirects=False).status_code == 303
            r = self.owner.post("/api/managed/login", json={"email": email, "password": _PASSWORD})
            assert r.status_code == 200, r.text
            body = r.json()
            self._accounts[name] = (body["account"], {"Origin": self.config.public_url, "X-Cortex-CSRF-Token": body["csrf_token"]})
        return self._accounts[name]

    def issue_key(self, name: str, label: str = "agent") -> tuple[str, str]:
        """Mint a `managed-api:` key for `name` through the real route. Returns (id, token)."""
        _, headers = self.register(name)
        r = self.owner.post("/api/managed/keys", headers=headers, json={"label": label})
        assert r.status_code == 201, r.text
        token = r.json()["token"]
        listed = self.owner.get("/api/managed/keys", headers=headers).json()["keys"]
        return listed[0]["id"], token

    def revoke_key(self, name: str, key_id: str):
        _, headers = self.register(name)
        r = self.owner.post("/api/managed/keys/revoke", headers=headers, json={"id": key_id})
        assert r.status_code == 200 and r.json()["revoked"] is True, r.text

    def post(self, path, **kwargs):
        return self.client.post(path, **kwargs)

    def tenant(self, name: str) -> dict:
        return self.service.tenant(self.register(name)[0])

    def store(self, name: str):
        """The named account's own tenant store, closed at teardown."""
        return self._stack.enter_context(self.service.store(self.tenant(name)))


@pytest.fixture
def managed_app(tmp_path):
    config = ManagedConfig(home=tmp_path, public_url="http://localhost:8430", allow_signup=True)
    mail = []
    service = ManagedControl(config, email_sender=lambda *args: mail.append(args))
    app = create_app(config, control=service)
    with ExitStack() as stack:
        owner = stack.enter_context(TestClient(app, base_url=config.public_url))
        client = stack.enter_context(TestClient(app, base_url=config.public_url))
        yield ManagedApp(config, service, mail, owner, client, stack)


@pytest.fixture
def api_key(managed_app):
    """A bearer token for account `acct-1`, minted through the real key route."""
    return managed_app.issue_key("acct-1")[1]


# ---------------------------------------------------------------------------
# Account-session fixtures (Phase 1). `issue_account_session` authenticates a real
# account, so a home with no account in it cannot exercise session behaviour at all.

ACCOUNT_EMAIL = "operator@example.com"
# `reader` is the narrowest real role: memory:read and nothing else. There is no "viewer"
# role in ROLE_SCOPES, which is what the plan's test sketch called this.
READER_EMAIL = "reader@example.com"
ACCOUNT_PASSWORD = "correct-test-password"
MANAGED_PASSWORD = _PASSWORD  # the password ManagedApp.register signs its accounts up with


@pytest.fixture
def tmp_home(tmp_path):
    """An identity home holding one verified, approved account ready to sign in."""
    home = tmp_path / "identity-home"
    home.mkdir()
    for email, display in ((ACCOUNT_EMAIL, "Operator"), (READER_EMAIL, "Reader")):
        create_account(home, email=email, password=ACCOUNT_PASSWORD, display_name=display)
        approve_account(home, email=email, verified=True)
    # `create_account` has no role parameter and the column defaults to `operator`, so the
    # read-only account is demoted directly. A session's scopes follow this column.
    conn = ingest_tokens._connect(home)
    try:
        conn.execute("UPDATE accounts SET role='reader' WHERE email=?", (READER_EMAIL,))
        conn.commit()
    finally:
        conn.close()
    return home


class _Clock:
    """Shifts wall-clock time for the modules that read it, without sleeping."""

    def __init__(self):
        self.offset = timedelta(0)

    def advance(self, **kwargs):
        self.offset += timedelta(**kwargs)


@pytest.fixture
def frozen_clock(monkeypatch):
    """Advance the clock that issues *and* verifies sessions.

    Expiry is stored as an absolute `expires_at` at issue time and compared against
    `datetime.now()` at verify time, in two different modules. Shifting only one of them
    would let a test "expire" a session that the issuer never dated, so both move together.
    """
    clock = _Clock()
    real = datetime

    class Shifted(datetime):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz) + clock.offset

    for module in (accounts, ingest_tokens):
        monkeypatch.setattr(module, "datetime", Shifted)
    return clock
