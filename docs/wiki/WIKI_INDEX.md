# Xibalba Cortex Wiki — Index

> Content catalog. Every page represents something that actually exists in the codebase right
> now — see the schema's "no aspirational content" rule. This is a focused core set covering
> Cortex's actual architecture, not an exhaustive catalog — contributions adding more pages are
> welcome.
> Last updated: 2026-08-28 | Total pages: 18 (10 concepts, 5 architecture, 3 entities, 1 query)

## Acronym glossary
- [MCP](concepts/mcp-tool-surface.md) — Model Context Protocol
- [FTS5](architecture/store-schema-overview.md) — SQLite's full-text search extension (v5), used for lexical recall
- [WAL](architecture/store-schema-overview.md) — SQLite Write-Ahead Logging journal mode

## Concepts
- [Graph Store](concepts/graph-store.md) — `GraphStore`: the SQLite (WAL + FTS5 + sqlite-vec) canonical store and its object model
- [Hash Chain and Merkle Roots](concepts/hash-chain-and-merkle-roots.md) — the per-memory event hash chain and the session exchange Merkle-style root; local tamper evidence, not a blockchain
- [MCP Tool Surface](concepts/mcp-tool-surface.md) — the ~40+ MCP tools exposed by `server.py`, and the stdio/streamable-HTTP transports
- [Runtime Adapters](concepts/runtime-adapters.md) — the richer, opt-in identity+policy layer for the three officially-adapted runtimes (claude, agy, codex)
- [Generic Ingestion](concepts/generic-ingestion.md) — `memory_ingest_agent_turn`, streamable-HTTP, and per-harness bearer-token auth for any agent harness
- [Redaction](concepts/redaction.md) — `redact()`: shared secret-scrubbing logic used across every ingestion path
- [Lifecycle and Forgetting](concepts/lifecycle-and-forgetting.md) — memory lifecycle states, contradiction, supersession, quarantine, and forgetting's residual-hash tradeoff
- [PARA Classification](concepts/para-classification.md) — reviewable Projects/Areas/Resources/Archives proposals with stale-source protection
- [Integrity and Merkle Evidence](concepts/integrity-and-merkle-evidence.md) — local roots, hash chains, and evidence boundaries
- [Embedding Worker](concepts/embedding-worker.md) — bounded, hash-protected vector backfill with strict validation
- [Contradiction Worker and Proposal Lifecycle](concepts/contradiction-worker.md) — bounded contradiction detection and reviewable proposal acceptance
- [Hybrid Extraction and Retrieval](concepts/hybrid-extraction-and-retrieval.md) — Hermes extraction validation, four-channel retrieval traces, and canonical-left projection reconciliation

## Entities
- [Sessions and Exchanges](entities/sessions-and-exchanges.md) — the `sessions`/`exchanges`/`exchange_memories`/`exchange_tool_calls`/`exchange_context_memories` tables
- [Entities and Relations](entities/entities-and-relations.md) — the `entities`/`relations` tables: bounded graph traversal, evidence-linked edges
- [Ingest Tokens](entities/ingest-tokens.md) — `ingest_tokens.py`: per-harness bearer tokens in a separate SQLite file, hash-only storage

## Architecture
- [Ecosystem Role](architecture/ecosystem-role.md) — Cortex as 🧠 The Brain in the three-repository ecosystem, and as a standalone MCP memory server first
- [Store Schema Overview](architecture/store-schema-overview.md) — a schema-level tour of every table in `graph-memory.sqlite3`
- [Inference Queue and Recovery](architecture/inference-queue.md) — claim ownership, leases, bounded retries, and legacy queue reconciliation
- [Viewer and Local API](architecture/viewer-and-local-api.md) — graph, recall, inference, PARA, integrity, and headless validation
- [Hybrid Local-First Providers](architecture/hybrid-local-first-providers.md) — local/hybrid modes, native harness inference, and local embeddings

## Open queries
- [Compliance Evidence Trail](queries/compliance-evidence-trail.md) — how far Cortex's queryable, hash-chained history goes toward compliance-grade evidence, and what's still open (streaming queries, multi-tenant sharing, opt-in anchoring)

## Reference
- [index.md](index.md) — the wiki landing page
- [WIKI_LOG.md](WIKI_LOG.md) — chronological record of every wiki change, append-only
- [WIKI_SCHEMA.md](WIKI_SCHEMA.md) — page format, frontmatter, tag taxonomy
