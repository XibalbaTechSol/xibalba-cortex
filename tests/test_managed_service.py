"""Managed billing and tenant boundaries. Stripe and email are explicit test fixtures."""
import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from xibalba_cortex.managed.api import create_app
from xibalba_cortex.managed.config import ManagedConfig
from xibalba_cortex.managed.control import LimitExceeded, ManagedControl
from xibalba_cortex.managed.plans import PLANS
from xibalba_cortex.managed.stripe_gateway import BillingUnavailable, StripeGateway


class FakeStripe:
    """Never used by the application outside tests; creates no Stripe resources."""
    def __init__(self, config):
        self.config = config
        self.calls = []
        self.customers = {}
        self.sessions = {}
        self.subscriptions = {}
        self.idempotent = {}
        self.prices = {
            config.pro_price_id: self.price(config.pro_price_id, 2900),
            config.team_price_id: self.price(config.team_price_id, 14900),
        }

    @staticmethod
    def price(price_id, cents):
        return {"id": price_id, "currency": "usd", "unit_amount": cents,
            "recurring": {"interval": "month", "interval_count": 1}, "active": True}

    def verify_event(self, body, signature):
        return StripeGateway(self.config).verify_event(body, signature)

    def request(self, method, path, *, data=None, idempotency_key=None):
        self.calls.append((method, path, data, idempotency_key))
        if idempotency_key in self.idempotent:
            return self.idempotent[idempotency_key]
        if method == "GET" and path.startswith("/prices/"):
            return self.prices[path.split("/")[-1]]
        if method == "POST" and path == "/customers":
            result = {"id": f"cus_fixture_{len(self.customers) + 1}"}
            self.customers[result["id"]] = result
        elif method == "POST" and path == "/checkout/sessions":
            result = {"id": f"cs_fixture_{len(self.sessions) + 1}", "status": "open", "url": "https://checkout.stripe.com/test-fixture"}
            self.sessions[result["id"]] = result
        elif method == "GET" and path.startswith("/checkout/sessions/"):
            return self.sessions[path.split("/")[-1]]
        elif method == "GET" and path.startswith("/subscriptions/"):
            return self.subscriptions[path.split("/")[-1]]
        elif path == "/billing_portal/sessions":
            return {"url": "https://billing.stripe.com/test-fixture"}
        else:
            raise AssertionError((method, path))
        if idempotency_key:
            self.idempotent[idempotency_key] = result
        return result


@pytest.fixture
def setup(tmp_path):
    config = ManagedConfig(home=tmp_path, public_url="http://localhost:8430", allow_signup=True,
        stripe_secret_key="sk_test_unit_fixture", stripe_webhook_secret="whsec_fixture",
        pro_price_id="price_pro", team_price_id="price_team")
    mail = []
    stripe = FakeStripe(config)
    service = ManagedControl(config, stripe=stripe, email_sender=lambda *args: mail.append(args))
    with TestClient(create_app(config, control=service), base_url=config.public_url) as client:
        yield config, service, stripe, mail, client


def register(setup, name="alice"):
    config, service, stripe, mail, client = setup
    email = name + "@example.com"
    response = client.post("/api/managed/signup", json={"email": email, "password": "correct-test-password", "display_name": name})
    assert response.status_code == 202, response.text
    token = parse_qs(urlsplit(mail[-1][2].splitlines()[-1]).query)["token"][0]
    response = client.get("/api/managed/verify", params={"token": token}, follow_redirects=False)
    assert response.status_code == 303
    response = client.post("/api/managed/login", json={"email": email, "password": "correct-test-password"})
    assert response.status_code == 200, response.text
    body = response.json()
    headers = {"Origin": config.public_url, "X-Cortex-CSRF-Token": body["csrf_token"]}
    return body["account"], headers


