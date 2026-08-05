# Agent Memory Landscape Research

Date: 2026-08-05

This report informs the Xibalba Advanced Memory implementation plan. Documented capabilities are separated from Xibalba recommendations. Vendor benchmark results are not treated as independently verified facts.

## Executive findings

The strongest recurring pattern is not that graphs universally outperform vectors. It is:

1. Preserve raw episodes.
2. Extract compact facts and entities without discarding source provenance.
3. Model valid time separately from transaction or knowledge time.
4. Combine lexical, dense, entity, graph, and temporal retrieval.
5. Rerank a small candidate set before context assembly.
6. Treat updates as versioning or invalidation, never silent destructive replacement.
7. Keep reflections and summaries as derived evidence-linked artifacts.

## Systems reviewed

| System | Documented strengths | Capability Xibalba should adopt | Important limitation or caveat |
|---|---|---|---|
| Mem0 | Multi-level memory, entity linking, semantic plus BM25 plus temporal retrieval, lifecycle operations, self-hosted deployment | Additive extraction, entity linking, expiration/decay, pluggable reranking, evidence-linked synthesis | Current graph memory primarily links entities to memories through co-occurrence; it does not expose a typed entity-to-entity relation model. Vendor benchmark claims require reproduction. |
| Zep / Graphiti | Temporal context graph, episodes, entities, typed facts, provenance, bi-temporal validity, hybrid search | Immutable episodes, typed facts, valid-time and knowledge-time intervals, non-destructive invalidation, graph traversal | Managed Zep internals are proprietary. Recency or invalidation is not semantic truth. |
| Letta / MemGPT | Working/core memory, archival memory, agent-controlled edits, persistent messages, human-readable memory files, version history | Inspectable materializations, explicit agent edits, rollback, working/episodic separation | No equivalent native cryptographic claim lineage or full temporal property graph was established. |
| LangMem / LangGraph | Semantic, episodic, procedural memory; hot-path tools; background extraction; profile or collection patterns; namespaces | Separate memory types, hot-path versus background workers, typed profiles, storage abstraction | Graph, provenance, reranking, tenancy enforcement, and truth semantics are application responsibilities. |
| Supermemory | Automatic capture, static/dynamic profiles, hybrid memory plus document retrieval, connectors, MCP, local deployment | Product-facing profile/context API, connectors, shadow comparison, unified document and memory recall | Ranking and extraction internals are not fully specified; hosted benchmark claims are self-reported. |
| Hindsight | World facts, experiences, opinions, observations, semantic/BM25/graph/temporal retrieval, reciprocal-rank fusion, cross-encoder reranking, reflection | Separate fact/experience/reflection classes, multi-channel retrieval, evidence-linked observations, security-event records | Reflections remain model-derived. Do not promote them to declared fact. |
| Cognee | Knowledge graph, vector and lexical search, ontologies, multimodal ingestion, improve/memify pipelines, MCP, OpenTelemetry | Ontology pipeline, regenerable graph projections, operational telemetry, multimodal extension point | Production PostgreSQL graph functionality has licensing/feature caveats in its documentation. |
| MIRIX | Specialized core, episodic, semantic, procedural, resource, and knowledge-vault memory | Rich memory taxonomy and restricted vault lane | Graph, cryptographic provenance, and benchmark tooling were not established in reviewed materials. |

## Feature-parity target

Xibalba must implement the following capabilities before it is considered a credible replacement candidate:

- Working/session memory and bounded context assembly.
- Immutable raw episodic history.
- Semantic fact and entity memory.
- Procedural memory for validated workflows and policies.
- Resource/document memory with chunk provenance.
- Static, dynamic, topical, and role-scoped profiles.
- Typed entity and relationship graph.
- Valid-time and transaction-time history.
- Contradiction, supersession, correction, expiration, and tombstone semantics.
- Dense vector retrieval with versioned embeddings.
- Lexical retrieval, initially PostgreSQL full-text and later an independently benchmarked BM25 extension if required.
- Entity-aware and graph-neighborhood retrieval.
- Temporal pre-filtering and time-aware scoring.
- Reciprocal Rank Fusion and optional local cross-encoder reranking.
- Query classification and retrieval routing.
- Reflection/consolidation with source links and model/prompt provenance.
- Explicit feedback and retrieval-quality evaluation.
- Document connectors and file processing.
- Model Context Protocol, REST/OpenAPI, command-line interface, and eventual Hermes provider integration.
- Profile and namespace isolation enforced by the database and application.
- Backups, restore drills, migration tooling, and rebuildable projections.
- Integrity Protocol evidence: signed declarations, provenance, append-only events, Merkle checkpoints, inclusion proofs, and optional StateAnchor evidence.
- Retrieval-injection defense, trust tiers, quarantine, audit logs, and privacy controls.

## Database comparison

