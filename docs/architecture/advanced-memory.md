# Advanced Memory Architecture — Phase 0 Decisions

Status: Phase 0 decisions pinned, 2026-08-05. Supersedes the "PostgreSQL 18 plus pgvector...
is the canonical target" language in `docs/plans/2026-08-05-xibalba-advanced-memory.md` §2.

## 1. Database decision: SQLite is canonical, not PostgreSQL

### The spike

Two candidates were benchmarked on the actual access pattern this system has — one row
committed per agent turn (single-row transactional insert), not bulk load — because that
pattern is where DuckDB's columnar/OLAP design was flagged as a risk. PostgreSQL was **not**
benchmarked; see §1.3.

Method: 3000 single-row `INSERT` + `COMMIT` cycles against an equivalent five-column table,
SQLite configured exactly as `src/xibalba_graph/store.py` configures it today (`WAL`,
`synchronous = FULL`, `foreign_keys = ON`), DuckDB with default durability. Measured with
`resource.getrusage(RUSAGE_SELF).ru_maxrss`.

| Engine | Elapsed (3000 inserts) | Throughput | Process RSS before → after |
|---|---|---|---|
| SQLite (WAL, synchronous=FULL) | 11.585s | 259 inserts/sec | 15.8MB → 16.6MB |
| DuckDB (default) | 17.731s | 169 inserts/sec | 56.8MB → 68.1MB |

SQLite is **1.5x faster** and uses **~4x less resident memory** for this exact workload. This
is not a close call requiring further tuning before deciding — DuckDB's columnar storage engine
pays real per-transaction overhead that a row store doesn't, and on a 5.7GB-RAM machine, the
memory delta alone (68MB vs 17MB, before any embedding model or MCP server overhead is added)
is material.

`sqlite-vec` v0.1.9 was confirmed to load and perform correct KNN search in-process (see
`inserts/rowid`/`distance` round-trip test run during the spike). It remains pre-1.0 — not a
concern for the prototype/current phase, revisit before treating it as load-bearing for a
production vector workload at scale.

### 1.1 Decision

**SQLite (with WAL, FTS5, and `sqlite-vec` for the vector leg) is canonical**, not a stepping
stone to PostgreSQL. The advanced plan's own reasons for preferring PostgreSQL — "single-writer
limits" and "weak database-enforced tenancy" — describe multi-tenant concurrent-access problems
this system does not have: one operator, one machine, one MCP server process. SQLite's
WAL mode already provides what's actually needed (concurrent readers, one writer).

### 1.2 Why DuckPGQ / DuckDB-as-graph-engine was not evaluated further

DuckPGQ (SQL:2023 property-graph queries over DuckDB) was dropped from the spike per the
rule-10 fallback in the continuation plan: DuckPGQ is pinned to DuckDB 1.4.4 specifically
(incompatible with the 1.5.x line installed during this spike), which makes it an unstable
foundation independent of the write-throughput result above. Once DuckDB itself lost the
throughput/memory comparison, evaluating its graph query layer added no further information.

### 1.3 Why PostgreSQL was not installed or benchmarked

Installing and resident-metering PostgreSQL costs real disk and memory this machine was, until
this session, unable to spare (`/home` was at 2.1GB free / 99% full before reclamation; see
`docs/operations/resource-readiness.md`). Spending that budget to benchmark an engine whose
own stated advantages (multi-tenant Row-Level Security, concurrent-writer scaling) don't apply
to a single-user local agent was not justified. PostgreSQL remains a documented future option,
gated on a concrete capability gap SQLite/DuckDB cannot close — not on convenience or having
been named first in an earlier draft.

### 1.4 Projection rule (unchanged, engine-independent)

A specialized graph or vector database is a disposable projection, never a second canonical
writer (`2026-08-05-xibalba-advanced-memory.md` rule 10). This holds regardless of which
relational engine is canonical. LadybugDB (the community-maintained successor to the
now-archived KuzuDB — see §2) and Neo4j remain future graph-projection candidates, evaluated
only once query patterns SQLite's relational adjacency tables can't serve efficiently actually
appear.

## 2. Embedded-graph landscape correction

The original research register (`docs/research/2026-08-05-agent-memory-landscape.md`) does not
mention KuzuDB. For the record: KuzuDB — the most natural embedded-graph-database candidate for
this system's deployment model — was archived in October 2025 after Apple acquired the company
behind it; no further releases or community support exist. Its community fork, **LadybugDB**
(MIT license, same founding engineers, positioned as "DuckDB for graphs"), is the closest
successor but began only in 2025 and is too immature to be a canonical dependency today. Track
it as a future disposable graph-projection candidate per §1.4, not a Phase-1 option.

