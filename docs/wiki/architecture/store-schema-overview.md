---
title: Store Schema Overview
acronyms: [WAL, FTS5]
created: 2026-08-12
updated: 2026-08-12
type: concept
tags: [storage, provenance]
confidence: high
source_files:
  - src/xibalba_cortex/store.py
  - docs/operations/store-contract.md
---

## Table of contents

- [Overview](#overview)
- [Provenance and content](#provenance-and-content)
- [Session and turn structure](#session-and-turn-structure)
- [Graph](#graph)
- [Lifecycle and tamper evidence](#lifecycle-and-tamper-evidence)
- [Inference, attachments, embeddings, and integrity links](#inference-attachments-embeddings-and-integrity-links)

## Overview

A schema-level tour of `graph-memory.sqlite3`, the single canonical SQLite database `GraphStore`
opens (WAL journal mode, FTS5, optional `sqlite-vec`). Deeper explanations of the hash-chain and
store-model concepts live on their own pages — this page links out rather than repeating them,
per the no-duplication rule.

## Provenance and content

- **`sources`** — raw evidence: origin/locator, content hash, capture time, `identity_mode`
  (`full`/`pseudonymous`/`omit`), and Claude Code's own `prompt_id` correlation key.
- **`memories`** — the queryable unit: content, content hash, lifecycle `status`,
  `derivation_family`, optional `supersedes_id`, and a unique `idempotency_key`.
- **`memory_fts`** — an FTS5 virtual table mirroring `memories.content` for lexical recall.

Full object-model detail: [Graph Store](../concepts/graph-store.md).

## Session and turn structure

- **`sessions`** — one row per external session, with `retention_tier`
  (`verbatim`/`synopsis`/`digest`).
- **`exchanges`**, **`exchange_memories`**, **`exchange_tool_calls`**,
  **`exchange_context_memories`** — the turn-by-turn, Merkle-chained structure linking prompt,
  response, tool-call, and context memories per exchange.
- **`otel_events`** — a local mirror of the Integrity Oracle's `unsigned_vendor` OTel evidence
  shape (spans/metrics/logs), used purely for local operator querying — never signed, never
  anchored, never fed into any scoring.

Full detail: [Sessions and Exchanges](../entities/sessions-and-exchanges.md).

## Graph

- **`entities`**, **`entity_aliases`**, **`memory_entities`** — extracted/asserted graph nodes
  and their evidence links back to memories.
- **`relations`** — subject/predicate/object edges with confidence, lifecycle status, and a
  required `evidence_memory_id`.

Full detail: [Entities and Relations](../entities/entities-and-relations.md).

## Lifecycle and tamper evidence

- **`contradictions`** — pairs of memories flagged as contradicting, with a reason.
- **`memory_events`** — the append-only, hash-chained event log per memory (`create`, `confirm`,
  `contradict`, `supersede`, `quarantine`, `forget`, `restore`, `attach_media`).

Full detail: [Lifecycle and Forgetting](../concepts/lifecycle-and-forgetting.md) and
[Hash Chain and Merkle Roots](../concepts/hash-chain-and-merkle-roots.md).

## Inference, attachments, embeddings, and integrity links

- **`memory_inference_tasks`** — the harness-facing queue for LLM-derived summaries and metadata
  (`summarize_session`, `extract_memory_metadata`, `extract_entities`, …). Cortex does not run an
  LLM locally; it queues deterministic tasks the calling harness claims, solves, and writes back
  (`memory_inference_subagent_manifest`, `memory_request_inference`,
  `memory_claim_inference_task`, `memory_complete_inference_task` — see
  [MCP Tool Surface](../concepts/mcp-tool-surface.md)).
- **`attachments`** — files/artifacts attached to a memory.
- **`embeddings_meta`** — metadata for caller-supplied vectors (model id, dimension, source
  content hash); the store never generates embeddings itself. Stored vectors must use
  `BAAI/bge-small-en-v1.5` at dimension `384`.
- **`integrity_links`** — one-way citation references from a local object to a remote Integrity
  Memory DAG node or anchor, plus proof metadata. `memory_verify_integrity_link` compares a
  memory's local content hash against the cited DAG node's hash — byte-lineage verification
  only, never a claim of truth, authorization, or on-chain anchoring (see
  [Ecosystem Role](ecosystem-role.md) and
  [Compliance Evidence Trail](../queries/compliance-evidence-trail.md)).

`schema_migrations` records the applied schema version (`3` as of this writing); see
`docs/operations/store-contract.md` for the migration history.