def subscribe(setup, account, *, plan="pro", status="active", sub_id="sub_fixture"):
    config, service, stripe, mail, client = setup
    service.checkout(account, plan)
    tenant = service.tenant(account)
    price_id = config.pro_price_id if plan == "pro" else config.team_price_id
    stripe.subscriptions[sub_id] = {
        "id": sub_id, "customer": tenant["customer_id"], "status": status,
        "cancel_at_period_end": False, "items": {"data": [{"quantity": 1,
            "price": stripe.prices[price_id], "current_period_end": int(time.time()) + 86400}]},
    }
    event = {"id": "evt_" + sub_id + status, "type": "customer.subscription.updated", "livemode": False,
        "data": {"object": {"id": sub_id, "customer": tenant["customer_id"]}}}
    service.apply_event(event)
    return event


def signed(config, event, *, timestamp=None):
    body = json.dumps(event).encode()
    timestamp = int(time.time()) if timestamp is None else timestamp
    signature = hmac.new(config.stripe_webhook_secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return body, f"t={timestamp},v1={signature}"


def test_approved_catalog_and_placeholder_key_never_call_stripe(tmp_path, monkeypatch):
    config = ManagedConfig(home=tmp_path, stripe_secret_key="sk_test_dummy")
    assert not config.billing_ready
    assert [(p.id, p.monthly_cents) for p in PLANS.values()] == [("free", 0), ("pro", 2900), ("team", 14900)]
    monkeypatch.setattr("requests.request", lambda *a, **k: pytest.fail("placeholder reached Stripe"))
    with pytest.raises(BillingUnavailable):
        StripeGateway(config).request("POST", "/checkout/sessions")
    assert "sk_test_dummy" not in repr(config)


def test_signup_verification_required_and_link_is_single_use(setup):
    config, service, stripe, mail, client = setup
    assert client.post("/api/managed/signup", json={"email": "a@example.com", "password": "correct-test-password", "display_name": "A"}).status_code == 202
    response = client.post("/api/managed/login", json={"email": "a@example.com", "password": "correct-test-password"})
    assert response.status_code == 400
    assert "verification" in response.json()["error"]
    token = parse_qs(urlsplit(mail[-1][2].splitlines()[-1]).query)["token"][0]
    assert service.verify_email(token)
    assert not service.verify_email(token)


def test_memories_and_keys_cannot_cross_tenants(setup):
    _, service, _, _, client = setup
    alice, headers = register(setup)
    response = client.post("/api/managed/memories", json={"content": "Alice-only secret"}, headers={**headers, "Idempotency-Key": "alice-write-001"})
    assert response.status_code == 201, response.text
    memory_id = response.json()["id"]
    key = client.post("/api/managed/keys", json={"label": "account:alice@example.com"}, headers=headers)
    assert key.status_code == 201, key.text
    alice_key = key.json()["token"]
    assert client.get('/api/managed/memories/' + memory_id + '/verify').json()['valid']
    bob, bob_headers = register(setup, "bob")
    assert alice["profile_id"] != bob["profile_id"]
    assert client.get("/api/managed/memories/" + memory_id).status_code == 404
    assert client.get("/api/managed/memories/" + memory_id + "/verify").status_code == 404
    assert client.get("/api/managed/memories", params={"q": "Alice-only"}).json()["memories"] == []
    client.cookies.clear()
    key_headers = {"Authorization": "Bearer " + alice_key}
    assert client.get("/api/managed/memories/" + memory_id, headers=key_headers).status_code == 200
    assert client.post("/api/managed/checkout", json={"plan": "pro"}, headers=key_headers).status_code == 403
    assert client.post("/api/managed/keys", json={"label": "child"}, headers=key_headers).status_code == 403
    assert client.get("/api/managed/memories", params={"profile_id": bob["profile_id"]}, headers=key_headers).json()["memories"][0]["id"] == memory_id


def test_cookie_mutations_require_matching_origin_and_csrf(setup):
    _, _, _, _, client = setup
    _, headers = register(setup)
    data = {"label": "agent"}
    assert client.post("/api/managed/keys", json=data).status_code == 403
    assert client.post("/api/managed/keys", json=data, headers={**headers, "Origin": "https://attacker.example"}).status_code == 403
    assert client.post("/api/managed/keys", json=data, headers=headers).status_code == 201


def test_write_retries_are_idempotent_and_changed_body_is_rejected(setup):
    _, service, _, _, client = setup
    account, headers = register(setup)
    headers["Idempotency-Key"] = "one-write-retry"
    first = client.post("/api/managed/memories", json={"content": "one memory"}, headers=headers)
    second = client.post("/api/managed/memories", json={"content": "one memory"}, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert service.usage(service.tenant(account))["used"]["writes"] == 1
    assert client.post("/api/managed/memories", json={"content": "different content"}, headers=headers).status_code == 400


def test_quota_reservation_cannot_be_raced(setup, monkeypatch):
    _, service, _, _, _ = setup
    account, _ = register(setup)
    monkeypatch.setitem(PLANS, "free", replace(PLANS["free"], writes_per_month=3))
    tenant = service.tenant(account)
    def consume(_):
        try:
            service.consume(tenant, "writes")
            return True
        except LimitExceeded:
            return False
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(consume, range(12))) == 3
    assert service.usage(tenant)["used"]["writes"] == 3


def test_checkout_retries_reuse_session_and_cannot_change_price(setup):
    _, service, stripe, _, _ = setup
    account, _ = register(setup)
    assert service.checkout(account, "pro") == service.checkout(account, "pro")
    assert len(stripe.sessions) == len(stripe.customers) == 1
    with pytest.raises(ValueError, match="existing checkout"):
        service.checkout(account, "team")
    with pytest.raises(ValueError):
        service.checkout(account, "price_attacker")
    stripe.prices["price_pro"]["unit_amount"] = 1
    with pytest.raises(ValueError, match="approved Cortex catalog"):
        service.checkout(account, "pro")


def test_webhook_signature_replay_expiry_and_test_live_separation(setup):
    config, service, stripe, _, client = setup
    account, _ = register(setup)
    event = subscribe(setup, account)
    event["id"] = "evt_signed"
    body, signature = signed(config, event)
    response = client.post("/api/managed/stripe/webhook", content=body, headers={"Stripe-Signature": signature})
    assert response.status_code == 200, response.text
    assert client.post("/api/managed/stripe/webhook", content=body, headers={"Stripe-Signature": signature}).json()["duplicate"]
    assert client.post("/api/managed/stripe/webhook", content=body + b" ", headers={"Stripe-Signature": signature}).status_code == 400
    _, stale_signature = signed(config, event, timestamp=int(time.time()) - 301)
    assert client.post("/api/managed/stripe/webhook", content=body, headers={"Stripe-Signature": stale_signature}).status_code == 400
    event["livemode"] = True
    body, signature = signed(config, event)
    assert client.post("/api/managed/stripe/webhook", content=body, headers={"Stripe-Signature": signature}).status_code == 400


def test_out_of_order_events_use_current_provider_state(setup):
    _, service, stripe, _, _ = setup
    account, _ = register(setup)
    event = subscribe(setup, account)
    stripe.subscriptions["sub_fixture"]["status"] = "canceled"
    stale = {**event, "id": "evt_stale_active"}
    stale["data"] = {"object": {**event["data"]["object"], "status": "active"}}
    service.apply_event(stale)
    tenant = service.tenant(account)
    assert tenant["status"] == "canceled"
    assert not service.entitlement(tenant)["writable"]


@pytest.mark.parametrize("status", ["past_due", "unpaid", "canceled", "incomplete", "paused"])
def test_nonpaying_subscription_is_read_only_without_data_loss(setup, status):
    _, service, stripe, _, client = setup
    account, headers = register(setup)
    response = client.post("/api/managed/memories", json={"content": "retain this record"}, headers={**headers, "Idempotency-Key": "retain-before-cancel"})
    assert response.status_code == 201, response.text
    subscribe(setup, account, status=status)
    assert client.post("/api/managed/memories", json={"content": "blocked new record"}, headers={**headers, "Idempotency-Key": "after-cancel-new"}).status_code == 403
    assert len(client.get("/api/managed/export").json()["memories"]) == 1


def test_cancel_at_period_end_keeps_paid_access_until_expiry(setup):
    _, service, stripe, _, _ = setup
    account, _ = register(setup)
    event = subscribe(setup, account)
    stripe.subscriptions["sub_fixture"]["cancel_at_period_end"] = True
    service.apply_event({**event, "id": "evt_cancel_scheduled"})
    assert service.entitlement(service.tenant(account))["writable"]
    stripe.subscriptions["sub_fixture"]["items"]["data"][0]["current_period_end"] = int(time.time()) - 1
    service.apply_event({**event, "id": "evt_expired"})
    assert not service.entitlement(service.tenant(account))["writable"]


def test_body_limits_and_missing_api_routes_do_not_fall_through(setup):
    config, _, _, _, client = setup
    _, headers = register(setup)
    response = client.post("/api/managed/memories", content=b"x" * (config.max_body_bytes + 1), headers={**headers, "Content-Type": "application/json"})
    assert response.status_code == 413
    assert client.get("/api/managed/not-a-route").status_code == 404
    assert client.get("/api/managed/me").headers["cache-control"] == "no-store"


def test_managed_pilot_readiness_reports_dummy_key_and_local_origin_as_blockers(tmp_path, monkeypatch):
    monkeypatch.delenv("CORTEX_SMTP_HOST", raising=False)
    monkeypatch.delenv("CORTEX_SMTP_FROM", raising=False)
    config = ManagedConfig(home=tmp_path, public_url="http://localhost:8430", stripe_secret_key="sk_test_dummy", allow_signup=False)
    client = TestClient(create_app(config), base_url=config.public_url)
    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["schema_version"] == "xibalba.managed_pilot_readiness.v1"
    assert body["ready"] is False
    assert body["checks"]["public_origin"]["ready"] is False
    assert body["checks"]["stripe_sandbox"]["ready"] is False
    assert body["checks"]["smtp_delivery"]["ready"] is False




def test_tenant_storage_rejects_path_escape(setup):
    _, service, _, _, _ = setup
    with pytest.raises(PermissionError):
        with service.store({"id": "../../elsewhere", "plan": "free"}):
            pytest.fail("escaped tenant storage root")


def test_key_revocation_is_scoped_and_effective_immediately(setup):
    _, _, _, _, client = setup
    _, headers = register(setup)
    key = client.post('/api/managed/keys', json={'label': 'agent'}, headers=headers).json()['token']
    listed = client.get('/api/managed/keys').json()['keys']
    assert len(listed) == 1
    assert 'token_hash' not in listed[0]
    assert client.post('/api/managed/keys/revoke', json={'id': listed[0]['id']}, headers=headers).json()['revoked']
    client.cookies.clear()
    assert client.get('/api/managed/memories', headers={'Authorization': 'Bearer ' + key}).status_code == 401


def test_password_recovery_revokes_sessions_and_cannot_replay(setup):
    _, service, _, mail, client = setup
    account, _ = register(setup)
    response = client.post('/api/managed/recovery/forgot-password', json={'email': account['email']})
    assert response.status_code == 202
    token = parse_qs(urlsplit(mail[-1][2].splitlines()[-1]).query)['reset_token'][0]
    response = client.post('/api/managed/recovery/reset', json={'token': token, 'password': 'replacement-test-password'})
    assert response.status_code == 200
    assert client.get('/api/managed/me').status_code == 401
    assert not service.reset_password(token, 'second-replacement-password')
    assert client.post('/api/managed/login', json={'email': account['email'], 'password': 'replacement-test-password'}).status_code == 200


def test_subscription_customer_mismatch_never_changes_entitlement(setup):
    _, service, stripe, _, _ = setup
    account, _ = register(setup)
    event = subscribe(setup, account)
    stripe.subscriptions['sub_fixture']['customer'] = 'cus_another_customer'
    with pytest.raises(ValueError, match='customer does not match'):
        service.apply_event({**event, 'id': 'evt_wrong_customer'})
    assert service.tenant(account)['plan'] == 'pro'


def test_download_export_remains_available_after_cancellation(setup):
    _, _, _, _, client = setup
    account, headers = register(setup)
    saved = client.post('/api/managed/memories', json={'content': 'Keep this in an export'}, headers={**headers, 'Idempotency-Key': 'download-export-01'})
    assert saved.status_code == 201
    subscribe(setup, account, status='canceled')
    exported = client.get('/api/managed/export-download')
    assert exported.status_code == 200
    assert 'attachment' in exported.headers['content-disposition']
    assert exported.json()['memories'][0]['id'] == saved.json()['id']


def test_stored_memory_capacity_is_reported_as_a_quota_limit(setup, monkeypatch):
    _, _, _, _, client = setup
    _, headers = register(setup)
    monkeypatch.setitem(PLANS, 'free', replace(PLANS['free'], max_memories=1))
    assert client.post('/api/managed/memories', json={'content': 'first'}, headers={**headers, 'Idempotency-Key': 'capacity-first'}).status_code == 201
    response = client.post('/api/managed/memories', json={'content': 'second'}, headers={**headers, 'Idempotency-Key': 'capacity-second'})
    assert response.status_code == 429, response.text


def test_simultaneous_checkouts_create_one_customer_and_subscription_session(setup):
    _, service, stripe, _, _ = setup
    account, _ = register(setup)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: service.checkout(account, 'pro'), range(3)))
    assert results[0] == results[1] == results[2]
    assert len(stripe.customers) == len(stripe.sessions) == 1


