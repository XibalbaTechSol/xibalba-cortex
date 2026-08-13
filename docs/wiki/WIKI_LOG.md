# Xibalba Cortex Wiki — Log

> Chronological record of wiki actions. Append-only — never edit past entries.
> Actions: ingest, create, update, lint, query, archive

## [2026-08-13] update | Strict contradiction evidence scope

- Replaced worker-side unrestricted similarity candidate retrieval with explicit task-contract `evidence_scope` retrieval.
- Tasks without explicit scope fail closed; out-of-scope candidates are excluded; evidence order is deterministic.
- Candidate discovery remains a trusted task-creation responsibility and must bind candidate IDs and observed hashes before queueing.
- Verification: focused contradiction/evidence suite passed 27 tests.
- Residual limits: no live MCP/external-model proof; full-suite fixed-port and daemon-thread contamination remains separate.


- Added `concepts/contradiction-worker.md`, covering the bounded worker, source-hash checks,
  candidate-memory hash binding, reviewable proposal lifecycle, and actionable-status guard.
- Added the page to `index.md` and `WIKI_INDEX.md`.
- Focused verification recorded: 25 tests passed for contradiction worker, stale-hash proposal handling,
  task-contract migration, extraction proposals, and provider validation.
- Preserved the boundary that local focused tests do not prove live Model Context Protocol (MCP)
  integration or external-model execution. Fixed-port and daemon-thread test contamination remains
  open separately.

## [2026-08-13] create | Hybrid local-first provider boundary

- Added `architecture/hybrid-local-first-providers.md` and `concepts/integrity-and-merkle-evidence.md`.
- Documented local, hybrid, and remote-inference/local-embedding modes; native agent-harness inference; local embedding workers; rebuildable projections; and Merkle evidence boundaries.
- Implemented and tested `src/xibalba_cortex/config.py`, `src/xibalba_cortex/providers.py`, operator `config`/`doctor` commands, and PARA worker routing through the native-harness provider boundary.
- Current implementation remains in the uncommitted worktree; model registry, hybrid retrieval fusion, general inclusion proofs, and remote projection reconciliation remain planned.

## [2026-08-13] create | Latest hybrid extraction and retrieval partial implementation

- Added the bounded Hermes extraction worker, versioned output validation, source snapshot hash checking, and claim-token completion path.
- Added lexical/vector/graph/temporal retrieval fusion with persisted trace provenance and a SHA-256 trace root.
- Added canonical-left Merkle root comparison and projection rebuild recommendation helpers.
- Added specification, implementation plan, and wiki concept page for the latest partial implementation.
- Focused verification: `.venv/bin/python -m pytest -q -o addopts='' tests/test_hybrid_extraction_latest.py` -> 4 passed.
- Hardening verification: `.venv/bin/python -m pytest -q -o addopts='' tests/test_integrity_hardening_latest.py` -> 4 passed.
- Full post-change verification: `.venv/bin/python -m pytest -q -o addopts=''` -> 237 passed, 1 skipped, 1 warning.
- Live Hermes diagnostic: direct `hermes -z` returned schema-valid output with the correct snapshot hash, but quote-containment validation rejected unrelated recalled-context quotes. This is measured failure evidence, not complete Hermes/MCP integration.


