# Xibalba Advanced Memory Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a local, provenance-aware, graph-plus-vector memory system that reaches feature parity with leading agent-memory systems while preserving attributable intent, temporal history, profile isolation, and Integrity Protocol evidence.

**Architecture:** PostgreSQL 18 plus pgvector and relational adjacency tables will be the canonical production store. The current SQLite implementation remains the low-resource prototype and migration source. Raw episodes and Integrity events are authoritative; facts, entities, graph edges, embeddings, profiles, summaries, and specialized graph/vector indexes are rebuildable projections. Xibalba itself performs no local inference. Hermes is the only inference surface for extraction, summarization, reranking, reflection, entity resolution, and contradiction analysis. Qdrant is the future vector-heavy projection candidate and Neo4j is the future traversal-heavy projection candidate; neither may become a second canonical writer. Supermemory remains active during a shadow period; Xibalba initially integrates through a local Model Context Protocol server and only later evaluates native Hermes provider replacement.

**Tech Stack:** Python 3.11+, PostgreSQL 18, pgvector, FastAPI, Model Context Protocol, SQLAlchemy or psycopg, PostgreSQL Full-Text Search, Hermes-mediated inference calls, remote or externally provided embedding services, Docker Compose, OpenTelemetry, existing Integrity Protocol Software Development Kit and Middleware Merkle compatibility profile.

---

## 0. Non-negotiable design rules

1. A raw source episode is never replaced by an extracted fact, profile, summary, embedding, or reflection.
2. Valid time means when a proposition applies to the represented world. Transaction time means when Xibalba recorded or changed its system belief. They are separate fields.
3. Every derived fact, entity, edge, profile line, reflection, and procedural rule has one or more typed evidence links.
4. `declared_intent`, `observed_event`, `extracted_proposition`, `inference`, `summary`, and `policy` are distinct epistemic classes.
5. A Behavioral Commitment Chain signature proves that a key signed particular bytes. A Merkle proof proves inclusion under a root. A Memory Directed Acyclic Graph proves structural lineage. A StateAnchor proves contract-level anchoring. None proves semantic truth, honesty, authorization, fulfillment, or completeness.
6. Contradictions coexist. Current-state projections may prioritize an explicit authority policy, but historical records remain queryable.
7. Retrieval results are untrusted evidence and cannot silently become instructions, system authority, or tool permissions.
8. Profile, workspace, user, agent, key, session, event sequence, query, and root scope are explicit. Cross-profile foreign keys are rejected.
9. Ordinary writes are append-only. Corrections, supersessions, tombstones, revocations, and deletions are new events.
10. A specialized graph or vector database is a disposable projection, never a second canonical writer.
11. Consequential consolidation, hard deletion, procedural promotion, external publication, and anchoring are approval-gated and recorded as intent-linked operations.

## 1. Current hardware and deployment consequence

The development workstation currently has four central processing unit cores, 5.7 GiB memory, no discrete graphics processing unit, and 2.1 GiB free disk space on `/home`. The existing swap usage and nearly full disk make a large local model, PostgreSQL stack, and multiple projections unsafe to install blindly.

Readiness gates:

- Prototype gate: retain SQLite, use Full-Text Search 5, and call Hermes for extraction, summarization, contradiction analysis, and reranking. If embeddings are needed in the prototype, use an approved remote embedding endpoint or a Hermes-exposed embedding route; do not add a local inference model.
- The prototype vector path may use `sqlite-vec` for exact or small-scale search; its pre-1.0 status means it is not the production vector authority.
- PostgreSQL gate: free at least 20 GiB, preferably 50 GiB; target 16 GiB memory, preferably 32 GiB, before running PostgreSQL, indexes, and background inference-heavy workers continuously.
- Inference gate: Hermes must expose the required extraction and reranking endpoints or tools before background consolidation becomes mandatory. Store the embedding provider identifier, revision, dimensions, normalization, and content hash for every vector, even if the provider is remote.
- Do not use the current workstation as a production-scale 1-million-memory benchmark until storage and memory are expanded.

## 2. Database decision

PostgreSQL 18 plus pgvector plus relational adjacency tables is the canonical target because it can commit an episode, derived claim, graph edge, embedding manifest, Integrity event, and projection-outbox record in one transaction. PostgreSQL also provides mature backup, recovery, recursive queries, range types, full-text search, and Row-Level Security.

