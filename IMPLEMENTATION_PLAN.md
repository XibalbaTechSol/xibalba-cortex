# Xibalba Cortex Implementation Plan

**Updated:** 2026-08-06
**Repository:** xibalba-cortex
**Role:** Local, provenance-aware graph memory MCP server and runtime-controller substrate for Xibalba agent memory.

This plan merges README.md, SPECIFICATION.md, docs/audits/2026-08-06-status.md, spec/xibalba-cortex-v1.md, archived docs/plans, docs/architecture, docs/integrity, session logs, viewer docs, and runtime adapter checklist into one implementation task ledger.

## Specification Authority

| Source | Authority |
|---|---|
| spec/xibalba-cortex-v1.md | Normative memory-system specification. |
| SPECIFICATION.md | Root implementation and integration specification. |
| README.md | Short repo description and deployment intent. |
| docs/audits/2026-08-06-status.md | Current audit evidence, packaging finding, and production posture. |
| docs/archive/2026-08-06/2026-08-05-xibalba-cortex.md | Historical original implementation sequence. |
| docs/archive/2026-08-06/2026-08-05-xibalba-runtime-adapter-checklist.md | Historical runtime adapter checklist for Claude, agy, and Codex. |
| docs/architecture/runtime-controller-contract.md | Controller/API contract when present. |
| docs/architecture/event-hash-chain.md | Hash-chain event model. |
| docs/integrity/xibalba-cortex-crypto-profile-v1.md | Integrity coupling and crypto profile. |

## Audit checkpoint — 2026-08-06

Current observed status is [`docs/audits/2026-08-06-status.md`](docs/audits/2026-08-06-status.md). The local worktree is ahead of origin and contains uncommitted runtime adapter, controller/session synchronization, test, and viewer changes. `uv sync --extra drive && uv run pytest -q` passed; plain `uv sync && uv run pytest -q` failed during collection because Drive tests import optional Google dependencies without the Drive extra. `[x]` entries below mean a model, scaffold, or tested path exists in the observed worktree, not that the uncommitted baseline has been reviewed or production-certified.

## Closed

- [x] SQLite is specified as the canonical local store.
- [x] Provenance-first memory model is specified: sources, memories, content hashes, derivation family, lifecycle status.
- [x] Event hash chain model is specified for memory state transitions.
- [x] Entity/relation graph model is specified with evidence-linked edges.
- [x] Contradiction/supersession/forgetting lifecycle is specified.
- [x] Integrity DAG citation boundary is specified as one-way/read-only.
- [x] Runtime adapter checklist exists for Claude, agy, and Codex.
- [x] Viewer scaffold exists in the worktree.
- [x] Tests exist for server/store/transcript ingest and runtime adapter contracts in the current worktree.
- [x] Core package test suite passes when installed with the Drive extra.

## Planned And Todo

### MVP Memory Page Wiring

Goal: make the viewer's memory page demonstrate the full Xibalba Cortex product, not only graph search. The page should prove the system can capture a complete model turn, show the prompt/response/context that produced it, expose the local Merkle root, delegate inference work to the user's agent harness, and inspect provenance/lifecycle state without implying recalled memory is instruction authority.

#### Backend/API prerequisites

- [x] Promote `GraphStore.record_model_exchange` to the primary demo write path: one call stores user prompt, full model response, and explicit context contributions, then appends the exchange chain node.
- [x] Expose read/write local API routes for MVP-only browser operation, keeping the existing localhost-only boundary:
  - [x] `POST /api/exchanges/model` -> `record_model_exchange`.
  - [x] `GET /api/session/{id}/exchanges` -> `session_exchanges`.
  - [x] `GET /api/session/{id}/merkle-root` -> `session_merkle_root`.
  - [x] `GET /api/memory/{id}/events` -> `memory_events`.
  - [x] `GET /api/memory/{id}/otel` -> `memory_otel_events`.
  - [x] `GET /api/inference/manifest` -> `memory_inference_subagent_manifest` equivalent.
  - [x] `POST /api/inference/tasks` -> `request_inference_task`.
  - [x] `GET /api/inference/tasks?status=` -> `list_inference_tasks`.
  - [x] `POST /api/inference/tasks/{id}/claim` -> `claim_inference_task`.
  - [x] `POST /api/inference/tasks/{id}/complete` -> `complete_inference_task`.
- [x] Add minimal mutation safety for local API writes: localhost bind, CORS allowlist, payload size cap, no restore/hard-purge routes, and clear docs that browser write routes are local-development/operator routes.
- [x] Add seed/demo command that creates a representative profile: preferences, project facts, contradiction, supersession, forgotten memory, entity relations, embeddings when available, one full prompt/response exchange, context contributions, inference tasks, and a valid exchange Merkle root.
- [x] Extend API tests around every new route, including malformed context payloads, invalid inference task types, missing sessions, and Merkle verification after tampering.

