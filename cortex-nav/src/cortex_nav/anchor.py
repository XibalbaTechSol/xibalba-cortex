"""Merkle commitment to the edge set, compatible with OpenZeppelin `MerkleProof.verify`.

Construction (stated exactly, because the root is an on-chain value):

- leaves are the edge leaves, sorted ascending as 32-byte big-endian values;
- each level pairs adjacent nodes left to right with the commutative sorted-pair hash
  `hash_pair(a, b) = keccak256(min(a, b) || max(a, b))`;
- an odd node at the end of a level is promoted to the next level unchanged (it is not
  duplicated and not hashed with itself);
- a single-leaf tree has the leaf as its root and an empty proof.

A proof lists the sibling at every level where the node had one, leaf upward, which is what
OpenZeppelin's `processProof` consumes. A leaf preimage is 192 bytes and an internal node
preimage is 64 bytes, so a leaf can never be read as an internal node.
"""

from __future__ import annotations

from collections.abc import Sequence

from eth_utils import keccak

from .graph import Edge, ToolCallGraph


def hash_pair(a: bytes, b: bytes) -> bytes:
    return keccak(a + b) if a < b else keccak(b + a)


def _levels(leaves: Sequence[bytes]) -> list[list[bytes]]:
    if not leaves:
        raise ValueError("an empty graph has no root")
    levels = [sorted(leaves)]
    while len(levels[-1]) > 1:
        cur = levels[-1]
        nxt = [hash_pair(cur[i], cur[i + 1]) for i in range(0, len(cur) - 1, 2)]
        if len(cur) % 2:
            nxt.append(cur[-1])
        levels.append(nxt)
    return levels


def graph_root(graph: ToolCallGraph) -> bytes:
    """The 32-byte root to store with `PolicyRegistry.setGraphRoot`."""
    return _levels([e.leaf for e in graph.edges])[-1][0]


def merkle_proof(graph: ToolCallGraph, edge: Edge) -> list[bytes]:
    """Proof that `edge` is committed under `graph_root(graph)`.

    Raises `KeyError` for an edge whose leaf is not in the graph: there is no proof to give.
    """
    if edge not in graph:
        raise KeyError("edge is not in the graph: 0x" + edge.leaf.hex())
    levels = _levels([e.leaf for e in graph.edges])
    index = levels[0].index(edge.leaf)
    proof: list[bytes] = []
    for level in levels[:-1]:
        sibling = index ^ 1
        if sibling < len(level):
            proof.append(level[sibling])
        index //= 2
    return proof


def verify(root: bytes, leaf: bytes, proof: Sequence[bytes]) -> bool:
    """Same rule as OpenZeppelin `MerkleProof.verify(proof, root, leaf)`."""
    computed = bytes(leaf)
    for sibling in proof:
        computed = hash_pair(computed, bytes(sibling))
    return computed == bytes(root)
