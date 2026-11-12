from __future__ import annotations

import pytest
from eth_utils import keccak

from cortex_nav.canonical import ZERO_ADDRESS, ZERO_SELECTOR, leaf, leaf_preimage, node_id, selector_for

B1, B2, B3 = (i.to_bytes(32, "big") for i in (1, 2, 3))
TARGET = "0x00000000000000000000000000000000000000CA"
SEL = bytes.fromhex("a9059cbb")
# Asserted in Solidity too (PolicyRegistry.leafOf); do not regenerate from this implementation.
GOLDEN_LEAF = "58febd532cdbee740056933391a0fc3ca82d1d90cef567a211dc4e049ea138d0"


def test_golden_leaf_vector():
    assert leaf(B1, B2, B3, TARGET, SEL, 500).hex() == GOLDEN_LEAF


def test_target_may_be_given_as_bytes_or_any_hex_casing():
    as_bytes = bytes.fromhex(TARGET[2:])
    assert leaf(B1, B2, B3, as_bytes, SEL, 500).hex() == GOLDEN_LEAF
    assert leaf(B1, B2, B3, TARGET.lower(), SEL, 500).hex() == GOLDEN_LEAF


def test_preimage_is_192_bytes_with_abi_word_padding():
    pre = leaf_preimage(B1, B2, B3, TARGET, SEL, 500)
    assert len(pre) == 192
    assert pre[0:32] == B1 and pre[32:64] == B2 and pre[64:96] == B3
    # address: left-padded with 12 zero bytes
    assert pre[96:108] == bytes(12) and pre[108:128] == bytes.fromhex(TARGET[2:])
    # bytes4: RIGHT-padded with 28 zero bytes
    assert pre[128:132] == SEL and pre[132:160] == bytes(28)
    # uint16: left-padded, big-endian
    assert pre[160:190] == bytes(30) and pre[190:192] == (500).to_bytes(2, "big")
    assert keccak(pre) == leaf(B1, B2, B3, TARGET, SEL, 500)


def test_every_field_is_bound_into_the_leaf():
    base = leaf(B1, B2, B3, TARGET, SEL, 500)
    variants = [
        leaf(B2, B2, B3, TARGET, SEL, 500),
        leaf(B1, B1, B3, TARGET, SEL, 500),
        leaf(B1, B2, B1, TARGET, SEL, 500),
        leaf(B1, B2, B3, ZERO_ADDRESS, SEL, 500),
        leaf(B1, B2, B3, TARGET, bytes.fromhex("095ea7b3"), 500),
        leaf(B1, B2, B3, TARGET, SEL, 501),
    ]
    assert len({base, *variants}) == 7


@pytest.mark.parametrize(
    "bad",
    [
        dict(from_node=b"\x01"),
        dict(relation=bytes(31)),
        dict(to_node=bytes(33)),
        dict(target="0x1234"),
        dict(target=bytes(19)),
        dict(target_selector=bytes(3)),
        dict(risk_weight_bps=-1),
        dict(risk_weight_bps=65536),
        dict(risk_weight_bps=True),
        dict(risk_weight_bps=1.0),
    ],
)
def test_malformed_fields_are_rejected_not_padded(bad):
    args = dict(from_node=B1, relation=B2, to_node=B3, target=TARGET, target_selector=SEL, risk_weight_bps=500)
    args.update(bad)
    with pytest.raises((ValueError, TypeError)):
        leaf(**args)


def test_node_id_is_keccak_of_utf8():
    assert node_id("state:idle") == keccak(b"state:idle")
    assert node_id("tool:read_file") == keccak("tool:read_file".encode("utf-8"))
    assert len(node_id("état:prêt")) == 32 and node_id("état:prêt") == keccak("état:prêt".encode("utf-8"))
    assert node_id("state:idle") != node_id("state:idle ")


def test_selector_for_matches_the_evm_function_selector():
    assert selector_for("transfer(address,uint256)") == SEL
    assert selector_for("approve(address,uint256)").hex() == "095ea7b3"


def test_selector_for_none_is_zero():
    assert selector_for(None) == b"\x00\x00\x00\x00" == ZERO_SELECTOR
    assert ZERO_ADDRESS == "0x" + "00" * 20
