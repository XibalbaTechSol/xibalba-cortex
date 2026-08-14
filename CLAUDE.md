# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository.

## What this is

xibalba-cortex — the graph-memory MCP server for the Xibalba ecosystem. It is the "brain": the
persistent, hash-chained memory layer that `xibalba-shield` (local enforcement/detection) and
`integrity-core` (on-chain identity/reputation protocol) both read from and write into via MCP
tool calls. Python 3.12, `uv`-managed, exposes ~56 MCP tools (`memory_remember`,
`memory_hybrid_retrieve`, `memory_recall`, `memory_verify_chain`, `runtime_*` bridge tools, etc.)
over stdio or streamable-HTTP.

Normative spec: `spec/xibalba-cortex-v1.md` — highest authority in this repo (see
`SPECIFICATION.md` §2's authority table). `SPECIFICATION.md` itself declares the store schema,
hash-chain format, and MCP core tool contract **frozen for v1** as of 2026-08-12; new tools and
runtime strings are additive/extensible, but do not change the frozen surface without updating
the spec in the same change. `IMPLEMENTATION_PLAN.md` is the running closed/planned/todo ledger —
check it before assuming a feature is unimplemented.

## Repository layout

```
src/xibalba_cortex/
├── server.py              # MCP server entry — @server.tool() decorators, all ~56 tools
├── store.py                # GraphStore — canonical SQLite persistence, hash-chained events,
│                             domain-separated Merkle roots
├── config.py                # CortexConfig — mode local/hybrid/remote-inference, YAML/env driven
├── auth_middleware.py, redaction.py
├── local_api.py             # localhost HTTP API consumed by viewer/
├── runtime_controller.py, runtime_bridge_contract.py,
│   agy_adapter.py, claude_adapter.py, codex_probe.py   # runtime-harness adapter layer
└── embedding_worker.py, para_worker.py,
    contradiction_worker.py                             # out-of-process background workers

viewer/          # React 19 + Vite 8 + TS graph/timeline UI (react-force-graph-2d, three.js)
tests/           # pytest, testpaths=tests; tests/conformance/test_vectors.json
docs/
├── wiki/         # canonical wiki source — synced to GitHub Wiki via scripts/sync_wiki.py
│                   (CI: .github/workflows/sync-wiki.yml on push touching docs/wiki/**)
├── architecture/, audits/, operations/, plans/, research/, session-log/
spec/
├── xibalba-cortex-v1.md         # normative memory-system spec
└── latest-hybrid-extraction.md
scripts/
├── claude_pre_tool_hook.js
├── setup-cortex-worker-profile.sh   # installs the isolated Hermes extraction worker profile
├── sync_wiki.py, wiki_toc.py
```

Root also has a handful of dev-scratch scripts and loose artifacts (`fix_sessions.py`,
`manual_inference.py`, `process_queue.py`, stray JSON/PNG files) — these are not part of the
installed package (`src/` is), treat them as throwaway tooling, not API surface.

## Cross-repo dependency

`pyproject.toml` pins `integrity-sdk` as a **local path dependency** on `../integrity-core/
integrity-sdk` — this repo assumes `integrity-core` is checked out as a sibling directory. `uv
sync` will fail if that path doesn't resolve.

## Common commands

```bash
uv sync                       # install deps
uv sync --extra drive         # + Google Drive ingestion extras (pypdf, Google API client)
uv run pytest -q              # tests/ — last known clean run: 273 passed, 1 skipped
uv run xibalba-cortex          # MCP server, stdio by default
uv run xibalba-cortex --transport streamable-http

# console scripts (all under uv run):
xibalba-cortex-operator, xibalba-cortex-embedding-worker, xibalba-cortex-para-worker,
xibalba-cortex-contradiction-worker, xibalba-cortex-ingest-tokens, xibalba-cortex-session-sync,
xibalba-cortex-session-open, xibalba-cortex-transcript-ingest, xibalba-cortex-demo-seed,
xibalba-cortex-wiki-ingest, xibalba-cortex-drive-ingest, xibalba-cortex-otlp-receiver,
xibalba-cortex-raw-ingest

# viewer/ (npm)
cd viewer && npm install
npm run dev        # local dev server
npm run build       # production build
npm run lint         # oxlint
npm run preview
```

There is no root Makefile, CONTRIBUTING.md, or test/lint CI workflow beyond the wiki-sync
Action — `uv run pytest -q` is the enforcement mechanism, run it before calling a change done.

To run a single test: `uv run pytest tests/test_file.py::test_name`. Some tests are env-gated,
e.g. Hermes MCP smoke tests need `XIBALBA_RUN_HERMES_MCP_SMOKE=1` to run rather than skip.

## Architecture

**Hash-chained events + domain-separated Merkle roots** (`store.py`) are the core integrity
primitive — every memory write is an append-only, hash-chained event, and Merkle roots are
computed per domain so a caller can verify a subset of the graph without needing the whole
chain. `memory_verify_chain` and `memory_session_merkle_root` expose this to callers.

**Hybrid retrieval** combines lexical, vector, graph, and temporal signals via Reciprocal Rank
Fusion (RRF) rather than any single retrieval mode — `memory_hybrid_retrieve` is the primary
read path; `memory_retrieval_trace` exposes which signals contributed to a given result, useful
when debugging why something did or didn't surface.

**Extraction is proposal-only, never auto-written.** Entity/relationship extraction runs through
an isolated Hermes worker profile (installed via `scripts/setup-cortex-worker-profile.sh`,
config env `XIBALBA_CORTEX_MODE` local/hybrid/remote-inference) and produces
`extraction_proposals` that require explicit review before being committed to the graph — this
is a deliberate safety gate, not an oversight; do not wire extraction output directly into the
store without going through the proposal/review lifecycle (`memory_claim_inference_task` →
`memory_complete_inference_task`).

**Runtime adapter layer** (`runtime_controller.py`, `*_adapter.py`, `codex_probe.py`) bridges
this store to different agent harnesses (agy, Claude Code, Codex) via a shared
`runtime_bridge_contract.py` — new runtime integrations should implement that contract rather
than adding harness-specific logic to `server.py` directly.

## Config / environment

No `.env.example` — configuration is YAML/env-var driven through `config.py`'s `CortexConfig`.
Key env vars: `XIBALBA_CORTEX_HOME`, `XIBALBA_CORTEX_MODE` (local/hybrid/remote-inference),
`XIBALBA_CORTEX_IDENTITY_MODE` (pseudonymous/full/omit), `XIBALBA_CORTEX_RETENTION_TIER`,
`XIBALBA_ANCHOR_URL`, `XIBALBA_AUTO_ANCHOR_ON_SESSION_END`, `XIBALBA_AGENT_ID`, `XIBALBA_RUNTIME`,
`XIBALBA_SESSION_ID`, `XIBALBA_ORACLE_URL`, `XIBALBA_GRAPH_HOOK_SURFACE`. Storage defaults to
`~/.hermes/xibalba-cortex` (SQLite, local-only) — no Docker/containerization is set up for this
service.

## Testing conventions

pytest with pytest-asyncio for async paths. Covers auth, config, the three background workers,
Hermes bridge/observer/smoke paths (env-gated), local API routes, Merkle-domain correctness,
retrieval trace/completeness, runtime adapters/bridge contract, vault inspection, and wiki
ingest. `tests/conformance/test_vectors.json` holds fixed input/output vectors — treat changes
to those vectors as a spec-surface change, not a routine test update.

## Status note

This repo is under active development (current work centers on hybrid extraction/retrieval and
viewer graph panels) — treat this file as a snapshot, not a frozen contract. When in doubt about
what's actually implemented vs. planned, check `IMPLEMENTATION_PLAN.md` and `git log` over
re-trusting prose here.
