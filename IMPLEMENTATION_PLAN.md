# Xibalba Graph Memory Implementation Plan

**Updated:** 2026-08-06
**Repository:** xibalba-graph-memory
**Role:** Local, provenance-aware graph memory MCP server and runtime-controller substrate for Xibalba agent memory.

This plan merges README.md, SPECIFICATION.md, docs/audits/2026-08-06-status.md, spec/xibalba-graph-memory-v1.md, archived docs/plans, docs/architecture, docs/integrity, session logs, viewer docs, and runtime adapter checklist into one implementation task ledger.

## Specification Authority

| Source | Authority |
|---|---|
| spec/xibalba-graph-memory-v1.md | Normative memory-system specification. |
| SPECIFICATION.md | Root implementation and integration specification. |
| README.md | Short repo description and deployment intent. |
| docs/audits/2026-08-06-status.md | Current audit evidence, packaging finding, and production posture. |
| docs/archive/2026-08-06/2026-08-05-xibalba-graph-memory.md | Historical original implementation sequence. |
| docs/archive/2026-08-06/2026-08-05-xibalba-runtime-adapter-checklist.md | Historical runtime adapter checklist for Claude, agy, and Codex. |
| docs/architecture/runtime-controller-contract.md | Controller/API contract when present. |
| docs/architecture/event-hash-chain.md | Hash-chain event model. |
| docs/integrity/xibalba-graph-crypto-profile-v1.md | Integrity coupling and crypto profile. |

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

### Core Memory Store

- [ ] Confirm schema version and migrations are documented against src/xibalba_graph/store.py.
- [ ] Finish tests for bootstrap, WAL, foreign keys, FTS5, idempotency, and profile isolation.
- [ ] Confirm append-only event transitions for create, confirm, contradict, supersede, quarantine, forget, and restore.
- [ ] Document backup/restore and residual hash disclosure for forgotten records.

### Retrieval And Graph

- [ ] Finalize lexical recall behavior and eligible lifecycle states.
- [ ] Finalize optional vector embedding path and model metadata.
- [ ] Verify bounded neighbors/path traversal limits and truncation reporting.
- [ ] Add contradiction visibility to recall and graph views.

### MCP And Controller

- [ ] Expose MCP tools for store, recall, link, neighbors, path, contradict, forget, verify, status, and backup.
- [ ] Finalize runtime controller contract and API boundaries.
- [ ] Ensure no runtime writes directly to storage without controller API.
- [ ] Add failure-mode tests for missing runtime hooks and fabricated telemetry claims.

### Runtime Adapters

- [ ] Claude adapter: preserve session start/end, pre-tool, post-tool, trace continuity, and controller ingest.
- [ ] agy adapter: lifecycle wrapper with honest missing-tool-hook status.
- [ ] Codex adapter: inspect launch surface, implement wrapper/launcher, normalize telemetry, document unsupported hooks.
- [ ] Prove shared Xibalba identity use where intended without fabricating parity.

### Documentation And Audit Baseline

- [ ] Decide whether Drive ingestion dependencies are supported by default, optional test extras, or skipped cleanly when absent.
- [ ] Add a reproducible CI command that installs the correct extras and runs all tests.
- [ ] Review and commit or discard runtime adapter, controller, session synchronization, test, and viewer work as a separate change set.
- [ ] Expand README with installation, current status, privacy, retention, backup/restore, profile isolation, and MCP operations.
- [ ] Verify MCP discovery and direct tool calls through an isolated Hermes profile.
- [ ] Verify Integrity DAG links distinguish byte lineage from truth, authorization, and completeness.

### Viewer And Operations

- [ ] Finish viewer integration with recall, graph traversal, provenance, contradiction, forgetting, and verification states.
- [ ] Add operator commands for resource readiness, backup, restore, and integrity verification.
- [ ] Document Supermemory coexistence/shadow period and migration gate.
- [ ] Add smoke test for MCP server discovery through Hermes profile config.

## Blocked

- [ ] Full runtime parity is blocked by Codex and agy hook-surface limits until wrappers are verified.
- [ ] Integrity DAG anchoring is blocked on consuming the Integrity Memory DAG once available; this repo must not implement a parallel chain anchor.
- [ ] Viewer production readiness is blocked until service/API contract stabilizes.

- [ ] Plain default test execution is blocked until Drive dependency policy is decided and collection handles optional extras deterministically.

## Acceptance Criteria

- [ ] Canonical SQLite store can be created, migrated, backed up, restored, and verified.
- [ ] Memories retain provenance, identity mode, derivation family, status, and event history.
- [ ] Retrieval never treats recalled text as instruction authority.
- [ ] Entity graph traversal is bounded and evidence-linked.
- [ ] Claude, agy, and Codex use shared identity/memory through documented adapter boundaries.
- [ ] Runtime capability gaps are explicit and tested.
- [ ] Viewer and MCP tools expose provenance and verification state clearly.

## Update Rule

Update this file whenever the spec, runtime controller contract, MCP tools, adapter status, viewer status, or Integrity coupling changes.
