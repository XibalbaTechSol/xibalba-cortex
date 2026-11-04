"""Unit and integration tests for OIDC and OAuth 2.0 social authentication."""
import time
from unittest.mock import MagicMock

import pytest

from xibalba_cortex.oauth import (
    GitHubOAuthProvider,
    GoogleOAuthProvider,
    OAuthError,
    generate_pkce,
    sign_oauth_state,
    verify_oauth_state,
)


def test_pkce_generation():
    verifier, challenge = generate_pkce()
    assert len(verifier) >= 43
    assert len(challenge) > 20
    assert "=" not in challenge  # RFC 7636 unpadded base64url


def test_oauth_state_roundtrip():
    secret = b"test-secret-key-32-bytes-long!!!"
    state = sign_oauth_state(secret, provider="google", code_verifier="verifier-123", redirect_uri="http://localhost:8420/callback")
    verified = verify_oauth_state(secret, state, expected_provider="google")
    assert verified["p"] == "google"
    assert verified["v"] == "verifier-123"
    assert verified["r"] == "http://localhost:8420/callback"


def test_oauth_state_tampering():
    secret = b"test-secret-key-32-bytes-long!!!"
    state = sign_oauth_state(secret, provider="google", code_verifier="verifier-123")
    parts = state.split(".")
    # Tamper with the signature bytes directly
    tampered_sig = ("A" if parts[1][0] != "A" else "B") + parts[1][1:]
    tampered = f"{parts[0]}.{tampered_sig}"
    with pytest.raises(OAuthError, match="Invalid or tampered"):
        verify_oauth_state(secret, tampered, expected_provider="google")


def test_oauth_state_expired():
    secret = b"test-secret-key-32-bytes-long!!!"
    state = sign_oauth_state(secret, provider="google", code_verifier="verifier-123", ttl_seconds=-1)
    with pytest.raises(OAuthError, match="expired"):
        verify_oauth_state(secret, state, expected_provider="google")


def test_oauth_state_mismatched_provider():
    secret = b"test-secret-key-32-bytes-long!!!"
    state = sign_oauth_state(secret, provider="google", code_verifier="verifier-123")
    with pytest.raises(OAuthError, match="provider mismatch"):
        verify_oauth_state(secret, state, expected_provider="github")


def test_google_provider_urls():
    p = GoogleOAuthProvider(client_id="my-google-client", client_secret="my-google-secret")
    assert p.configured is True
    url = p.authorization_url(state="xyz", code_challenge="chal", redirect_uri="https://app.com/cb")
    assert "https://accounts.google.com/o/oauth2/v2/auth" in url
    assert "client_id=my-google-client" in url
    assert "code_challenge=chal" in url
    assert "code_challenge_method=S256" in url
    assert "state=xyz" in url


def test_github_provider_urls():
    p = GitHubOAuthProvider(client_id="my-github-client", client_secret="my-github-secret")
    assert p.configured is True
    url = p.authorization_url(state="xyz", redirect_uri="https://app.com/cb")
    assert "https://github.com/login/oauth/authorize" in url
    assert "client_id=my-github-client" in url
    assert "state=xyz" in url


def test_unconfigured_providers_raise():
    p = GoogleOAuthProvider("", "")
    assert p.configured is False
    with pytest.raises(OAuthError, match="not configured"):
        p.authorization_url(state="s", code_challenge="c", redirect_uri="r")


def test_google_exchange_success():
    p = GoogleOAuthProvider("client", "secret")
    session = MagicMock()

    # Mock token response
    token_resp = MagicMock()
    token_resp.ok = True
    token_resp.json.return_value = {"access_token": "ya29.mock-token"}

    # Mock userinfo response
    user_resp = MagicMock()
    user_resp.ok = True
    user_resp.json.return_value = {
        "sub": "10987654321",
        "email": "clinician@hospital.org",
        "email_verified": True,
        "name": "Dr. House",
    }

    session.post.return_value = token_resp
    session.get.return_value = user_resp

    user_info = p.exchange_code(code="auth-code", code_verifier="verifier", redirect_uri="https://app.com/cb", session=session)
    assert user_info.provider == "google"
    assert user_info.provider_user_id == "10987654321"
    assert user_info.email == "clinician@hospital.org"
    assert user_info.display_name == "Dr. House"
    assert user_info.email_verified is True


def test_google_unverified_email_rejected():
    p = GoogleOAuthProvider("client", "secret")
    session = MagicMock()
    token_resp = MagicMock(ok=True)
    token_resp.json.return_value = {"access_token": "ya29.mock"}
    user_resp = MagicMock(ok=True)
    user_resp.json.return_value = {"sub": "123", "email": "unverified@gmail.com", "email_verified": False}
    session.post.return_value = token_resp
    session.get.return_value = user_resp

    with pytest.raises(OAuthError, match="email is not verified"):
        p.exchange_code(code="c", code_verifier="v", redirect_uri="r", session=session)


def test_github_exchange_success():
    p = GitHubOAuthProvider("client", "secret")
    session = MagicMock()

    token_resp = MagicMock(ok=True)
    token_resp.json.return_value = {"access_token": "gho_mock"}

    user_resp = MagicMock(ok=True)
    user_resp.json.return_value = {"id": 99999, "login": "octocat", "name": "Mona Lisa Octocat"}

    email_resp = MagicMock(ok=True)
    email_resp.json.return_value = [
        {"email": "unverified@example.com", "primary": False, "verified": False},
        {"email": "mona@github.com", "primary": True, "verified": True},
    ]

    session.post.return_value = token_resp
    session.get.side_effect = [user_resp, email_resp]

    user_info = p.exchange_code(code="auth-code", redirect_uri="https://app.com/cb", session=session)
    assert user_info.provider == "github"
    assert user_info.provider_user_id == "99999"
    assert user_info.email == "mona@github.com"
    assert user_info.display_name == "Mona Lisa Octocat"
    assert user_info.email_verified is True


def test_account_creation_and_login_via_oauth(tmp_path):
    from xibalba_cortex import accounts

    home = tmp_path / "identity"

    # 1. New user signs up via Google
    token1, acc1, created1 = accounts.authenticate_or_create_oauth_account(
        home,
        provider="google",
        provider_user_id="sub-1001",
        email="operator@xibalba.solutions",
        display_name="Xibalba Operator",
    )
    assert created1 is True
    assert acc1["email"] == "operator@xibalba.solutions"
    assert acc1["display_name"] == "Xibalba Operator"
    assert acc1["email_verified"] is True
    assert acc1["approval_status"] == "approved"
    assert token1 is not None

    # Verify session token works
    recovered = accounts.account_for_token(home, token1)
    assert recovered is not None
    assert recovered["id"] == acc1["id"]

    # 2. Existing user logs in again via Google
    token2, acc2, created2 = accounts.authenticate_or_create_oauth_account(
        home,
        provider="google",
        provider_user_id="sub-1001",
        email="operator@xibalba.solutions",
        display_name="Xibalba Operator",
    )
    assert created2 is False
    assert acc2["id"] == acc1["id"]
    assert token2 is not None

    # 3. User links another provider (e.g. GitHub) with same email
    token3, acc3, created3 = accounts.authenticate_or_create_oauth_account(
        home,
        provider="github",
        provider_user_id="gh-8888",
        email="operator@xibalba.solutions",
        display_name="GH Operator",
    )
    assert created3 is False
    assert acc3["id"] == acc1["id"]

