# Local Event Hash-Chain — Phase 1 Addendum

Status: implemented, 2026-08-05. Extends `docs/architecture/advanced-memory.md` with the
mechanism that lets this memory system inherit Integrity Protocol's security properties without
depending on the Integrity DAG (`INTEGRITY-LATEST/docs/design/memory-dag.md`) actually existing.

## The idea

Don't wait for the real Memory DAG. Implement the same pattern — content-addressed,
hash-linked, append-only — as this system's own local trust kernel, and treat anchoring to the
real on-chain `StateAnchor` as an optional later upgrade to a mechanism that already works, not
a dependency this system is blocked on.

`memory_events` was already the right shape for this: append-only, one row per state
transition. It needed two columns to become an actual hash chain rather than just an audit log.

## Mechanism

Each event node commits to its own content and its predecessor's id:

```
node = {
  schema:           "xibalba.memory.event.v1",
  memory_id:         <memory this event belongs to>,
  event_type:        "create" | "confirm" | "contradict" | "supersede" | "quarantine" | "forget" | "restore",
  detail:            <event-specific JSON, canonically encoded>,
  parent_event_id:   <previous event's node_id for this memory, or null>,
}
node_id = sha256(canonical_json(node))
```

`GraphStore._append_event()` (`src/xibalba_cortex/store.py`) is the single insertion point —
every `memory_events` write goes through it, so no call site can accidentally skip hash-chaining.
`GraphStore.verify_chain(memory_id)` recomputes every node from scratch and checks
`parent_event_id` resolves at each step — pure computation, no network, no external dependency.
Corrupting any historical event (even one nobody reads directly) breaks verification, because
every later node's hash transitively depends on it.

This maps directly onto the DAG design's object/ref split: `memory_events` rows are the
immutable **objects**; `memories.id` is the **ref** — the stable, human-facing name that
supersession moves to point at a new head, exactly like `refs/heads/main` moves on commit.

## What was deliberately kept out of the hash chain

`contradictions` stays a separate, non-hash-linked table. Per `memory-dag.md`'s own hard-won
lesson: structural edges (`parents`) must be strictly backward-in-time or the graph isn't
acyclic by construction. `contradicts` is symmetric, not temporal — hashing it into `parents`
would create exactly the unhashable cycle the DAG design document warns against. This was
already correct in the existing schema before this addendum; worth stating explicitly so a
future change doesn't "fix" it into a bug.

## Why this keeps the MCP server simple

- **No network calls for the trust property that matters most.** `verify_chain` is pure
  computation over rows already in SQLite — fits a stdio MCP tool with zero added latency or
  external dependency.
- **No key custody.** Nothing here requires the server to hold a private key. Signed
  `declared_intent` envelopes (future work) are verified, not generated, in-process — consistent
  with the crypto profile's existing rule.
- **Trustless verification.** Any client holding the event rows — not just this server — can
  independently recompute the chain. The MCP server's word is not the security boundary; the
  hash is.
- **Cheap on the hot path.** One extra SHA-256 per write, on top of the content hash already
  computed. Negligible next to the ~4ms/insert baseline measured in the Phase 0 spike.

## Migration path to the real Integrity DAG

When `INTEGRITY-LATEST`'s Memory DAG ships, `integrity_links.node_id` starts referencing *its*
node ids instead of (or alongside) this local chain's. No schema change to `memory_events` is
needed — the local chain remains valid on its own terms; external anchoring becomes an additive
verification state (`hash_match_local` → `ancestry_verified` → `anchored_to_configured_root`),
not a replacement mechanism. Nothing built now is thrown away.

## Test coverage

`tests/test_store.py::test_event_chain_is_hash_linked_and_tamper_evident` covers: parent linkage
across a `create` → `supersede` transition, distinct `node_id`s per event, `verify_chain`
succeeding on an intact chain, and `verify_chain` detecting a directly-tampered row (bypassing
the `GraphStore` API entirely, via a raw SQL `UPDATE`) as invalid — the actual property being
claimed, not just the happy path.