The current SQLite plus sqlite-vec implementation remains the portable prototype. Qdrant may be added when filtered approximate-nearest-neighbor latency or vector index memory becomes the measured bottleneck. Neo4j may be added when unconstrained multi-hop traversal or graph analytics becomes the measured bottleneck. Both must be populated from PostgreSQL through the transactional outbox, expose a sequence watermark, and remain disposable and rebuildable. Apache AGE and SurrealDB are evaluation spikes, not adoption decisions.

## 3. Feature-parity target

The system is feature-complete for the first replacement review only when it provides:

- working/session memory and bounded context assembly;
- immutable episodic history;
- semantic facts and user/entity profiles;
- procedural memory for validated workflows and policies;
- resource/document memory with exact chunk provenance;
- typed entity and relationship graph;
- valid-time and transaction-time history;
- contradiction, supersession, correction, expiration, decay, tombstone, and hard-purge policies;
- dense vector, lexical, entity, graph, temporal, and metadata retrieval;
- reciprocal-rank fusion, diversity control, and optional Hermes or remote cross-encoder reranking;
- query routing and structured evidence reading;
- reflection and consolidation with lineage;
- explicit feedback, retrieval traces, benchmarks, and reproducible replay;
- connectors and document processing;
- local Model Context Protocol, REST/OpenAPI, command-line interface, and future Hermes provider adapter;
- database-enforced profile isolation;
- encrypted backup, restore drills, migration, and rebuildable projections;
- Integrity Protocol declarations, proofs, checkpoints, and optional anchors;
- quarantine and retrieval-injection defenses.

The detailed research and source register are in:

`/home/xibalba/Projects/xibalba-graph-memory/docs/research/2026-08-05-agent-memory-landscape.md`

## 4. Canonical data model

Implement the PostgreSQL schema with migrations under the planned `migrations/` directory. Every profile-owned table uses composite keys or composite foreign keys containing `profile_id`.

### Identity and policy

- `profiles(profile_id, owner_subject, namespace, retention_policy, encryption_key_ref, status)`
- `workspaces(workspace_id, profile_id, policy_version)`
- `agents(agent_id, profile_id, did, role, status)`
- `agent_keys(agent_id, key_id, key_epoch, public_key, algorithm, valid_from, valid_to, revoked_at)`
- `memory_policies(profile_id, policy_version, trust_rules, retention_rules, retrieval_rules)`

### Immutable evidence and source provenance

- `source_episodes(profile_id, episode_id, source_type, source_locator, session_id, message_id, actor_id, occurred_at, ingested_at, raw_payload, raw_payload_hash_algorithm, raw_payload_hash, sensitivity_class, trust_class, quarantine_state)`
- `source_spans(profile_id, span_id, episode_id, start_offset, end_offset, span_hash)`
- `memory_events(profile_id, event_sequence, event_id, event_type, evidence_class, canonical_payload, payload_hash, previous_event_hash, occurred_at_claimed, recorded_at, actor_id, software_version, policy_version)`
- `evidence_links(profile_id, link_id, derived_id, source_episode_id, source_span_id, relation, support_weight, created_by)`

### Typed graph and temporal claims

- `entities(profile_id, entity_id, entity_type, canonical_name, resolution_status, created_event_id)`
- `entity_aliases(profile_id, entity_id, alias, source_episode_id, confidence)`
- `claims(profile_id, claim_id, subject_entity_id, predicate, object_entity_id, object_value, value_type, valid_from, valid_to, recorded_from, superseded_at, status, confidence, authority_scope)`
- `graph_edges(profile_id, edge_id, source_node_id, target_node_id, relation_type, valid_from, valid_to, recorded_from, recorded_to, status, evidence_event_id)`
- `claim_relations(profile_id, source_claim_id, target_claim_id, relation_type)` for `supports`, `contradicts`, `supersedes`, `derived_from`, `revises`, and `explains`

### Embeddings and search projections

