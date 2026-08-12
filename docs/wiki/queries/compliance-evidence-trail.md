---
title: Compliance Evidence Trail
acronyms: []
created: 2026-08-12
updated: 2026-08-12
type: query
tags: [compliance, provenance]
confidence: medium
source_files:
  - src/xibalba_cortex/store.py
  - src/xibalba_cortex/server.py
  - README.md
  - SPECIFICATION.md
---

## Table of contents

- [Open question](#open-question)
- [What's built and queryable today](#what-s-built-and-queryable-today)
- [What's still open](#what-s-still-open)
- [Relationship to xibalba-shield's compliance story](#relationship-to-xibalba-shield-s-compliance-story)

## Open question

Can Cortex support retrieval "down to the exact second an agent did something," for a
compliance reviewer who needs to reconstruct exactly what an agent did and when? This page is an
open assessment, not a settled conclusion — per the wiki schema, `type: query` pages record
investigation notes, not finished answers.

## What's built and queryable today

- **Session Merkle roots** — every exchange in a session chains into a local Merkle-style root
  over prompt, response, tool-call, and context-contribution hashes
  (`memory_session_merkle_root`, `memory_verify_exchange_chain`). See
  [Hash Chain and Merkle Roots](../concepts/hash-chain-and-merkle-roots.md).
- **Hash-chained memory events** — every lifecycle transition on a memory is append-only and
  independently verifiable (`memory_verify_chain`). See
  [Lifecycle and Forgetting](../concepts/lifecycle-and-forgetting.md).
- **Timestamped OTel spans and tool calls** — `otel_events` records per-span/metric/log
  timestamps (`start_time`/`end_time`), queryable per session (`memory_session_otel_summary`,
  `memory_otel_events`) and linked into the exchange that produced them
  (`exchange_tool_calls`). See [Store Schema Overview](../architecture/store-schema-overview.md).
- **MCP surface + local viewer** — all of the above is queryable through the ~40+ tool MCP
  surface (see [MCP Tool Surface](../concepts/mcp-tool-surface.md)) and through the local
  viewer's provenance/graph/lifecycle rendering.

Together, this supports reconstructing what an agent did, in what order, with what tool calls,
and whether the record has been tampered with since — as far back as timestamped records exist
locally.

## What's still open

- **Real-time streaming/subscription queries are not built.** A compliance reviewer today polls
  the MCP tools or the local viewer; there is no push/subscription mechanism for "notify me when
  a new exchange lands."
- **Multi-tenant profile-sharing for a compliance team is not built.** The store is
  profile-isolated and local; there is no built-in mechanism for multiple reviewers or a
  compliance team to query a shared, access-controlled view.
- **Integrity-anchoring of session roots is opt-in, not automatic.** Anchoring to integrity-core
  requires `XIBALBA_ANCHOR_URL` to be configured, and even then only fires automatically if
  `XIBALBA_AUTO_ANCHOR_ON_SESSION_END=1` is set — otherwise it requires a manual
  `memory_anchor_session_root` call. A local hash chain alone is tamper-evident *locally* (you
  can prove the chain wasn't silently edited after the fact, on this machine) but is not
  cryptographic proof to a third party until anchored externally. See
  [Ecosystem Role](../architecture/ecosystem-role.md).
- **Forgotten records complicate "the exact second" claim by design.** Forgetting removes
  user-visible content but retains a residual hash and event history — an auditor can confirm
  something was forgotten and roughly when, but cannot recover what it said. See
  [Lifecycle and Forgetting](../concepts/lifecycle-and-forgetting.md).

## Relationship to xibalba-shield's compliance story

This is intentionally the same topic/title as xibalba-shield's own
[`queries/compliance-evidence-trail.md`](https://github.com/XibalbaTechSol/xibalba-shield/wiki/compliance-evidence-trail)
page, so the two repositories' compliance stories read as one narrative once both pages exist:
Cortex provides the queryable-history half (what happened, in what order, tamper-evidently);
Shield provides the real-time-enforcement half (what was blocked or gated as it happened).
Neither repository's page should duplicate the other's detail — cross-link instead.
