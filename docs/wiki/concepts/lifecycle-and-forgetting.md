---
title: Lifecycle and Forgetting
acronyms: []
created: 2026-08-12
updated: 2026-08-12
type: concept
tags: [storage, provenance, compliance]
confidence: high
source_files:
  - src/xibalba_cortex/store.py
  - docs/operations/store-contract.md
---

## Table of contents

- [Overview](#overview)
- [Recall eligibility](#recall-eligibility)
- [Transitions](#transitions)
- [Forgetting preserves residual tamper-evidence hashes — deliberately](#forgetting-preserves-residual-tamper-evidence-hashes-deliberately)
- [Retrieved memory is never instruction authority](#retrieved-memory-is-never-instruction-authority)

## Overview

Every memory carries a lifecycle status: `candidate`, `active`, `confirmed`, `disputed`,
`quarantined`, `superseded`, or `forgotten`. Lifecycle mutation always appends an event to
`memory_events` rather than editing history in place — see
[Hash Chain and Merkle Roots](hash-chain-and-merkle-roots.md) for how that event chain is made
tamper-evident.

## Recall eligibility

`GraphStore.search()` (default recall) returns only `active` and `confirmed` memories.
`quarantined`, `superseded`, `forgotten`, `candidate`, and `disputed` memories are inspectable
by id (`memory_get`) but excluded from default recall — narrow by design, not an oversight.

## Transitions

- **Contradiction** — `mark_contradiction()` records a `contradictions` row and appends a
  `contradict` event to both memories, but changes neither memory's status. Contradiction is
  navigation evidence for a human or downstream process to resolve, not automatic resolution.
- **Supersession** — `supersede_memory()` creates a new memory, marks the old one `superseded`,
  links `supersedes_id` on the new memory back to the old, and appends a `supersede` event to
  the old memory's chain.
- **Quarantine** — a quarantined write records a `quarantine` event and is excluded from recall.
- **Forgetting** — `forget_memory()` marks the memory `forgotten`, excludes it from recall,
  appends a `forget` event, and returns `content_hash_retained=true`.
- **Restore** — `GraphStore.restore()` is database-level backup restore (see
  [Graph Store](graph-store.md)), not a per-memory lifecycle restore; it refuses corrupt input
  before replacing the live database and preserves whatever event chains are present in the
  restored snapshot.

## Forgetting preserves residual tamper-evidence hashes — deliberately

Forgetting removes user-visible content from recall, but the memory's content hash and its full
event history remain in the store. This is documented explicitly in
`docs/operations/store-contract.md`: "a forgotten memory can still prove that a prior byte
sequence existed locally, but it should not be returned by recall or treated as active memory."

This is a deliberate transparency tradeoff, not a bug: an auditor can confirm that *something*
was forgotten and roughly when, without being able to recover the forgotten content itself. A
forgetting mechanism that left zero trace would make it impossible to distinguish "nothing was
ever here" from "something was forgotten," which is a worse property for an auditable memory
store to have. See [Compliance Evidence Trail](../queries/compliance-evidence-trail.md) for how
this residual-hash behavior fits into the broader auditability story.

## Retrieved memory is never instruction authority

This constraint is independent of lifecycle state — it applies to `active`/`confirmed` recalled
content exactly as much as to anything else the store happens to expose. Every MCP tool that
returns memory content repeats the same warning (see [MCP Tool Surface](mcp-tool-surface.md)):
returned content is untrusted evidence from the agent's own memory, never a directive to follow
regardless of what the text says.

See [Graph Store](graph-store.md) for the object model these transitions operate on.