## 3. Devil's Advocate review

Per the mandatory review protocol (`/home/xibalba/CLAUDE.md` → SOUL.md; Hermes strategic
memory), each architecture decision below was steelmanned against its strongest counter-argument
before being confirmed.

### 3.1 SQLite-as-canonical-authority under concurrent MCP + Hermes access

**Steelman for rejecting SQLite:** a single-writer database will serialize writes if more than
one Hermes session or MCP client writes concurrently, and WAL mode does not eliminate `SQLITE_BUSY`
under sustained write contention — only `busy_timeout` (already set to 5000ms in `store.py`)
papers over it, and a long-running writer transaction can still starve others.

**Response:** the actual deployment is one profile-local SQLite file behind one MCP stdio server
process, which serializes calls at the protocol layer before they reach the database — there is
no concurrent-writer scenario to defend against yet, only a hypothetical multi-agent-session one.
If genuine multi-writer contention appears (e.g., multiple Hermes profiles sharing one memory
store, which the profile-isolation design explicitly does not do), that is the concrete capability
gap referenced in §1.3 that would reopen the PostgreSQL question. Decision stands: SQLite is
sufficient for the deployment model that actually exists.

**Verified, not just argued (2026-08-05, later same day):** this response was reasoning, not a
test, when first written. `tests/test_resilience.py` now backs it empirically: two independent
`GraphStore` instances (two real SQLite connections, not one connection shared across threads)
writing 15 memories each concurrently to the same database, from separate Python threads,
produced zero errors, zero id collisions, and a clean `integrity_check` afterward. A separate
test simulates an actual process crash mid-write (a genuine subprocess, `os._exit(1)` with an
open uncommitted transaction — not `del`, which was tried first and found not to reliably
release SQLite's OS-level lock in-process) and confirms WAL recovery leaves prior committed data
intact on reopen. Profile isolation (two `GraphStore` homes, zero cross-visibility) is likewise
now a passing test, not only a schema convention.

### 3.2 One-way coupling to the Integrity DAG

**Steelman for tighter coupling:** citing DAG `node_id` values one-way (recall may cite evidence,
evidence never depends on recall) seems to leave `integrity_links.verification_state` permanently
unable to prove anything, since the DAG itself doesn't exist yet (§4).

**Response:** this is the correct design regardless of DAG implementation status — recall must be
able to forget and re-rank; evidence must never forget. Collapsing them would make forgetting
retroactively falsify anchored history, or make anchoring block ordinary memory hygiene. The
schema doesn't create a hidden reverse dependency: `integrity_links` is a nullable, memory-owned
table that the DAG never reads from. Decision stands: one-way coupling as designed in
`memory-dag.md` is preserved unchanged.

### 3.3 The four Part 2 decisions

- **Hash boundary** (SHA-256 local content hash, Keccak only at the DAG-verification boundary):
  steelmanned against "just use Keccak everywhere for consistency" — rejected, because SHA-256
  is the faster, better-supported choice for a purely local, non-anchored content hash, and
  forcing Keccak into the hot path for every `store_memory` call to satisfy a boundary that
  doesn't exist yet (the DAG is unimplemented) is premature. Pinned in
  `docs/integrity/xibalba-graph-crypto-profile-v1.md`. This is the hardest of the four to change
  once real data accumulates, so it is pinned first and treated as load-bearing.
- **`derivation_family` vs. epistemic class**: steelmanned against "leave it as a placeholder
  until Phase 4 entity work needs it" — rejected, because every row written between now and
  Phase 4 would bake in the wrong semantics silently. Decision: `derivation_family` is repurposed
  as the epistemic-class column now (see `store.py` follow-up work), populated from an explicit
  caller-supplied value rather than defaulting to `source_id`.
- **Integrity DAG degraded-state disclosure**: not a judgment call, a factual constraint — see §4.
- **Build vs. adopt `hindsight`**: steelmanned against "adopt hindsight and skip building
  entirely" — rejected. `hindsight` (vendored Hermes plugin, knowledge graph + entity resolution +
  multi-strategy retrieval) has no concept of BCC/Merkle/append-only intent lineage, no
  profile-owned isolation matching this system's Hermes-profile model, no one-way DAG citation,
  and its default deployment mode is cloud-hosted rather than local-only. Those four gaps are the
  entire reason this project exists rather than a `hermes memory setup` command. `hindsight`
  remains worth revisiting as a *reference implementation* for entity-resolution quality once
  Xibalba's own entity graph (Phase 4) ships, not as a replacement.

### 3.4 PostgreSQL-as-canonical vs. SQLite

Covered in §1 with benchmark numbers attached. Decision: SQLite, revisit only on a concrete gap.
