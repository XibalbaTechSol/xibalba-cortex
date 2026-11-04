"""Phase 3 Tasks 1 and 2: the billing gateway, against a fake one.

The plan asks for a `FakeGateway` test double and tests for checkout, portal and webhook
handling. Most of that already exists in `test_managed_service.py` -- a `FakeStripe`, a
`setup` fixture, and 26 tests. Mapped against what the plan asks for, four things were
genuinely missing, and only those are here:

1. **`portal` was never called by any test.** `FakeStripe` has a `/billing_portal/sessions`
   branch, so it looked covered; nothing exercised it, including its refusal for a tenant
   with no Stripe customer -- the one assertion the plan names for portal.
2. **Nothing pinned the fake to the real gateway.** `FakeStripe` subclasses `object`, not
   `StripeGateway`, so a signature change on the real gateway leaves the double behind and
   every test above keeps passing against an interface that no longer exists. That is the
   plan's "satisfying the same protocol" and it was not being checked.
3. **A webhook with no signature header at all** was untested. The existing test covers a
   tampered body, a stale timestamp and a livemode mismatch -- all cases where a signature is
   present and wrong, not absent.
4. **Replay idempotency was not isolated.** It is asserted inside a test that also covers
   tampering, expiry and live/test separation, so the plan's Step 5 ("drop the event-id check
   and confirm ONLY the replay test goes red") could not attribute a failure to it. And what
   it asserted was the `duplicate` flag, not the thing that matters: that the entitlement did
   not advance twice.

The plan's example fixture (`managed_app`, `post_signed_webhook`) does not exist; this uses
the real one, `setup`.
"""

import inspect
import json

import pytest

from xibalba_cortex.managed.stripe_gateway import StripeGateway

# The existing fixture and helpers. Imported, not reimplemented: a second FakeStripe would be
# a second thing to keep in step with the real gateway, which is the very problem below.
from test_managed_service import (  # noqa: F401 -- `setup` is used as a fixture
    FakeStripe,
    register,
    setup,
    signed,
    subscribe,
)


# --- Task 1: the double, and portal -----------------------------------------------------

def test_the_fake_gateway_offers_every_method_the_real_one_does():
    """If the real gateway grows a method, the fake must too, or the suite is testing an
    interface the service no longer calls."""
    real = {name for name, _ in inspect.getmembers(StripeGateway, inspect.isfunction)
            if not name.startswith("_")}
    fake = {name for name, _ in inspect.getmembers(FakeStripe, inspect.isfunction)
            if not name.startswith("_")}

    assert real <= fake, f"the fake gateway is missing: {sorted(real - fake)}"


def _call_contract(func):
    """Parameter names, kinds and defaults -- what a caller has to satisfy. Annotations are
    deliberately excluded: the real gateway is typed and the fixture double is not, and a
    strict `inspect.signature` comparison fails on that cosmetic difference while saying
    nothing about whether a call written for one works against the other."""
    return [(p.name, p.kind, p.default) for p in inspect.signature(func).parameters.values()]


@pytest.mark.parametrize("method", ["request", "verify_event"])
def test_the_fake_gateway_keeps_the_real_call_contract(method):
    """Same method names is not enough: a double whose PARAMETERS have drifted passes tests
    that the real gateway would reject at the call site -- or, as happened here, makes a real
    behaviour unreachable. `FakeStripe.verify_event` was missing the real `now` keyword, which
    is how the gateway's 300-second signature window is tested without moving the clock."""
    assert _call_contract(getattr(FakeStripe, method)) == _call_contract(
        getattr(StripeGateway, method)
    ), f"FakeStripe.{method} no longer matches StripeGateway.{method}"


def test_the_portal_refuses_a_workspace_with_no_stripe_customer(setup):
    """The plan's named portal assertion. A tenant that has never checked out has no customer
    record, and there is no portal to send them to -- it must say so rather than call Stripe
    with an empty customer id."""
    _, service, stripe, _, _ = setup
    account, _ = register(setup)

    with pytest.raises(ValueError, match="no Stripe billing account"):
        service.portal(account)

    portal_calls = [call for call in stripe.calls if call[1] == "/billing_portal/sessions"]
    assert portal_calls == [], (
        "the portal called Stripe for a workspace with no customer record"
    )


def test_the_portal_returns_a_session_once_a_customer_exists(setup):
    """The other half, so the refusal above is not passing because portal never works."""
    _, service, _, _, _ = setup
    account, _ = register(setup)
    service.checkout(account, "pro")  # this is what creates the Stripe customer

    assert service.portal(account)["url"].startswith("https://")


# --- Task 2: webhook signature and replay -----------------------------------------------

def test_a_webhook_with_no_signature_header_is_refused(setup):
    """Present-and-wrong is covered elsewhere. Absent is its own path: a missing header must
    not be read as "nothing to verify"."""
    config, service, stripe, _, client = setup
    account, _ = register(setup)
    event = subscribe(setup, account)
    body = json.dumps(event).encode()

    assert client.post("/api/managed/stripe/webhook", content=body).status_code == 400


def test_replaying_an_event_does_not_advance_the_entitlement_twice(setup):
    """Isolated so that dropping the event-id check reds THIS test and nothing else -- the
    plan's Step 5. And asserted on the entitlement itself, not on the `duplicate` flag: a
    handler could report `duplicate` and still have applied the event again."""
    config, service, stripe, _, client = setup
    account, _ = register(setup)
    event = subscribe(setup, account)
    event["id"] = "evt_replay_once"
    body, signature = signed(config, event)
    headers = {"Stripe-Signature": signature}

    first = client.post("/api/managed/stripe/webhook", content=body, headers=headers)
    assert first.status_code == 200, first.text
    before = dict(service.tenant(account))

    second = client.post("/api/managed/stripe/webhook", content=body, headers=headers)

    assert second.status_code == 200, second.text
    assert dict(service.tenant(account)) == before, (
        "replaying one Stripe event changed the workspace's entitlement a second time"
    )