- `embedding_models(model_id, provider, model_name, revision, dimensions, distance, normalization, content_hash, status)`
- `memory_embeddings(profile_id, object_type, object_id, model_id, embedding, generated_from_hash, generated_at)`
- `lexical_documents(profile_id, object_id, search_text, tsvector, tokenizer_version)`
- `entity_embeddings(profile_id, entity_id, model_id, embedding)`
- `retrieval_queries(profile_id, retrieval_id, query_text_hash, query_type, filters, model_versions, created_at)`
- `retrieval_candidates(profile_id, retrieval_id, object_id, channel, raw_score, fused_score, rerank_score, exclusion_reason)`

### Memory classes and derived materializations

- semantic fact;
- episodic experience;
- procedural rule or workflow;
- resource/document;
- static profile fact;
- dynamic profile context;
- observation or reflection;
- intent declaration and revision;
- action and outcome;
- security or policy event.

Profiles and summaries are projections with `derived_from_event_ids`, `model_id`, `prompt_hash`, `confidence`, `evidence_coverage`, `generated_at`, and `regeneration_state`.

### Lifecycle and operations

- `consolidation_jobs`
- `feedback_events`
- `forgetting_events`
- `deletion_requests`
- `deletion_receipts`
- `projection_outbox(profile_id, event_sequence, projection_kind, payload, delivered_at, failure_count)`
- `schema_migrations`

## 5. Integrity and intent timeline

Use a graph-specific, versioned cryptographic profile before implementation. Pin canonicalization, domain separation, complete signed BCC envelope encoding, leaf ordering, sorted-pair behavior, odd-node duplication policy, proof serialization, and cross-language vectors in a normative document under the planned `docs/integrity/` directory.

The intent timeline must support:

1. signed or unsigned declaration;
2. declared, inferred, observed, extracted, and policy evidence classes;
3. actor, profile, agent, DID, key identifier, key epoch, nonce stream, nonce, and signature status;
4. canonical intended-state payload and Secure Hash Algorithm 256-bit intended-state hash;
5. transactionally assigned per-profile/per-agent capture sequence;
6. previous event hash and previous checkpoint root;
7. gate decision and authorization status;
8. action evidence and outcome evidence;
9. revision, revocation, supersession, contradiction, and expiration;
10. Merkle batch manifest, member positions, proofs, and verification status;
11. optional Memory Directed Acyclic Graph reference;
12. optional StateAnchor lifecycle: local, submitted, mined, confirmed, finalized, failed, or reorged.

Merkle roots must use an explicitly typed graph root identifier and must not be represented as a BCC commitment hash, raw content hash, Memory Directed Acyclic Graph node hash, middleware leaf hash, or StateAnchor transaction identifier.

Development dogfooding must send supported telemetry, tool decisions, Behavioral Commitment Chain records, unsupported-telemetry gaps, and completed work units to the `xibalba.integrity` development collection. Unsupported fields are recorded as gaps, never fabricated.

## 6. Retrieval architecture

Implement retrieval as a staged pipeline:

1. classify the query as factual, temporal, relational, global, preference, historical, provenance-sensitive, or procedural;
2. derive lexical terms, entity candidates, and time interval candidates;
3. retrieve raw episodes and fact-expanded keys through lexical search;
4. retrieve dense vectors using the requested embedding provider and profile filter;
5. retrieve entity and graph neighborhoods only when the query requires them;
6. apply valid-time, transaction-time, trust, quarantine, sensitivity, authority, and retention filters;
7. fuse channels with Reciprocal Rank Fusion or a measured alternative;
8. apply diversity or Maximal Marginal Relevance to avoid redundant context;
9. optionally rerank with Hermes or a remotely hosted cross-encoder;
10. assemble a bounded structured evidence bundle with source IDs, evidence class, time, confidence, status, and verification state;
11. let the reader extract evidence before reasoning, and require abstention when evidence is absent or conflicts cannot be resolved by policy;
12. record a replayable retrieval trace.

Graph algorithms are conditional, not mandatory for every query. Use bounded breadth-first traversal for ordinary relation questions and evaluate Personalized PageRank for associative multi-hop retrieval. Use regenerable community summaries only for global questions.

## 7. Ingestion and consolidation

Separate the hot path from background work.

Hot path:

- append the raw episode and provenance;
- assign durable sequence and hash;
- classify sensitivity and prompt-injection risk;
- optionally store an explicit user-requested memory;
- return an event identifier without requiring full extraction.

