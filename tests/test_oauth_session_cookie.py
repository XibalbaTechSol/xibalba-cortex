"""OAuth sign-in must end with a session cookie, not a server error.

Regression: the Supabase session exchange and the direct OAuth callback both called an
undefined `_attach_session_cookie`, so every Google/GitHub sign-in returned 500 and the viewer
fell back to the landing page.
"""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from super_cortex.api import SESSION_COOKIE_NAME, create_app
from super_cortex.config import SuperCortexConfig
from super_cortex.managed import ManagedConfig
from super_cortex.oauth_and_storage import SupabaseAuthVerifier


def _client(tmp_path: Path) -> TestClient:
    cfg = SuperCortexConfig(db_path=tmp_path / "provenance.db")
    app = create_app(config=cfg, managed_config=ManagedConfig(home=tmp_path / "managed"))
    return TestClient(app, raise_server_exceptions=False)


def test_supabase_session_exchange_sets_cookie_and_signs_in(tmp_path: Path, monkeypatch) -> None:
    claims = {"email": "ada@example.com", "sub": "supa-user-1",
              "user_metadata": {"full_name": "Ada"}, "app_metadata": {"provider": "google"}}
    monkeypatch.setattr(SupabaseAuthVerifier, "verify_token", lambda self, token: claims)
    client = _client(tmp_path)

    r = client.post("/api/managed/auth/supabase/session", json={"access_token": "header.payload.sig"})
    assert r.status_code == 200, r.text
    assert SESSION_COOKIE_NAME in r.cookies
    me = client.get("/api/managed/me?strict_auth=1")
    assert me.status_code == 200 and me.json()["account"]["email"] == "ada@example.com"
