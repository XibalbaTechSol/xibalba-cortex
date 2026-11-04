"""OIDC and OAuth 2.0 social authentication provider integration."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import requests


class OAuthError(RuntimeError):
    """Raised when an OAuth / OIDC authorization or token exchange fails."""


@dataclass(frozen=True)
class OAuthUserInfo:
    provider: str
    provider_user_id: str
    email: str
    display_name: str
    email_verified: bool
    raw: dict[str, Any] = field(default_factory=dict)


def generate_pkce() -> tuple[str, str]:
    """Generate a high-entropy PKCE code_verifier and code_challenge (S256)."""
    # code_verifier: 43 to 128 characters (RFC 7636)
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def sign_oauth_state(
    secret: bytes | str,
    *,
    provider: str,
    code_verifier: str,
    redirect_uri: str = "",
    ttl_seconds: int = 600,
) -> str:
    """Pack and sign an HMAC-SHA256 state string to protect against CSRF and replay attacks."""
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    now = int(time.time())
    payload = {
        "p": provider,
        "v": code_verifier,
        "r": redirect_uri,
        "t": now,
        "exp": now + ttl_seconds,
        "n": secrets.token_hex(16),
    }
    raw_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(secret_bytes, raw_json, hashlib.sha256).digest()
    p_b64 = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    s_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{p_b64}.{s_b64}"


def verify_oauth_state(
    secret: bytes | str,
    state_token: str,
    expected_provider: str,
) -> dict[str, Any]:
    """Verify state token signature, expiration, and provider binding."""
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    parts = state_token.split(".")
    if len(parts) != 2:
        raise OAuthError("Malformed OAuth state token")
    p_b64, s_b64 = parts
    try:
        p_padding = "=" * (-len(p_b64) % 4)
        raw_json = base64.urlsafe_b64decode(p_b64 + p_padding)
        s_padding = "=" * (-len(s_b64) % 4)
        expected_sig = base64.urlsafe_b64decode(s_b64 + s_padding)
    except Exception as exc:
        raise OAuthError("Invalid base64 encoding in state token") from exc

    actual_sig = hmac.new(secret_bytes, raw_json, hashlib.sha256).digest()
    if not hmac.compare_digest(actual_sig, expected_sig):
        raise OAuthError("Invalid or tampered OAuth state signature")

    try:
        payload = json.loads(raw_json.decode("utf-8"))
    except Exception as exc:
        raise OAuthError("Invalid JSON in OAuth state") from exc

    if payload.get("p") != expected_provider:
        raise OAuthError(f"OAuth state provider mismatch: expected {expected_provider}, got {payload.get('p')}")

    now = int(time.time())
    if payload.get("exp", 0) < now:
        raise OAuthError("OAuth state has expired; please restart the sign-in flow")

    return payload


class OAuthProvider:
    """Base class for social and enterprise OIDC/OAuth providers."""

    def authorization_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        raise NotImplementedError

    def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> OAuthUserInfo:
        raise NotImplementedError


class GoogleOAuthProvider(OAuthProvider):
    AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def authorization_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        if not self.configured:
            raise OAuthError("Google OAuth is not configured on this server")
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{self.AUTH_ENDPOINT}?{urlencode(params)}"

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        session: requests.Session | None = None,
    ) -> OAuthUserInfo:
        if not self.configured:
            raise OAuthError("Google OAuth is not configured on this server")
        http = session or requests
        token_payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        resp = http.post(self.TOKEN_ENDPOINT, data=token_payload, timeout=15)
        if not resp.ok:
            raise OAuthError(f"Google token exchange failed: {resp.status_code}")
        tokens = resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise OAuthError("Google did not return an access token")

        user_resp = http.get(self.USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
        if not user_resp.ok:
            raise OAuthError(f"Google userinfo request failed: {user_resp.status_code}")
        info = user_resp.json()

        email = str(info.get("email", "")).strip().lower()
        sub = str(info.get("sub", "")).strip()
        display_name = str(info.get("name") or info.get("given_name") or email.split("@")[0]).strip()
        email_verified = bool(info.get("email_verified", False))

        if not email or not sub:
            raise OAuthError("Incomplete profile data from Google")
        if not email_verified:
            raise OAuthError("Google account email is not verified; cannot be used for authentication")

        return OAuthUserInfo(
            provider="google",
            provider_user_id=sub,
            email=email,
            display_name=display_name,
            email_verified=email_verified,
            raw=info,
        )


class GitHubOAuthProvider(OAuthProvider):
    AUTH_ENDPOINT = "https://github.com/login/oauth/authorize"
    TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
    USER_ENDPOINT = "https://api.github.com/user"
    EMAILS_ENDPOINT = "https://api.github.com/user/emails"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def authorization_url(self, *, state: str, code_challenge: str = "", redirect_uri: str) -> str:
        if not self.configured:
            raise OAuthError("GitHub OAuth is not configured on this server")
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
            "allow_signup": "true",
        }
        return f"{self.AUTH_ENDPOINT}?{urlencode(params)}"

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str = "",
        redirect_uri: str = "",
        session: requests.Session | None = None,
    ) -> OAuthUserInfo:
        if not self.configured:
            raise OAuthError("GitHub OAuth is not configured on this server")
        http = session or requests
        token_payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        resp = http.post(
            self.TOKEN_ENDPOINT,
            data=token_payload,
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if not resp.ok:
            raise OAuthError(f"GitHub token exchange failed: {resp.status_code}")
        tokens = resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            err = tokens.get("error_description") or tokens.get("error") or "no access token"
            raise OAuthError(f"GitHub did not return an access token: {err}")

        user_resp = http.get(
            self.USER_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            timeout=15,
        )
        if not user_resp.ok:
            raise OAuthError("GitHub user request failed")
        user = user_resp.json()
        gh_id = str(user.get("id", "")).strip()
        display_name = str(user.get("name") or user.get("login") or "GitHub User").strip()

        # Fetch emails to guarantee verified primary email
        email_resp = http.get(
            self.EMAILS_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
            timeout=15,
        )
        primary_email = ""
        email_verified = False
        if email_resp.ok:
            emails = email_resp.json()
            if isinstance(emails, list):
                for item in emails:
                    if item.get("primary") and item.get("verified"):
                        primary_email = str(item.get("email", "")).strip().lower()
                        email_verified = True
                        break
                if not primary_email:
                    for item in emails:
                        if item.get("verified"):
                            primary_email = str(item.get("email", "")).strip().lower()
                            email_verified = True
                            break

        if not primary_email and user.get("email"):
            primary_email = str(user.get("email")).strip().lower()
            email_verified = True

        if not gh_id or not primary_email or not email_verified:
            raise OAuthError("A verified email address is required from your GitHub account")

        return OAuthUserInfo(
            provider="github",
            provider_user_id=gh_id,
            email=primary_email,
            display_name=display_name,
            email_verified=email_verified,
            raw=user,
        )


def get_oauth_provider(name: str, client_id: str, client_secret: str) -> GoogleOAuthProvider | GitHubOAuthProvider:
    clean = str(name).strip().lower()
    if clean == "google":
        return GoogleOAuthProvider(client_id, client_secret)
    elif clean == "github":
        return GitHubOAuthProvider(client_id, client_secret)
    raise OAuthError(f"Unsupported OAuth provider: {name}")