Background path:

- send the event to Hermes for typed extraction, entity resolution, summarization, contradiction analysis, intent interpretation, and reranking if needed;
- validate structured output against a schema;
- resolve aliases and entities;
- create embeddings and lexical projections using the approved embedding provider;
- detect contradiction and supersession candidates;
- update materialized profiles;
- consolidate or reflect only under policy;
- generate Integrity events and close Merkle batches;
- emit metrics and retrieval/indexing traces.

Reflection is never an authority upgrade. A reflection must identify its supporting records, extractor model, prompt hash, confidence, and regeneration status.

## 8. Interface surface

Initial local Model Context Protocol tools:

- `memory_remember`
- `memory_recall`
- `memory_profile`
- `memory_timeline`
- `memory_traverse`
- `memory_sources`
- `memory_explain`
- `memory_feedback`
- `memory_correct`
- `memory_forget`
- `memory_verify`
- `memory_reflect`

Approval-gated administrative tools:

- `memory_consolidate`
- `memory_export`
- `memory_restore`
- `memory_hard_purge`
- `memory_anchor`
- `memory_policy_update`

REST/OpenAPI and command-line interfaces should call the same service layer. No interface may bypass profile authorization, append-only event creation, quarantine checks, or approval gates.

The future Hermes provider adapter should implement initialization, prefetch, asynchronous prefetch, turn synchronization, session-end extraction, pre-compression extraction, session switching, explicit memory writes, and backup-path reporting. It must not be enabled until shadow evaluation passes. The adapter remains the sole place where inference is invoked; Xibalba storage and retrieval services must never require a local model.

## 9. Implementation phases and bite-sized work packages

### Phase 0: Architecture and resource gate

**Files:** create `docs/integrity/xibalba-graph-crypto-profile-v1.md`, `docs/architecture/advanced-memory.md`, `docs/operations/resource-readiness.md`, and `tests/conformance/`.

Tasks:

1. Record the research register and feature-parity matrix.
2. Pin the database decision and projection rule.
3. Pin cryptographic algorithms and deterministic test vectors.
4. Define the evidence taxonomy and verification dimensions.
5. Define storage readiness checks and reject unsafe startup when disk or memory thresholds fail.
6. Create a conformance fixture that an independent Python implementation can reproduce.

Exit gate: no schema or production hash implementation proceeds while tree conventions, envelope encoding, profile boundaries, and deletion semantics remain ambiguous.

### Phase 1: Portable event kernel

**Modify:** existing `src/xibalba_graph/store.py` only as needed.
**Create:** `src/xibalba_graph/canonical.py`, `src/xibalba_graph/events.py`, `tests/test_events.py`, `tests/test_conformance.py`.

Tasks:

1. Add canonical JSON or canonical CBOR version identifiers.
2. Add append-only event sequences and previous-event hashes.
3. Add evidence classes and verification dimensions.
4. Add typed source and derivation links.
5. Add signed BCC envelope ingestion without storing private keys.
6. Add intent, revision, action, outcome, and revocation events.
7. Add deterministic Merkle batch creation and inclusion proofs.
8. Test replay, reordering, nonce races, key rotation, odd-node behavior, tampering, and profile mixing.

Exit gate: all conformance vectors pass and all known earlier graph-memory red tests are green.

### Phase 2: PostgreSQL canonical store

**Create:** `docker-compose.postgres.yml`, `migrations/`, `src/xibalba_graph/db/postgres.py`, `src/xibalba_graph/db/repositories.py`, `tests/integration/test_postgres_store.py`.

Tasks:

1. Pin PostgreSQL major version and pgvector version.
2. Translate the portable schema without PostgreSQL-only assumptions in the event model.
3. Enable foreign keys, constraints, exclusion constraints for valid-time overlaps where appropriate, and append-only permissions.
4. Add composite profile foreign keys.
5. Enable and force Row-Level Security on profile-owned tables.
6. Create separate owner, migration, writer, reader, projector, and backup roles.
7. Add health checks, connection pooling, migration locking, and transaction tests.
8. Migrate the SQLite prototype and verify hashes, event sequences, graph edges, and tombstones.
9. Add encrypted backup and restore verification.

