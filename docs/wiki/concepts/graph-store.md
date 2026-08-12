---
title: Graph Store
acronyms: []
created: 2026-08-12
updated: 2026-08-12
type: concept
tags: [storage, provenance]
confidence: high
source_files:
  - src/xibalba_cortex/store.py
  - SPECIFICATION.md
  - docs/operations/store-contract.md
---

## Table of contents

- [Overview](#overview)
- [Object model](#object-model)
- [Retrieval](#retrieval)

## Overview

`GraphStore` in `src/xibalba_cortex/store.py` is the canonical local store for Xibalba Cortex.
It is a single profile-local SQLite database (`graph-memory.sqlite3`) opened in WAL mode with
FTS5 (lexical recall) and `sqlite-vec` (optional vector recall) extensions loaded. The profile
directory is created with mode `0700` and the database file with mode `0600`. `GraphStore.status()`
reports schema version, WAL journal mode, foreign-key enforcement, FTS5 availability,
`PRAGMA integrity_check`, identity mode, database path, and memory count — see
[Store Schema Overview](../architecture/store-schema-overview.md) for the full table list.

`SPECIFICATION.md` §4 "Store Model" is the normative source for the object model; this page
summarizes it at the level a new contributor needs before reading code.

## Object model

- **Sources** — raw evidence with provenance: origin/locator, content hash, capture time, and
  profile. Every memory points back to exactly one source row (`memories.source_id`), so a
  memory's claim is never disconnected from where it came from.
- **Memories** — the queryable unit. Each has an epistemic class (`derivation_family`), a
  lifecycle status (`candidate`, `active`, `confirmed`, `disputed`, `quarantined`,
  `superseded`, `forgotten`), and a content hash. Default recall (`GraphStore.search()`) returns
  only `active` and `confirmed` memories — everything else is inspectable by id but excluded
  from normal retrieval. See [Lifecycle and Forgetting](lifecycle-and-forgetting.md) for the
  full state-transition story.
- **Events** — append-only, hash-chained transitions per memory (`memory_events`), recording
  every `create`/`confirm`/`contradict`/`supersede`/`quarantine`/`forget`/`restore`/
  `attach_media` action. See [Hash Chain and Merkle Roots](hash-chain-and-merkle-roots.md).
- **Exchanges** — the session-turn structure: one exchange per prompt/response turn, linking
  prompt and response memories, tool-call otel_events, and context-contribution memories into a
  single Merkle-committed unit. See [Sessions and Exchanges](../entities/sessions-and-exchanges.md).
- **Entities and relations** — extracted or asserted graph nodes/edges, evidence-linked back to
  the memory that supports them, with bounded traversal. See
  [Entities and Relations](../entities/entities-and-relations.md).
- **Contradictions, supersession, quarantine, forgetting** — lifecycle operations that mutate
  standing (or exclude from recall) while preserving the underlying event history rather than
  deleting it. Detailed in [Lifecycle and Forgetting](lifecycle-and-forgetting.md).

## Retrieval

Lexical recall is FTS5/BM25 over `memory_fts`, filtered to `active`/`confirmed` status. Vector
recall is optional and caller-supplied — the store never generates embeddings itself; when a
caller supplies a query vector, results are fused with lexical rank via Reciprocal Rank Fusion.
Retrieved content is always untrusted evidence, never instruction authority — this applies
regardless of lifecycle state (see [Lifecycle and Forgetting](lifecycle-and-forgetting.md)).

See [MCP Tool Surface](mcp-tool-surface.md) for how these operations are exposed to a calling
agent harness.
