"""Phase 3 Task 3: the three plan limits refuse at their boundary, and only there.

Mapped against what already existed before writing anything:

- `writes_per_month` had boundary coverage, but inside `test_quota_reservation_cannot_be_raced`
  -- a concurrency test. `max_memories` likewise, inside two capacity tests. So a check could
  be removed and *a* test would red, but not one that names the limit, which is what the
  plan's Step 5 asks for ("remove one check at a time and confirm **only** that limit's test
  goes red. Three separate reverts, not one.").
- `retrievals_per_month` had **no test at all**. Every read route calls
  `service.consume(tenant, "retrievals")`, and nothing asserted that the resulting limit is
  reached, or that it is the retrieval limit rather than the write limit doing the refusing.
- The "**and allows the same call on Pro**" half of the plan's Step 1 was untested for all
  three. A limit that refuses on every plan is as wrong as one that refuses on none, and no
  test would have noticed.
- The monthly reset was untested. `consume` keys usage on
  `datetime.now(timezone.utc).strftime("%Y-%m")`, so the reset is UTC by construction -- but
  a switch to local time would have broken no test.

Note on why the limits are not greppable: `consume` reads them with
`getattr(PLANS[plan], meter + "_per_month")`, so searching for the literal field names finds
only `plans.py`. They are enforced; they just cannot be found that way.
"""

from dataclasses import replace

import pytest

from xibalba_cortex.managed.control import LimitExceeded
from xibalba_cortex.managed.plans import PLANS

from test_managed_service import (  # noqa: F401 -- `setup` is used as a fixture
    register,
    setup,
    subscribe,
)

# Small enough to reach in a test, on the Free tier only. Pro keeps its real allowance, so
# "allows on Pro" is a statement about the catalog and not about a second patched number.
FREE_BOUNDARY = 2


@pytest.fixture
def tight_free(monkeypatch):
    """Free, with all three limits lowered to the same small number. One fixture for all
    three so that a test reaching one boundary proves it is *that* meter refusing: the other
    two are equally tight and equally close."""
    monkeypatch.setitem(PLANS, "free", replace(
        PLANS["free"],
        max_memories=FREE_BOUNDARY,
        writes_per_month=FREE_BOUNDARY,
        retrievals_per_month=FREE_BOUNDARY,
    ))


def _write(setup, headers, n):
    _, _, _, _, client = setup
    # The key must be 8-128 characters; "write-0" is seven and earns a 400 that looks
    # nothing like a limit refusal.
    return client.post("/api/managed/memories", json={"content": f"memory number {n}"},
                       headers={**headers, "Idempotency-Key": f"plan-limit-write-{n}"})


def _read(setup):
    _, _, _, _, client = setup
    return client.get("/api/managed/memories")


# --- writes_per_month -------------------------------------------------------------------

def test_the_write_limit_refuses_the_call_past_the_boundary(setup, tight_free):
    account, headers = register(setup)

    for n in range(FREE_BOUNDARY):
        assert _write(setup, headers, n).status_code == 201, f"write {n} was refused early"

    refused = _write(setup, headers, FREE_BOUNDARY)
    assert refused.status_code == 429, refused.text
    assert "writes" in refused.text


def test_the_same_write_is_allowed_on_pro(setup, tight_free):
    """The other half: a limit that refuses on every plan would pass the test above."""
    account, headers = register(setup)
    subscribe(setup, account, plan="pro")

    for n in range(FREE_BOUNDARY + 1):
        assert _write(setup, headers, n).status_code == 201, (
            f"write {n} was refused on Pro, which has its own, larger allowance"
        )


# --- retrievals_per_month ---------------------------------------------------------------

def test_the_retrieval_limit_refuses_the_call_past_the_boundary(setup, tight_free):
    """Untested before this. Every read route meters retrievals; nothing asserted the limit
    was ever reached."""
    register(setup)

    for n in range(FREE_BOUNDARY):
        assert _read(setup).status_code == 200, f"read {n} was refused early"

    refused = _read(setup)
    assert refused.status_code == 429, refused.text
    assert "retrievals" in refused.text, (
        f"a read was refused, but not by the retrieval limit: {refused.text}"
    )


