"""A redeemed enrollment code must leave behind an agent the console can actually open.

Phase 2 Task 3. The plan's Task 3 is written as viewer work -- "wire the bind result into
the existing choose-then-go path" -- on the assumption that a redemption produces something
the console lists. It does not. `redeem_code` marks the code redeemed and writes an audit
event; it creates no `agent_devices` row and no `sources` row, so `GraphStore.agent_workspaces()`
never sees the enrolled agent and `/api/agents` never returns it.

That matters because `AgentsPage`'s open path is `workspace.choose(agentId, store_id)`, and
both of those values come from the agent listing. Wiring the viewer to a listing that the
server never changes would be a test of a mock: the e2e would prove the console reacts to a
0 -> 1 transition that production cannot produce.

So the bind is closed here, at the route, where the `GraphStore` lives -- and asserted
through the real HTTP handler rather than by reading the source, because three tasks running
have produced source-inspection tests that passed vacuously.

The authorisation argument: `associate_agent_device` is normally operator-gated
(`_assert_pair_manager`). Here the enrollment code *is* the operator's authorisation -- an
operator issued it for this workspace, and the signature proves the redeemer holds the key
for the DID it claims. That is the whole purpose of the code.
"""

import threading
from base64 import b64encode
from http.server import ThreadingHTTPServer

import pytest
import requests

from integrity_sdk.did import Ed25519PrivateKey, fingerprint_for_pubkey

from xibalba_cortex.enrollment import issue_code
from xibalba_cortex.local_api import _make_handler
from xibalba_cortex.store import GraphStore

WORKSPACE = "ws-1"
DEVICE = "device-1"


def _identity():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    did = f"did:integrity:{fingerprint_for_pubkey(public)}"
    return did, public, private.sign


@pytest.fixture
def served(tmp_path):
    """The real handler over a real socket: no source inspection, no stubbed store."""
    store = GraphStore(tmp_path, features={"inference": False, "embeddings": False})
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(store, allowed_origins=("*",)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield store, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.close()


def _redeem(origin, code, identity, *, device_id=DEVICE):
    did, public, sign = identity
    return requests.post(
        origin + "/api/enrollment/redeem",
        json={
            "code": code,
            "did": did,
            "device_id": device_id,
            "public_key": b64encode(public).decode(),
            "signature": b64encode(sign(code.encode())).decode(),
        },
        headers={"Origin": origin},
        timeout=5,
    )


def _enrolled(served):
    """Issue a code for WORKSPACE and redeem it as a fresh identity. Returns (did, response).

    Note the agent id the console must select is NOT the DID: `GraphStore.storage_agent_id`
    pseudonymises an identity before persisting it (`pseudonym:<hex>`), which is why these
    tests read the id back out of the bind result instead of assuming the DID's own form.
    A test that hardcoded the DID would be asserting against the store's identity mode."""
    store, origin = served
    identity = _identity()
    code = issue_code(WORKSPACE, home=store.home)
    return identity[0], _redeem(origin, code, identity)


def test_a_redeemed_code_leaves_an_agent_the_console_can_list(served):
    store, _ = served
    _, response = _enrolled(served)

    assert response.status_code == 200, response.text
    listed = {str(item["agent_id"]) for item in store.agent_workspaces(limit=100)}
    assert response.json()["agent_id"] in listed, (
        "the redemption succeeded but the agent it reports binding is not in the agent "
        "listing, so the console has no agent to select"
    )


def test_the_bind_result_names_the_agent_and_the_store_to_open(served):
    """`workspace.choose(agentId, storeId)` needs both. A bind that reports neither cannot be
    wired to the choose-then-go path by any amount of viewer code."""
    _, response = _enrolled(served)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("agent_id"), f"the bind did not name the agent it bound: {body}"
    assert body.get("store_id"), f"the bind did not name the store to open it in: {body}"


def test_the_listed_agent_carries_the_device_that_redeemed_the_code(served):
    store, _ = served
    _, response = _enrolled(served)

    assert response.status_code == 200, response.text
    bound = response.json()["agent_id"]
    rows = [item for item in store.agent_workspaces(limit=100) if str(item["agent_id"]) == bound]
    assert rows, "the enrolled agent is not listed at all"
    assert str(rows[0]["device_id"]) == DEVICE, (
        "the enrolled agent is listed without the device that redeemed its code, so the "
        "console cannot show which device is bound"
    )


def test_a_refused_redemption_binds_nothing(served):
    """The negative half. A refusal must not leave a half-registered agent behind -- the
    same property Task 5 asserts for the on-chain path."""
    store, origin = served
    identity = _identity()
    # resolved the same way the route resolves it, because the DID is not what is persisted
    would_be = store.storage_agent_id(identity[0])
    # never issued: there is no such code
    response = _redeem(origin, "not-a-real-code", identity)

    assert response.status_code == 403
    listed = {str(item["agent_id"]) for item in store.agent_workspaces(limit=100)}
    assert would_be not in listed, "a refused redemption still bound the agent to the workspace"


def test_the_new_agent_is_visible_immediately_not_after_the_listing_cache_expires(served):
    """`agent_workspaces()` is cached for 60 seconds and the console's header selector warms
    that cache on every page load. Without an invalidation on the pairing write, an operator
    who runs `cortex connect --code` watches the connect screen show nothing for up to a
    minute and concludes the enrollment failed."""
    store, _ = served
    store.agent_workspaces(limit=100)  # warm the cache, as the console's page load does

    _, response = _enrolled(served)

    assert response.status_code == 200, response.text
    listed = {str(item["agent_id"]) for item in store.agent_workspaces(limit=100)}
    assert response.json()["agent_id"] in listed, (
        "the enrolled agent is missing from a listing that was warmed before the redemption, "
        "so the pairing write did not invalidate the cache"
    )