Exit gate: concurrent writers, rollback, crash recovery, cross-profile access attempts, backup restore, and migration rollback all pass.

### Phase 3: Embedding and lexical layer

**Create:** `src/xibalba_graph/embeddings/`, `src/xibalba_graph/search/lexical.py`, `src/xibalba_graph/search/vector.py`, `tests/search/`.

Tasks:

1. Define the embedding model registry and version manifest.
2. Implement Hermes-mediated extraction and reranking contracts for development.
3. Connect an approved remote embedding service or Hermes-exposed embedding route for development.
4. Store multiple embedding-provider versions without overwriting old vectors.
5. Add re-embedding jobs with progress, cancellation, and rollback.
6. Add pgvector exact search, then HNSW after measurement.
7. Add PostgreSQL full-text search and a BM25/ParadeDB spike; retain native search if the extension adds unacceptable risk.
8. Add metadata and time filters before approximate search where possible.
9. Measure filtered HNSW recall and use iterative scans, partial indexes, or partitions only when data justifies them.

Exit gate: vector model migration, index rebuild, deterministic query replay, and profile-filtered recall pass.

### Phase 4: Entity graph and temporal memory

**Create:** `src/xibalba_graph/graph/`, `src/xibalba_graph/temporal/`, `tests/graph/`, `tests/temporal/`.

Tasks:

1. Add entity extraction and alias resolution.
2. Add typed claim and edge creation linked to source spans.
3. Add valid-time and transaction-time query operators.
4. Add non-destructive contradiction and supersession relations.
5. Add bounded traversal, path proofs, and cycle protection.
6. Add historical-state and current-state query modes.
7. Evaluate Personalized PageRank and store it as a rebuildable ranking projection.
8. Add optional community-summary cache with source lineage.

Exit gate: delayed ingestion, backdated claims, overlapping validity, contradictory actors, and historical reconstruction pass without silent deletion.

### Phase 5: Hybrid retrieval and context assembly

**Create:** `src/xibalba_graph/retrieval/`, `tests/retrieval/`.

Tasks:

1. Implement query classification and routing.
2. Add lexical, vector, entity, graph, and temporal candidate channels.
3. Add rank fusion and diversity control.
4. Add Hermes or remote cross-encoder reranking behind a feature flag.
5. Add authority, trust, quarantine, sensitivity, recency, importance, and decay scoring.
6. Add structured evidence bundles and abstention behavior.
7. Add retrieval traces and candidate exclusion reasons.
8. Add token-budgeted context assembly.

Exit gate: each answer claim can be traced to an evidence bundle, unsupported claims are measurable, and quarantined content cannot reach normal action authority.

### Phase 6: Profiles, reflection, and lifecycle

**Create:** `src/xibalba_graph/profiles/`, `src/xibalba_graph/consolidation/`, `tests/profiles/`, `tests/lifecycle/`.

Tasks:

1. Implement static, dynamic, topical, and role-specific profile projections.
2. Add profile evidence coverage and freshness.
3. Implement background consolidation as an outbox worker.
4. Implement reflection with explicit inference labels.
5. Implement decay and reinforcement as ranking signals.
6. Implement expiration without deleting source evidence.
7. Implement auditable tombstones and hard-purge policy checks.
8. Implement signed deletion receipts and residual-anchor disclosure.
9. Add human review for low-confidence or instruction-like inferred memories.

Exit gate: corrections, forgetting, retention policy, profile regeneration, and reflection rollback pass.

### Phase 7: Interfaces and operations

**Create:** `src/xibalba_graph/api/`, `src/xibalba_graph/mcp_server.py`, `src/xibalba_graph/cli.py`, `tests/protocol/`, `Dockerfile`, and `docker-compose.yml`.

Tasks:

1. Add service-layer authorization.
2. Add Model Context Protocol stdio server and protocol tests.
3. Add local REST/OpenAPI server.
4. Add command-line health, search, timeline, verify, backup, restore, and migration commands.
5. Add Docker health checks and a mounted control surface.
6. Add structured logs and OpenTelemetry spans without fabricating unsupported fields.
7. Add admin approval workflow for irreversible or external operations.
8. Keep Supermemory active and build a shadow-read comparator.

