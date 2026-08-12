---
title: Sessions and Exchanges
acronyms: []
created: 2026-08-12
updated: 2026-08-12
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

`memory_build_session_exchanges` / `memory_session_exchanges` (MCP tools) expose building and
reading this structure; see [MCP Tool Surface](../concepts/mcp-tool-surface.md).