- Added `concepts/para-classification.md`, documenting task filtering, source-hash freshness, reviewable proposals, explicit decisions, and the current absence of live PARA proposals.
- Added `concepts/embedding-worker.md`, documenting eligibility, bounded batches, strict vector validation, content-hash compare-and-set writes, retryable failures, and the observed zero eligible live workload.
- Added `architecture/inference-queue.md`, documenting schema version 5 claim ownership, lease recovery, bounded retries, transactional PARA completion, and the six malformed legacy claimed rows that remain an explicit operational gap.
- Added `architecture/viewer-and-local-api.md`, documenting the graph, timeline, Recall, Inference, PARA, Integrity, and headless-browser validation surfaces.
- Added `docs/assets/knowledge-graph.png`, a real headless Chromium screenshot of the populated viewer graph, and linked it from the root README with profile-dependent-data caveats.
- Updated `WIKI_INDEX.md` and `index.md`. Verification is recorded by the subsequent checks below.
- Verification: `python3 scripts/wiki_toc.py --check`, relative Markdown-link audit, `git diff --check`, full `uv run pytest -q`, and `viewer/npm run build` passed. The screenshot file is a 1440 x 1000 PNG with SHA-256 `c1581bef4ce1f23966112fbab9aecfc0f1b580d47d45eb2b4bf7cab81eacebc7`.
- Hybrid extension implementation: added profile-scoped configuration and redacted effective-config output in `src/xibalba_cortex/config.py`, native-harness/local-embedding provider boundaries in `src/xibalba_cortex/providers.py`, and operator `config`/`doctor` diagnostics. Defaults were verified against the live profile as local mode, SQLite canonical storage, Hermes native-harness inference, local `BAAI/bge-small-en-v1.5` embeddings, and optional remote projections.
- Merkle evidence implementation: added `GraphStore.session_merkle_evidence()` and `GET /api/session/{id}/merkle-proof?index=`. The inclusion-proof test and local API route test passed. The proof is explicitly documented as byte-inclusion evidence, not truth, authorization, completeness, ownership, or external finality.
- Native-harness inference contract implementation: added versioned `InferenceTaskContract` metadata for evidence scope, input snapshot hash, output schema, promotion policy, and worker runtime. The contract is persisted inside the task input envelope to preserve the existing SQLite schema and legacy callers. Provider, store, and focused API/queue tests passed.


- Seeded the initial Xibalba Cortex wiki content tree this session: `docs/wiki/{concepts,entities,architecture,queries}/`, plus `WIKI_SCHEMA.md`, `WIKI_INDEX.md`, `WIKI_LOG.md`, and `index.md`.
- Covered the store model (`GraphStore`, sources/memories/events/exchanges/entities/relations) grounded in `src/xibalba_cortex/store.py` and `SPECIFICATION.md` §4.
- Covered the hash-chain/Merkle model: the per-memory `memory_events` chain and the per-session `exchanges` local Merkle-style root, explicit that this is local tamper evidence, not a blockchain, and not cryptographic proof to a third party until externally anchored.
- Covered the MCP tool surface (`src/xibalba_cortex/server.py`, ~40+ tools across store/recall, sessions, lifecycle, graph, verification, exchanges, inference, and runtime-controller groups) and its two transports (stdio, streamable-HTTP).
- Covered runtime adapters (`runtime_bridge_contract.py`, `runtime_controller.py`, `claude_adapter.py`, `agy_adapter.py`, `codex_probe.py`) for the three officially-adapted runtimes (claude, agy, codex), including the honest note that the `runtime_*` MCP tools accept any non-empty string rather than enforcing the `Literal` type.
- Covered generic ingestion (`memory_ingest_agent_turn`, streamable-HTTP transport, `ingest_tokens.py`, `auth_middleware.py`'s `BearerTokenAuth`) built this session, including the researched Google Antigravity CLI and Perplexity integration targets.
- Covered redaction (`redaction.py`'s shared `redact()`, extracted this session from duplicated logic in `transcript_ingest.py`/`session_sync.py`).
- Covered lifecycle and forgetting, including forgetting's deliberate residual-hash-disclosure tradeoff (documented in `docs/operations/store-contract.md`).
- Covered ecosystem role: Cortex as 🧠 The Brain in the three-repository ecosystem, explicitly framed as a standalone MCP memory product first, with ecosystem integration (Merkle-root anchoring to integrity-core, surfacing to integrity-core's integrity-dashboard component) as additive value.
- Covered entities (sessions/exchanges, entities/relations, ingest tokens) and a schema-level architecture tour of every table in `graph-memory.sqlite3`.
- Opened one query page, `queries/compliance-evidence-trail.md`, cross-linked (by URL, pending both sides existing) to xibalba-shield's page of the same name/topic.
- Ran `python3 scripts/wiki_toc.py` to generate every page's `## Table of contents` block, then `python3 scripts/wiki_toc.py --check` to confirm all pages current.
