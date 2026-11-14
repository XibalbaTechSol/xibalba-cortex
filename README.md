# Super-Cortex (`super-cortex`)

High-performance, cryptographic graph memory engine and Model Context Protocol (MCP) server for the Xibalba ecosystem, built upon **Supermemory Local**.

---

## Overview

`super-cortex` bridges **Supermemory Local** (`127.0.0.1:6767`) with **Xibalba's Cryptographic Provenance Ledger**. It replaces bespoke, heavyweight embedding pipelines with Supermemory's native vector search, automatic profile synthesis, and local neural indexing while enforcing Xibalba's non-negotiable integrity invariants:

1. **Cryptographic Hash-Chains:** Append-only event history where every transition (`remember`, `contradict`, `supersede`, `forget`, `link_entities`) is chained via SHA-256 (`prior_hash -> event_hash`).
2. **Domain-Separated Merkle Roots:** Deterministic session-level Merkle trees computed over turn hashes and context contributions (`memory_session_merkle_root`).
3. **Epistemic Classifications & Lifecycles:** Tracks memories as `fact`, `inference`, `assumption`, `belief`, `goal`, `observation`, or `rule`, with state transitions (`active`, `superseded`, `contradicted`, `quarantined`, `forgotten`).
4. **Knowledge Graph & Entity Edges:** Directed entity-relationship graph (`subject -[predicate]-> object`) with confidence scores and evidence links.
5. **Untrusted Content Boundaries:** Recalled context is explicitly tagged as untrusted evidence per Cortex Spec §3 so it never overrides system or developer prompt instructions.
6. **Unified MCP Server Contract:** Provides drop-in compatibility for AI agent harnesses (Claude Code, Hermes, Antigravity, Codex) via stdio and SSE/HTTP transports.

---

## Quickstart

### Prerequisites
- Python 3.12+ with `uv`
- Supermemory Local daemon running on `127.0.0.1:6767`

### Diagnostic Doctor
Verify daemon connectivity, API key authorization, and database chain integrity:
```bash
uv run super-cortex doctor
```

### Ingesting & Searching Memories
```bash
# Store a memory
uv run super-cortex remember "Integrity Protocol enforces domain-agnostic provenance verification." --class rule

# Semantic search with cosine similarity ranking
uv run super-cortex search "What does Integrity Protocol enforce?"

# Verify cryptographic audit chain
uv run super-cortex verify
```

### Running the MCP Server
Launch the stdio server for MCP agent harnesses:
```bash
uv run super-cortex run --transport stdio
# or via entrypoint:
uv run super-cortex-server
```

---

## MCP Tool Surface

| Tool | Parameters | Description |
|---|---|---|
| `memory_remember` | `text`, `epistemic_class`, `namespace`, `metadata`, `session_id`, `source_origin` | Ingests into Supermemory Local and records cryptographic provenance. |
| `memory_recall` | `memory_id` | Fetches memory record by exact ID. |
| `memory_hybrid_retrieve` | `query`, `namespace`, `limit` | Performs semantic search with attached cryptographic provenance. |
| `memory_profile` | `namespace`, `buckets` | Synthesizes profile buckets (interests, goals, facts) via Supermemory. |
| `memory_contradict` | `target_memory_id`, `reason`, `counter_evidence` | Records contradiction in append-only event ledger. |
| `memory_supersede` | `target_memory_id`, `replacement_text`, `reason`, `namespace` | Supersedes prior memory with an updated replacement. |
| `memory_forget` | `target_memory_id`, `namespace` | Quarantines memory while preserving cryptographic audit trail. |
| `memory_link_entities` | `subject`, `predicate`, `object`, `confidence`, `evidence_links` | Adds directed entity relationship edge to knowledge graph. |
| `memory_neighbors` | `node`, `max_depth` | Queries neighboring edges for an entity. |
| `memory_record_model_exchange` | `session_id`, `prompt_text`, `response_text`, `tool_calls`, `context_hashes` | Captures turn exchange and updates session Merkle root. |
| `memory_verify_chain` | *(none)* | Verifies integrity of the cryptographic event chain. |
| `memory_session_merkle_root` | `session_id` | Computes domain-separated Merkle root for a given session. |
| `supermemory_status` | *(none)* | Inspects Supermemory Local daemon connectivity and namespaces. |
| `super_cortex_health` | *(none)* | Reports operational health and ledger metrics. |

---

## Configuration

Settings are configured via environment variables or `.env`:

| Variable | Default | Description |
|---|---|---|
| `SUPERMEMORY_URL` | `http://127.0.0.1:6767` | Base URL of Supermemory Local |
| `SUPERMEMORY_API_KEY` | *(read from `~/.supermemory/api-key`)* | Bearer authorization token |
| `SUPER_CORTEX_DB_PATH` | `~/.super-cortex/provenance.db` | SQLite cryptographic ledger path |
| `SUPER_CORTEX_DEFAULT_NAMESPACE` | `xibalba` | Default memory namespace |
| `SUPER_CORTEX_ACTOR_DID` | `did:integrity:68fed133...` | Default actor identity |

---

## Testing

Run the full pytest suite:
```bash
uv run pytest -v
```