| Option | Assessment for canonical Xibalba memory |
|---|---|
| PostgreSQL 18 plus pgvector plus relational adjacency tables | Recommended. Strong transactions, constraints, Row-Level Security, backups, vector indexes, full-text search, range types, recursive queries, and mature clients. Graph traversal is less ergonomic than Cypher but sufficient for bounded memory paths. |
| SQLite plus sqlite-vec | Recommended prototype and edge format. Small and portable, with Full-Text Search 5 and vector extension support. Single-writer limits, immature vector extension, and weak database-enforced tenancy make it unsuitable as the long-term concurrent authority. |
| Neo4j | Strong graph-first projection candidate. Excellent traversal and native vector/full-text indexes. More licensing, edition, backup, and relational-filtering complexity for the canonical evidence ledger. |
| Qdrant | Strong future vector projection. Dense, sparse, multivector, filtering, quantization, and hybrid query support. It cannot atomically commit graph edges, provenance, and Integrity events with a relational authority. |
| FalkorDB | Attractive low-latency graph engine and Graphiti backend. Durability, general transaction semantics, licensing, and ecosystem risk make it unsuitable as canonical evidence. |
| Weaviate | Excellent turnkey vector and hybrid search, with multi-tenancy. Cross-references are not a full graph traversal model and general multi-object transactions are not the canonical fit. |
| Milvus | Strong for very large vector workloads but operationally heavy and graph-free. Not appropriate for the initial workstation. |
| LanceDB | Strong local vector and multimodal sidecar with versioned tables and full-text search. No native graph or server-enforced tenant isolation. |
| SurrealDB | Promising unified graph/vector/document engine, but fast-moving semantics, Business Source License constraints, and shorter operational history make it a spike candidate only. |
| PostgreSQL plus Apache AGE | Possible future graph projection or experiment. Adds extension and migration complexity; do not make it a prerequisite for the first production slice. |
| ParadeDB | BM25-capable PostgreSQL distribution worth a search spike. Do not make it canonical until extension upgrade, licensing, and pgvector compatibility are verified. |

## Academic and benchmark evidence

- MemGPT, arXiv:2310.08560: hierarchical context management and agent-controlled paging; useful memory-control pattern, not a truth model.
- Generative Agents, arXiv:2304.03442: relevance plus recency plus importance, with reflection; reflections must remain derived artifacts.
- MemoryBank, arXiv:2305.10250: profile synthesis and decay/reinforcement; decay must alter ranking rather than erase critical evidence.
- HippoRAG, arXiv:2405.14831: query-seeded graph diffusion can improve associative retrieval, but graph construction quality and indexing cost matter.
- GraphRAG, arXiv:2404.16130: community summaries help global questions, but summaries are not a replacement for source evidence.
- LoCoMo, arXiv:2402.17753: tests single-hop, multi-hop, temporal, open-domain, and adversarial long-term conversation memory.
- LongMemEval, arXiv:2410.10813: tests information extraction, multi-session reasoning, temporal reasoning, knowledge updates, and abstention. It demonstrates benefits from fact-expanded keys and time-aware retrieval but does not test cryptographic provenance or poisoning.
- Zep, arXiv:2501.13956: bi-temporal context graphs and non-destructive invalidation; results are partly author-reported and assistant-side recall regressed in one reported category.
- Mem0, arXiv:2504.19413: extracted memories and graph variants; graph gains were task-dependent and reported category mappings require independent reproduction.
- Cognee, arXiv:2505.24478: graph/LLM interface parameters materially affect multi-hop retrieval.
- Hindsight, arXiv:2512.12818: retain, recall, reflect architecture with multiple retrieval channels; reflection remains inference.
- A-MEM, arXiv:2502.12110: linked atomic notes and contextual enrichment; memory evolution can blur original provenance if not versioned.
- Graph-based Agent Memory survey, arXiv:2602.05665: current taxonomy and techniques; use as a research index, not as a production specification.

## Source register

All retrieved 2026-08-05:

- Mem0 repository and documentation: https://github.com/mem0ai/mem0 and https://docs.mem0.ai
- Graphiti: https://github.com/getzep/graphiti
- Zep paper and documentation: https://arxiv.org/abs/2501.13956 and https://help.getzep.com
- Letta: https://github.com/letta-ai/letta and https://docs.letta.com
- LangMem: https://github.com/langchain-ai/langmem and https://langchain-ai.github.io/langmem
- Supermemory: https://github.com/supermemoryai/supermemory and https://supermemory.ai/docs
- Hindsight: https://github.com/vectorize-io/hindsight and https://hindsight.vectorize.io
- Cognee: https://github.com/topoteretes/cognee and https://docs.cognee.ai
- MIRIX: https://github.com/Mirix-AI/MIRIX and https://docs.mirix.io
- PostgreSQL: https://www.postgresql.org/docs/current
- pgvector: https://github.com/pgvector/pgvector
- Neo4j vector indexes: https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- Qdrant: https://github.com/qdrant/qdrant
- Weaviate: https://github.com/weaviate/weaviate
- Milvus: https://github.com/milvus-io/milvus
- LanceDB: https://github.com/lancedb/lancedb
- sqlite-vec: https://github.com/asg017/sqlite-vec
- SurrealDB: https://github.com/surrealdb/surrealdb
- Apache AGE: https://github.com/apache/age
- LoCoMo: https://github.com/snap-research/locomo
- LongMemEval: https://github.com/xiaowu0162/LongMemEval
- MemoryBench: https://github.com/supermemoryai/memorybench
