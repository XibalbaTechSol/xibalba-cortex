from __future__ import annotations

import hashlib
import hmac
import json
import time
import pytest

from super_cortex.managed import LimitExceeded, ManagedConfig, ManagedControl
from super_cortex.plans import PLANS
from super_cortex.store import ProvenanceStore
from super_cortex.stripe_gateway import BillingUnavailable, StripeConfig, StripeGateway


class FakeStripeGateway(StripeGateway):
    def __init__(self, config: ManagedConfig):
        super().__init__(config)
        self.calls: list[tuple[str, str, dict | None, str | None]] = []
        self.subscription_state: dict = {
            "id": "sub_test_123",
            "customer": "cus_test_123",
            "status": "active",
            "current_period_end": int(time.time()) + 86400 * 30,
            "cancel_at_period_end": False,
            "items": {
                "data": [
                    {
                        "quantity": 1,
                        "current_period_end": int(time.time()) + 86400 * 30,
                        "price": {
                            "id": config.pro_price_id or "price_pro_test",
                            "currency": "usd",
                            "unit_amount": PLANS["pro"].monthly_cents,
                            "recurring": {"interval": "month", "interval_count": 1},
                        },
                    }
                ]
            },
        }

    def request(self, method: str, path: str, *, data=None, idempotency_key=None) -> dict:
        self.calls.append((method, path, dict(data) if data else None, idempotency_key))
        if path.startswith("/prices/"):
            price_id = path.split("/")[-1]
            plan_id = "pro" if price_id == self.managed_config.pro_price_id else "team"
            return {
                "id": price_id,
                "currency": "usd",
                "unit_amount": PLANS[plan_id].monthly_cents,
                "recurring": {"interval": "month", "interval_count": 1},
            }
        if path == "/customers":
            return {"id": "cus_test_123"}
        if path == "/checkout/sessions":
            return {"id": "cs_test_123", "url": "https://checkout.stripe.com/c/pay/cs_test_123"}
        if path == "/billing_portal/sessions":
            return {"id": "bps_test_123", "url": "https://billing.stripe.com/p/session/bps_test_123"}
        if path.startswith("/subscriptions/"):
            return self.subscription_state
        return {"ok": True}


def test_stripe_config_rejects_placeholders():
    dummy = StripeConfig(secret_key="sk_test_" + "dummy_key", webhook_secret="whsec_" + "real123")
    assert dummy.billing_ready is False

    real = StripeConfig(secret_key="sk_test_" + "a1b2c3d4", webhook_secret="whsec_" + "a1b2c3d4")
    assert real.billing_ready is True


def test_stripe_webhook_signature_verification():
    cfg = StripeConfig(secret_key="sk_test_" + "a1b2c3d4", webhook_secret="whsec_" + "testsecret123", live=False)
    gw = StripeGateway(cfg)
    now = int(time.time())
    payload = json.dumps({
        "id": "evt_test_001",
        "type": "checkout.session.completed",
        "livemode": False,
        "data": {"object": {"id": "cs_123", "customer": "cus_123", "subscription": "sub_123"}},
    }).encode("utf-8")
    sig_hex = hmac.new(
        b"whsec_testsecret123",
        f"{now}.".encode("utf-8") + payload,
        hashlib.sha256,
    ).hexdigest()
    header = f"t={now},v1={sig_hex}"

    parsed = gw.verify_event(payload, header, now=now)
    assert parsed["id"] == "evt_test_001"

    with pytest.raises(ValueError, match="invalid or expired Stripe signature"):
        gw.verify_event(payload, header, now=now + 999)


def test_user_account_lifecycle_and_password_reset(tmp_path):
    store = ProvenanceStore(tmp_path / "prov.db")
    cfg = ManagedConfig(home=tmp_path / "managed", allow_signup=True)
    ctrl = ManagedControl(cfg, store=store)

    # Register user
    reg = ctrl.register(email="alice@xibalba.dev", password="super-secret-password-123", display_name="Alice Vance")
    assert reg["verification_required"] is False
    assert reg["account"]["email"] == "alice@xibalba.dev"
    assert reg["account"]["display_name"] == "Alice Vance"
    token = reg["session"]["token"]

    # Authenticate session
    auth = ctrl.authenticate_session(token)
    assert auth is not None
    account, tenant, csrf = auth
    assert account["email"] == "alice@xibalba.dev"
    assert tenant["plan"] == "free"
    assert csrf == reg["session"]["csrf_token"]

    # Password reset flow
    reset_tok = ctrl.request_password_reset("alice@xibalba.dev")
    assert reset_tok is not None
    ctrl.confirm_password_reset(reset_tok, "new-operator-password-456")

    # Old session is revoked after password reset
    assert ctrl.authenticate_session(token) is None

    # Login with new password succeeds
    login_res = ctrl.login(email="alice@xibalba.dev", password="new-operator-password-456")
    assert login_res["account"]["email"] == "alice@xibalba.dev"