#### Memory page information architecture

- [x] Replace the current single graph canvas page with a dense operator dashboard layout:
  - [x] Header: profile/home, store health, schema version, counts, selected session, local root validity.
  - [x] Left rail: session list, saved filters, lifecycle status filters, epistemic-class filters.
  - [x] Main tabs: `Timeline`, `Graph`, `Recall`, `Inference`, `Integrity`.
  - [x] Right inspector: selected memory/exchange/entity details, provenance, events, context contributors, contradictions, attachments, OTel correlation.
- [x] Ensure every memory card/badge displays `status`, `evidence_class`, `source.kind`, `content_hash`, and the untrusted-evidence warning in the inspector, not as repetitive page copy.
- [x] Keep cards only for repeated items and inspector sections; avoid nested cards and marketing-style layout.

#### Timeline tab

- [x] Show session exchanges in order, with user prompt, full assistant/model response, timestamps, latency, prompt id, and response id.
- [x] For each exchange, show contributing context as separate rows with `contribution_id`, `context_kind`, relevance, source, and memory hash.
- [x] Show tool/OTel events correlated by `prompt_id`/`memory_id`, including context-window token metrics when present.
- [x] Display the exchange node id and parent node id per turn, with a session-level Merkle root chip using `session_merkle_root`.
- [x] Add a “record demo exchange” form wired to `record_model_exchange` so the page can prove prompt/response/context capture interactively.

#### Graph tab

- [x] Keep the current memory/entity graph but add filters for lifecycle status, epistemic class, source kind, relation predicate, and similarity threshold.
- [x] Add relation-edge inspection that jumps to evidence memory and shows provenance/events.
- [x] Add contradiction edges or badges so conflicts are visible from graph navigation.
- [x] Add bounded traversal controls (`neighbors`, `find_path`) with explicit truncation display.

#### Recall tab

- [x] Show lexical recall results with status/source/evidence badges and content hash.
- [x] Add optional vector-search state in the UI: indicate whether embeddings are present and whether query vector search is unavailable from browser/local API.
- [x] Show similar memories for a selected memory and make cosine similarity visible without treating it as confidence/truth.
- [x] Add “use as context” selection that builds a context bundle for the demo exchange form.

#### Inference tab

- [x] Show the `xibalba-memory-inference` manifest: supported task types, input rule, output rule, and allowed write-back tools.
- [x] Queue inference tasks for selected subject types: memory, exchange, session, context bundle.
- [x] List pending/claimed/completed/failed tasks and allow local harness simulation: claim a task, paste structured output, complete/fail it.
- [x] Add task output affordances that demonstrate intended write-back flow without silently mutating memory: create extracted proposition, link entities, mark contradiction, or supersede memory after explicit operator action.

#### Integrity tab

- [x] Show store integrity status, schema version, WAL/foreign-key/FTS state, and backup readiness.
- [x] Show selected memory event chain with node ids, parent ids, event types, and verification result.
- [x] Show session exchange-chain Merkle root, exchange count, verification state, and boundary copy: local tamper evidence only, not truth, authorization, completeness, or Integrity DAG anchoring.
- [x] Show `integrity_links` state when available, with explicit `unlinked`/`content_unavailable` handling.

#### Demo acceptance criteria

- [x] A fresh local profile can be seeded and opened in the viewer with no manual database edits.
- [x] The memory page can create a new model exchange with at least two context contributions and immediately show it in Timeline, Graph, Recall, and Integrity views.
- [x] The page can show the current session Merkle root and detect an intentionally tampered exchange chain in a test fixture.
- [x] The page can queue, claim, and complete an inference task through the local API.
- [x] The page can inspect provenance, memory events, OTel correlations, contradictions, supersession, forgetting, and attachments from a selected memory.
- [x] `uv run pytest -q` and `npm run build` in `viewer/` pass before calling the MVP memory page done.

### Core Memory Store

- [x] Confirm schema version and migrations are documented against src/xibalba_cortex/store.py.
- [x] Finish tests for bootstrap, WAL, foreign keys, FTS5, idempotency, and profile isolation.
- [x] Confirm append-only event transitions for create, confirm, contradict, supersede, quarantine, forget, and restore.
- [x] Document backup/restore and residual hash disclosure for forgotten records.

### Retrieval And Graph

- [x] Finalize lexical recall behavior and eligible lifecycle states.
- [x] Finalize optional vector embedding path and model metadata.
- [x] Verify bounded neighbors/path traversal limits and truncation reporting.
- [x] Add contradiction visibility to recall and graph views.

### MCP And Controller

- [x] Expose MCP tools for store, recall, link, neighbors, path, contradict, forget, verify, status, and backup.
- [x] Finalize runtime controller contract and API boundaries.
- [x] Ensure no runtime writes directly to storage without controller API.
- [x] Add failure-mode tests for missing runtime hooks and fabricated telemetry claims.

