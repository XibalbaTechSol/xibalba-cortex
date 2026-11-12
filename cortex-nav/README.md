# cortex-nav

Reduced navigation engine: the off-chain half of a design where an agent's action space is
the edges of a verified graph. The on-chain side (`PolicyRegistry` in integrity-core) stores a
Merkle root over the allowed edges and verifies proofs; this package computes the same leaf
and the same root in Python.

Deliberately small: no neural networks, no torch, no embeddings, no training loop.

| Module | What it does |
| --- | --- |
| `canonical.py` | `leaf(...)` = `keccak256(abi.encode(bytes32, bytes32, bytes32, address, bytes4, uint16))` (192-byte preimage), `node_id`, `selector_for` |
| `graph.py` | `Edge`, `ToolCallGraph` with a deterministic edge order. A forbidden transition is absent, never negatively weighted |
| `anchor.py` | `graph_root`, `merkle_proof`, `verify`, compatible with OpenZeppelin `MerkleProof.verify` |
| `mask.py` | `action_mask`, `masked_probabilities`: invalid actions get probability exactly `0.0` |
| `reward.py` | `edge_ais`, `path_return` (default reward: `xibalba_cortex.ais_trajectory_reward.multiplicative_reward`) |
| `planner.py` | `best_path`: exhaustive search over simple paths in the masked graph |

## Standalone on purpose

`cortex-nav` has its own `pyproject.toml` and `uv.lock`. It path-depends on the root
`xibalba-cortex` package (`../`, editable) for the one reward function the repository has. It
is not listed in the root `pyproject.toml` or root `uv.lock`, and the pilot deployment, which
installs only the root package, does not install it.

## Running the tests

```bash
cd cortex-nav
uv sync
uv run pytest -q
```

Sibling-checkout note: the root package path-depends on `../integrity-core/integrity-sdk`,
so an `integrity-core` checkout must sit next to the `xibalba-cortex` checkout (the same
layout the root package and CI already need). In a git worktree, put or link an
`integrity-core` checkout next to the worktree directory.

## What the root commits to

The leaf commits to `from_node`, `relation`, `to_node`, `target`, `target_selector` and
`risk_weight_bps`. `grounded` and `r_task` are off-chain annotations on an `Edge`: they are
not in the leaf, so the root does not vouch for them.

Merkle construction: leaves sorted ascending; adjacent nodes paired with the commutative
sorted-pair hash `keccak256(min(a, b) || max(a, b))`; an odd node at the end of a level is
promoted unchanged; a single-leaf tree's root is the leaf. Proofs are listed leaf-upward.

## `edge_ais` mapping

```
edge_ais = clamp(base_ais, 0, 1000) * (10000 - risk_weight_bps) / 10000 * g
g = 1.0 if grounded else 0.5
```

Strictly decreasing in `risk_weight_bps` over `[0, 10000]`; `Edge` rejects a risk weight
above 10000 bps.

## Validation against the contract

`tests/fixtures/toy_toolgraph.golden.json` pins the root, leaves and proofs of the 5-edge
`toy_toolgraph.json`. Those values were accepted by the real `PolicyRegistry.checkGraphEdge`
(integrity-core `contracts/src/trust/PolicyRegistry.sol`, OpenZeppelin `MerkleProof`), and
tampered edges and proofs were rejected, using a generated Foundry test:

```bash
uv run python scripts/gen_forge_crosscheck.py tests/fixtures/toy_toolgraph.json \
  > <integrity-core>/contracts/test/CortexNavCrossCheck.t.sol
(cd <integrity-core>/contracts && forge test --match-path test/CortexNavCrossCheck.t.sol -vv)
```

The generated test is temporary and is not committed to integrity-core. Re-run it whenever
the leaf encoding, the tree construction or the fixture changes, then regenerate the golden
file with `--golden`. The single golden leaf in `tests/test_canonical.py` is also asserted in
integrity-core's own Solidity tests.