def test_agent_device_pairing_flow(tmp_path):
    store = ProvenanceStore(tmp_path / "prov.db")
    cfg = ManagedConfig(home=tmp_path / "managed", allow_signup=True)
    ctrl = ManagedControl(cfg, store=store)

    account, tenant, _ = ctrl.default_operator_context()
    agent_did = "did:integrity:b1a72980e8e45e97c7b92982a89b1963e470b45fa955c9bd245f046e1e32e39a"

    pair_req = ctrl.create_pairing_request(
        device_id="workstation-01",
        device_name="Xibalba Linux Workstation",
        agent_did=agent_did,
        agent_name="agy",
        callback_url="http://127.0.0.1:49152/callback",
    )
    user_code = pair_req["user_code"]
    assert "-" in user_code

    info = ctrl.get_pairing_request(user_code)
    assert info is not None
    assert info["status"] == "pending"
    assert info["agent_did"] == agent_did

    approved = ctrl.approve_pairing_request(user_code, account=account, tenant=tenant)
    assert approved["status"] == "approved"
    assert approved["token"].startswith("sc_live_")

    # Agent CLI polls and redeems token once
    polled = ctrl.poll_pairing_status(pair_req["device_code"])
    assert polled["status"] == "approved"
    assert polled["token"] == approved["token"]

    # Second poll returns redeemed so token cannot be intercepted twice
    polled_again = ctrl.poll_pairing_status(pair_req["device_code"])
    assert polled_again["status"] == "redeemed"


def test_stripe_subscription_checkout_webhook_and_quotas(tmp_path):
    store = ProvenanceStore(tmp_path / "prov.db")
    cfg = ManagedConfig(
        home=tmp_path / "managed",
        public_url="https://cortex-managed-pilot.onrender.com",
        stripe_secret_key="sk_test_" + "a1b2c3d4e5f6",
        stripe_webhook_secret="whsec_" + "a1b2c3d4e5f6",
        pro_price_id="price_pro_monthly_29",
        team_price_id="price_team_monthly_149",
        allow_signup=True,
    )
    fake_stripe = FakeStripeGateway(cfg)
    ctrl = ManagedControl(cfg, stripe=fake_stripe, store=store)

    reg = ctrl.register(email="bob@xibalba.dev", password="bob-secure-password-999", display_name="Bob Quant")
    account = ctrl.get_account_by_id(reg["account"]["id"])
    assert account is not None

    # Start Stripe Checkout for Pro plan
    checkout = ctrl.checkout(account, "pro")
    assert checkout["url"] == "https://checkout.stripe.com/c/pay/cs_test_123"

    # Apply webhook event for checkout completion
    event = {
        "id": "evt_checkout_pro_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "customer": "cus_test_123",
                "subscription": "sub_test_123",
            }
        },
    }
    applied = ctrl.apply_event(event)
    assert applied["received"] is True

    # Duplicate webhook delivery is idempotent
    dup = ctrl.apply_event(event)
    assert dup.get("duplicate") is True

    tenant = ctrl.tenant(account)
    ent = ctrl.entitlement(tenant)
    assert ent["plan"]["id"] == "pro"
    assert ent["status"] == "active"
    assert ent["writable"] is True

    # Open Billing Portal
    portal = ctrl.portal(account)
    assert portal["url"] == "https://billing.stripe.com/p/session/bps_test_123"

    # Consume write & retrieval meters
    ctrl.consume(tenant, "writes", request_key="req_1", fingerprint="fp_1")
    ctrl.consume(tenant, "retrievals")
    usage = ctrl.usage(tenant)
    assert usage["used"]["writes"] == 1
    assert usage["used"]["retrievals"] == 1

    # Simulate subscription cancellation webhook -> workspace becomes read-only
    fake_stripe.subscription_state["status"] = "canceled"
    cancel_event = {
        "id": "evt_sub_canceled_2",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_test_123", "customer": "cus_test_123"}},
    }
    ctrl.apply_event(cancel_event)

    tenant_after = ctrl.tenant(account)
    ent_after = ctrl.entitlement(tenant_after)
    assert ent_after["writable"] is False
    with pytest.raises(PermissionError, match="read-only"):
        ctrl.consume(tenant_after, "writes")