### Runtime Adapters

- [x] Claude adapter: preserve session start/end, pre-tool, post-tool, trace continuity, and controller ingest.
- [x] agy adapter: lifecycle wrapper with honest missing-tool-hook status.
- [x] Codex adapter: inspect launch surface, implement wrapper/launcher, normalize telemetry, document unsupported hooks.
- [x] Prove shared Xibalba identity use where intended without fabricating parity.

### Documentation And Audit Baseline

- [x] Decide whether Drive ingestion dependencies are supported by default, optional test extras, or skipped cleanly when absent.
- [x] Add a reproducible CI command that installs the correct extras and runs all tests.
- [x] Review and commit or discard runtime adapter, controller, session synchronization, test, and viewer work as a separate change set.
- [x] Expand README with installation, current status, privacy, retention, backup/restore, profile isolation, and MCP operations.
- [x] Verify MCP discovery through an isolated Hermes profile.
- [x] Verify Integrity DAG links distinguish byte lineage from truth, authorization, and completeness.

### Viewer And Operations

- [x] Finish viewer integration with recall, graph traversal, provenance, contradiction, forgetting, and verification states.
- [x] Add operator commands for resource readiness, backup, restore, and integrity verification.
- [x] Document Supermemory coexistence/shadow period and migration gate.
- [x] Add smoke test for MCP server discovery through Hermes profile config.

## Blocked

- [x] Full runtime parity is blocked by Codex and agy hook-surface limits until wrappers are verified.
- [x] Integrity DAG ancestry/root anchoring remains blocked on a configured root/anchor consumer; this repo must not implement a parallel chain anchor.
- [x] Viewer production readiness is blocked until service/API contract stabilizes.
- [x] Live Claude Code pre-tool hook installation proof remains blocked until the user-local plugin routes pre_tool_call into graph-memory.

- [x] Plain default test execution is blocked until Drive dependency policy is decided and collection handles optional extras deterministically.

## Acceptance Criteria

- [x] Canonical SQLite store can be created, migrated, backed up, restored, and verified.
- [x] Memories retain provenance, identity mode, derivation family, status, and event history.
- [x] Retrieval never treats recalled text as instruction authority.
- [x] Entity graph traversal is bounded and evidence-linked.
- [x] Claude, agy, and Codex use shared identity/memory through documented adapter boundaries.
- [x] Runtime capability gaps are explicit and tested.
- [x] Viewer and MCP tools expose provenance and verification state clearly.

## Known open items — not closed this session (2026-08-12)

Real gaps, honestly listed as open rather than implied closed. Each is either not this
repository's decision to make, or needs a resource this session doesn't have:

- **`INTEGRITY_CORE_PAT` GitHub secret does not exist, and may no longer even be needed.** It was
  meant for `integrity-dashboard`'s wiki-sync workflow to check out `integrity-core` as a private
  sibling repo — but `integrity-dashboard` now lives *inside* `integrity-core` (folded in during
  an earlier session), and that workflow still does a redundant second checkout of `integrity-core`
  from within `integrity-core` itself. Removing that redundant checkout would likely eliminate the
  need for this secret entirely — an `integrity-core`-side fix, out of scope for this repo, not
  evaluated further this session. Unrelated to this repo's own `sync-wiki.yml`, which only ever
  needed the default `GITHUB_TOKEN`.
- **`audit/harness-loop-2026-07-30` (in `integrity-core`) is not landed into `main`.** A timing
  decision for the user, not a code gap in this repository.
- **GitHub Actions "Read and write permissions" for the new `sync-wiki.yml` workflow** — a repo
  Settings toggle needed for the default `GITHUB_TOKEN` to push to the wiki repo; the user needs
  to confirm this is set (see `.github/workflows/sync-wiki.yml`'s own comment for the exact
  setting).
- **Real internet reachability for the streamable-HTTP ingestion endpoint** — the server binds
  loopback-only by default and has no TLS of its own; a tunnel or reverse proxy is a user/deploy
  decision, not something built here (see README.md's "Generic ingestion" section).
- **`xibalba-session-reconcile.py` and the Claude/agy session hooks (`~/.claude/xibalba/*.py`)
  live outside any git repo** — fixed live this session (stale `xibalba-graph-memory` path/module
  references after the rename), but there's no commit anywhere that captures the fix; if that
  machine's home directory is ever rebuilt, this fix is lost unless those scripts get checked
  into a repo.
- **Real-time streaming/subscription queries, multi-tenant profile-sharing, and a documented
  finance/healthcare audit-framework mapping** — all explicitly deferred past v1, see
  `SPECIFICATION.md`'s §11 Goals and Milestones for the full list and why each is deferred rather
  than silently unaddressed.

## Update Rule

Update this file whenever the spec, runtime controller contract, MCP tools, adapter status, viewer status, or Integrity coupling changes.
