"""Canonical encodings shared with the on-chain side (`PolicyRegistry.leafOf`).

The leaf is `keccak256(abi.encode(bytes32, bytes32, bytes32, address, bytes4, uint16))`:
standard (non-packed) ABI encoding, six 32-byte words, a 192-byte preimage. `address` and
`uint16` are left-padded, `bytes4` is right-padded. Malformed fields are rejected rather
than padded, so two different inputs can never collapse onto one leaf.
"""

from __future__ import annotations

from eth_abi import encode as abi_encode
from eth_utils import keccak

LEAF_ABI_TYPES = ("bytes32", "bytes32", "bytes32", "address", "bytes4", "uint16")
LEAF_PREIMAGE_BYTES = 192
ZERO_ADDRESS = "0x" + "00" * 20
ZERO_SELECTOR = b"\x00\x00\x00\x00"
UINT16_MAX = 0xFFFF


def _fixed_bytes(name: str, value: bytes, length: int) -> bytes:
    if not isinstance(value, (bytes, bytearray)):
        raise TypeError(f"{name} must be bytes, got {type(value).__name__}")
    if len(value) != length:
        raise ValueError(f"{name} must be exactly {length} bytes, got {len(value)}")
    return bytes(value)


def address_bytes(target: str | bytes) -> bytes:
    """Normalize an address given as 20 raw bytes or as a 40-hex-digit string (any casing)."""
    if isinstance(target, (bytes, bytearray)):
        return _fixed_bytes("target", target, 20)
    if not isinstance(target, str):
        raise TypeError(f"target must be str or bytes, got {type(target).__name__}")
    digits = target[2:] if target[:2] in ("0x", "0X") else target
    if len(digits) != 40:
        raise ValueError("target must be a 20-byte address")
    return bytes.fromhex(digits)


def leaf_preimage(
    from_node: bytes,
    relation: bytes,
    to_node: bytes,
    target: str | bytes,
    target_selector: bytes,
    risk_weight_bps: int,
) -> bytes:
    """The 192-byte `abi.encode(...)` preimage of an edge leaf."""
    if isinstance(risk_weight_bps, bool) or not isinstance(risk_weight_bps, int):
        raise TypeError("risk_weight_bps must be an int")
    if not 0 <= risk_weight_bps <= UINT16_MAX:
        raise ValueError("risk_weight_bps must fit in uint16")
    preimage = abi_encode(
        LEAF_ABI_TYPES,
        (
            _fixed_bytes("from_node", from_node, 32),
            _fixed_bytes("relation", relation, 32),
            _fixed_bytes("to_node", to_node, 32),
            "0x" + address_bytes(target).hex(),
            _fixed_bytes("target_selector", target_selector, 4),
            risk_weight_bps,
        ),
    )
    assert len(preimage) == LEAF_PREIMAGE_BYTES
    return preimage


def leaf(
    from_node: bytes,
    relation: bytes,
    to_node: bytes,
    target: str | bytes,
    target_selector: bytes,
    risk_weight_bps: int,
) -> bytes:
    """`keccak256` of the edge preimage; equal to `PolicyRegistry.leafOf(...)` on-chain."""
    return keccak(leaf_preimage(from_node, relation, to_node, target, target_selector, risk_weight_bps))


def node_id(canonical_string: str) -> bytes:
    """Node or relation id: `keccak256` of the UTF-8 bytes, e.g. `state:idle`, `tool:read_file`."""
    if not isinstance(canonical_string, str):
        raise TypeError("canonical_string must be str")
    return keccak(canonical_string.encode("utf-8"))


def selector_for(tool_name: str | None) -> bytes:
    """`keccak256(tool_name)[:4]` for a tool bound to an on-chain call.

    For an EVM function, pass its canonical signature (`transfer(address,uint256)`) to get
    the function selector. `None` marks an off-chain-only edge: its selector is zero and its
    target is the zero address.
    """
    if tool_name is None:
        return ZERO_SELECTOR
    if not isinstance(tool_name, str):
        raise TypeError("tool_name must be str or None")
    return keccak(tool_name.encode("utf-8"))[:4]
