---
title: Viewer and Local API
acronyms: [MCP, FTS5, WAL]
created: 2026-08-13
updated: 2026-09-18
type: architecture
tags: [infrastructure, storage, provenance]
confidence: high
source_files:
  - src/xibalba_cortex/local_api.py
  - src/xibalba_cortex/store.py
  - src/xibalba_cortex/accounts.py
  - src/xibalba_cortex/email_delivery.py
  - viewer/src/App.tsx
  - viewer/src/api.ts
  - viewer/src/index.css
  - viewer/src/ProvenancePanels.tsx
  - viewer/xibalba-3d-smoke.mjs
---

# Viewer and Local API

This page describes the implementation in the current Cortex worktree. The 2026-09-18
profile-store routing and read-only viewer work is on a feature branch until merged and
deployed; documenting it here does not make it a released capability.

The local API exposes read and operator-oriented surfaces over the canonical `GraphStore`. It is a local operator API, not a read-only API: bounded `POST` routes can record exchanges, create propositions, link entities, apply lifecycle changes (including forgetting a memory), manage inference tasks, and record PARA decisions. The React viewer presents memory browsing, the session/graph timeline, retrieval, inference, PARA review, and audit/integrity state without treating the viewer as the source of truth.

## Table of contents

- [Surfaces](#surfaces)
- [Agent workspaces](#agent-workspaces)
- [Profile-store routing](#profile-store-routing)
- [PARA and inference integration](#para-and-inference-integration)
- [Integrity presentation](#integrity-presentation)
- [Headless verification](#headless-verification)
- [Design boundaries](#design-boundaries)
- [Related pages](#related-pages)

## Surfaces

As of 2026-09-15 the viewer's left nav is: Overview, Agents, Memory Explorer, Sessions, Graph,
Search & Retrieval, Inference, Audit Log, Operations, Settings. Several of these are renames or
merges of the tabs this page previously described, done to match a proposed information
architecture without rewriting working code underneath the label:

- **Memory Explorer** — a paginated, status-filterable browse of the canonical memory store,
  independent of any search query. `GET /api/memories?limit=&offset=&status=&agent_id=` (new
  2026-09-15) backs it; `status` is a comma-separated subset of
  `candidate,active,confirmed,superseded,forgotten` (default: all five). Agent-scoped exactly
  like every other route (`_agent_filter`); an operator session sees every agent unless one is
  selected via the global agent switcher.
- **Sessions** (formerly "Timeline") — sessions, exchanges, tool events, and context
  contributions, plus inline transcript replay for the selected session. This remains one
  component (`TimelineTab`), not split into separate Sessions/Replay tabs — the two are
  tightly coupled around one `selectedSessionId`, and splitting them would add navigation
  without adding capability.
- **Graph** — nodes, edges, filters, 3D canvas, and bounded traversal controls.
- **Search & Retrieval** (formerly "Recall") — lexical/hybrid search over eligible memories.
- **Inference** — task queue, claim/complete controls, explicit write-back, and PARA review.
- **Audit Log** (formerly two separate tabs, "Integrity Audit" and "Provenance") — merged into
  one tab with an `All / Chain & Store Lineage / Extraction & Retrieval Traces` subnav (the same
  pattern Settings already used), since both were reading different slices of the same
  provenance/audit concern. Chain & Store Lineage: SQLite health, backup readiness, session
  Merkle root, and integrity-link state. Extraction & Retrieval Traces: autonomous extraction
  proposal review, hybrid-retrieval Merkle inclusion proofs, and projection-checkpoint drift.
- **Agents** — exact canonical agent/device workspaces. `GET /api/agents` lists namespaces and
  `GET /api/agent/{agent_id}/memories?device_id=` reads only that agent/device partition. Records
  without `sources.agent_id` remain outside these workspaces rather than being guessed into one.
  `GET /api/agents` also returns `oracle_reachable` and a per-agent `identity_verified` flag (new
  2026-09-15) — see "On-chain identity honesty" below.
- **Settings** — operator profile, inference-daemon policy, and account security, plus a
  Dark/Light/System theme picker (new 2026-09-15; `[data-theme]` CSS variable overrides in
  `viewer/src/index.css`, applied live and persisted to `localStorage`).

## Memory lifecycle: forget

`POST /api/memory/{id}/forget` (new 2026-09-15) exposes `GraphStore.forget_memory()` — previously
implemented in `store.py` but not reachable over HTTP. Sets the memory's status to `forgotten`
and returns a hash-bound deletion receipt (`content_hash` retained for chain verification; the
content itself is not). Agent-scoped like `supersede`. Raises `RuntimeError` (mapped to HTTP
`409`) when governance is disabled by feature policy, rather than a bare `500` — every route's
`RuntimeError` now maps to `409` for this reason. The viewer's memory Inspector panel requires an
explicit confirm step before calling it and disables the action once a memory is already
forgotten.

## On-chain identity honesty

`integrity_sdk.agent_identity.resolve_agent_identities` (shared with Shield and the dashboard)
fails open by design: an unreachable oracle still returns `on_chain: false` for every requested
DID rather than raising, so a naming lookup can never break a page that wanted to show an agent
list. Read alone, that makes "confirmed off-chain" and "couldn't check, oracle down"
indistinguishable. `GET /api/agents` independently probes the oracle (2s timeout) and adds
`oracle_reachable` (response-level) and `identity_verified` (per agent) so the viewer can render
an honest "status unverified" state instead of a confident but possibly-false on-chain/off-chain
badge. Do not add a similar on/off-chain claim anywhere else in the viewer without also carrying
this verified flag.

## Agent workspaces

The Agents view is a read-only operator surface over the exact `sources.agent_id` value. Selecting
a workspace calls `GET /api/agent/{agent_id}/memories` and optionally adds `device_id`; it never
falls back to the global memory list. This makes agent comparison safe even when multiple Shield
devices share one registered agent or when historical records have no canonical identity.

## Profile-store routing

The local API can mount additional profile databases as read-only agent stores. `GET
/api/agents` identifies each workspace with an opaque, stable `store_id` derived from its
profile ID and resolved database path, and returns its `profile_id`, `store_access`, and
`writable` flag. The same agent DID may occur in more than one mounted profile; callers must
pass `store_id` when the selected agent is ambiguous. Reads stay in that database and do not
merge or copy records across stores.

Viewer requests carry both `agent_id` and `store_id` for agent-scoped memories, search, graph,
session pages and details, and inference task listing. `GET /api/sessions/page` provides bounded
pagination (`limit` capped at 250, with `offset` and `has_more`) and returns the selected store
and profile. Counts marked as not counted remain unknown, not zero. The primary profile store
is writable; mounted secondary profile stores are read-only. The viewer disables write-back
controls for a read-only selection, and write endpoints remain bound to the API's primary store
and authorization checks.

These controls prevent a selected workspace from silently switching to another profile's data
or presenting an unknown session count as a measured zero. They do not prove that a running
deployment has mounted the intended profile directories; verify the live `/api/agents` response
and selected store before relying on a rendered view.

## PARA and inference integration

The viewer queues PARA work against the selected memory's current content hash. It polls proposed classifications and offers inspect, accept, keep-original, and dismiss actions. No classification moves a memory automatically.

Inference completion carries the task's claim owner and claim token. The viewer is an operator surface; durable authority remains in the store's transaction and ownership checks.

## Integrity presentation

The header and the Audit Log tab's Chain & Store Lineage section display observed store state such as schema version, Write-Ahead Logging (WAL), Full-Text Search (FTS5), backup readiness, and root validity. The UI also preserves the boundary that local tamper evidence is not proof of truth, authorization, completeness, or external anchoring.

## Headless verification

The viewer was exercised with headless Chromium at desktop and mobile sizes, under the pre-2026-09-15 tab names (Timeline, Recall, Integrity) — this evidence predates the Memory Explorer addition, the Sessions/Search & Retrieval renames, and the Audit Log merge, and has not been re-run against them. Screenshots were used as the visual source of truth for navigation, graph rendering, Timeline, Recall, Inference, Integrity, and responsive layout. The run observed no browser console errors, uncaught page errors, failed network requests, or horizontal document overflow.

The evidence set is generated locally under `/tmp/xibalba-cortex-playwright/`; it is not committed automatically because screenshots from a live profile may contain sensitive memory labels or operational history.

The 2026-09-15 additions (Memory Explorer, forget lifecycle, Audit Log merge, theme picker,
`identity_verified`/`oracle_reachable`) are source-verified plus `tsc --noEmit`/`vite build`/
`pytest` verified only — a live browser pass was attempted and blocked by an unrelated
environmental issue (the local API process wedged under host memory pressure, timing out on
every route including ones untouched by these changes) rather than completed. Re-run headless
verification before treating this set as browser-confirmed.

## Design boundaries

The local API's default Cross-Origin Resource Sharing (CORS) setting is permissive, so pass an explicit `--allowed-origin` for the viewer. Every route except `/healthz`, `/readyz`, and `/metrics` requires the same profile-bound bearer-token authentication as the streamable-HTTP Model Context Protocol transport (`auth_middleware.py` / `ingest_tokens.py`) — a `memory:read`-scoped token for GET and hybrid retrieval, `memory:write` for mutating POST routes, and `proposal:decide` for the two decision endpoints. Issue tokens with `xibalba-cortex-ingest-tokens issue`. There is no unauthenticated fallback; a deployment with no tokens issued has no working API. Production builds accept the token at runtime and retain it only in tab-scoped `sessionStorage`, rather than compiling it into public JavaScript. The local Vite development server instead creates a dedicated operator token on first boot, stores it in a mode-`0600` file under the profile home, and injects it through a loopback-only proxy; the browser receives only a non-secret development marker. This convenience path is excluded from production builds. Bind to `127.0.0.1` for local use; a non-loopback host still requires a valid token per request and external Transport Layer Security (TLS).

The API reads its default allowed origin from `CORTEX_ALLOWED_ORIGIN`, falling back to `*`;
`--allowed-origin` overrides it. The container image does not inject a safe deployment value,
so operators must configure an exact origin and external TLS before exposing the service.

Profile accounts include signup, login/logout, password change, session revocation, reset
request/confirmation, and administrative approval routes. Reset requests never return the raw
token. They require a configured reset URL and STARTTLS SMTP transport; missing configuration or
delivery failure returns `503` and deletes the newly issued token. A successful local test proves
the fail-closed application contract, not production inbox delivery.

The viewer can be unavailable while the MCP server and local store remain operational. Conversely, a successful page render does not prove that a write operation was authorized or completed. Validate mutations through API readback and database evidence.

Agent identity is intentionally exact: `XIBALBA_AGENT_ID` is persisted as `sources.agent_id` when
identity mode permits it, while `device_id` and optional `agent_name` remain source metadata. This
supports Shield's hybrid model (local rule enforcement plus redacted cloud memory) without merging
different devices or agents. Historical records are not rewritten to fabricate attribution.

## Related pages

- [PARA Classification Worker](../concepts/para-classification.md)
- [Inference Queue and Recovery](inference-queue.md)
- [Graph Store](../concepts/graph-store.md)
- [Hash Chain and Merkle Roots](../concepts/hash-chain-and-merkle-roots.md)
