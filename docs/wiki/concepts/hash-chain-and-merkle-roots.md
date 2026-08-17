---
title: Hash Chain and Merkle Roots
acronyms: []
created: 2026-08-12
updated: 2026-08-17
type: concept
tags: [provenance, cryptography, storage]
confidence: high
source_files:
  - src/xibalba_cortex/store.py
  - docs/operations/store-contract.md
---

## Table of contents

- [Overview](#overview)
- [Per-memory event chain](#per-memory-event-chain)
- [Session exchange chain (local Merkle root)](#session-exchange-chain-local-merkle-root)
- [Verification vs. anchoring](#verification-vs-anchoring)

## Overview

Xibalba Cortex builds tamper evidence out of two related, locally-computed hash structures.
Both use `integrity_sdk.crypto.merkle.compute_node_hash` and follow the same pattern: a new
node's `node_id` is a hash over its own content plus the previous node's `node_id`, so
reordering, forging, or dropping a node is detectable by recomputing the chain from the start.

Neither structure is a blockchain. There is no distributed consensus, no external validators,
and no proof-of-work — this is **local** tamper evidence only. It becomes cryptographic
evidence a third party can rely on only once anchored externally; see
[Compliance Evidence Trail](../queries/compliance-evidence-trail.md).

## Per-memory event chain

`memory_events` is append-only. Each event row (`create`, `confirm`, `contradict`, `supersede`,
`quarantine`, `forget`, `restore`, `attach_media`) carries a `node_id` and a `parent_event_id`
pointing at the previous event's `node_id` for that memory. `GraphStore.verify_chain(memory_id)`
recomputes every event's `node_id` from its recorded content and checks parent linkage, pure
local computation with no network dependency. `GraphStore._head_node_id(memory_id)` returns the
current chain tip.

## Session exchange chain (local Merkle root)

`exchanges` chains a session's turn-by-turn structure the same way, one level up: each
exchange's `node_id` commits to its prompt/response content hashes and tool-call identifiers
(via `exchange_tool_calls`), plus the previous exchange's `node_id` (`parent_node_id`).
`GraphStore.verify_exchange_chain(external_session_id)` recomputes and verifies the whole
sequence. `GraphStore.session_merkle_root(external_session_id)` returns the latest exchange's
`node_id` as the session's root — labeled `root_kind:
"xibalba.exchange_chain.local_merkle_root.v1"` in the returned payload, an explicit reminder that
this is a local Merkle-style root over this session's own exchanges, not a proof anchored to
anything external. `GraphStore.session_merkle_evidence()` exposes a separately versioned,
domain-separated and position-committing inclusion proof (`tree_kind:
"xibalba.exchange_batch.merkle.v2"`); the legacy unordered v1 construction is not used for new
responses. The proof remains inclusion evidence only, not proof of truth, authorization,
completeness, ownership, or external finality. See [Sessions and Exchanges](../entities/sessions-and-exchanges.md)
for how an exchange gets built out of a prompt, response, and tool calls.

## Verification vs. anchoring

`verify_chain()` and `verify_exchange_chain()` only prove internal self-consistency: that the
chain as stored hasn't been silently edited since it was written. They say nothing about
whether the store itself was tampered with wholesale, or whether a third party can trust the
chain without also trusting this machine. `memory_verify_integrity_link` compares a memory's
local content hash against an external Integrity Memory DAG node's hash — that's a
byte-lineage check, not proof of truth or authorization. Turning a local root into evidence a
compliance reviewer or counterparty can rely on requires anchoring it externally, which is
opt-in (`XIBALBA_ANCHOR_URL`, `memory_anchor_session_root`) rather than automatic — see
[Compliance Evidence Trail](../queries/compliance-evidence-trail.md) and
[Ecosystem Role](../architecture/ecosystem-role.md).

See [MCP Tool Surface](mcp-tool-surface.md) for the tools that expose chain verification and
session root inspection to a calling agent.
