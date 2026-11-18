"""User management, zero-trust agent device pairing, and Stripe subscription control plane for Super-Cortex."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .plans import PLANS, WRITE_STATUSES
from .stripe_gateway import BillingUnavailable, StripeGateway

log = logging.getLogger(__name__)

SESSION_TTL_HOURS = 24 * 14
SESSION_COOKIE_NAME = "cortex_managed_session"
_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_PLACEHOLDER_WORDS = ("dummy", "replace", "placeholder")


class LimitExceeded(RuntimeError):
    """Raised when a workspace exceeds its monthly plan quota or daily registration cap."""


@dataclass(frozen=True)
class ManagedConfig:
    home: Path
    public_url: str = "http://localhost:4174"
    stripe_secret_key: str = field(default="", repr=False)
    stripe_webhook_secret: str = field(default="", repr=False)
    pro_price_id: str = ""
    team_price_id: str = ""
    stripe_live: bool = False
    allow_signup: bool = True
    signup_daily_limit: int = 50
    require_email_verification: bool = False
    supabase_url: str = "https://ftspunijfgcbkuybobhf.supabase.co"
    supabase_jwt_audience: str = "authenticated"
    google_client_id: str = ""
    google_client_secret: str = field(default="", repr=False)
    github_client_id: str = ""
    github_client_secret: str = field(default="", repr=False)
    stripe_api_version: str = "2025-06-30.basil"

    def __post_init__(self) -> None:
        object.__setattr__(self, "home", Path(self.home).expanduser().resolve())

    @property
    def billing_ready(self) -> bool:
        key_prefix = "sk_live_" if self.stripe_live else "sk_test_"
        lowered_secret = self.stripe_secret_key.lower()
        return bool(
            self.stripe_secret_key.startswith(key_prefix)
            and not any(w in lowered_secret for w in _PLACEHOLDER_WORDS)
            and self.stripe_webhook_secret.startswith("whsec_")
            and not any(w in self.stripe_webhook_secret.lower() for w in _PLACEHOLDER_WORDS)
            and self.pro_price_id.startswith("price_")
            and self.team_price_id.startswith("price_")
        )

    @classmethod
    def from_env(cls, default_home: Path | None = None) -> ManagedConfig:
        home_raw = (
            os.getenv("CORTEX_MANAGED_HOME")
            or os.getenv("SUPER_CORTEX_HOME")
            or str(default_home or (Path.home() / ".super-cortex"))
        )
        allow_signup_raw = os.getenv("CORTEX_MANAGED_ALLOW_SIGNUP", "true").lower()
        stripe_live_raw = os.getenv("CORTEX_STRIPE_LIVE", "false").lower()
        verify_raw = os.getenv("CORTEX_REQUIRE_EMAIL_VERIFICATION", "false").lower()
        google_cid = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("SUPABASE_AUTH_EXTERNAL_GOOGLE_CLIENT_ID") or ""
        google_csec = os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("SUPABASE_AUTH_EXTERNAL_GOOGLE_CLIENT_SECRET") or ""
        if not google_cid or not google_csec:
            for candidate_json in (
                Path.home() / ".config" / "xibalba-secrets" / "client_secret_209789763691-lu1kmbqgbr21b35j0gcve5g6caskv5k2.apps.googleusercontent.com.json",
                Path.home() / "client_secret_209789763691-n8hbn67l7u1a61rd8fp077r45i36tu36.apps.googleusercontent.com.json",
            ):
                if candidate_json.exists():
                    try:
                        raw = json.loads(candidate_json.read_text(encoding="utf-8"))
                        web = raw.get("web") or raw.get("installed") or {}
                        google_cid = google_cid or str(web.get("client_id") or "")
                        google_csec = google_csec or str(web.get("client_secret") or "")
                        if google_cid and google_csec:
                            break
                    except Exception:
                        pass
        github_cid = os.getenv("GITHUB_CLIENT_ID") or os.getenv("SUPABASE_AUTH_EXTERNAL_GITHUB_CLIENT_ID") or ""
        github_csec = os.getenv("GITHUB_CLIENT_SECRET") or os.getenv("SUPABASE_AUTH_EXTERNAL_GITHUB_CLIENT_SECRET") or ""
        return cls(
            home=Path(home_raw),
            public_url=os.getenv("CORTEX_MANAGED_PUBLIC_URL", "http://localhost:4174"),
            stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", ""),
            stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
            pro_price_id=os.getenv("STRIPE_PRO_MONTHLY_PRICE_ID", ""),
            team_price_id=os.getenv("STRIPE_TEAM_MONTHLY_PRICE_ID", ""),
            stripe_live=stripe_live_raw in {"1", "true", "yes"},
            allow_signup=allow_signup_raw in {"1", "true", "yes"},
            signup_daily_limit=int(os.getenv("CORTEX_MANAGED_SIGNUP_DAILY_LIMIT", "50")),
            require_email_verification=verify_raw in {"1", "true", "yes"},
            supabase_url=os.getenv("SUPABASE_URL", "https://ftspunijfgcbkuybobhf.supabase.co"),
            supabase_jwt_audience=os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated"),
            google_client_id=google_cid,
            google_client_secret=google_csec,
            github_client_id=github_cid,
            github_client_secret=github_csec,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _password_hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    return base64.urlsafe_b64encode(salt).decode("ascii"), base64.urlsafe_b64encode(digest).decode("ascii")


def _password_matches(password: str, salt_text: str, digest_text: str) -> bool:
    try:
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        _, candidate = _password_hash(password, salt)
        return hmac.compare_digest(candidate, digest_text)
    except (ValueError, TypeError):
        return False


def _random_user_code() -> str:
    part1 = "".join(secrets.choice(_CODE_CHARS) for _ in range(4))
    part2 = "".join(secrets.choice(_CODE_CHARS) for _ in range(4))
    return f"{part1}-{part2}"


_MANAGED_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    role TEXT NOT NULL DEFAULT 'operator',
    email_verified INTEGER NOT NULL DEFAULT 1,
    approval_status TEXT NOT NULL DEFAULT 'approved',
    agent_ids_json TEXT NOT NULL DEFAULT '[]',
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_managed_accounts_email ON accounts(email);

CREATE TABLE IF NOT EXISTS account_sessions (
    token_hash TEXT PRIMARY KEY,
    csrf_token TEXT NOT NULL,
    account_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    scopes_json TEXT NOT NULL DEFAULT '["memory:read","memory:write","operator:admin"]',
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_account_sessions_account ON account_sessions(account_id);

CREATE TABLE IF NOT EXISTS managed_tenants (
    id TEXT PRIMARY KEY,
    owner_account_id TEXT NOT NULL UNIQUE,
    plan TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'free',
    customer_id TEXT UNIQUE,
    subscription_id TEXT,
    period_end INTEGER,
    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS managed_usage (
    tenant_id TEXT NOT NULL,
    month TEXT NOT NULL,
    meter TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(tenant_id, month, meter)
);

CREATE TABLE IF NOT EXISTS managed_operations (
    tenant_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    PRIMARY KEY(tenant_id, request_key)
);

CREATE TABLE IF NOT EXISTS stripe_events (
    id TEXT PRIMARY KEY,
    processed_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS checkout_requests (
    tenant_id TEXT PRIMARY KEY,
    plan TEXT NOT NULL,
    attempt TEXT NOT NULL,
    checkout_id TEXT,
    url TEXT
);

CREATE TABLE IF NOT EXISTS email_verifications (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT,
    email TEXT,
    event_type TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_pairing_requests (
    id TEXT PRIMARY KEY,
    user_code TEXT NOT NULL UNIQUE,
    device_id TEXT NOT NULL,
    device_name TEXT NOT NULL,
    agent_did TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    callback_url TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    approved_account_id TEXT,
    approved_tenant_id TEXT,
    issued_token TEXT,
    redeemed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pairing_user_code ON device_pairing_requests(user_code);

CREATE TABLE IF NOT EXISTS contact_inquiries (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    organization TEXT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class ManagedControl:
    """Unified user account, agent pairing, and Stripe subscription control plane."""

    def __init__(self, config: ManagedConfig, *, stripe: StripeGateway | None = None, store: Any = None) -> None:
        self.config = config
        self.config.home.mkdir(parents=True, exist_ok=True)
        self.db_path = self.config.home / "managed_control.sqlite3"
        self.stripe = stripe or StripeGateway(config)
        self.provenance_store = store
        self._init_db()

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.db() as conn:
            conn.executescript(_MANAGED_SCHEMA)
            # Seed a default operator account if none exist so local studio has immediate operator context
            row = conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()
            if row and row["c"] == 0:
                default_acc_id = "acc_xibalba_operator"
                default_tenant_id = "tenant_xibalba_core"
                salt, digest = _password_hash("xibalba-super-cortex-operator")
                now = _now_iso()
                conn.execute(
                    """INSERT INTO accounts (
                        id, email, display_name, password_hash, password_salt,
                        profile_id, status, role, email_verified, approval_status,
                        agent_ids_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', 'operator', 1, 'approved', ?, ?, ?)""",
                    (
                        default_acc_id,
                        "operator@xibalba.dev",
                        "Xibalba Executive Operator",
                        digest,
                        salt,
                        default_tenant_id,
                        json.dumps([
                            "did:integrity:68fed1331613937555a59398223e8e87520a87dd0305aac4fd7ecdc32a14a861",
                            "did:integrity:b1a72980e8e45e97c7b92982a89b1963e470b45fa955c9bd245f046e1e32e39a",
                            "did:integrity:f07438ae1fb67f6ab1a21df87fb4771bead162c502c6e98cfa0bbdd7020a7e75",
                        ]),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO managed_tenants (
                        id, owner_account_id, plan, status, created_at
                    ) VALUES (?, ?, 'free', 'free', ?)""",
                    (default_tenant_id, default_acc_id, int(time.time())),
                )

    def _record_event(self, conn: sqlite3.Connection, profile_id: str, email: str, event_type: str, detail: str = "") -> None:
        conn.execute(
            "INSERT INTO auth_events (profile_id, email, event_type, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (profile_id, email, event_type, detail, _now_iso()),
        )

    def list_auth_events(self, profile_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.db() as conn:
            if profile_id:
                rows = conn.execute(
                    "SELECT * FROM auth_events WHERE profile_id=? ORDER BY id DESC LIMIT ?",
                    (profile_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM auth_events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # USER ACCOUNTS & AUTHENTICATION
    # -------------------------------------------------------------------------
    def register(self, *, email: str, password: str, display_name: str = "") -> dict[str, Any]:
        if not self.config.allow_signup:
            raise BillingUnavailable("Managed registration is not enabled on this deployment")
        norm_email = _normalize_email(email)
        if not norm_email or "@" not in norm_email:
            raise ValueError("A valid email address is required")
        salt, digest = _password_hash(password)
        clean_name = (display_name or norm_email.split("@")[0]).strip()[:120]

        with self.db() as conn:
            day = int(time.time()) // 86400 * 86400
            daily_count = conn.execute(
                "SELECT COUNT(*) FROM managed_tenants WHERE created_at >= ?", (day,)
            ).fetchone()[0]
            if daily_count >= self.config.signup_daily_limit:
                raise LimitExceeded("Daily registration capacity reached; try again tomorrow")

            existing = conn.execute("SELECT id FROM accounts WHERE email=?", (norm_email,)).fetchone()
            if existing:
                raise ValueError("An account with this email already exists")

            account_id = "acc_" + uuid.uuid4().hex[:20]
            tenant_id = "t-" + uuid.uuid4().hex
            now_iso = _now_iso()
            email_verified = 0 if self.config.require_email_verification else 1
            approval_status = "pending" if self.config.require_email_verification else "approved"

            conn.execute(
                """INSERT INTO accounts (
                    id, email, display_name, password_hash, password_salt,
                    profile_id, status, role, email_verified, approval_status,
                    agent_ids_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', 'operator', ?, ?, '[]', ?, ?)""",
                (
                    account_id,
                    norm_email,
                    clean_name,
                    digest,
                    salt,
                    tenant_id,
                    email_verified,
                    approval_status,
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute(
                """INSERT INTO managed_tenants (
                    id, owner_account_id, plan, status, created_at
                ) VALUES (?, ?, 'free', 'free', ?)""",
                (tenant_id, account_id, int(time.time())),
            )
            self._record_event(conn, tenant_id, norm_email, "account.signup", f"Created workspace {tenant_id}")

        # Sync into ProvenanceStore tenants table if connected
        if self.provenance_store is not None:
            try:
                from .models import TenantPlan, TenantRecord
                self.provenance_store.save_tenant(
                    TenantRecord(
                        id=tenant_id,
                        name=f"{clean_name} Workspace",
                        plan=TenantPlan.FREE.value,
                        rate_limit_rpm=60,
                        daily_quota_requests=PLANS["free"].retrievals_per_month,
                        metadata={"owner_email": norm_email, "account_id": account_id},
                    )
                )
            except Exception as exc:
                log.warning("Could not mirror tenant to ProvenanceStore: %s", exc)

        account = self.get_account_by_id(account_id)
        assert account is not None
        if self.config.require_email_verification:
            return {"verification_required": True, "account": None}
        session = self.create_session(account)
        return {"verification_required": False, "account": self._public_account(account), "session": session}

    def login(self, *, email: str, password: str) -> dict[str, Any]:
        norm_email = _normalize_email(email)
        with self.db() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE email=?", (norm_email,)).fetchone()
            if not row:
                raise PermissionError("Invalid email or password")
            account = dict(row)
            if account.get("locked_until"):
                locked_dt = datetime.fromisoformat(account["locked_until"])
                if datetime.now(timezone.utc) < locked_dt:
                    raise PermissionError("Account is temporarily locked due to failed sign-in attempts")

            if not _password_matches(password, account["password_salt"], account["password_hash"]):
                attempts = int(account.get("failed_attempts") or 0) + 1
                locked_until = None
                if attempts >= 5:
                    locked_until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
                conn.execute(
                    "UPDATE accounts SET failed_attempts=?, locked_until=?, updated_at=? WHERE id=?",
                    (attempts, locked_until, _now_iso(), account["id"]),
                )
                self._record_event(conn, account["profile_id"], norm_email, "auth.login_failed", f"Attempt {attempts}")
                raise PermissionError("Invalid email or password")

            if not account.get("email_verified"):
                raise PermissionError("Email verification is required before signing in")
            if account.get("status") != "active":
                raise PermissionError("Account is disabled")

            conn.execute(
                "UPDATE accounts SET failed_attempts=0, locked_until=NULL, updated_at=? WHERE id=?",
                (_now_iso(), account["id"]),
            )
            self._record_event(conn, account["profile_id"], norm_email, "auth.login_success", "Operator session opened")

        session = self.create_session(account)
        return {"account": self._public_account(account), "session": session}

    def create_session(self, account: dict[str, Any]) -> dict[str, Any]:
        raw_token = "cxs_" + secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        token_hash = _sha256_hex(raw_token)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
        with self.db() as conn:
            conn.execute(
                """INSERT INTO account_sessions (
                    token_hash, csrf_token, account_id, tenant_id, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (token_hash, csrf_token, account["id"], account["profile_id"], expires_at, _now_iso()),
            )
        return {
            "token": raw_token,
            "csrf_token": csrf_token,
            "expires_at": expires_at,
        }

    def revoke_session(self, raw_token: str) -> None:
        if not raw_token:
            return
        token_hash = _sha256_hex(raw_token)
        with self.db() as conn:
            conn.execute(
                "UPDATE account_sessions SET revoked_at=? WHERE token_hash=?",
                (_now_iso(), token_hash),
            )

    def authenticate_session(self, raw_token: str | None) -> tuple[dict[str, Any], dict[str, Any], str] | None:
        """Validate session cookie or bearer token and return (account, tenant, csrf_token)."""
        if not raw_token:
            return None
        token_hash = _sha256_hex(raw_token.strip())
        with self.db() as conn:
            sess = conn.execute(
                "SELECT * FROM account_sessions WHERE token_hash=? AND revoked_at IS NULL",
                (token_hash,),
            ).fetchone()
            if not sess:
                return None
            expires_at = datetime.fromisoformat(sess["expires_at"])
            if datetime.now(timezone.utc) >= expires_at:
                return None
            acc = conn.execute("SELECT * FROM accounts WHERE id=?", (sess["account_id"],)).fetchone()
            if not acc or acc["status"] != "active":
                return None
            account = dict(acc)
            tenant = self._get_or_create_tenant_in_db(conn, account)
            return account, tenant, str(sess["csrf_token"])

    def default_operator_context(self) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Return the seeded default operator account & tenant for local studio zero-friction mode."""
        with self.db() as conn:
            acc = conn.execute("SELECT * FROM accounts ORDER BY created_at ASC LIMIT 1").fetchone()
            account = dict(acc)
            tenant = self._get_or_create_tenant_in_db(conn, account)
            return account, tenant, "local_studio_csrf"

    def get_account_by_id(self, account_id: str) -> dict[str, Any] | None:
        with self.db() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            return dict(row) if row else None

    def update_account_profile(
        self, account_id: str, *, display_name: str | None = None, agent_ids: list[str] | None = None
    ) -> dict[str, Any]:
        with self.db() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            if not row:
                raise KeyError("Account not found")
            acc = dict(row)
            new_name = (display_name.strip()[:120] if display_name is not None else acc["display_name"]) or acc["display_name"]
            if agent_ids is not None:
                for did in agent_ids:
                    if not did.startswith("did:integrity:") or len(did) > 160:
                        raise ValueError("Agent IDs must be valid did:integrity: identifiers")
                new_agents = json.dumps(agent_ids)
            else:
                new_agents = acc["agent_ids_json"]
            conn.execute(
                "UPDATE accounts SET display_name=?, agent_ids_json=?, updated_at=? WHERE id=?",
                (new_name, new_agents, _now_iso(), account_id),
            )
            updated = dict(conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())
            return self._public_account(updated)

    def request_password_reset(self, email: str) -> str | None:
        norm_email = _normalize_email(email)
        with self.db() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE email=?", (norm_email,)).fetchone()
            if not row:
                return None
            raw_token = secrets.token_urlsafe(32)
            token_hash = _sha256_hex(raw_token)
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            conn.execute(
                """INSERT INTO password_reset_tokens (
                    id, account_id, token_hash, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?)""",
                ("rst_" + uuid.uuid4().hex[:16], row["id"], token_hash, expires_at, _now_iso()),
            )
            self._record_event(conn, row["profile_id"], norm_email, "auth.password_reset_requested", "Issued 30m reset token")
            return raw_token

    def confirm_password_reset(self, raw_token: str, new_password: str) -> None:
        salt, digest = _password_hash(new_password)
        token_hash = _sha256_hex(raw_token.strip())
        with self.db() as conn:
            row = conn.execute(
                "SELECT * FROM password_reset_tokens WHERE token_hash=? AND used_at IS NULL",
                (token_hash,),
            ).fetchone()
            if not row:
                raise ValueError("Invalid or expired password reset link")
            expires_at = datetime.fromisoformat(row["expires_at"])
            if datetime.now(timezone.utc) >= expires_at:
                raise ValueError("Password reset link has expired")
            now = _now_iso()
            conn.execute("UPDATE password_reset_tokens SET used_at=? WHERE id=?", (now, row["id"]))
            conn.execute(
                "UPDATE accounts SET password_hash=?, password_salt=?, failed_attempts=0, locked_until=NULL, updated_at=? WHERE id=?",
                (digest, salt, now, row["account_id"]),
            )
            conn.execute("UPDATE account_sessions SET revoked_at=? WHERE account_id=?", (now, row["account_id"]))

    @staticmethod
    def _public_account(account: dict[str, Any]) -> dict[str, Any]:
        try:
            agents = json.loads(account.get("agent_ids_json") or "[]")
        except Exception:
            agents = []
        return {
            "id": account["id"],
            "email": account["email"],
            "display_name": account["display_name"],
            "profile_id": account["profile_id"],
            "role": account.get("role", "operator"),
            "status": account.get("status", "active"),
            "email_verified": bool(account.get("email_verified", 1)),
            "approval_status": account.get("approval_status", "approved"),
            "agent_ids": agents,
            "created_at": account.get("created_at"),
        }

    def configured_oauth_providers(self) -> list[dict[str, str]]:
        providers: list[dict[str, str]] = []
        if self.config.google_client_id or self.config.supabase_url:
            providers.append({"id": "google", "name": "Google"})
        if self.config.github_client_id or self.config.supabase_url:
            providers.append({"id": "github", "name": "GitHub"})
        return providers

    # -------------------------------------------------------------------------
    # ZERO-TRUST AGENT AUTH & RFC 8628 DEVICE PAIRING
    # -------------------------------------------------------------------------
    def create_pairing_request(
        self,
        *,
        device_id: str,
        device_name: str,
        agent_did: str,
        agent_name: str = "default",
        callback_url: str | None = None,
        ttl_seconds: int = 900,
    ) -> dict[str, Any]:
        if not agent_did.startswith("did:integrity:") or len(agent_did) > 160:
            raise ValueError("agent_did must be a valid did:integrity: identifier")
        device_code = secrets.token_urlsafe(32)
        user_code = _random_user_code()
        now_epoch = int(time.time())
        expires_epoch = now_epoch + ttl_seconds
        now_iso = _now_iso()
        expires_iso = datetime.fromtimestamp(expires_epoch, timezone.utc).isoformat()

        with self.db() as conn:
            conn.execute(
                """INSERT INTO device_pairing_requests (
                    id, user_code, device_id, device_name, agent_did, agent_name,
                    callback_url, created_at, expires_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    device_code,
                    user_code,
                    device_id.strip() or "dev_local",
                    (device_name.strip() or device_id.strip() or "Local Agent Host")[:120],
                    agent_did.strip(),
                    (agent_name.strip() or "default")[:80],
                    callback_url.strip() if callback_url else None,
                    now_iso,
                    expires_iso,
                ),
            )
        base = self.config.public_url.rstrip("/")
        return {
            "device_code": device_code,
            "user_code": user_code,
            "verification_uri": f"{base}/?pair_code={user_code}#pair",
            "verification_uri_complete": f"{base}/?pair_code={user_code}#pair",
            "expires_in": ttl_seconds,
            "interval": 2,
        }

    def get_pairing_request(self, code: str) -> dict[str, Any] | None:
        code_clean = code.strip()
        if not code_clean:
            return None
        with self.db() as conn:
            row = conn.execute(
                "SELECT * FROM device_pairing_requests WHERE id=? OR user_code=?",
                (code_clean, code_clean.upper()),
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            expires_at = datetime.fromisoformat(data["expires_at"])
            if datetime.now(timezone.utc) > expires_at and data["status"] == "pending":
                conn.execute("UPDATE device_pairing_requests SET status='expired' WHERE id=?", (data["id"],))
                data["status"] = "expired"
            data["expires_in"] = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
            return data

    def approve_pairing_request(self, code: str, *, account: dict[str, Any], tenant: dict[str, Any]) -> dict[str, Any]:
        req = self.get_pairing_request(code)
        if not req:
            raise KeyError("Pairing request not found")
        if req["status"] == "expired":
            raise ValueError("Pairing request has expired")
        if req["status"] == "approved" and req.get("issued_token"):
            return {
                "status": "approved",
                "token": req["issued_token"],
                "device_id": req["device_id"],
                "device_name": req["device_name"],
                "agent_did": req["agent_did"],
                "agent_name": req["agent_name"],
                "callback_url": req.get("callback_url"),
            }

        raw_token = "sc_live_" + secrets.token_urlsafe(28)
        label = f"{req['agent_name']}@{req['device_name']} ({req['agent_did'][:26]}...)"
        if self.provenance_store is not None:
            try:
                from .models import TenantPlan, TenantRecord
                if not self.provenance_store.get_tenant(tenant["id"]):
                    self.provenance_store.save_tenant(
                        TenantRecord(
                            id=tenant["id"],
                            name=f"{account['display_name']} Workspace",
                            plan=tenant.get("plan", TenantPlan.FREE.value),
                        )
                    )
                _, raw_token = self.provenance_store.create_tenant_key(
                    tenant_id=tenant["id"],
                    label=label,
                    scopes=["memory:read", "memory:write", "read:graph", "write:memory", "exec:deterministic"],
                    rate_limit_rpm=180,
                )
                self.provenance_store.register_agent(
                    agent_id=req["agent_name"],
                    name=f"{req['agent_name']} ({req['device_name']})",
                    default_scope_id=f"agent:{req['agent_name']}",
                    client_type="paired_device",
                )
            except Exception as exc:
                log.warning("Could not register paired agent in ProvenanceStore: %s", exc)

        with self.db() as conn:
            conn.execute(
                """UPDATE device_pairing_requests
                   SET status='approved', approved_account_id=?, approved_tenant_id=?, issued_token=?
                   WHERE id=?""",
                (account["id"], tenant["id"], raw_token, req["id"]),
            )
            # Attach agent_did to account's agent_ids_json if not already present
            try:
                agent_ids = json.loads(account.get("agent_ids_json") or "[]")
            except Exception:
                agent_ids = []
            if req["agent_did"] not in agent_ids:
                agent_ids.append(req["agent_did"])
                conn.execute(
                    "UPDATE accounts SET agent_ids_json=?, updated_at=? WHERE id=?",
                    (json.dumps(agent_ids), _now_iso(), account["id"]),
                )
            self._record_event(
                conn,
                tenant["id"],
                account["email"],
                "agent.device_paired",
                f"Authorized {req['agent_name']} on {req['device_name']} ({req['agent_did']})",
            )

        return {
            "status": "approved",
            "token": raw_token,
            "device_id": req["device_id"],
            "device_name": req["device_name"],
            "agent_did": req["agent_did"],
            "agent_name": req["agent_name"],
            "callback_url": req.get("callback_url"),
        }

    def poll_pairing_status(self, code: str) -> dict[str, Any]:
        req = self.get_pairing_request(code)
        if not req:
            raise KeyError("Pairing request not found")
        if req["status"] != "approved":
            return {"status": req["status"], "expires_in": req["expires_in"]}
        token = req.get("issued_token")
        if not token or req.get("redeemed_at"):
            return {"status": "redeemed"}
        with self.db() as conn:
            conn.execute(
                "UPDATE device_pairing_requests SET redeemed_at=?, issued_token=NULL WHERE id=?",
                (_now_iso(), req["id"]),
            )
        return {
            "status": "approved",
            "token": token,
            "tenant_id": req.get("approved_tenant_id"),
            "device_id": req["device_id"],
            "agent_did": req["agent_did"],
            "agent_name": req["agent_name"],
        }

    # -------------------------------------------------------------------------
    # STRIPE SUBSCRIPTION & USAGE CONTROL PLANE
    # -------------------------------------------------------------------------
    def _get_or_create_tenant_in_db(self, conn: sqlite3.Connection, account: dict[str, Any]) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM managed_tenants WHERE owner_account_id=? OR id=?",
            (account["id"], account["profile_id"]),
        ).fetchone()
        if row:
            return dict(row)
        tenant_id = account["profile_id"] or ("t-" + uuid.uuid4().hex)
        conn.execute(
            "INSERT INTO managed_tenants (id, owner_account_id, plan, status, created_at) VALUES (?, ?, 'free', 'free', ?)",
            (tenant_id, account["id"], int(time.time())),
        )
        return dict(conn.execute("SELECT * FROM managed_tenants WHERE id=?", (tenant_id,)).fetchone())

    def tenant(self, account: dict[str, Any]) -> dict[str, Any]:
        with self.db() as conn:
            return self._get_or_create_tenant_in_db(conn, account)

    def entitlement(self, tenant: dict[str, Any]) -> dict[str, Any]:
        plan_id = tenant.get("plan") if tenant.get("plan") in PLANS else "free"
        plan = PLANS[plan_id]
        status = str(tenant.get("status") or "free")
        period_end = tenant.get("period_end")
        expired_paid = (
            plan_id != "free"
            and isinstance(period_end, int)
            and period_end < int(time.time())
            and status not in {"free"}
        )
        writable = status in WRITE_STATUSES and not expired_paid
        return {
            "plan": plan.public(),
            "status": "past_due" if expired_paid and status == "active" else status,
            "period_end": period_end,
            "cancel_at_period_end": bool(tenant.get("cancel_at_period_end")),
            "writable": writable,
        }

    def usage(self, tenant: dict[str, Any]) -> dict[str, Any]:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.db() as conn:
            rows = conn.execute(
                "SELECT meter, amount FROM managed_usage WHERE tenant_id=? AND month=?",
                (tenant["id"], month),
            ).fetchall()
        used = {row["meter"]: int(row["amount"]) for row in rows}
        # Include live stored memory count from ProvenanceStore if available
        stored_memories = 0
        if self.provenance_store is not None:
            try:
                stored_memories = len(self.provenance_store.list_memories(limit=50000))
            except Exception:
                stored_memories = 0
        used.setdefault("writes", 0)
        used.setdefault("retrievals", 0)
        used["memories"] = stored_memories
        return {"month": month, "timezone": "UTC", "used": used}

    def consume(
        self,
        tenant: dict[str, Any],
        meter: str,
        *,
        request_key: str | None = None,
        fingerprint: str = "",
    ) -> None:
        if meter not in {"writes", "retrievals"}:
            raise ValueError("unknown usage meter")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.db() as conn:
            current = dict(
                conn.execute("SELECT * FROM managed_tenants WHERE id=?", (tenant["id"],)).fetchone()
            )
            if meter == "writes" and not self.entitlement(current)["writable"]:
                raise PermissionError(
                    "Subscription is read-only; existing memories remain available for reading and export"
                )
            if request_key:
                prior = conn.execute(
                    "SELECT fingerprint FROM managed_operations WHERE tenant_id=? AND request_key=?",
                    (tenant["id"], request_key),
                ).fetchone()
                if prior:
                    if not hmac.compare_digest(prior["fingerprint"], fingerprint):
                        raise ValueError("Idempotency-Key was already used with different input")
                    return
            limit = getattr(PLANS[current["plan"]], meter + "_per_month")
            conn.execute(
                "INSERT OR IGNORE INTO managed_usage VALUES (?, ?, ?, 0)",
                (tenant["id"], month, meter),
            )
            changed = conn.execute(
                "UPDATE managed_usage SET amount=amount+1 WHERE tenant_id=? AND month=? AND meter=? AND amount<?",
                (tenant["id"], month, meter, limit),
            ).rowcount
            if not changed:
                raise LimitExceeded(f"Monthly {meter} limit reached")
            if request_key:
                conn.execute(
                    "INSERT INTO managed_operations VALUES (?, ?, ?)",
                    (tenant["id"], request_key, fingerprint),
                )

    def validate_price(self, price: dict[str, Any], plan_id: str) -> None:
        expected_id = self.config.pro_price_id if plan_id == "pro" else self.config.team_price_id
        if (
            price.get("id") != expected_id
            or price.get("currency") != "usd"
            or price.get("unit_amount") != PLANS[plan_id].monthly_cents
            or price.get("recurring", {}).get("interval") != "month"
            or price.get("recurring", {}).get("interval_count") != 1
        ):
            raise ValueError("Stripe price does not match the approved Super-Cortex catalog")

    def checkout(self, account: dict[str, Any], plan_id: str) -> dict[str, str]:
        if plan_id not in {"pro", "team"}:
            raise ValueError("Choose a paid plan: pro or team")
        price_id = self.config.pro_price_id if plan_id == "pro" else self.config.team_price_id
        if not price_id:
            raise BillingUnavailable("Stripe billing is not configured")
        self.validate_price(self.stripe.request("GET", "/prices/" + price_id), plan_id)

        tenant = self.tenant(account)
        if tenant.get("subscription_id") and tenant.get("status") not in {"canceled", "incomplete_expired"}:
            raise ValueError("Manage the existing subscription through the billing portal")

        attempt = uuid.uuid4().hex
        with self.db() as conn:
            conn.execute(
                """INSERT INTO checkout_requests (tenant_id, plan, attempt, checkout_id, url)
                   VALUES (?, ?, ?, NULL, NULL)
                   ON CONFLICT(tenant_id) DO UPDATE SET plan=excluded.plan, attempt=excluded.attempt,
                   checkout_id=NULL, url=NULL""",
                (tenant["id"], plan_id, attempt),
            )
            row = dict(conn.execute("SELECT * FROM managed_tenants WHERE id=?", (tenant["id"],)).fetchone())

        customer_id = row.get("customer_id")
        if not customer_id:
            customer = self.stripe.request(
                "POST",
                "/customers",
                data={
                    "email": account["email"],
                    "name": account["display_name"],
                    "metadata[tenant_id]": tenant["id"],
                    "metadata[account_id]": account["id"],
                },
                idempotency_key="cortex-customer:" + tenant["id"],
            )
            customer_id = str(customer["id"])
            with self.db() as conn:
                conn.execute(
                    "UPDATE managed_tenants SET customer_id=? WHERE id=?",
                    (customer_id, tenant["id"]),
                )

        base_url = self.config.public_url.rstrip("/")
        data = {
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": tenant["id"],
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": 1,
            "subscription_data[metadata][tenant_id]": tenant["id"],
            "success_url": f"{base_url}/?billing=success#billing",
            "cancel_url": f"{base_url}/?billing=canceled#billing",
        }
        session = self.stripe.request(
            "POST",
            "/checkout/sessions",
            data=data,
            idempotency_key="cortex-checkout:" + attempt,
        )
        with self.db() as conn:
            conn.execute(
                "UPDATE checkout_requests SET checkout_id=?, url=? WHERE tenant_id=?",
                (session["id"], session["url"], tenant["id"]),
            )
        return {"url": str(session["url"])}

    def portal(self, account: dict[str, Any]) -> dict[str, str]:
        tenant = self.tenant(account)
        if not tenant.get("customer_id"):
            raise ValueError("This workspace has no Stripe billing account yet")
        base_url = self.config.public_url.rstrip("/")
        result = self.stripe.request(
            "POST",
            "/billing_portal/sessions",
            data={"customer": tenant["customer_id"], "return_url": f"{base_url}/#billing"},
        )
        return {"url": str(result["url"])}

    def apply_event(self, event: dict[str, Any]) -> dict[str, Any]:
        if event.get("type") not in {
            "checkout.session.completed",
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            return {"received": True, "ignored": True}
        obj = event["data"]["object"]
        with self.db() as conn:
            if conn.execute("SELECT 1 FROM stripe_events WHERE id=?", (event["id"],)).fetchone():
                return {"received": True, "duplicate": True}
            customer_id = obj.get("customer")
            tenant = conn.execute(
                "SELECT * FROM managed_tenants WHERE customer_id=?", (customer_id,)
            ).fetchone()
            if tenant is None:
                return {"received": True, "ignored": True}
            sub_id = obj.get("subscription") if event["type"] == "checkout.session.completed" else obj.get("id")
            if not isinstance(sub_id, str) or not sub_id.startswith("sub_"):
                raise ValueError("Missing subscription reference")
            sub = self.stripe.request("GET", "/subscriptions/" + sub_id)
            if sub.get("customer") != customer_id:
                raise ValueError("Subscription customer does not match the workspace")
            if (
                tenant["subscription_id"]
                and tenant["subscription_id"] != sub_id
                and (
                    tenant["status"] not in {"canceled", "incomplete_expired"}
                    or sub.get("status") not in {"active", "trialing"}
                )
            ):
                conn.execute("INSERT INTO stripe_events VALUES (?, ?)", (event["id"], int(time.time())))
                return {"received": True, "ignored": True}
            items = sub.get("items", {}).get("data", [])
            if len(items) != 1 or items[0].get("quantity") != 1:
                raise ValueError("Subscription must contain exactly one Super-Cortex plan")
            price = items[0].get("price", {})
            plan_id = {
                self.config.pro_price_id: "pro",
                self.config.team_price_id: "team",
            }.get(price.get("id"))
            if (
                not plan_id
                or price.get("currency") != "usd"
                or price.get("unit_amount") != PLANS[plan_id].monthly_cents
                or price.get("recurring", {}).get("interval") != "month"
                or price.get("recurring", {}).get("interval_count") != 1
            ):
                raise ValueError("Subscription price does not match the configured Super-Cortex catalog")
            period_end = items[0].get("current_period_end", sub.get("current_period_end"))
            if not isinstance(period_end, int):
                raise ValueError("Subscription period is missing")
            conn.execute(
                """UPDATE managed_tenants
                   SET plan=?, status=?, subscription_id=?, period_end=?, cancel_at_period_end=?
                   WHERE id=?""",
                (
                    plan_id,
                    str(sub["status"]),
                    sub_id,
                    period_end,
                    int(bool(sub.get("cancel_at_period_end"))),
                    tenant["id"],
                ),
            )
            conn.execute("INSERT INTO stripe_events VALUES (?, ?)", (event["id"], int(time.time())))
        return {"received": True}

    def save_contact_inquiry(
        self, *, name: str, email: str, organization: str = "", message: str = ""
    ) -> dict[str, Any]:
        clean_name = name.strip()[:120]
        clean_email = _normalize_email(email)[:160]
        clean_message = message.strip()[:4000]
        if not clean_name or not clean_email or "@" not in clean_email or not clean_message:
            raise ValueError("Name, valid email, and message are required")
        inquiry_id = "inq_" + uuid.uuid4().hex[:16]
        with self.db() as conn:
            conn.execute(
                "INSERT INTO contact_inquiries (id, name, email, organization, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (inquiry_id, clean_name, clean_email, organization.strip()[:160], clean_message, _now_iso()),
            )
        return {"ok": True, "id": inquiry_id, "message": "Your inquiry has been received by Xibalba Solutions."}

    def oauth_login_or_register(
        self,
        *,
        provider: str,
        provider_user_id: str,
        email: str,
        display_name: str = "",
    ) -> dict[str, Any]:
        """Find or create a managed account from a verified OAuth identity (Google / GitHub) and open a session."""
        norm_email = _normalize_email(email)
        if not norm_email or "@" not in norm_email:
            raise ValueError("OAuth provider did not supply a valid email address")
        clean_name = (display_name or norm_email.split("@")[0]).strip()[:120]

        with self.db() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE email=?", (norm_email,)).fetchone()
            if row:
                account = dict(row)
                conn.execute(
                    "UPDATE accounts SET email_verified=1, approval_status='approved', updated_at=? WHERE id=?",
                    (_now_iso(), account["id"]),
                )
                self._record_event(
                    conn,
                    account["profile_id"],
                    norm_email,
                    f"auth.oauth_{provider}_login",
                    f"provider_uid={provider_user_id}",
                )
            else:
                account_id = "acc_" + uuid.uuid4().hex[:20]
                tenant_id = "t-" + uuid.uuid4().hex
                salt, digest = _password_hash(secrets.token_urlsafe(24))
                now_iso = _now_iso()
                conn.execute(
                    """INSERT INTO accounts (
                        id, email, display_name, password_hash, password_salt,
                        profile_id, status, role, email_verified, approval_status,
                        agent_ids_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', 'operator', 1, 'approved', '[]', ?, ?)""",
                    (
                        account_id,
                        norm_email,
                        clean_name,
                        digest,
                        salt,
                        tenant_id,
                        now_iso,
                        now_iso,
                    ),
                )
                conn.execute(
                    """INSERT INTO managed_tenants (
                        id, owner_account_id, plan, status, created_at
                    ) VALUES (?, ?, 'free', 'free', ?)""",
                    (tenant_id, account_id, int(time.time())),
                )
                self._record_event(
                    conn,
                    tenant_id,
                    norm_email,
                    f"auth.oauth_{provider}_signup",
                    f"provider_uid={provider_user_id}",
                )
                account = dict(conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())

        session = self.create_session(account)
        return {"account": self._public_account(account), "session": session, "provider": provider}

