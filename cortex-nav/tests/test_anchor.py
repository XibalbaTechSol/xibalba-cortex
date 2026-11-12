from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from eth_utils import keccak

from cortex_nav.anchor import graph_root, merkle_proof, verify
from cortex_nav.canonical import ZERO_ADDRESS, ZERO_SELECTOR, node_id
from cortex_nav.graph import Edge, ToolCallGraph
from cortex_nav.mask import action_mask

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "toy_toolgraph.golden.json").read_text(encoding="utf-8"))


def oz_process_proof(proof: list[bytes], leaf: bytes) -> bytes:
    """Independent re-implementation of OpenZeppelin MerkleProof.processProof (the oracle).

    computedHash = leaf; for each proof element p: computedHash = commutativeKeccak256(computedHash, p),
    where commutativeKeccak256(a, b) = a < b ? keccak256(a ++ b) : keccak256(b ++ a).
    """
    computed = leaf
    for p in proof:
        computed = keccak(computed + p) if int.from_bytes(computed, "big") < int.from_bytes(p, "big") else keccak(p + computed)
    return computed


def _chain(n: int) -> ToolCallGraph:
    return ToolCallGraph(
        Edge(
            from_node=node_id(f"state:{i}"),
            relation=node_id("tool:step"),
            to_node=node_id(f"state:{i + 1}"),
            target=ZERO_ADDRESS,
            target_selector=ZERO_SELECTOR,
            risk_weight_bps=i,
            grounded=True,
            r_task=1.0,
        )
        for i in range(n)
    )


def test_every_mask_allowed_edge_has_a_proof_that_verifies(toy):
    root = graph_root(toy)
    seen = 0
    for node in {e.from_node for e in toy.edges}:
        for allowed, edge in zip(action_mask(toy, node), toy.edges, strict=True):
            if not allowed:
                continue
            proof = merkle_proof(toy, edge)
            assert oz_process_proof(proof, edge.leaf) == root
            assert verify(root, edge.leaf, proof)
            seen += 1
    assert seen == len(toy.edges) == 5


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 16, 17, 33])
def test_all_proofs_verify_under_oz_rule_for_every_tree_shape(n):
    graph = _chain(n)
    root = graph_root(graph)
    for edge in graph.edges:
        proof = merkle_proof(graph, edge)
        assert oz_process_proof(proof, edge.leaf) == root
        assert verify(root, edge.leaf, proof)
    if n == 1:
        assert root == graph.edges[0].leaf and merkle_proof(graph, graph.edges[0]) == []


def test_root_is_independent_of_insertion_order(toy):
    assert graph_root(ToolCallGraph(reversed(toy.edges))) == graph_root(toy)


def test_hallucinated_edge_has_no_valid_proof(toy, toy_spec):
    root = graph_root(toy)
    # A direct idle -> done shortcut that the graph does not contain.
    fake = Edge(
        from_node=node_id(toy_spec["start"]),
        relation=node_id("tool:teleport"),
        to_node=node_id(toy_spec["goal"]),
        target=ZERO_ADDRESS,
        target_selector=ZERO_SELECTOR,
        risk_weight_bps=0,
        grounded=True,
        r_task=100.0,
    )
    assert fake not in toy
    with pytest.raises(KeyError):
        merkle_proof(toy, fake)
    assert not verify(root, fake.leaf, [])
    # Reusing any real edge's proof does not help, and neither does any prefix/suffix of one.
    for real in toy.edges:
        proof = merkle_proof(toy, real)
        assert not verify(root, fake.leaf, proof)
        assert oz_process_proof(proof, fake.leaf) != root
        for k in range(len(proof)):
            assert not verify(root, fake.leaf, proof[:k])
            assert not verify(root, fake.leaf, proof[k:])


def test_tampering_any_committed_field_invalidates_the_proof(toy):
    root = graph_root(toy)
    real = toy.edges[0]
    proof = merkle_proof(toy, real)
    assert verify(root, real.leaf, proof)
    lowered_risk = dataclasses.replace(real, risk_weight_bps=real.risk_weight_bps + 1)
    assert not verify(root, lowered_risk.leaf, proof)
    retargeted = dataclasses.replace(real, target="0x" + "11" * 20)
    assert not verify(root, retargeted.leaf, proof)
    if proof:
        flipped = [bytes([proof[0][0] ^ 1]) + proof[0][1:], *proof[1:]]
        assert not verify(root, real.leaf, flipped)


def test_empty_graph_has_no_root():
    with pytest.raises(ValueError):
        graph_root(ToolCallGraph([]))


def test_pinned_root_and_proofs_validated_against_policy_registry(toy):
    """These values were accepted by the real PolicyRegistry.checkGraphEdge (see README)."""
    assert "0x" + graph_root(toy).hex() == GOLDEN["root"]
    assert len(GOLDEN["edges"]) == len(toy.edges)
    for edge, pinned in zip(toy.edges, GOLDEN["edges"], strict=True):
        assert "0x" + edge.leaf.hex() == pinned["leaf"]
        assert ["0x" + p.hex() for p in merkle_proof(toy, edge)] == pinned["proof"]
