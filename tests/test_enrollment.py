"""Enrollment codes: the one-shot bearer secret that binds an agent DID to a workspace.

Review Focus item 5. A code is a bearer secret, so it is short-lived, single-use, rate
limited, and every issue and redeem is audited.

The security property that matters most here is not "the signature verifies" but "the
signature verifies *against the DID being claimed*". `did:integrity:<hex>` is
SHA-256 over the raw Ed25519 public key, so a redeemer who supplies their own keypair
alongside someone else's DID must be refused -- otherwise the signature check is
theatre and anyone holding a code can bind any DID they can name.
"""

import pytest

from integrity_sdk.did import Ed25519PrivateKey, fingerprint_for_pubkey

from xibalba_cortex.enrollment import (
    EnrollmentRefused,
    issue_code,
    redeem_code,
)

WORKSPACE = "ws-1"


def _identity():
    """A fresh agent identity: (did, public_key_bytes, sign)."""
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    did = f"did:integrity:{fingerprint_for_pubkey(public)}"
    return did, public, private.sign


@pytest.fixture
def agent():
    return _identity()


@pytest.fixture
def other():
    return _identity()


# --- generation -------------------------------------------------------------------------

def test_issuing_a_code_returns_a_high_entropy_secret(tmp_path):
    code = issue_code(WORKSPACE, home=tmp_path)

    assert isinstance(code, str)
    assert len(code) >= 32, "a bearer secret this short is guessable"


def test_two_codes_are_never_the_same(tmp_path):
    codes = {issue_code(WORKSPACE, home=tmp_path) for _ in range(20)}

    assert len(codes) == 20


# --- the happy path ---------------------------------------------------------------------

def test_a_signed_redemption_binds_the_did_to_the_workspace(tmp_path, agent):
    did, public, sign = agent
    code = issue_code(WORKSPACE, home=tmp_path)

    result = redeem_code(code, did=did, device_id="d1", public_key=public,
                         signature=sign(code.encode()), home=tmp_path)

    assert result["did"] == did
    assert result["workspace_id"] == WORKSPACE
    assert result["device_id"] == "d1"


# --- single use -------------------------------------------------------------------------

def test_a_code_cannot_be_redeemed_twice(tmp_path, agent):
    did, public, sign = agent
    code = issue_code(WORKSPACE, home=tmp_path)
    redeem_code(code, did=did, device_id="d1", public_key=public,
                signature=sign(code.encode()), home=tmp_path)

    with pytest.raises(EnrollmentRefused):
        redeem_code(code, did=did, device_id="d2", public_key=public,
                    signature=sign(code.encode()), home=tmp_path)


def test_a_replayed_redemption_does_not_rebind_the_workspace(tmp_path, agent, other):
    """The replay that matters: a second, *different* agent presenting a captured code."""
    did, public, sign = agent
    other_did, other_public, other_sign = other
    code = issue_code(WORKSPACE, home=tmp_path)
    redeem_code(code, did=did, device_id="d1", public_key=public,
                signature=sign(code.encode()), home=tmp_path)

    with pytest.raises(EnrollmentRefused):
        redeem_code(code, did=other_did, device_id="d2", public_key=other_public,
                    signature=other_sign(code.encode()), home=tmp_path)


# --- TTL --------------------------------------------------------------------------------

def test_an_expired_code_is_refused(tmp_path, agent):
    did, public, sign = agent
    code = issue_code(WORKSPACE, ttl_seconds=0, home=tmp_path)

    with pytest.raises(EnrollmentRefused):
        redeem_code(code, did=did, device_id="d1", public_key=public,
                    signature=sign(code.encode()), home=tmp_path)


def test_a_code_inside_its_ttl_is_accepted(tmp_path, agent):
    """The converse, so the expiry test is not passing because everything is refused."""
    did, public, sign = agent
    code = issue_code(WORKSPACE, ttl_seconds=600, home=tmp_path)

    assert redeem_code(code, did=did, device_id="d1", public_key=public,
                       signature=sign(code.encode()), home=tmp_path)["did"] == did


# --- signature verification -------------------------------------------------------------

