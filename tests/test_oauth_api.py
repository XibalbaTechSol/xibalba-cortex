"""Tests for OAuth API endpoints and email-delivery fault tolerance."""
from __future__ import annotations

import os
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from xibalba_cortex.email_delivery import EmailDeliveryError
from xibalba_cortex.managed.api import create_app
from xibalba_cortex.managed.config import ManagedConfig
from xibalba_cortex.managed.control import ManagedControl
from xibalba_cortex.oauth import OAuthUserInfo


@pytest.fixture
def managed_setup(tmp_path):
    config = ManagedConfig(
        home=tmp_path,
        public_url="http://localhost:8430",
        allow_signup=True,
        google_client_id="mock-google-client-id",
        google_client_secret="mock-google-client-secret",
        github_client_id="mock-github-client-id",
        github_client_secret="mock-github-client-secret",
    )
    mail = []
    service = ManagedControl(config, email_sender=lambda *args: mail.append(args))
    app = create_app(config, control=service)
    with TestClient(app, base_url=config.public_url) as client:
        yield config, service, mail, client


def test_oauth_providers_unconfigured(tmp_path):
    config = ManagedConfig(home=tmp_path, public_url="http://localhost:8430")
    service = ManagedControl(config)
    app = create_app(config, control=service)
    with TestClient(app, base_url=config.public_url) as client:
        res = client.get("/api/managed/oauth/providers")
        assert res.status_code == 200
        assert res.json() == {"providers": []}

        # Also via alias
        res_alias = client.get("/api/auth/oauth/providers")
        assert res_alias.status_code == 200
        assert res_alias.json() == {"providers": []}


def test_oauth_providers_configured(managed_setup):
    config, service, mail, client = managed_setup
    res = client.get("/api/managed/oauth/providers")
    assert res.status_code == 200
    providers = res.json()["providers"]
    assert len(providers) == 2
    assert {"id": "google", "name": "Google"} in providers
    assert {"id": "github", "name": "GitHub"} in providers


def test_oauth_authorize_redirect(managed_setup):
    config, service, mail, client = managed_setup
    res = client.get("/api/managed/oauth/google/authorize", follow_redirects=False)
    assert res.status_code == 303
    location = res.headers["location"]
    parsed = urlsplit(location)
    assert parsed.netloc == "accounts.google.com"
    params = parse_qs(parsed.query)
    assert params["client_id"] == ["mock-google-client-id"]
    assert "state" in params
    assert "code_challenge" in params
    assert params["code_challenge_method"] == ["S256"]
    assert params["redirect_uri"] == ["http://localhost:8430/api/managed/oauth/google/callback"]


def test_oauth_authorize_unsupported_provider(managed_setup):
    config, service, mail, client = managed_setup
    res = client.get("/api/managed/oauth/facebook/authorize", follow_redirects=False)
    assert res.status_code == 404


def test_oauth_callback_provider_error(managed_setup):
    config, service, mail, client = managed_setup
    res = client.get(
        "/api/managed/oauth/google/callback?error=access_denied&error_description=User+denied",
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "User" in res.headers["location"] and "denied" in res.headers["location"]


def test_oauth_callback_missing_state(managed_setup):
    config, service, mail, client = managed_setup
    res = client.get("/api/managed/oauth/google/callback?code=mock-code", follow_redirects=False)
    assert res.status_code == 303
    assert "missing_code_or_state" in res.headers["location"]


def test_oauth_callback_tampered_state(managed_setup):
    config, service, mail, client = managed_setup
    res = client.get(
        "/api/managed/oauth/google/callback?code=mock-code&state=tampered.state.value",
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "error=" in res.headers["location"]


def test_oauth_callback_unverified_email(managed_setup):
    config, service, mail, client = managed_setup
    auth_res = client.get("/api/managed/oauth/google/authorize", follow_redirects=False)
    state = parse_qs(urlsplit(auth_res.headers["location"]).query)["state"][0]

    unverified_info = OAuthUserInfo(
        provider="google",
        provider_user_id="google-sub-unverified",
        email="unverified@example.com",
        display_name="Unverified User",
        email_verified=False,
    )

    with patch("xibalba_cortex.oauth.GoogleOAuthProvider.exchange_code", return_value=unverified_info):
        res = client.get(
            f"/api/managed/oauth/google/callback?code=mock-code&state={state}",
            follow_redirects=False,
        )
        assert res.status_code == 303
        assert "error=unverified_email" in res.headers["location"]


def test_oauth_callback_success_login_and_me(managed_setup):
    config, service, mail, client = managed_setup
    auth_res = client.get("/api/managed/oauth/google/authorize", follow_redirects=False)
    state = parse_qs(urlsplit(auth_res.headers["location"]).query)["state"][0]

    verified_info = OAuthUserInfo(
        provider="google",
        provider_user_id="google-sub-12345",
        email="doctor.alice@hospital.org",
        display_name="Dr. Alice Chen",
        email_verified=True,
    )

    with patch("xibalba_cortex.oauth.GoogleOAuthProvider.exchange_code", return_value=verified_info):
        res = client.get(
            f"/api/managed/oauth/google/callback?code=mock-code&state={state}",
            follow_redirects=False,
        )
        assert res.status_code == 303
        assert res.headers["location"] == "/managed"
        assert "cortex_managed_session=" in res.headers["set-cookie"]

        # Call /api/managed/me to verify authenticated session
        me_res = client.get("/api/managed/me")
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["account"]["email"] == "doctor.alice@hospital.org"
        assert me_data["account"]["display_name"] == "Dr. Alice Chen"
        assert me_data["account"]["status"] == "active"
        assert me_data["account"]["email_verified"] == 1


def test_signup_catches_email_delivery_error(tmp_path):
    config = ManagedConfig(home=tmp_path, public_url="http://localhost:8430", allow_signup=True)

    def failing_email_sender(*args, **kwargs):
        raise EmailDeliveryError("SMTP connection refused")

    service = ManagedControl(config, email_sender=failing_email_sender)
    app = create_app(config, control=service)
    with TestClient(app, base_url=config.public_url) as client:
        # Should not raise 500 / 503; gracefully returns 202
        res = client.post(
            "/api/managed/signup",
            json={"email": "newuser@example.com", "password": "secure-password-123", "display_name": "Test User"},
        )
        assert res.status_code == 202
        assert "message" in res.json()
