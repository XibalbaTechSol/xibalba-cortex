---
title: Viewer and Local API
acronyms: [MCP, FTS5, WAL]
created: 2026-08-13
updated: 2026-08-13
type: architecture
tags: [infrastructure, storage, provenance]
confidence: high
source_files:
  - src/xibalba_cortex/local_api.py
  - viewer/src/App.tsx
  - viewer/src/api.ts
  - viewer/src/index.css
  - viewer/xibalba-3d-smoke.mjs
---

# Viewer and Local API

The implementation described on this page exists in the current uncommitted worktree and has passed the cited tests. It is not a released or default-branch capability until the worktree changes are reviewed and committed.

The local API exposes read and operator-oriented surfaces over the canonical `GraphStore`. It is a local operator API, not a read-only API: bounded `POST` routes can record exchanges, create propositions, link entities, apply lifecycle changes, manage inference tasks, and record PARA decisions. The React viewer presents the graph, timeline, recall, inference, PARA review, and integrity state without treating the viewer as the source of truth.

## Table of contents

- [Surfaces](#surfaces)
- [PARA and inference integration](#para-and-inference-integration)
- [Integrity presentation](#integrity-presentation)
- [Headless verification](#headless-verification)
- [Design boundaries](#design-boundaries)
- [Related pages](#related-pages)

## Surfaces

- **Timeline** — sessions, exchanges, tool events, and context contributions.
- **Graph** — nodes, edges, filters, 3D canvas, and bounded traversal controls.
- **Recall** — lexical search over eligible memories.
- **Inference** — task queue, claim/complete controls, explicit write-back, and PARA review.
- **Integrity** — SQLite health, backup readiness, session Merkle root, and integrity-link state.

## PARA and inference integration

The viewer queues PARA work against the selected memory's current content hash. It polls proposed classifications and offers inspect, accept, keep-original, and dismiss actions. No classification moves a memory automatically.

Inference completion carries the task's claim owner and claim token. The viewer is an operator surface; durable authority remains in the store's transaction and ownership checks.

## Integrity presentation

The header and Integrity tab display observed store state such as schema version, Write-Ahead Logging (WAL), Full-Text Search (FTS5), backup readiness, and root validity. The UI also preserves the boundary that local tamper evidence is not proof of truth, authorization, completeness, or external anchoring.

## Headless verification

The viewer was exercised with headless Chromium at desktop and mobile sizes. Screenshots were used as the visual source of truth for navigation, graph rendering, Timeline, Recall, Inference, Integrity, and responsive layout. The run observed no browser console errors, uncaught page errors, failed network requests, or horizontal document overflow.

The evidence set is generated locally under `/tmp/xibalba-cortex-playwright/`; it is not committed automatically because screenshots from a live profile may contain sensitive memory labels or operational history.

## Design boundaries

The local API defaults to a loopback-oriented host posture, but it has no built-in authentication and its default CORS setting is permissive. Bind it to `127.0.0.1` for local use and pass an explicit `--allowed-origin` for the viewer. Passing a non-loopback host changes the exposure boundary and requires external network controls.

The viewer can be unavailable while the MCP server and local store remain operational. Conversely, a successful page render does not prove that a write operation was authorized or completed. Validate mutations through API readback and database evidence.

## Related pages

- [PARA Classification Worker](../concepts/para-classification.md)
- [Inference Queue and Recovery](inference-queue.md)
- [Graph Store](../concepts/graph-store.md)
- [Hash Chain and Merkle Roots](../concepts/hash-chain-and-merkle-roots.md)
