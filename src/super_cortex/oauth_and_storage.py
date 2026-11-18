"""Google & GitHub OAuth 2.0 PKCE providers and Render/Supabase durable SQLite snapshot sync."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import sqlite3
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode((encoded + padding).encode("ascii"))


def generate_pkce() -> tuple[str, str]:
    """Generate RFC 7636 PKCE (code_verifier, code_challenge) using S256."""
    verifier = _b64url_encode(secrets.token_bytes(32))
    challenge = _b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def sign_oauth_state(
    payload: dict[str, Any],
    secret: str,
    *,
    ttl_seconds: int = 600,
) -> str:
    """Create an HMAC-SHA256 signed OAuth state token with embedded expiration."""
    now = int(time.time())
    body = {
        **payload,
        "iat": now,
        "exp": now + ttl_seconds,
        "nonce": secrets.token_hex(8),
    }
    encoded_body = _b64url_encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    key = (secret or "super-cortex-oauth-default-secret").encode("utf-8")
    sig = _b64url_encode(hmac.new(key, encoded_body.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded_body}.{sig}"


def verify_oauth_state(token: str, secret: str) -> dict[str, Any]:
    """Verify an HMAC-SHA256 signed OAuth state token and return its decoded payload."""
    if not token or "." not in token:
        raise ValueError("Invalid OAuth state format")
    encoded_body, sig = token.split(".", 1)
    key = (secret or "super-cortex-oauth-default-secret").encode("utf-8")
    expected_sig = _b64url_encode(hmac.new(key, encoded_body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("OAuth state signature verification failed")
    payload = json.loads(_b64url_decode(encoded_body).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("OAuth state token has expired")
    return payload


@dataclass(frozen=True)
class OAuthProfile:
    provider: str
    provider_user_id: str
    email: str
    display_name: str
    avatar_url: str = ""
    email_verified: bool = True


class GoogleOAuthProvider:
    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def build_authorize_url(self, state: str, code_challenge: str | None = None) -> str:
        params: dict[str, str] = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{self.AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_profile(self, code: str, code_verifier: str | None = None) -> OAuthProfile:
        data: dict[str, str] = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        req = urllib.request.Request(
            self.TOKEN_URL,
            data=urllib.parse.urlencode(data).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_payload = json.loads(resp.read().decode("utf-8"))
        access_token = token_payload.get("access_token")
        if not access_token:
            raise RuntimeError("Google OAuth token exchange returned no access_token")

        info_req = urllib.request.Request(
            self.USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(info_req, timeout=15) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        email = str(info.get("email") or "").strip().lower()
        if not email:
            raise RuntimeError("Google OAuth userinfo did not return an email address")
        return OAuthProfile(
            provider="google",
            provider_user_id=str(info.get("sub") or email),
            email=email,
            display_name=str(info.get("name") or email.split("@")[0]),
            avatar_url=str(info.get("picture") or ""),
            email_verified=bool(info.get("email_verified", True)),
        )


class GitHubOAuthProvider:
    AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    USER_URL = "https://api.github.com/user"
    EMAILS_URL = "https://api.github.com/user/emails"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def build_authorize_url(self, state: str, code_challenge: str | None = None) -> str:
        params: dict[str, str] = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{self.AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_profile(self, code: str, code_verifier: str | None = None) -> OAuthProfile:
        data: dict[str, str] = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        req = urllib.request.Request(
            self.TOKEN_URL,
            data=urllib.parse.urlencode(data).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_payload = json.loads(resp.read().decode("utf-8"))
        access_token = token_payload.get("access_token")
        if not access_token:
            raise RuntimeError("GitHub OAuth token exchange returned no access_token")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Super-Cortex-OAuth/1.0",
        }
        user_req = urllib.request.Request(self.USER_URL, headers=headers, method="GET")
        with urllib.request.urlopen(user_req, timeout=15) as resp:
            user = json.loads(resp.read().decode("utf-8"))

        email = str(user.get("email") or "").strip().lower()
        verified = True
        if not email:
            emails_req = urllib.request.Request(self.EMAILS_URL, headers=headers, method="GET")
            with urllib.request.urlopen(emails_req, timeout=15) as resp:
                emails = json.loads(resp.read().decode("utf-8"))
            primary = next(
                (item for item in emails if item.get("primary") and item.get("verified")),
                next((item for item in emails if item.get("verified")), None),
            )
            if primary:
                email = str(primary.get("email") or "").strip().lower()
                verified = bool(primary.get("verified", True))
        if not email:
            raise RuntimeError("GitHub OAuth account has no verified email address")

        return OAuthProfile(
            provider="github",
            provider_user_id=str(user.get("id") or user.get("login") or email),
            email=email,
            display_name=str(user.get("name") or user.get("login") or email.split("@")[0]),
            avatar_url=str(user.get("avatar_url") or ""),
            email_verified=verified,
        )


DEFAULT_SUPABASE_URL = "https://ftspunijfgcbkuybobhf.supabase.co"
DEFAULT_SUPABASE_AUDIENCE = "authenticated"
SUPPORTED_OAUTH_PROVIDERS = ("google", "github")


class SupabaseAuthError(RuntimeError):
    """Raised when Supabase Auth JWT or user verification fails."""


class SupabaseAuthVerifier:
    """Shared Supabase Auth broker verifier (used across Super-Cortex, Xibalba Shield, and Integrity Console)."""

    def __init__(
        self,
        supabase_url: str | None = None,
        audience: str | None = None,
        jwks_client: Any = None,
    ) -> None:
        raw_url = supabase_url or os.getenv("SUPABASE_URL", DEFAULT_SUPABASE_URL)
        self.supabase_url = raw_url.strip().rstrip("/")
        self.audience = (audience or os.getenv("SUPABASE_JWT_AUDIENCE", DEFAULT_SUPABASE_AUDIENCE)).strip()
        self.jwks_url = f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
        self._jwks_client = jwks_client

    def get_authorization_url(self, provider: str, redirect_to: str) -> str:
        provider_norm = provider.strip().lower()
        if provider_norm not in SUPPORTED_OAUTH_PROVIDERS:
            raise ValueError(f"Unsupported OAuth provider: {provider}")
        params = {
            "provider": provider_norm,
            "redirect_to": redirect_to.strip(),
        }
        return f"{self.supabase_url}/auth/v1/authorize?{urllib.parse.urlencode(params)}"

    def verify_token(self, token: str) -> dict[str, Any]:
        cleaned = token.strip()
        if not cleaned or len(cleaned) > 16384:
            raise SupabaseAuthError("Missing or malformed Supabase access token")
        try:
            import jwt
            from jwt import PyJWKClient

            if self._jwks_client is None:
                self._jwks_client = PyJWKClient(self.jwks_url, timeout=10)
            signing_key = self._jwks_client.get_signing_key_from_jwt(cleaned)
            claims = jwt.decode(
                cleaned,
                signing_key.key,
                algorithms=["RS256", "ES256", "EdDSA"],
                audience=self.audience,
                options={
                    "verify_exp": True,
                    "verify_aud": bool(self.audience),
                },
            )
            return dict(claims)
        except Exception as exc:
            raise SupabaseAuthError(f"Invalid or expired Supabase token: {exc}") from exc



class SupabaseSnapshotSync:
    """Durable SQLite snapshot sync for stateless Render containers using Supabase REST or local backup target."""

    def __init__(
        self,
        *,
        supabase_url: str | None = None,
        supabase_service_key: str | None = None,
        snapshot_dir: Path | None = None,
    ) -> None:
        self.supabase_url = (supabase_url or os.getenv("SUPABASE_URL") or "").rstrip("/")
        self.supabase_service_key = (
            supabase_service_key
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
            or ""
        )
        default_snap_dir = os.getenv("SUPER_CORTEX_SNAPSHOT_DIR")
        self.snapshot_dir = Path(default_snap_dir) if default_snap_dir else snapshot_dir

    @property
    def enabled(self) -> bool:
        return bool((self.supabase_url and self.supabase_service_key) or self.snapshot_dir)

    def create_clean_sqlite_snapshot(self, source_db: Path) -> bytes:
        """Use sqlite3 backup API to produce a consistent byte snapshot even while WAL is active."""
        if not source_db.exists():
            return b""
        with tempfile.TemporaryDirectory(prefix="super_cortex_snap_") as tmp:
            dest = Path(tmp) / source_db.name
            src_conn = sqlite3.connect(str(source_db), timeout=30.0)
            dst_conn = sqlite3.connect(str(dest), timeout=30.0)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()
            return dest.read_bytes()

    def backup_database(self, db_path: Path, snapshot_key: str = "provenance.db") -> dict[str, Any]:
        """Backup SQLite database to local snapshot directory and/or Supabase Storage."""
        raw_bytes = self.create_clean_sqlite_snapshot(db_path)
        if not raw_bytes:
            return {"backed_up": False, "reason": "source_db_missing", "bytes": 0}
        sha256_digest = hashlib.sha256(raw_bytes).hexdigest()

        if self.snapshot_dir is not None:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            target = self.snapshot_dir / snapshot_key
            target.write_bytes(raw_bytes)
            meta_target = self.snapshot_dir / f"{snapshot_key}.meta.json"
            meta_target.write_text(
                json.dumps(
                    {
                        "snapshot_key": snapshot_key,
                        "bytes": len(raw_bytes),
                        "sha256": sha256_digest,
                        "updated_at": int(time.time()),
                    }
                ),
                encoding="utf-8",
            )
            return {
                "backed_up": True,
                "backend": "local_snapshot_dir",
                "snapshot_key": snapshot_key,
                "bytes": len(raw_bytes),
                "sha256": sha256_digest,
            }

        if self.supabase_url and self.supabase_service_key:
            bucket = os.getenv("SUPER_CORTEX_SUPABASE_BUCKET", "cortex-snapshots")
            url = f"{self.supabase_url}/storage/v1/object/{bucket}/{snapshot_key}"
            req = urllib.request.Request(
                url,
                data=raw_bytes,
                headers={
                    "Authorization": f"Bearer {self.supabase_service_key}",
                    "apikey": self.supabase_service_key,
                    "Content-Type": "application/octet-stream",
                    "x-upsert": "true",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                _ = resp.read()
            return {
                "backed_up": True,
                "backend": "supabase_storage",
                "snapshot_key": snapshot_key,
                "bytes": len(raw_bytes),
                "sha256": sha256_digest,
            }

        return {"backed_up": False, "reason": "no_snapshot_backend_configured", "bytes": len(raw_bytes)}

    def restore_database(self, db_path: Path, snapshot_key: str = "provenance.db") -> dict[str, Any]:
        """Restore SQLite database from snapshot storage if available."""
        raw_bytes: bytes | None = None
        backend = "none"

        if self.snapshot_dir is not None:
            candidate = self.snapshot_dir / snapshot_key
            if candidate.exists():
                raw_bytes = candidate.read_bytes()
                backend = "local_snapshot_dir"
        elif self.supabase_url and self.supabase_service_key:
            bucket = os.getenv("SUPER_CORTEX_SUPABASE_BUCKET", "cortex-snapshots")
            url = f"{self.supabase_url}/storage/v1/object/{bucket}/{snapshot_key}"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.supabase_service_key}",
                    "apikey": self.supabase_service_key,
                },
                method="GET",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw_bytes = resp.read()
                    backend = "supabase_storage"
            except Exception as exc:
                log.warning("Could not restore snapshot %s from Supabase: %s", snapshot_key, exc)

        if not raw_bytes:
            return {"restored": False, "backend": backend, "bytes": 0}

        db_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(db_path.parent), delete=False, suffix=".restore") as tmp_file:
            tmp_file.write(raw_bytes)
            tmp_path = Path(tmp_file.name)
        shutil.move(str(tmp_path), str(db_path))
        return {
            "restored": True,
            "backend": backend,
            "snapshot_key": snapshot_key,
            "bytes": len(raw_bytes),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        }
