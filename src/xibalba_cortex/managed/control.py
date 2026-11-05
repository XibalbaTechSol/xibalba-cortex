"""Subscription and usage state, kept outside the frozen canonical memory store."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import threading
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone

from .. import accounts
from ..ingest_tokens import _connect as identity_connection
from ..oauth import OAuthUserInfo
from ..store import GraphStore
from .config import ManagedConfig
from .plans import PLANS, WRITE_STATUSES
from .stripe_gateway import BillingUnavailable, StripeGateway
from .storage import ManagedDbFactoryLike, SupabaseManagedDbFactory


class LimitExceeded(RuntimeError):
    pass



class ManagedControl:
    def __init__(self, config: ManagedConfig, *, stripe=None, email_sender=None,
                 db_factory: ManagedDbFactoryLike | None = None,
                 bootstrap_schema: bool | None = None):
        self.config = config
        if bootstrap_schema is None:
            bootstrap_schema = config.storage_backend != "supabase"
        elif bootstrap_schema and config.storage_backend == "supabase":
            raise ValueError("Supabase schema must be managed by migrations, not SQLite bootstrap")
        if config.storage_backend == "supabase" and db_factory is None:
            if not config.supabase_database_url:
                raise RuntimeError("CORTEX_MANAGED_DATABASE_URL is required for Supabase managed storage")
            db_factory = SupabaseManagedDbFactory(config.supabase_database_url)
        self.identity_home = config.home / "identity"
        self.tenant_root = config.home / "tenants"
        config.home.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.tenant_root.mkdir(mode=0o700, exist_ok=True)
        self.path = config.home / "managed.sqlite3"
        self.stripe = stripe or StripeGateway(config)
        # SQLite remains the default for local mode. A Postgres/Supabase factory
        # can be injected by tests and migration tools or built from the server
        # DSN configured for the managed service.
        self._db_factory = db_factory or self._sqlite_db
        if config.storage_backend == "supabase":
            self._validate_supabase_schema()
        self._write_locks: dict[str, threading.RLock] = {}
        self._write_locks_guard = threading.Lock()
        if email_sender is None:
            from ..email_delivery import send_email
            email_sender = send_email
        self.email_sender = email_sender
        accounts._ensure_schema(self.identity_home)
        if bootstrap_schema:
            with self.db() as db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY, owner_account_id TEXT NOT NULL UNIQUE,
                    plan TEXT NOT NULL DEFAULT 'free', status TEXT NOT NULL DEFAULT 'free',
                    customer_id TEXT UNIQUE, subscription_id TEXT, period_end INTEGER,
                    cancel_at_period_end INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage (
                    tenant_id TEXT NOT NULL, month TEXT NOT NULL, meter TEXT NOT NULL,
                    amount INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(tenant_id,month,meter)
                );
                CREATE TABLE IF NOT EXISTS operations (
                    tenant_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, PRIMARY KEY(tenant_id,request_key)
                );
                CREATE TABLE IF NOT EXISTS stripe_events (id TEXT PRIMARY KEY, processed_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS checkout_requests (
                    tenant_id TEXT PRIMARY KEY, plan TEXT NOT NULL, attempt TEXT NOT NULL,
                    checkout_id TEXT, url TEXT
                );
                CREATE TABLE IF NOT EXISTS email_verifications (
                    token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires_at INTEGER NOT NULL
                );
                """)
        if bootstrap_schema:
            self.path.chmod(0o600)

    def _validate_supabase_schema(self) -> None:
        """Fail startup unless the configured Supabase database is reachable and migrated."""
        required_tables = {
            "tenants", "tenant_memberships", "usage", "operations", "stripe_events",
            "checkout_requests", "email_verifications", "auth_identity_migrations",
        }
        required_mapping_columns = {
            "auth_user_id", "legacy_account_id", "tenant_id", "migration_batch",
            "owner_link_created", "membership_role_before", "account_email",
            "account_display_name", "account_role", "account_status",
            "account_email_verified", "account_approval_status",
        }
        try:
            with self.db() as db:
                tables = {
                    row["tablename"] for row in db.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
                    ).fetchall()
                }
                columns = {
                    row["column_name"] for row in db.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema=current_schema() AND table_name='auth_identity_migrations'"
                    ).fetchall()
                }
        except Exception:
            raise RuntimeError("Supabase managed database connection or schema check failed") from None
        missing_tables = required_tables - tables
        missing_columns = required_mapping_columns - columns
        if missing_tables or missing_columns:
            raise RuntimeError("Supabase managed database is missing required Cortex migrations")

    @contextmanager
    def _sqlite_db(self, *, write=False):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def db(self, *, write=False):
        """Open the configured managed control-plane transaction."""
        return self._db_factory(write=write)

    def account_for_auth_subject(self, subject: str) -> dict | None:
        """Resolve a verified subject from the durable Supabase identity mapping."""
        with self.db() as db:
            row = db.execute(
                "SELECT m.legacy_account_id AS id,m.account_email AS email,"
                "m.account_display_name AS display_name,m.account_role AS role,"
                "m.account_status AS status,m.account_email_verified AS email_verified,"
                "m.account_approval_status AS approval_status,t.id AS profile_id "
                "FROM auth_identity_migrations m "
                "JOIN tenants t ON t.id=m.tenant_id AND t.owner_user_id=m.auth_user_id "
                "WHERE m.auth_user_id=?", (subject,)
            ).fetchone()
        return dict(row) if row else None

    def legacy_account_exists(self, email: str) -> bool:
        """Detect an unmigrated legacy account; never use email to link identities."""
        with closing(identity_connection(self.identity_home)) as identities:
            return accounts._account(self.identity_home, email) is not None

    def provision_auth_subject(self, subject: str, *, batch_id: str | None = None) -> dict:
        """Create a new Supabase-backed Cortex account after verified Auth signup.

        Existing legacy accounts are deliberately excluded; they must use the
        explicit account-ID migration path instead of email-based linking.
        """
        if not self.config.allow_signup:
            raise PermissionError("Supabase-backed Cortex signup is disabled")
        batch_id = batch_id or "supabase-provision:" + subject
        now = int(time.time())
        with self.db(write=True) as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (subject,))
            existing = db.execute(
                "SELECT auth_user_id FROM auth_identity_migrations WHERE auth_user_id=?", (subject,)
            ).fetchone()
            if existing:
                pass
            else:
                auth_user = db.execute(
                    "SELECT email,email_confirmed_at,raw_user_meta_data FROM auth.users WHERE id=?", (subject,)
                ).fetchone()
                if not auth_user or not auth_user["email"] or auth_user["email_confirmed_at"] is None:
                    raise PermissionError("A confirmed Supabase Auth user is required")
                email = str(auth_user["email"])
                if self.legacy_account_exists(email):
                    raise PermissionError("An existing Cortex account must be explicitly migrated by account ID")
                if db.execute("SELECT COUNT(*) FROM tenants WHERE created_at>=?", (now // 86400 * 86400,)).fetchone()[0] >= self.config.signup_daily_limit:
                    raise LimitExceeded("Daily registration capacity reached; try again tomorrow")
                account_id = "supabase:" + subject
                tenant = db.execute(
                    "SELECT id,owner_user_id FROM tenants WHERE owner_account_id=?", (account_id,)
                ).fetchone()
                if tenant is None:
                    tenant_id = "t-" + uuid.uuid4().hex
                    db.execute(
                        "INSERT INTO tenants(id,owner_account_id,owner_user_id,created_at,updated_at) "
                        "VALUES(?,?,?,?,?)", (tenant_id, account_id, None, now, now)
                    )
                else:
                    tenant_id = str(tenant["id"])
                    if tenant["owner_user_id"] is not None and str(tenant["owner_user_id"]) != subject:
                        raise PermissionError("Supabase account workspace is already linked to another subject")
                metadata = auth_user["raw_user_meta_data"] or {}
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                display_name = str(metadata.get("display_name") or metadata.get("full_name") or email.split("@", 1)[0])[:120]
                self._link_auth_subject_in_db(
                    db, subject, account_id, batch_id,
                    account={"email": email, "display_name": display_name, "role": "operator",
                             "status": "active", "email_verified": True, "approval_status": "approved"},
                )
        account = self.account_for_auth_subject(subject)
        if account is None:
            raise RuntimeError("Supabase account provisioning did not create a readable mapping")
        return account

    def link_auth_subject(self, subject: str, account_id: str, *, batch_id: str = "interactive") -> None:
        """Attach a Supabase subject only to its existing stable Cortex tenant."""
        with self.db(write=True) as db:
            self._link_auth_subject_in_db(db, subject, account_id, batch_id)

    @staticmethod
    def _link_auth_subject_in_db(db, subject: str, account_id: str, batch_id: str,
                                 account: dict | None = None) -> None:
        tenant = db.execute("SELECT id,owner_user_id FROM tenants WHERE owner_account_id=?", (account_id,)).fetchone()
        if tenant is None:
            raise LookupError("legacy Cortex account has no managed tenant")
        if tenant["owner_user_id"] is not None and str(tenant["owner_user_id"]) != subject:
            raise ValueError("managed tenant is already linked to another Supabase subject")
        existing = db.execute(
            "SELECT auth_user_id,legacy_account_id,tenant_id,migration_batch "
            "FROM auth_identity_migrations WHERE auth_user_id=? OR legacy_account_id=? OR tenant_id=?",
            (subject, account_id, tenant["id"]),
        ).fetchone()
        if existing:
            if (str(existing["auth_user_id"]) == subject and existing["legacy_account_id"] == account_id
                    and existing["tenant_id"] == tenant["id"] and existing["migration_batch"] == batch_id):
                return
            raise ValueError("identity is already linked by another migration batch")
        membership = db.execute(
            "SELECT role FROM tenant_memberships WHERE tenant_id=? AND user_id=?",
            (tenant["id"], subject),
        ).fetchone()
        owner_link_created = tenant["owner_user_id"] is None
        if account is None:
            auth_user = db.execute(
                "SELECT email,raw_user_meta_data,email_confirmed_at FROM auth.users WHERE id=?", (subject,)
            ).fetchone()
            if auth_user is None:
                raise LookupError("Supabase Auth user does not exist")
            metadata = auth_user["raw_user_meta_data"] or {}
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            email = str(auth_user["email"] or "")
            account = {
                "email": email,
                "display_name": str(metadata.get("display_name") or metadata.get("full_name") or email.split("@", 1)[0]),
                "role": "operator", "status": "active",
                "email_verified": auth_user["email_confirmed_at"] is not None,
                "approval_status": "approved",
            }
        db.execute(
            "INSERT INTO auth_identity_migrations(auth_user_id,legacy_account_id,tenant_id,migration_batch,"
            "owner_link_created,membership_role_before,account_email,account_display_name,account_role,"
            "account_status,account_email_verified,account_approval_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (subject, account_id, tenant["id"], batch_id, owner_link_created,
             membership["role"] if membership else None, account["email"], account["display_name"],
             account["role"], account["status"], bool(account["email_verified"]), account["approval_status"]),
        )
        if owner_link_created:
            db.execute("UPDATE tenants SET owner_user_id=? WHERE id=?", (subject, tenant["id"]))
        if membership is None:
            db.execute(
                "INSERT INTO tenant_memberships(tenant_id,user_id,role) VALUES(?,?,'owner')",
                (tenant["id"], subject),
            )
        elif membership["role"] != "owner":
            db.execute(
                "UPDATE tenant_memberships SET role='owner' WHERE tenant_id=? AND user_id=?",
                (tenant["id"], subject),
            )

    def unlink_auth_subject(self, subject: str, *, batch_id: str | None = None) -> None:
        """Rollback subject links while leaving all legacy account and tenant data intact."""
        with self.db(write=True) as db:
            self._unlink_auth_subject_in_db(db, subject, batch_id)

    @staticmethod
    def _unlink_auth_subject_in_db(db, subject: str, batch_id: str | None = None) -> None:
        predicate = "auth_user_id=?" if batch_id is None else "auth_user_id=? AND migration_batch=?"
        params = (subject,) if batch_id is None else (subject, batch_id)
        mapped = db.execute(
            "SELECT tenant_id,owner_link_created,membership_role_before "
            "FROM auth_identity_migrations WHERE " + predicate, params
        ).fetchone()
        if mapped:
            if mapped["membership_role_before"] is None:
                db.execute("DELETE FROM tenant_memberships WHERE tenant_id=? AND user_id=?", (mapped["tenant_id"], subject))
            else:
                db.execute(
                    "UPDATE tenant_memberships SET role=? WHERE tenant_id=? AND user_id=?",
                    (mapped["membership_role_before"], mapped["tenant_id"], subject),
                )
            if mapped["owner_link_created"]:
                db.execute("UPDATE tenants SET owner_user_id=NULL WHERE id=? AND owner_user_id=?",
                            (mapped["tenant_id"], subject))
            db.execute("DELETE FROM auth_identity_migrations WHERE " + predicate, params)

    def rollback_auth_subject_batch(self, batch_id: str) -> int:
        """Rollback every subject in a batch atomically, restoring captured prior state."""
        if not batch_id.strip():
            raise ValueError("batch_id is required")
        with self.db(write=True) as db:
            rows = db.execute(
                "SELECT auth_user_id FROM auth_identity_migrations WHERE migration_batch=?",
                (batch_id,),
            ).fetchall()
            for row in rows:
                self._unlink_auth_subject_in_db(db, str(row["auth_user_id"]), batch_id)
        return len(rows)

    def migrate_auth_subjects(self, links: list[dict[str, str]], *, batch_id: str, apply: bool = False) -> dict:
        """Validate or apply explicit Auth-subject to existing-account links."""
        if not batch_id.strip() or not links:
            raise ValueError("batch_id and at least one identity link are required")
        seen_subjects, seen_accounts = set(), set()
        normalized = []
        for item in links:
            subject, account_id = item.get("auth_user_id", "").strip(), item.get("legacy_account_id", "").strip()
            if not subject or not account_id or subject in seen_subjects or account_id in seen_accounts:
                raise ValueError("identity links must contain unique non-empty subjects and account IDs")
            seen_subjects.add(subject); seen_accounts.add(account_id)
            with closing(identity_connection(self.identity_home)) as identities:
                account = identities.execute("SELECT id,email,display_name,role,status,email_verified,approval_status FROM accounts WHERE id=? AND status='active'", (account_id,)).fetchone()
            with self.db() as db:
                tenant = db.execute("SELECT id,owner_user_id FROM tenants WHERE owner_account_id=?", (account_id,)).fetchone()
                prior = db.execute("SELECT legacy_account_id FROM auth_identity_migrations WHERE auth_user_id=?", (subject,)).fetchone()
            if account is None or tenant is None or not account["email_verified"] or account["approval_status"] != "approved":
                raise ValueError("each mapping must target an active, verified account with a managed tenant")
            if (tenant["owner_user_id"] is not None and str(tenant["owner_user_id"]) != subject) or (
                prior and prior["legacy_account_id"] != account_id
            ):
                raise ValueError("identity mapping conflicts with an existing subject link")
            normalized.append({"auth_user_id": subject, "legacy_account_id": account_id, "account": dict(account)})
        if apply:
            with self.db(write=True) as db:
                for item in normalized:
                    self._link_auth_subject_in_db(db, item["auth_user_id"], item["legacy_account_id"], batch_id,
                                                  account=item["account"])
        return {"batch_id": batch_id, "count": len(normalized), "applied": apply,
                "links": [{"auth_user_id": item["auth_user_id"], "legacy_account_id": item["legacy_account_id"]}
                          for item in normalized]}

    def register(self, *, email: str, password: str, display_name: str) -> None:
        if not self.config.allow_signup:
            raise BillingUnavailable("Managed registration is not enabled on this deployment")
        # A server-wide daily cap bounds free-profile provisioning even with rotating IPs.
        with self.db(write=True) as db:
            day = int(time.time()) // 86400 * 86400
            if db.execute("SELECT COUNT(*) FROM tenants WHERE created_at>=?", (day,)).fetchone()[0] >= self.config.signup_daily_limit:
                raise LimitExceeded("Daily registration capacity reached; try again tomorrow")
            tenant_id = "t-" + uuid.uuid4().hex
            account = accounts.create_account(self.identity_home, email=email, password=password,
                display_name=display_name, profile_id=tenant_id)
            if self.config.require_email_verification:
                with closing(identity_connection(self.identity_home)) as identities:
                    identities.execute("UPDATE accounts SET email_verified=0, approval_status='pending' WHERE id=?", (account["id"],))
                    identities.commit()
            db.execute("INSERT INTO tenants(id,owner_account_id,created_at) VALUES(?,?,?)", (tenant_id, account["id"], int(time.time())))
        if self.config.require_email_verification:
            self.send_verification(str(account["id"]), str(account["email"]))

    def oauth_login_or_register(self, user_info: OAuthUserInfo) -> tuple[str, dict[str, object]]:
        """Authenticate via an external OAuth provider, provisioning a tenant if new."""
        existing_acc = accounts._account(self.identity_home, user_info.email)
        conn = accounts._connect(self.identity_home)
        try:
            id_row = conn.execute(
                "SELECT account_id FROM oauth_identities WHERE provider=? AND provider_user_id=?",
                (user_info.provider, user_info.provider_user_id),
            ).fetchone()
            linked_account_id = id_row["account_id"] if id_row else None
        finally:
            conn.close()

        tenant_id = None
        if linked_account_id or existing_acc:
            target_id = linked_account_id or existing_acc["id"]
            with self.db() as db:
                tenant_row = db.execute("SELECT id FROM tenants WHERE owner_account_id=?", (target_id,)).fetchone()
                if tenant_row:
                    tenant_id = tenant_row["id"]

        if not tenant_id:
            with self.db(write=True) as db:
                day = int(time.time()) // 86400 * 86400
                if db.execute("SELECT COUNT(*) FROM tenants WHERE created_at>=?", (day,)).fetchone()[0] >= self.config.signup_daily_limit:
                    raise LimitExceeded("Daily registration capacity reached; try again tomorrow")
            tenant_id = "t-" + uuid.uuid4().hex

        token, account, created = accounts.authenticate_or_create_oauth_account(
            self.identity_home,
            provider=user_info.provider,
            provider_user_id=user_info.provider_user_id,
            email=user_info.email,
            display_name=user_info.display_name,
            profile_id=tenant_id,
        )

        with self.db(write=True) as db:
            existing_tenant = db.execute("SELECT 1 FROM tenants WHERE owner_account_id=?", (account["id"],)).fetchone()
            if not existing_tenant:
                db.execute("INSERT INTO tenants(id,owner_account_id,created_at) VALUES(?,?,?)", (tenant_id, account["id"], int(time.time())))

        self.tenant(account)
        return token, account


    def send_verification(self, account_id: str, email: str) -> None:
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.db(write=True) as db:
            db.execute("DELETE FROM email_verifications WHERE account_id=?", (account_id,))
            db.execute("INSERT INTO email_verifications VALUES(?,?,?)", (digest, account_id, int(time.time()) + 3600))
        self.email_sender(email, "Verify your Cortex account",
            "Verify your email to activate your isolated memory workspace:\n\n" + self.config.public_url.rstrip("/") + "/api/managed/verify?token=" + token)

    def resend_verification(self, email: str) -> None:
        account = accounts._account(self.identity_home, email)
        if account is None or account['email_verified']:
            return
        with self.db() as db:
            recent = db.execute('SELECT 1 FROM email_verifications WHERE account_id=? AND expires_at>?', (account['id'], int(time.time()) + 3540)).fetchone()
        if not recent:
            self.send_verification(account['id'], account['email'])

    def request_reset(self, email: str) -> None:
        account = accounts._account(self.identity_home, email)
        if account is None or not account['email_verified']:
            return
        now = datetime.now(timezone.utc)
        with closing(identity_connection(self.identity_home)) as db:
            recent = db.execute('SELECT 1 FROM password_reset_tokens WHERE account_id=? AND created_at>?',
                (account['id'], (now - timedelta(minutes=1)).isoformat())).fetchone()
            if recent:
                return
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO password_reset_tokens(id,account_id,token_hash,expires_at,created_at) VALUES(?,?,?,?,?)',
                (uuid.uuid4().hex, account['id'], hashlib.sha256(token.encode()).hexdigest(), (now + timedelta(minutes=30)).isoformat(), now.isoformat()))
            db.commit()
        self.email_sender(account['email'], 'Reset your Cortex password',
            'Reset your password with this time-limited link:\n\n' + self.config.public_url.rstrip('/') + '/managed?reset_token=' + token)

    def reset_password(self, token: str, password: str) -> bool:
        with closing(identity_connection(self.identity_home)) as db:
            row = db.execute('SELECT a.email FROM password_reset_tokens p JOIN accounts a ON a.id=p.account_id WHERE p.token_hash=? AND p.used_at IS NULL',
                (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or not accounts.reset_password(self.identity_home, reset_token=token, new_password=password):
            return False
        with closing(identity_connection(self.identity_home)) as db:
            db.execute("UPDATE ingest_tokens SET revoked_at=CURRENT_TIMESTAMP WHERE label=? AND revoked_at IS NULL", ('account:' + row['email'],))
            db.commit()
        return True

    def verify_email(self, token: str) -> bool:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.db(write=True) as db:
            row = db.execute("SELECT * FROM email_verifications WHERE token_hash=? AND expires_at>?", (digest, int(time.time()))).fetchone()
            if row is None:
                return False
            with closing(identity_connection(self.identity_home)) as identities:
                identities.execute("UPDATE accounts SET email_verified=1, approval_status='approved' WHERE id=?", (row["account_id"],))
                identities.commit()
            db.execute("DELETE FROM email_verifications WHERE account_id=?", (row["account_id"],))
        return True

    def tenant(self, account: dict) -> dict:
        with self.db() as db:
            row = db.execute("SELECT * FROM tenants WHERE owner_account_id=? AND id=?", (account["id"], account["profile_id"])).fetchone()
        if row is None:
            raise PermissionError("No managed workspace belongs to this account")
        return dict(row)

    def entitlement(self, tenant: dict) -> dict:
        plan = PLANS[tenant["plan"]]
        writable = tenant["status"] in WRITE_STATUSES
        if tenant["plan"] != "free" and (not tenant["period_end"] or tenant["period_end"] <= time.time()):
            writable = False
        return {"plan": plan.public(), "status": tenant["status"], "writable": writable,
            "period_end": tenant["period_end"], "cancel_at_period_end": bool(tenant["cancel_at_period_end"])}

    def usage(self, tenant: dict) -> dict:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.db() as db:
            rows = db.execute("SELECT meter,amount FROM usage WHERE tenant_id=? AND month=?", (tenant["id"], month)).fetchall()
        return {"month": month, "timezone": "UTC", "used": {row["meter"]: row["amount"] for row in rows}}

    def consume(self, tenant: dict, meter: str, *, request_key: str | None = None, fingerprint: str = "") -> None:
        if meter not in {"writes", "retrievals"}:
            raise ValueError("unknown usage meter")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        # Resolve current entitlement inside the same transaction as quota reservation. A
        # concurrently processed cancellation cannot leave a stale paid allowance writable.
        with self.db(write=True) as db:
            current = dict(db.execute("SELECT * FROM tenants WHERE id=?", (tenant["id"],)).fetchone())
            if meter == "writes" and not self.entitlement(current)["writable"]:
                raise PermissionError("Subscription is read-only; existing memories remain available for reading and export")
            if request_key:
                prior = db.execute("SELECT fingerprint FROM operations WHERE tenant_id=? AND request_key=?", (tenant["id"], request_key)).fetchone()
                if prior:
                    if not hmac.compare_digest(prior["fingerprint"], fingerprint):
                        raise ValueError("Idempotency-Key was already used with different input")
                    return
            limit = getattr(PLANS[current["plan"]], meter + "_per_month")
            db.execute("INSERT OR IGNORE INTO usage VALUES(?,?,?,0)", (tenant["id"], month, meter))
            changed = db.execute("UPDATE usage SET amount=amount+1 WHERE tenant_id=? AND month=? AND meter=? AND amount<?", (tenant["id"], month, meter, limit)).rowcount
            if not changed:
                raise LimitExceeded(f"Monthly {meter} limit reached")
            if request_key:
                db.execute("INSERT INTO operations VALUES(?,?,?)", (tenant["id"], request_key, fingerprint))

    @contextmanager
    def write_guard(self, tenant: dict):
        # One service worker is a deployment requirement. Each request opens a store
        # connection; serialize a tenant's capacity check plus insert across those connections.
        with self._write_locks_guard:
            lock = self._write_locks.setdefault(tenant['id'], threading.RLock())
        with lock:
            yield

    @contextmanager
    def store(self, tenant: dict):
        # The path comes exclusively from a server-generated ID authenticated via membership.
        tenant_id = tenant["id"]
        if not tenant_id.startswith("t-") or len(tenant_id) != 34 or any(c not in "0123456789abcdef" for c in tenant_id[2:]):
            raise PermissionError("Invalid managed workspace identity")
        home = self.tenant_root / tenant_id
        home.mkdir(mode=0o700, exist_ok=True)
        if home.is_symlink() or home.resolve().parent != self.tenant_root.resolve():
            raise PermissionError("Managed workspace path escaped its storage root")
        # Hosted inference is disabled until a separately metered provider is configured. No
        # shared developer Hermes profile is inherited by managed customer workloads.
        store = GraphStore(home, profile_id=tenant_id,
            quotas={"max_memories": PLANS[tenant["plan"]].max_memories},
            features={"inference": False, "embeddings": False})
        try:
            yield store
        finally:
            store.close()

    def validate_price(self, price: dict, plan_id: str) -> None:
        expected_id = self.config.pro_price_id if plan_id == 'pro' else self.config.team_price_id
        if price.get('id') != expected_id or price.get('currency') != 'usd' or price.get('unit_amount') != PLANS[plan_id].monthly_cents or price.get('recurring', {}).get('interval') != 'month' or price.get('recurring', {}).get('interval_count') != 1:
            raise ValueError('Stripe price does not match the approved Cortex catalog')

    def checkout(self, account: dict, plan_id: str) -> dict:
        if plan_id not in {"pro", "team"}:
            raise ValueError("Choose a paid plan: pro or team")
        price_id = self.config.pro_price_id if plan_id == 'pro' else self.config.team_price_id
        if not price_id:
            raise BillingUnavailable('Stripe billing is not configured')
        self.validate_price(self.stripe.request('GET', '/prices/' + price_id), plan_id)
        tenant = self.tenant(account)
        row_lock = " FOR UPDATE" if self.config.storage_backend == "supabase" else ""
        with self.db(write=True) as db:
            row = dict(db.execute("SELECT * FROM tenants WHERE id=?" + row_lock, (tenant["id"],)).fetchone())
            if row["subscription_id"] and row["status"] not in {"canceled", "incomplete_expired"}:
                raise ValueError("Manage the existing subscription through the billing portal")
            if not row["customer_id"]:
                customer = self.stripe.request("POST", "/customers", data={"email": account["email"], "metadata[tenant_id]": tenant["id"]}, idempotency_key="cortex-customer:" + tenant["id"])
                db.execute("UPDATE tenants SET customer_id=? WHERE id=?", (customer["id"], tenant["id"]))
                row["customer_id"] = customer["id"]
        # Persist the attempt before talking to Stripe. A crash after Stripe creates a session
        # reuses the same key on retry instead of creating a second billable subscription.
        with self.db(write=True) as db:
            db.execute("SELECT id FROM tenants WHERE id=?" + row_lock, (tenant["id"],)).fetchone()
            pending = db.execute("SELECT * FROM checkout_requests WHERE tenant_id=?", (tenant["id"],)).fetchone()
            if pending and pending["checkout_id"]:
                session = self.stripe.request("GET", "/checkout/sessions/" + pending["checkout_id"])
                if session.get("status") == "open":
                    if pending["plan"] != plan_id:
                        raise ValueError("Finish or expire the existing checkout before choosing a different plan")
                    return {"url": session["url"]}
                if session.get("status") == "complete":
                    raise ValueError("Payment is processing; wait for subscription confirmation")
                db.execute("DELETE FROM checkout_requests WHERE tenant_id=?", (tenant["id"],))
                pending = None
            if pending and pending["plan"] != plan_id:
                raise ValueError("Retry the pending plan before choosing a different plan")
            if not pending:
                db.execute("INSERT INTO checkout_requests VALUES(?,?,?,?,?)", (tenant["id"], plan_id, uuid.uuid4().hex, None, None))
        with self.db(write=True) as db:
            pending = db.execute("SELECT * FROM checkout_requests WHERE tenant_id=?", (tenant["id"],)).fetchone()
            if not pending or pending["plan"] != plan_id:
                raise ValueError("Checkout changed; retry the selected plan")
            current = db.execute("SELECT subscription_id,status FROM tenants WHERE id=?", (tenant["id"],)).fetchone()
            if current["subscription_id"] and current["status"] not in {"canceled", "incomplete_expired"}:
                raise ValueError("Manage the existing subscription through the billing portal")
            data = {"mode": "subscription", "customer": row["customer_id"], "client_reference_id": tenant["id"],
                "line_items[0][price]": self.config.pro_price_id if plan_id == "pro" else self.config.team_price_id,
                "line_items[0][quantity]": 1, "subscription_data[metadata][tenant_id]": tenant["id"],
                "success_url": self.config.public_url.rstrip("/") + "/managed?checkout=success",
                "cancel_url": self.config.public_url.rstrip("/") + "/managed?checkout=canceled"}
            session = self.stripe.request("POST", "/checkout/sessions", data=data, idempotency_key="cortex-checkout:" + pending["attempt"])
            db.execute("UPDATE checkout_requests SET checkout_id=?,url=? WHERE tenant_id=?", (session["id"], session["url"], tenant["id"]))
        return {"url": session["url"]}

    def portal(self, account: dict) -> dict:
        tenant = self.tenant(account)
        if not tenant["customer_id"]:
            raise ValueError("This workspace has no Stripe billing account yet")
        result = self.stripe.request("POST", "/billing_portal/sessions", data={"customer": tenant["customer_id"], "return_url": self.config.public_url.rstrip("/") + "/managed"})
        return {"url": result["url"]}

    def apply_event(self, event: dict) -> dict:
        if event["type"] not in {"checkout.session.completed", "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
            return {"received": True, "ignored": True}
        obj = event["data"]["object"]
        with self.db(write=True) as db:
            if db.execute("SELECT 1 FROM stripe_events WHERE id=?", (event["id"],)).fetchone():
                return {"received": True, "duplicate": True}
            customer_id = obj.get("customer")
            tenant = db.execute("SELECT * FROM tenants WHERE customer_id=?", (customer_id,)).fetchone()
            if tenant is None:
                # Events for unrelated Stripe products/accounts grant no Cortex access.
                return {"received": True, "ignored": True}
            sub_id = obj.get("subscription") if event["type"] == "checkout.session.completed" else obj.get("id")
            if not isinstance(sub_id, str) or not sub_id.startswith("sub_"):
                raise ValueError("Missing subscription reference")
            # Re-read current provider state: delivery order and event timestamps do not
            # determine entitlements. Serialize application with other billing updates.
            sub = self.stripe.request("GET", "/subscriptions/" + sub_id)
            if sub.get("customer") != customer_id:
                raise ValueError("Subscription customer does not match the workspace")
            if tenant["subscription_id"] and tenant["subscription_id"] != sub_id and (tenant["status"] not in {"canceled", "incomplete_expired"} or sub.get("status") not in {"active", "trialing"}):
                db.execute("INSERT INTO stripe_events VALUES(?,?)", (event["id"], int(time.time())))
                return {"received": True, "ignored": True}
            items = sub.get("items", {}).get("data", [])
            if len(items) != 1 or items[0].get("quantity") != 1:
                raise ValueError("Subscription must contain exactly one Cortex plan")
            price = items[0].get("price", {})
            plan_id = {self.config.pro_price_id: "pro", self.config.team_price_id: "team"}.get(price.get("id"))
            if not plan_id or price.get("currency") != "usd" or price.get("unit_amount") != PLANS[plan_id].monthly_cents or price.get("recurring", {}).get("interval") != "month" or price.get("recurring", {}).get("interval_count") != 1:
                raise ValueError("Subscription price does not match the configured Cortex catalog")
            period_end = items[0].get("current_period_end", sub.get("current_period_end"))
            if not isinstance(period_end, int):
                raise ValueError("Subscription period is missing")
            db.execute("UPDATE tenants SET plan=?,status=?,subscription_id=?,period_end=?,cancel_at_period_end=? WHERE id=?", (plan_id, str(sub["status"]), sub_id, period_end, int(bool(sub.get("cancel_at_period_end"))), tenant["id"]))
            db.execute("INSERT INTO stripe_events VALUES(?,?)", (event["id"], int(time.time())))
        return {"received": True}
