# Xibalba Cortex Store Contract

This document is the operator-facing companion to `src/xibalba_cortex/store.py`. The normative model remains `spec/xibalba-cortex-v1.md`; this file records what the current implementation exposes and how it is verified.

## SQLite Authority And Schema

- The canonical profile-local database is `graph-memory.sqlite3` under the configured graph-memory home.
- `GraphStore` creates the profile directory with mode `0700` and the database file with mode `0600`.
- Current schema version is `3`, recorded in `schema_migrations` and surfaced by `GraphStore.status()` / `GET /api/status`.
- Migrations are in `GraphStore._bootstrap()`:
  - Version 1 records the base schema bootstrap.
  - Version 2 migrates `memory_vectors` to cosine distance when a legacy L2 `sqlite-vec` table is detected.
  - Version 3 is the current schema marker for the model-exchange, inference-task, and viewer/API surface.
- Health checks exposed by `GraphStore.status()` include SQLite WAL journal mode, foreign-key enforcement, FTS5 availability, `PRAGMA integrity_check`, identity mode, database path, memory count, and online-backup readiness.

## Canonical Tables

The store bootstraps source provenance, memory, graph, lifecycle, telemetry, inference, and integrity tables from `store.py`:

- `sources`, `memories`, `memory_events`, `memory_fts`
- `entities`, `entity_aliases`, `memory_entities`, `relations`, `contradictions`
- `sessions`, `model_exchanges`, `exchange_context_memories`, `exchange_tool_calls`
- `otel_events`, `attachments`, `embeddings_meta`, `memory_vectors`
- `memory_inference_tasks`, `integrity_links`, `schema_migrations`

Derived indexes are rebuildable. Source, memory, relation, event, and exchange-chain rows are the durable authority.

## Lifecycle And Event Chains

Memory lifecycle states are `candidate`, `active`, `confirmed`, `disputed`, `quarantined`, `superseded`, and `forgotten`.

Default recall eligibility is intentionally narrow: `GraphStore.search()` returns only `active` and `confirmed` memories. `quarantined`, `superseded`, `forgotten`, `candidate`, and `disputed` memories are inspectable by id but excluded from default recall.

Lifecycle mutation behavior:

- `store_memory(..., status='confirmed')` records a `create` event with confirmed status. There is no separate `confirm_memory()` mutation today.
- Quarantined writes record a `quarantine` event and are excluded from recall.
- `supersede_memory()` creates a new memory, marks the old one `superseded`, links `supersedes_id`, and appends a `supersede` event to the old memory.
- `mark_contradiction()` records the contradiction row and appends `contradict` events to both memories without changing either memory status.
- `forget_memory()` marks the memory `forgotten`, excludes it from recall, appends `forget`, and returns `content_hash_retained=true`.
- `restore()` is database-level backup restore, not a per-memory lifecycle restore. It refuses corrupt input before replacing the live database and preserves the event chains present in the restored snapshot.

Every memory event node is hash-linked through `node_id` and `parent_event_id`; `verify_chain(memory_id)` recomputes that chain. This is local tamper evidence only, not truth, authorization, completeness, or Integrity DAG anchoring.

`verify_integrity_link(memory_id, node_id=...)` reads Integrity Memory DAG `memory_nodes.jsonl`
files and compares the cited node's Keccak `content_hash` to the local memory content's Keccak
hash. A match writes `hash_match_local` to `integrity_links`. This is byte-lineage verification
only; it does not prove truth, authorization, completeness, ancestry to a root, or on-chain
anchoring.

## Backup, Restore, And Forgotten Hash Disclosure

`GraphStore.backup(destination)` uses SQLite's online backup API, writes a `0600` snapshot, and verifies the backup's `integrity_check` and schema version before returning.

`GraphStore.restore(source)` verifies the source database first. If verification fails, the live store is not touched. If verification passes, the live database file is replaced from the backup and reopened.

For forgotten records, content is excluded from recall but the content hash and event history remain. This is deliberate residual disclosure: a forgotten memory can still prove that a prior byte sequence existed locally, but it should not be returned by recall or treated as active memory.

## Retrieval And Vector Metadata

Lexical recall is FTS5/BM25 over `memory_fts`, status-filtered to active/confirmed memories.

Vector recall is optional and caller-supplied. The server never generates embeddings. Stored vectors must use `BAAI/bge-small-en-v1.5` and dimension `384`; metadata is recorded in `embeddings_meta` with the source content hash. When a caller supplies a query vector, `GraphStore.search()` fuses lexical and vector ranks using Reciprocal Rank Fusion.

## Graph Traversal

Entity graph traversal is bounded and evidence-linked:

- `neighbors(subject, max_depth=1)` accepts depths `1..3`, enforces node and edge limits, and returns `truncated` truthfully.
- `find_path(from_entity, to_entity, max_depth=3)` accepts depths `1..5` and returns the shortest discovered relation path.
- Relation rows carry `evidence_memory_id` so the viewer and MCP caller can jump back to provenance.
- Graph payloads include relation, similarity, and contradiction edges; contradiction edges are navigation evidence, not automatic resolution.

## Current Verification Anchors

Focused tests proving this contract live in:

- `tests/test_store.py::test_bootstrap_creates_secure_healthy_sqlite_store`
- `tests/test_store.py::test_store_memory_preserves_provenance_and_is_idempotent`
- `tests/test_store.py::test_supersession_contradiction_and_forgetting_preserve_history`
- `tests/test_store.py::test_entity_relations_support_bounded_neighbors_and_paths`
- `tests/test_store.py::test_memory_vectors_migrates_existing_l2_table_to_cosine_preserving_data`
- `tests/test_store.py::test_backup_produces_verified_restorable_snapshot`
- `tests/test_store.py::test_verify_integrity_link_checks_memory_dag_hash_without_claiming_anchor`
- `tests/test_resilience.py` for WAL recovery, concurrency, and profile isolation behavior
- `tests/test_server.py` for MCP recall, embedding, graph, status, and backup paths
