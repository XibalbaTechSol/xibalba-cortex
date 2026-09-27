---
title: Sessions and Exchanges
acronyms: []
created: 2026-08-12
updated: 2026-09-18
type: entity
tags: [storage, provenance]
confidence: high
source_files:
  - src/xibalba_cortex/store.py
---

## Table of contents

- [Overview](#overview)
- [Tables](#tables)
- [How one exchange gets built](#how-one-exchange-gets-built)
- [Identifiers, empty sessions, and summaries](#identifiers-empty-sessions-and-summaries)
- [Agent attribution and profile stores](#agent-attribution-and-profile-stores)

## Overview

`sessions`, `exchanges`, `exchange_memories`, `exchange_tool_calls`, and
`exchange_context_memories` together give a session a walkable, Merkle-chained sequence of
turns — the same content-addressed, backward-linked pattern proven for `memory_events` (see
[Hash Chain and Merkle Roots](../concepts/hash-chain-and-merkle-roots.md)), applied one level up
to a session's turn-by-turn structure instead of a single memory's revisions.

## Tables

- **`sessions`** — `id`, `external_session_id` (unique, caller-supplied), `retention_tier`
  (`verbatim`/`synopsis`/`digest`), `started_at`, `ended_at`, `summary_memory_id`.
- **`exchanges`** — one row per turn: `id`, `session_id`, `sequence_number`, `prompt_id`,
  `prompt_time`, `response_time`, `latency_ms`, `node_id`, `parent_node_id`. `UNIQUE(session_id,
  sequence_number)`.
- **`exchange_memories`** — many-to-many, not two FK columns on `exchanges`: a single prompt can
  produce several response memories (e.g. separate thinking-block and text memories), so this
  stays flexible about which memory is "the" response. Each row has a `role`
  (`prompt`/`response`).
- **`exchange_tool_calls`** — links an exchange to the `otel_events` rows representing its tool
  calls.
- **`exchange_context_memories`** — links an exchange to the memories that were supplied as
  context for that turn, each tagged with a `contribution_id`, `context_kind`, and optional
  `relevance` score (0–1).

## How one exchange gets built

`record_model_exchange()` (and the higher-level `memory_ingest_agent_turn` /
`ingest_agent_turn()`, see [Generic Ingestion](../concepts/generic-ingestion.md)) links a prompt
memory, a response memory, tool-call `otel_events`, and context-contribution memories into one
row in `exchanges`. The exchange's `node_id` commits to its prompt/response content hashes and
its tool-call identifiers, plus the previous exchange's `node_id` — so the whole session's
turn sequence is tamper-evident, verified with `verify_exchange_chain()` /
`session_merkle_root()`. See [Hash Chain and Merkle Roots](../concepts/hash-chain-and-merkle-roots.md)
for the chaining mechanics.

## Identifiers, empty sessions, and summaries

Session APIs accept either the caller-supplied `external_session_id` or the internal `sessions.id` UUID and always normalize results back to the external id. Legacy source rows linked with the internal UUID remain visible. Empty or whitespace-only identifiers are rejected.

An exchange build now returns `status="built"`, `status="unchanged"` with `deduplicated=true`, or `status="empty"` with the reason `no_non_summary_memories_or_otel_events`. A zero count is therefore no longer ambiguous. A closing summary created by `end_session()` defaults to `candidate`; only a caller that has independently verified it should explicitly request `summary_status="confirmed"`. Summary evidence remains in the context block `summaries` bucket and is never promoted to `current_facts`.

`memory_build_session_exchanges` / `memory_session_exchanges` (MCP tools) expose building and
reading this structure; see [MCP Tool Surface](../concepts/mcp-tool-surface.md).

## Agent attribution and profile stores

The runtime controller persists the bound agent partition when `open_session()` creates a
session. Its event-ingest path also reuses an existing session binding when it must create the
session implicitly. Without a binding, the session remains unattributed; profile names and
external session IDs are not identity evidence.

The local viewer may read sessions from mounted profile databases. Each page and session-detail
request is scoped by both agent and store where needed; profile databases remain separate and
secondary mounts are read-only. `GET /api/sessions/page` reports the selected `store_id` and
`profile_id`, and `count_status="page_loaded"` describes pagination only, not a total session
count. See [Viewer and Local API](../architecture/viewer-and-local-api.md).
