"""Subscription and usage state, kept outside the frozen canonical memory store."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
import threading
import uuid
import logging
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone

from .. import accounts
from ..ingest_tokens import _connect as identity_connection
from ..store import GraphStore
from .config import ManagedConfig
from .plans import PLANS, WRITE_STATUSES
from .stripe_gateway import BillingUnavailable, StripeGateway
from .supabase_adapter import SupabaseAdapter


class LimitExceeded(RuntimeError):
    pass

log = logging.getLogger(__name__)


class ManagedControl:
    def __init__(self, config: ManagedConfig, *, stripe=None, email_sender=None):
        self.config = config
        self.identity_home = config.home / "identity"
        self.tenant_root = config.home / "tenants"
        config.home.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.tenant_root.mkdir(mode=0o700, exist_ok=True)
        self.path = config.home / "managed.sqlite3"
        self.stripe = stripe or StripeGateway(config)
        self.supabase = SupabaseAdapter(config.supabase_url, config.supabase_service_role_key) if config.supabase_url and config.supabase_service_role_key else None
        self._write_locks: dict[str, threading.RLock] = {}
        self._write_locks_guard = threading.Lock()
        if email_sender is None:
            from ..email_delivery import send_email
            email_sender = send_email
        self.email_sender = email_sender
        accounts._ensure_schema(self.identity_home)
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
        self.path.chmod(0o600)

    @contextmanager
    def db(self, *, write=False):
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
            with closing(identity_connection(self.identity_home)) as identities:
                identities.execute("UPDATE accounts SET email_verified=0, approval_status='pending' WHERE id=?", (account["id"],))
                identities.commit()
            db.execute("INSERT INTO tenants(id,owner_account_id,created_at) VALUES(?,?,?)", (tenant_id, account["id"], int(time.time())))
        if self.supabase:
            try:
                self.supabase.mirror_tenant({"id": tenant_id, "owner_account_id": account["id"], "plan": "free", "status": "free", "customer_id": None, "subscription_id": None, "period_end": None, "cancel_at_period_end": False})
            except Exception:
                log.exception("Supabase tenant mirror failed")
        self.send_verification(str(account["id"]), str(account["email"]))

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
            if self.supabase:
                try:
                    amount = db.execute("SELECT amount FROM usage WHERE tenant_id=? AND month=? AND meter=?", (tenant["id"], month, meter)).fetchone()["amount"]
                    self.supabase.mirror_usage(tenant["id"], month, meter, int(amount))
                except Exception:
                    log.exception("Supabase usage mirror failed")

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
        with self.db(write=True) as db:
            row = dict(db.execute("SELECT * FROM tenants WHERE id=?", (tenant["id"],)).fetchone())
            if row["subscription_id"] and row["status"] not in {"canceled", "incomplete_expired"}:
                raise ValueError("Manage the existing subscription through the billing portal")
            if not row["customer_id"]:
                customer = self.stripe.request("POST", "/customers", data={"email": account["email"], "metadata[tenant_id]": tenant["id"]}, idempotency_key="cortex-customer:" + tenant["id"])
                db.execute("UPDATE tenants SET customer_id=? WHERE id=?", (customer["id"], tenant["id"]))
                row["customer_id"] = customer["id"]
        # Persist the attempt before talking to Stripe. A crash after Stripe creates a session
        # reuses the same key on retry instead of creating a second billable subscription.
        with self.db(write=True) as db:
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
            mirrored = dict(tenant)
            mirrored.update({"plan": plan_id, "status": str(sub["status"]), "subscription_id": sub_id, "period_end": period_end, "cancel_at_period_end": bool(sub.get("cancel_at_period_end"))})
            if self.supabase:
                try:
                    self.supabase._request("PATCH", "cortex_tenants", payload={k: mirrored[k] for k in ("plan", "status", "subscription_id", "period_end", "cancel_at_period_end")}, params={"id": "eq." + tenant["id"]})
                except Exception:
                    log.exception("Supabase subscription mirror failed")
            db.execute("INSERT INTO stripe_events VALUES(?,?)", (event["id"], int(time.time())))
        return {"received": True}