def test_concurrent_writes_cannot_overfill_a_tenant_store(setup, monkeypatch):
    import threading
    from xibalba_cortex.store import GraphStore
    _, _, _, _, client = setup
    _, headers = register(setup)
    monkeypatch.setitem(PLANS, 'free', replace(PLANS['free'], max_memories=1))
    original = GraphStore.store_memory
    state = {'active': 0, 'peak': 0}
    lock = threading.Lock()
    def measured(self, *args, **kwargs):
        with lock:
            state['active'] += 1
            state['peak'] = max(state['peak'], state['active'])
        try:
            time.sleep(0.1)
            return original(self, *args, **kwargs)
        finally:
            with lock:
                state['active'] -= 1
    monkeypatch.setattr(GraphStore, 'store_memory', measured)
    def write(index):
        return client.post('/api/managed/memories', json={'content': f'memory {index}'},
            headers={**headers, 'Idempotency-Key': f'concurrent-write-{index}'}).status_code
    with ThreadPoolExecutor(max_workers=3) as pool:
        statuses = list(pool.map(write, range(3)))
    assert state['peak'] == 1
    assert sorted(statuses) == [201, 429, 429]


def test_recovery_delivery_failure_does_not_reveal_registered_email(setup):
    from xibalba_cortex.email_delivery import EmailDeliveryError

    _, service, _, _, client = setup
    account, _ = register(setup)

    def unavailable(*args):
        raise EmailDeliveryError('test delivery failure')

    service.email_sender = unavailable
    existing = client.post('/api/managed/recovery/forgot-password', json={'email': account['email']})
    unknown = client.post('/api/managed/recovery/forgot-password', json={'email': 'unknown@example.com'})
    assert existing.status_code == unknown.status_code == 202
    assert existing.json() == unknown.json()