Exit gate: MCP discovery, tool schemas, profile isolation, health, restart, backup, and shadow comparison pass.

### Phase 8: Evaluation and parity

**Create:** `benchmarks/`, `tests/evaluation/`, `docs/evaluation/advanced-memory.md`.

Compare:

1. full history where feasible;
2. vector-only episode retrieval;
3. fact-expanded vector retrieval;
4. graph-only retrieval;
5. vector plus graph;
6. vector plus graph plus temporal filtering;
7. full Xibalba with provenance and Integrity policy;
8. Supermemory during shadow mode;
9. selected local systems only when their installation is safe and reproducible.

Run LoCoMo, LongMemEval-S, LongMemEval-M, optional LongMemEval-V2, DMR as a smoke test, and a conventional multi-hop set such as MuSiQue or 2WikiMultiHopQA.

Xibalba-specific tests must include signed intent later revoked, unsigned claims conflicting with signed declarations, delayed ingestion, false but correctly signed claims, malicious prompt injection, duplicate claims, source omission, profile crossover, and current-versus-historical questions.

Required metrics:

- Recall@k, Precision@k, Mean Reciprocal Rank, and Normalized Discounted Cumulative Gain;
- supporting-episode recall and provenance completeness;
- contradiction-pair recall and temporal-window accuracy;
- current-state and historical-state accuracy;
- declared-versus-inferred classification accuracy;
- signature, inclusion, attribution, and anchor-status accuracy;
- unsupported-claim and cryptographic-truth confusion rates;
- retrieval p50/p95, ingestion p50/p95, extraction cost, token use, storage growth, index rebuild time, central processing unit, memory, and disk usage.

Freeze model, embedding, reranker, prompt, schema, and policy versions per experiment. Ingest chronologically. Tune only on a development split. Publish category mappings and confidence intervals because public benchmark reports vary in setup and labels.

Exit gate: local Xibalba must meet a predefined parity threshold on retrieval quality and operational reliability, not merely match a vendor’s claimed headline score.

### Phase 9: Native Hermes provider decision

Only after shadow evaluation:

1. implement the Hermes provider lifecycle adapter;
2. run automatic capture in audit-only mode;
3. compare recall, latency, contamination, and user corrections against Supermemory;
4. enable automatic recall for one isolated profile;
5. require rollback and provider-switch documentation;
6. migrate only after acceptance review.

## 10. Security and privacy controls

- Treat all retrieved text as data, never executable instructions.
- Quarantine instruction-like content and untrusted source classes.
- Run extraction workers without tool authority.
- Apply tenant and policy filters before scoring and reranking.
- Keep Protected Health Information classification and encryption policy explicit.
- Do not expose raw payloads to logs; use content hashes and redacted evidence summaries.
- Protect embeddings as potentially sensitive derived data.
- Use encrypted volumes and encrypted backup repositories.
- Deny ordinary update/delete on evidence tables.
- Test prompt-injection, poisoning, relation-channel conflict, cross-profile leakage, replay, backdating, nonce reuse, key revocation, and deletion leakage.
- Disclose that anchored roots and hashes may retain information about deleted content.

## 11. Definition of done

The system is not ready to replace Supermemory until all of the following are true:

- canonical PostgreSQL state, graph, vectors, profiles, and Integrity events commit atomically;
- every derived claim has source lineage;
- current and historical temporal queries are correct;
- hybrid retrieval beats the agreed vector-only baseline on the selected evaluation split without unacceptable latency;
- profile isolation and quarantine tests pass under adversarial inputs;
- Merkle proofs and signed commitments pass independent conformance vectors;
- backups restore to a verified equivalent state;
- projections can be deleted and rebuilt from canonical events;
- retrieval traces explain inclusion and exclusion;
- all external writes and irreversible operations are approval-gated;
- unsupported telemetry and semantic uncertainty are reported honestly;
- shadow comparison against Supermemory is complete and reviewed.

The correct immediate implementation order is Phase 0, then the portable event kernel and conformance vectors, then PostgreSQL migration. Do not begin with a graph database or a large embedding model. Build the evidence and replay boundary first, because every later vector, graph, profile, and retrieval feature must remain rebuildable from it.