def test_a_binding_cannot_be_created_without_a_signature_from_the_agents_key(tmp_path, agent, other):
    did, _public, _sign = agent
    _other_did, other_public, other_sign = other
    code = issue_code(WORKSPACE, home=tmp_path)

    with pytest.raises(EnrollmentRefused):
        redeem_code(code, did=did, device_id="d1",
                    public_key=other_public, signature=other_sign(code.encode()), home=tmp_path)


def test_a_key_that_does_not_match_the_claimed_did_is_refused(tmp_path, agent, other):
    """The attack the signature check alone does not stop: a valid signature over the code,
    made with the attacker's own key, presented alongside the victim's DID."""
    victim_did, _victim_public, _ = agent
    _other_did, other_public, other_sign = other
    code = issue_code(WORKSPACE, home=tmp_path)

    with pytest.raises(EnrollmentRefused):
        redeem_code(code, did=victim_did, device_id="d1",
                    public_key=other_public, signature=other_sign(code.encode()), home=tmp_path)


def test_a_signature_over_something_other_than_the_code_is_refused(tmp_path, agent):
    did, public, sign = agent
    code = issue_code(WORKSPACE, home=tmp_path)

    with pytest.raises(EnrollmentRefused):
        redeem_code(code, did=did, device_id="d1", public_key=public,
                    signature=sign(b"some other message"), home=tmp_path)


def test_a_garbage_signature_is_refused_and_does_not_raise_something_else(tmp_path, agent):
    did, public, _sign = agent
    code = issue_code(WORKSPACE, home=tmp_path)

    with pytest.raises(EnrollmentRefused):
        redeem_code(code, did=did, device_id="d1", public_key=public,
                    signature=b"not-a-signature", home=tmp_path)


# --- unknown and wrong-workspace --------------------------------------------------------

def test_an_unknown_code_is_refused(tmp_path, agent):
    did, public, sign = agent

    with pytest.raises(EnrollmentRefused):
        redeem_code("nope" * 10, did=did, device_id="d1", public_key=public,
                    signature=sign((("nope" * 10)).encode()), home=tmp_path)


# --- the refusals do not enumerate ------------------------------------------------------

def test_every_refusal_reads_the_same_to_the_caller(tmp_path, agent, other):
    """A caller holding a code must not be able to tell *why* it failed. Distinguishable
    messages turn this endpoint into an oracle: which workspace a code belongs to, whether
    a code ever existed, whether it was already used. The reason is audited, not returned."""
    did, public, sign = agent
    _other_did, other_public, other_sign = other

    messages = set()

    expired = issue_code(WORKSPACE, ttl_seconds=0, home=tmp_path)
    used = issue_code(WORKSPACE, home=tmp_path)
    redeem_code(used, did=did, device_id="d1", public_key=public,
                signature=sign(used.encode()), home=tmp_path)
    badsig = issue_code(WORKSPACE, home=tmp_path)
    unknown = "z" * 43

    for code, kwargs in (
        (expired, dict(public_key=public, signature=sign(expired.encode()))),
        (used, dict(public_key=public, signature=sign(used.encode()))),
        (badsig, dict(public_key=other_public, signature=other_sign(badsig.encode()))),
        (unknown, dict(public_key=public, signature=sign(unknown.encode()))),
    ):
        with pytest.raises(EnrollmentRefused) as caught:
            redeem_code(code, did=did, device_id="dx", home=tmp_path, **kwargs)
        messages.add(str(caught.value))

    assert len(messages) == 1, f"the refusal enumerates its causes: {messages}"


# --- rate limit -------------------------------------------------------------------------

def test_redemption_attempts_are_rate_limited(tmp_path, agent):
    """Codes are bearer secrets; unbounded attempts make them brute-forceable."""
    did, public, sign = agent

    refusals = 0
    for _ in range(50):
        try:
            redeem_code("y" * 43, did=did, device_id="d1", public_key=public,
                        signature=sign((("y" * 43)).encode()), home=tmp_path)
        except EnrollmentRefused:
            refusals += 1

    # Once the limiter engages a *valid* code must also be refused, which is the only
    # externally visible proof that attempts are being counted rather than just failing.
    good = issue_code(WORKSPACE, home=tmp_path)
    with pytest.raises(EnrollmentRefused):
        redeem_code(good, did=did, device_id="d1", public_key=public,
                    signature=sign(good.encode()), home=tmp_path)
    assert refusals == 50


