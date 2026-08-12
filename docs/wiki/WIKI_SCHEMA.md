# Xibalba Cortex Wiki — Schema (v1)

## Domain
The compiled knowledge base for the Xibalba Cortex repository: a local, provenance-aware graph
memory Model Context Protocol (MCP) server for AI agent harnesses — the SQLite store, its
hash-chain/Merkle tamper-evidence model, the MCP tool surface, the runtime-adapter and
generic-ingestion paths, and its role in the wider Xibalba ecosystem.

## Conventions
- **Canonical source**: `xibalba-cortex/docs/wiki/` on the main branch is the only authoring
  source of truth. The repository's GitHub Wiki is a generated, read-only projection of these
  files. Do not author or reconcile content in a downstream mirror; the next sync may overwrite
  it.
- **Table of contents**: every canonical article contains a generated `## Table of contents`
  block covering its level-two and level-three headings. Run `python3 scripts/wiki_toc.py`
  after heading changes and `python3 scripts/wiki_toc.py --check` in validation. Do not
  hand-edit the generated block.
- **Filenames**: lowercase, hyphenated, `.md` (e.g. `hash-chain-and-merkle-roots.md`).
- **Wikilinks**: use `[Title](relative/path.md)` to interlink entities/concepts/acronyms.
  Minimum 2 outbound links per page.
- **Frontmatter**: required on every page (template below).
- **Index sync**: every new page is added to `WIKI_INDEX.md` in the same pass it's created.
- **Append log**: every creation/update is logged in `WIKI_LOG.md` (append-only).
- **No aspirational content**: only document what exists in the code. Planned-but-unbuilt is
  marked `[PLANNED]`.
- **No duplication**: each fact lives on exactly one canonical page; others link to it.
- **Code over prose**: include real function signatures, schemas, or CLI commands, not
  paraphrase.

## Frontmatter template
```yaml
---
title: Page Title
acronyms: [optional, e.g. MCP, FTS5]
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query
tags: [see taxonomy below]
confidence: high | medium | low
source_files:
  - relative/path/to/file
---
```

### Confidence scoring
| Level | Meaning |
|---|---|
| `high` | Verified against source within the last 14 days |
| `medium` | Previously verified; source may have changed since — needs review |
| `low` | Carried over from a spec/plan, not yet verified against real code |

## Tag taxonomy
- `storage` — SQLite schema, WAL/FTS5/sqlite-vec, recall, backup/restore
- `provenance` — sources, content hashes, hash chains, evidence links
- `mcp` — the MCP tool surface, transports, protocol-level concerns
- `identity` — runtime identity binding, bearer tokens, agent identity modes
- `compliance` — auditability, redaction, evidence trails, retention
- `infrastructure` — server, transports, deploy/runtime plumbing, CLIs

## Directory structure
- `entities/` — concrete tables/objects and standalone subsystems with their own lifecycle
  (sessions/exchanges, entities/relations, ingest tokens)
- `concepts/` — shared mechanisms and protocols that cut across the store (the store itself,
  hash chains, the MCP surface, runtime adapters, generic ingestion, redaction, lifecycle)
- `architecture/` — cross-cutting structural/ecosystem docs (schema tour, ecosystem role)
- `queries/` — open research questions, investigation notes (not conclusions)

## Publication flow

```text
xibalba-cortex/docs/wiki
        └── scripts/sync_wiki.py ──> GitHub Wiki
```

There is no second dashboard consumer for this repository's wiki — unlike integrity-core, Cortex
does not currently sync into another product's `/wiki` route.

## Source binding rule
Every page's `source_files` must list real files that exist right now. If a listed file is
deleted or renamed, the page is stale — fix it or remove the page in the same pass that changes
the code.