def test_the_same_retrieval_is_allowed_on_pro(setup, tight_free):
    account, _ = register(setup)
    subscribe(setup, account, plan="pro")

    for n in range(FREE_BOUNDARY + 1):
        assert _read(setup).status_code == 200, f"read {n} was refused on Pro"


# --- max_memories -----------------------------------------------------------------------

def test_the_stored_memory_limit_refuses_the_call_past_the_boundary(setup, monkeypatch):
    """Capacity, not rate: a plan may permit the write and still have nowhere to put it. The
    write meter is left generous here so that only capacity can refuse."""
    monkeypatch.setitem(PLANS, "free", replace(
        PLANS["free"], max_memories=FREE_BOUNDARY, writes_per_month=1_000))
    account, headers = register(setup)

    for n in range(FREE_BOUNDARY):
        assert _write(setup, headers, n).status_code == 201, f"write {n} was refused early"

    refused = _write(setup, headers, FREE_BOUNDARY)
    assert refused.status_code == 429, refused.text
    assert "capacity" in refused.text.lower(), (
        f"the write was refused, but not by stored-memory capacity: {refused.text}"
    )


def test_the_same_stored_memory_is_allowed_on_pro(setup, monkeypatch):
    monkeypatch.setitem(PLANS, "free", replace(
        PLANS["free"], max_memories=FREE_BOUNDARY, writes_per_month=1_000))
    account, headers = register(setup)
    subscribe(setup, account, plan="pro")

    for n in range(FREE_BOUNDARY + 1):
        assert _write(setup, headers, n).status_code == 201, f"write {n} was refused on Pro"


# --- the reset --------------------------------------------------------------------------

def test_the_monthly_allowance_is_keyed_on_the_UTC_month(setup, monkeypatch):
    """A tenant at its limit is writable again in the next month, and the month boundary is
    UTC -- not the server's local midnight, which would move the reset by up to a day and
    differ between deployments."""
    import xibalba_cortex.managed.control as control

    # capacity is not monthly: leaving max_memories tight would keep refusing after the
    # reset, for a reason that has nothing to do with the allowance under test.
    monkeypatch.setitem(PLANS, "free", replace(
        PLANS["free"], max_memories=1_000, writes_per_month=FREE_BOUNDARY,
        retrievals_per_month=FREE_BOUNDARY))
    _, service, _, _, _ = setup
    account, headers = register(setup)
    for n in range(FREE_BOUNDARY):
        assert _write(setup, headers, n).status_code == 201
    assert _write(setup, headers, FREE_BOUNDARY).status_code == 429

    real_datetime = control.datetime
    captured: list[object] = []

    class NextMonth:
        @staticmethod
        def now(tz=None):
            captured.append(tz)
            moment = real_datetime.now(tz)
            return moment.replace(year=moment.year + 1)

    monkeypatch.setattr(control, "datetime", NextMonth)
    assert _write(setup, headers, 99).status_code == 201, (
        "the allowance did not reset when the month changed"
    )
    from datetime import timezone
    assert captured and all(tz is timezone.utc for tz in captured), (
        f"the usage month was computed in a timezone other than UTC: {captured}"
    )


def test_a_refusal_never_discards_the_data_already_stored(setup, tight_free):
    """The refusal is a limit, not a loss: everything written before it is still readable and
    exportable. (`consume` raises before the store is touched, so this is the guarantee that
    makes a 429 safe to retry.)"""
    _, _, _, _, client = setup
    account, headers = register(setup)
    for n in range(FREE_BOUNDARY):
        assert _write(setup, headers, n).status_code == 201
    assert _write(setup, headers, FREE_BOUNDARY).status_code == 429

    assert len(client.get("/api/managed/export").json()["memories"]) == FREE_BOUNDARY