# --- audit ------------------------------------------------------------------------------

def test_issue_and_redeem_are_audited_without_recording_the_code(tmp_path, agent):
    from xibalba_cortex.enrollment import enrollment_events

    did, public, sign = agent
    code = issue_code(WORKSPACE, home=tmp_path)
    redeem_code(code, did=did, device_id="d1", public_key=public,
                signature=sign(code.encode()), home=tmp_path)

    events = enrollment_events(tmp_path)
    kinds = [e["event_type"] for e in events]
    assert "enrollment_code_issued" in kinds
    assert "enrollment_code_redeemed" in kinds
    # The code is the secret. An audit trail that stores it is a second copy to steal.
    assert code not in repr(events)


# --- the issue route --------------------------------------------------------------------

def test_the_issue_route_requires_the_operator_or_admin_role():
    """The plan's requirement: a viewer-role session is refused with the *existing*
    operator/admin message, not a new one invented for this route."""
    from xibalba_cortex.local_api import _assert_pair_manager

    with pytest.raises(PermissionError, match="operator or admin role is required"):
        _assert_pair_manager({"roles": ["reader"]})

    # and the converse, so the test above is not passing because everything is refused
    _assert_pair_manager({"roles": ["operator"]})
    _assert_pair_manager({"roles": ["admin"]})


def test_the_issue_route_is_wired_and_gated():
    """The route exists, is gated by `_assert_pair_manager`, and returns the code once."""
    import inspect

    from xibalba_cortex import local_api

    source = inspect.getsource(local_api)
    assert '["api", "enrollment", "codes"]' in source, "the issue route is not wired"
    # the gate must be in the same branch as the issue call
    # The window must end at the NEXT branch. A fixed character count does not: with the
    # gate deleted from this branch, the following `agent-devices/associate` branch's own
    # `_assert_pair_manager` fell inside a 1400-character window and the test passed
    # vacuously. Proved by a mutation that removed the gate and left this test green.
    after = source.split('["api", "enrollment", "codes"]', 1)[1]
    branch = after.split('elif parts ==', 1)[0]
    assert "_assert_pair_manager(principal)" in branch, "the issue route is not role-gated"
    assert "issue_code(" in branch


# --- the redeem route and `cortex connect --code` ---------------------------------------

def test_the_redeem_route_is_wired_and_is_deliberately_unauthenticated():
    """The plan's Files list names only an issue route, but redemption cannot be
    client-local: the code table lives on the server. So a redeem route is required.

    It takes no bearer token *by design* -- the code plus a signature from the DID's key
    IS the credential, and an agent enrolling for the first time has no token yet. That is
    why `redeem_code` is rate limited and why its refusals do not enumerate."""
    import inspect

    from xibalba_cortex import local_api

    source = inspect.getsource(local_api)
    assert '["api", "enrollment", "redeem"]' in source, "the redeem route is not wired"
    # This route is an `if ... return` handled before the auth preamble (as /api/contact
    # is), not an `elif` in the chain, so the branch ends at its own `return` -- splitting
    # on the next `elif parts ==` ran far past it and picked up an unrelated
    # `_assert_pair_manager` from later in do_POST.
    after = source.split('["api", "enrollment", "redeem"]', 1)[1]
    branch = after.split('\n                return', 1)[0]
    assert "redeem_code(" in branch
    # It must NOT be behind the pairing gate; an operator role is exactly what the
    # enrolling agent does not have.
    assert "_assert_pair_manager" not in branch


def test_connect_accepts_a_code_and_signs_it_with_the_agents_own_key():
    import inspect

    from xibalba_cortex import connect as connect_module

    source = inspect.getsource(connect_module)
    assert "--code" in source, "`cortex connect --code` is not wired"
    assert "redeem" in source
    # The signature must be made locally from the keypair, never by sending the key away.
    assert "sign(" in source
    assert "private_bytes" not in source, "connect must never transmit private key material"
