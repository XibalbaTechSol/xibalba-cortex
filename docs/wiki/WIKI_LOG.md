# Xibalba Cortex Wiki — Log

> Chronological record of wiki actions. Append-only — never edit past entries.
> Actions: ingest, create, update, lint, query, archive

## [2026-08-12] create | Initial Cortex wiki

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
