# Xibalba Graph Memory Implementation Plan

> **For Hermes:** Execute with strict test-driven development, one vertical slice at a time.

**Goal:** Build a local, profile-isolated, provenance-aware graph memory Model Context Protocol server that coexists with Supermemory and can verify byte lineage against the Integrity Memory Directed Acyclic Graph.

**Architecture:** SQLite is the sole authoritative store. Sources and immutable memory revisions feed explicit entity and relation edges; Full-Text Search 5 provides lexical retrieval, optional local embeddings remain derived indexes, and every result carries provenance. A standard-input/standard-output Model Context Protocol server exposes explicit tools while Supermemory remains Hermes's active automatic memory provider.

**Technology stack:** Python 3.12, SQLite Write-Ahead Logging and Full-Text Search 5, Model Context Protocol Python software development kit, pytest, and Ethereum-compatible Keccak hashing.

## Security invariants

1. Recalled text is untrusted evidence and cannot override instructions.
2. Every memory revision has source provenance and a content hash.
3. Automatic or untrusted content starts as `candidate` or `quarantined`; only eligible states are recalled by default.
4. Graph traversal is bounded by depth, node count, edge types, and timeout.
5. Integrity status means byte integrity or lineage only, never factual truth.
6. Profile storage paths are explicit and remain under the configured Hermes home.
7. Derived indexes are rebuildable; immutable source revisions are authoritative.
8. Forgetting propagates to searchable data and reports residual hashes or backups honestly.

## Task 1: Database bootstrap

- Test: `tests/test_store.py`
- Create: `src/xibalba_graph/store.py`
- Write a failing test for secure directory creation, schema version, WAL, foreign keys, FTS5, and integrity checks.
- Implement the minimum bootstrap and rerun the test.

## Task 2: Provenance-preserving memory storage

- Test explicit memory insertion with required source metadata, deterministic content hash, immutable revisions, idempotency key, security-state validation, and injection quarantine.
- Implement source, document, memory, event, and FTS rows in one transaction.

## Task 3: Recall and corrections

- Test ranked FTS5 recall, exclusion of quarantined/forgotten material, structured evidence bundles, supersession, and contradiction visibility.
- Implement lexical retrieval and correction without deleting history.

## Task 4: Entity graph

- Test conservative entity creation, aliases, typed edges, evidence attachment, bounded neighbors, and bounded shortest paths.
- Implement relational adjacency tables and traversal limits.

## Task 5: Forgetting and backup

- Test immediate suppression, logical forgetting, derived-edge removal, residual-attestation disclosure, SQLite online backup, and restore integrity.
- Implement forget events and online backup.

## Task 6: Integrity Memory DAG links

- Test local Keccak hash matching, missing nodes, mismatches, corrupt JSON Lines input, and terminology that distinguishes lineage from truth.
- Implement read-only verification against a configured vault path; never use the JSON Lines file as the hot index.

## Task 7: MCP tools

- Test advertised schemas and direct tool handlers for store, recall, link, neighbors, path, contradict, forget, verify, status, and backup.
- Implement a standard-input/standard-output server with no network listener.

## Task 8: Hermes integration

- Keep `memory.provider: supermemory` unchanged.
- Register `mcp_servers.xibalba_graph` with an explicit profile-local data directory.
- Restart or reload Model Context Protocol discovery.
- Verify tools are discovered and exercise store, recall, graph traversal, forgetting, backup, and Integrity verification through the protocol.

## Task 9: Acceptance and documentation

- Run unit, integration, concurrency, process-kill, backup/restore, profile-isolation, prompt-injection, and missing-model tests.
- Document schema, threat model, operational commands, backup, restore, and the future migration gate for replacing Supermemory.
