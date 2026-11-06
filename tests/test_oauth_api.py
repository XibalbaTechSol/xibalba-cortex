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
from managed_test_support import managed_control_options
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
    config, storage_options = managed_control_options(config)
    service = ManagedControl(config, email_sender=lambda *args: mail.append(args), **storage_options)
    app = create_app(config, control=service)
    with TestClient(app, base_url=config.public_url) as client:
        yield config, service, mail, client


def test_oauth_providers_unconfigured(tmp_path):
    config = ManagedConfig(home=tmp_path, public_url="http://localhost:8430")
    config, storage_options = managed_control_options(config)
    service = ManagedControl(config, **storage_options)
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

    config, storage_options = managed_control_options(config)
    service = ManagedControl(config, email_sender=failing_email_sender, **storage_options)
    app = create_app(config, control=service)
    with TestClient(app, base_url=config.public_url) as client:
        # Should not raise 500 / 503; gracefully returns 202
        res = client.post(
            "/api/managed/signup",
            json={"email": "newuser@example.com", "password": "secure-password-123", "display_name": "Test User"},
        )
        assert res.status_code == 202
        assert "message" in res.json()


def test_device_pairing_api_endpoints(managed_setup):
    config, service, mail, client = managed_setup

    # 1. Initiate pairing from agent device
    agent_did = "did:integrity:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    req_res = client.post(
        "/api/managed/device/pair/request",
        json={
            "device_id": "test-device-uuid",
            "device_name": "Developer Laptop",
            "agent_did": agent_did,
            "agent_name": "claude-desktop",
            "callback_url": "http://127.0.0.1:8435/callback",
        },
    )
    assert req_res.status_code == 201
    req_data = req_res.json()
    assert req_data["device_code"]
    assert req_data["user_code"]
    assert "/managed#pair?code=" in req_data["verification_url"]

    user_code = req_data["user_code"]
    device_code = req_data["device_code"]

    # 2. Get info
    info_res = client.get(f"/api/managed/device/pair/{user_code}")
    assert info_res.status_code == 200
    info_data = info_res.json()
    assert info_data["device_name"] == "Developer Laptop"
    assert info_data["agent_did"] == agent_did
    assert info_data["status"] == "pending"

    # 3. Poll while pending
    poll_res = client.get(f"/api/managed/device/pair/{device_code}/status")
    assert poll_res.status_code == 200
    assert poll_res.json()["status"] == "pending"

    # 4. Authenticate user in browser
    auth_res = client.get("/api/managed/oauth/google/authorize", follow_redirects=False)
    state = parse_qs(urlsplit(auth_res.headers["location"]).query)["state"][0]
    verified_info = OAuthUserInfo(
        provider="google",
        provider_user_id="google-sub-dev",
        email="developer@example.com",
        display_name="Dev User",
        email_verified=True,
    )
    with patch("xibalba_cortex.oauth.GoogleOAuthProvider.exchange_code", return_value=verified_info):
        login_res = client.get(f"/api/managed/oauth/google/callback?code=mock-code&state={state}", follow_redirects=False)
        assert login_res.status_code == 303

    # Get CSRF token
    me_res = client.get("/api/managed/me")
    csrf_token = me_res.json()["csrf_token"]
    headers = {"Origin": config.public_url, "X-Cortex-CSRF-Token": csrf_token}

    # 5. User approves pairing in browser
    approve_res = client.post(f"/api/managed/device/pair/{user_code}/approve", headers=headers)
    assert approve_res.status_code == 200
    approve_data = approve_res.json()
    assert approve_data["ok"] is True
    assert approve_data["token"]
    assert approve_data["callback_url"] == "http://127.0.0.1:8435/callback"

    # 6. Poll after approval
    poll_approved = client.get(f"/api/managed/device/pair/{device_code}/status")
    assert poll_approved.status_code == 200
    assert poll_approved.json()["status"] == "approved"
    assert poll_approved.json()["token"] == approve_data["token"]


def test_oauth_providers_and_authorize_with_supabase_auth(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from xibalba_cortex.managed import api as managed_api

    config = ManagedConfig(
        home=tmp_path,
        public_url="http://localhost:8430",
        storage_backend="supabase",
        identity_backend="supabase_auth",
        supabase_url="https://testproject.supabase.co",
    )
    monkeypatch.setattr(managed_api, "SupabaseAuthVerifier", lambda *args, **kwargs: object())
    monkeypatch.setattr(ManagedControl, "_validate_supabase_schema", lambda self: None)
    service = ManagedControl(config, db_factory=MagicMock())
    app = create_app(config, control=service)

    with TestClient(app, base_url=config.public_url) as client:
        # 1. Providers endpoint lists Google and GitHub when brokered by Supabase
        res = client.get("/api/managed/oauth/providers")
        assert res.status_code == 200
        providers = res.json()["providers"]
        assert {"id": "google", "name": "Google"} in providers
        assert {"id": "github", "name": "GitHub"} in providers

        # Also via alias
        res_alias = client.get("/api/auth/oauth/providers")
        assert res_alias.status_code == 200
        assert res_alias.json() == res.json()

        # 2. Authorize redirects to Supabase Auth endpoint
        res_auth = client.get("/api/managed/oauth/google/authorize", follow_redirects=False)
        assert res_auth.status_code == 303
        location = res_auth.headers["location"]
        parsed = urlsplit(location)
        assert parsed.netloc == "testproject.supabase.co"
        assert parsed.path == "/auth/v1/authorize"
        params = parse_qs(parsed.query)
        assert params["provider"] == ["google"]
        assert params["redirect_to"] == ["http://localhost:8430/managed"]

        # Alias /api/auth/oauth/google/authorize also redirects to Supabase
        res_alias_auth = client.get("/api/auth/oauth/google/authorize", follow_redirects=False)
        assert res_alias_auth.status_code == 303
        assert res_alias_auth.headers["location"] == location

        # Custom redirect_to query parameter is honored
        res_custom = client.get(
            "/api/managed/oauth/github/authorize?redirect_to=http://localhost:8430/custom-callback",
            follow_redirects=False,
        )
        assert res_custom.status_code == 303
        custom_params = parse_qs(urlsplit(res_custom.headers["location"]).query)
        assert custom_params["provider"] == ["github"]
        assert custom_params["redirect_to"] == ["http://localhost:8430/custom-callback"]

        # 3. Session endpoint mounted at /api/auth/supabase/session
        res_session = client.post("/api/auth/supabase/session", json={"access_token": "invalid"})
        assert res_session.status_code == 401

