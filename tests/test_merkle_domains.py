from __future__ import annotations

from xibalba_cortex.events import (
    domain_merkle_proof,
    domain_merkle_root,
    merkle_root,
    verify_domain_merkle_proof,
)


def _h(byte: str) -> str:
    return "sha256:" + (byte * 2) * 32


LEAVES = [_h("aa"), _h("bb"), _h("cc")]


def test_different_domains_over_identical_leaves_produce_different_roots():
    proj = domain_merkle_root(LEAVES, domain="projection_checkpoint")
    trace = domain_merkle_root(LEAVES, domain="retrieval_trace")
    assert proj is not None and trace is not None
    assert proj != trace


def test_reordered_leaves_produce_a_different_domain_root():
    # The load-bearing property for "verify rebuilt projection against a new root": a
    # permutation of the same leaf set must not be indistinguishable from the original.
    forward = domain_merkle_root(LEAVES, domain="projection_checkpoint")
    reordered = domain_merkle_root(list(reversed(LEAVES)), domain="projection_checkpoint")
    assert forward != reordered


def test_plain_merkle_root_has_the_blind_spot_domain_merkle_root_fixes():
    # Documents *why* domain_merkle_root exists: merkle_parent sorts its two children before
    # hashing, so a same-pair swap under the plain (legacy, untouched) construction is
    # indistinguishable from the original -- this is the reorder-detection blind spot.
    pair = [_h("aa"), _h("bb")]
    assert merkle_root(pair) == merkle_root(list(reversed(pair)))
    # domain_merkle_root does not have this blind spot even for a same-pair swap, because the
    # position is committed into each leaf's own hash before pairing happens.
    assert domain_merkle_root(pair, domain="projection_checkpoint") != domain_merkle_root(
        list(reversed(pair)), domain="projection_checkpoint"
    )


def test_domain_merkle_root_of_empty_leaves_is_none():
    assert domain_merkle_root([], domain="projection_checkpoint") is None


def test_domain_merkle_proof_round_trips_for_every_leaf():
    for index in range(len(LEAVES)):
        proof = domain_merkle_proof(LEAVES, index, domain="retrieval_trace")
        assert verify_domain_merkle_proof(proof)
        assert proof["root"] == domain_merkle_root(LEAVES, domain="retrieval_trace")


def test_domain_merkle_proof_fails_on_tampered_leaf():
    proof = domain_merkle_proof(LEAVES, 1, domain="retrieval_trace")
    proof["payload_hash"] = _h("ff")
    assert not verify_domain_merkle_proof(proof)


def test_unknown_domain_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="unknown Merkle domain"):
        domain_merkle_root(LEAVES, domain="not-a-real-domain")
