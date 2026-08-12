# Xibalba Cortex — Cryptographic Profile v1

Status: pinned, 2026-08-05. This is the normative reference for hashing decisions in this
project; code and future documents must not silently diverge from it.

## Hash algorithm boundary

Two distinct hash algorithms are in scope, used at two distinct boundaries. They are never
interchangeable and never compared to each other directly.

| Boundary | Algorithm | Where | Why |
|---|---|---|---|
| Local content hash | SHA-256, `sha256:`-hex-prefixed | `sources.content_hash`, `memories.content_hash` in `src/xibalba_cortex/store.py` | Purely local, never anchored, never leaves this process. SHA-256 is faster and better-supported for a hot-path hash computed on every `store_memory` call. |
| Integrity DAG verification | Keccak-256 (`eth-hash[pycryptodome]`) | `integrity_links.node_id` comparison only | Matches `keccak256` node-id convention in `integrity-core/docs/design/memory-dag.md` and `StateAnchor.sol`'s leaf hashing. Used only when comparing against, or computing a candidate for, an anchored DAG node id. |

**Rule:** a content hash computed for local storage (`memories.content_hash`) is never presented
as, or compared against, a DAG `node_id`. If a memory needs to be verified against the DAG, its
canonical body is re-hashed with Keccak specifically for that comparison; the SHA-256 value
already stored is not reused or converted.

## Why this is pinned now rather than left to convention

`store.py` already computes SHA-256 for every stored memory; `pyproject.toml` already declares
`eth-hash[pycryptodome]` as a dependency for DAG work. Without an explicit boundary, Task 6-style
work ("local Keccak hash matching" against the DAG) risks comparing a SHA-256 digest to a
Keccak-256 digest and silently treating a type mismatch as a verification failure, or worse,
coercing one into the other's format. This is the highest-cost-to-change decision in the system
once real memory data accumulates under the SHA-256 scheme, so it is pinned before Phase 1 writes
begin, per `docs/architecture/advanced-memory.md` §3.3.

## Anchoring selection policy (pinned ahead of DAG availability)

Not every memory should be anchored once the DAG exists — per-memory anchoring is noisy and
mostly immortalizes provisional content nobody needs a tamper-evident record of. Two-tier
policy, decided now so it doesn't get improvised later:

- **Always anchor:** `declared_intent` and `policy` evidence classes (see the epistemic-class
  column, `memories.derivation_family` in `store.py`). These are the load-bearing "the agent
  declared it would do X" record BCC/Merkle exists to make provable — skipping them defeats the
  purpose.
- **Randomly sample the rest** (`observed_event`, `extracted_proposition`, `summary`,
  `inference`): unpredictable sampling makes the corpus spot-checkable and deters selective
  curation (anchoring only "confirmed"-looking memories while embarrassing ones stay
  perpetually `candidate`/`disputed`) — the same rationale as random audit sampling. Pure random
  selection alone is insufficient, because the one memory that mattered (an intent revision, a
  contradicted claim) might simply not be drawn; hence the two-tier split rather than pure
  randomness.

## Deferred (not yet needed)

The portable event kernel uses the versioned canonical JSON encoding above and a local SHA-256
Merkle batch profile: leaves retain insertion position, each pair is sorted lexicographically
before hashing, and an odd final node is promoted unchanged. Inclusion proofs omit a sibling at
an unchanged promotion level. These rules are published in `tests/conformance/test_vectors.json`
so an independent implementation can reproduce them. This local batch root is evidence of byte
inclusion only; it is not a BCC commitment, Memory DAG node, or StateAnchor identifier.
