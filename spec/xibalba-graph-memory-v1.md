# Xibalba Graph Memory — Specification v1

Status: normative, 2026-08-05. This is the authoritative reference for this project — where
this document and any other doc under `docs/` disagree, this document wins, and the other
document should be corrected. Supersedes scattered decisions across
`docs/plans/2026-08-05-xibalba-graph-memory.md`, `docs/plans/2026-08-05-xibalba-advanced-memory.md`,
`docs/architecture/advanced-memory.md`, `docs/architecture/event-hash-chain.md`, and
`docs/integrity/xibalba-graph-crypto-profile-v1.md`, which remain as historical design records.
For the narrative of how the Integrity Protocol coupling decisions in section 6 were reached —
including two corrected mistakes worth reading before extending that section — see
`docs/session-log/2026-08-05-integrity-coupling-session.md`.

## 1. Purpose and scope

A local, single-user, provenance-aware memory system for Hermes Agent, exposed as a Model
Context Protocol (MCP) server. It provides recall (semantic + lexical retrieval over an agent's
own history) and a typed entity/relationship graph, while keeping every stored fact traceable to
its source and every historical revision inspectable rather than silently overwritten.

**In scope:** local storage, provenance, lexical + vector recall, entity/relationship graph,
supersession/contradiction/forgetting lifecycle, local tamper-evident history (event hash
chain), one-way citation into the Integrity Protocol's Memory DAG when it exists.

**Out of scope:** multi-tenant serving, the Integrity Protocol's on-chain anchoring mechanism
itself (consumed, not implemented, here), running an LLM for extraction (the calling agent
extracts; this system stores, indexes, and retrieves), replacing Supermemory (coexists with it
during the shadow period defined in §9).

## 2. Non-negotiable design rules

Inherited from `docs/plans/2026-08-05-xibalba-advanced-memory.md` §0, restated here as binding:

1. A raw source episode is never replaced by an extracted fact, profile, summary, or reflection.
2. Valid time (when a proposition applies to the world) and transaction time (when this system
   recorded or changed its belief) are separate fields, never conflated.
3. Every derived fact, entity, edge, and relation carries typed evidence linking it to source.
4. `declared_intent`, `observed_event`, `extracted_proposition`, `inference`, `summary`, and
   `policy` are distinct epistemic classes (`memories.derivation_family`, §4.2). A memory's class
   must not be inferred from its content by a reader — it is recorded explicitly at write time.
5. A hash chain node id proves content identity and lineage. A BCC signature proves a key signed
   particular bytes. A Merkle proof proves inclusion under a root. None of these prove semantic
   truth, honesty, authorization, or completeness. Verification states must never be described in
   language that blurs this (§6.3).
6. Contradictions coexist. A contradicting memory does not delete or silently supersede the
   memory it conflicts with — see §5.4.
7. Retrieval results are untrusted evidence and cannot silently become instructions, system
   authority, or tool permissions (§7).
8. Ordinary writes are append-only. Corrections, supersessions, and forgetting are new events
   layered on top of history, never in-place mutation or row deletion (§5).
9. This system is a disposable-projection producer, never a canonical writer for a specialized
   graph or vector engine. If a future graph/vector engine is added, it is populated from this
   system, rebuildable, and never the source of truth (§3.2).

## 3. Architecture

### 3.1 Database: SQLite, canonical

SQLite (WAL, FTS5, `sqlite-vec` for the vector leg) is canonical, not a prototype awaiting
migration to PostgreSQL. This was a benchmark-gated decision, not a default: see
`docs/architecture/advanced-memory.md` §1 for the write-throughput/memory spike that decided it
(SQLite 1.5x faster, ~4x less resident memory than DuckDB for this system's actual single-row
transactional write pattern; PostgreSQL was not installed or benchmarked, since its stated
advantages — multi-tenant concurrency, Row-Level Security — don't apply to a single-user local
agent). Revisit only on a concrete capability gap, not on convenience or precedent.

### 3.2 Projections stay disposable

Any future specialized graph engine (e.g., LadybugDB, once mature — see §11) or vector engine is
populated from this system's canonical tables and is rebuildable from them. It is never a second
writer. This system's own `entities`/`relations` tables are themselves the graph; there is no
separate graph database in v1.

### 3.3 Deployment model

One profile-local SQLite file per Hermes profile, behind one MCP stdio server process
(`src/xibalba_graph/server.py`). No network listener, no concurrent-writer scenario to defend
against beyond what SQLite WAL already provides (concurrent readers, one writer), because MCP
stdio serializes calls at the protocol layer before they reach the database. Storage path is
always explicit and derived from the configured Hermes home (`hermes_home` kwarg convention used
by Hermes memory-provider plugins) — never a hardcoded `~/.hermes` path.

## 4. Data model

Schema lives in `src/xibalba_graph/store.py::_SCHEMA`. This section is the narrative reference;
the code is authoritative for exact column types and constraints.

### 4.1 Provenance: `sources`, `memories`

Every memory has exactly one `source` row recording where it came from (`kind`, `locator`,
`role`, `session_id`, `message_id`, `tool_name`, `observed_at`) and a `content_hash` (SHA-256,
see §6.1). `memories` holds the actual content, its own `content_hash`, `status` (§4.3),
`supersedes_id` (§5.1), `derivation_family` — the epistemic-class column (§4.2) — and an optional
`idempotency_key` for exactly-once writes under retry.

### 4.1a Agent identity capture (`sources.agent_id`, `identity_mode`)

A caller may pass `agent_id` in `source` (e.g. a DID, per the Integrity Protocol's `did:integrity:`
scheme). Whether and how it's persisted is governed by `GraphStore.identity_mode`, a
per-profile setting — privacy posture and compliance requirements vary by deployment, so this
is configurable, never hardcoded:

| Mode | Stored value | Use case |
|---|---|---|
| `full` | Raw `agent_id`, as given | Deployments that need to query/audit by exact agent identity |
| `pseudonymous` (default) | `"pseudonym:" + HMAC-SHA256(profile_salt, agent_id)` | Still lets you correlate "same agent produced these" without persisting who — the default because this system doesn't yet know its deployment's compliance posture |
| `omit` | `NULL`, regardless of what was passed | Deployments where agent identity must not be recorded at all |

`profile_salt` (`<home>/identity_salt`, 32 random bytes, `0600`) is generated once per profile
and never leaves it — pseudonyms are stable within a profile (same agent → same pseudonym,
enabling correlation) but **not correlatable across profiles** even for the same underlying
`agent_id`, verified by test (`test_identity_mode_pseudonymous_is_consistent_per_agent_and_profile_scoped`).
This is not a signing key and carries none of the "no key custody" concerns elsewhere in this
spec (§6.2) — it only needs to make pseudonyms unguessable, not authenticate anything.

The mode in effect is recorded per-row (`sources.identity_mode`) at write time, the same
audit pattern already used for `embedding_models`/`derivation_family` — so it's always
inspectable later which policy was active when a given memory was written, even after a
profile's configured default changes. Set via `XIBALBA_GRAPH_MEMORY_IDENTITY_MODE` in
`mcp_servers.xibalba_graph_memory.env`; surfaced at runtime via `memory_status`.

### 4.2 Epistemic class (`derivation_family`)

One of `declared_intent`, `observed_event` (default), `extracted_proposition`, `inference`,
`summary`, `policy`. Supplied explicitly by the caller at `store_memory` time via
`evidence_class`; never inferred from content. This is what the anchoring-selection policy
(§6.4) keys on once the Integrity DAG exists.

### 4.3 Lifecycle status

`candidate`, `active`, `confirmed`, `disputed`, `quarantined`, `superseded`, `forgotten`. Only
`active` and `confirmed` are recalled by default (`GraphStore.search`). Untrusted or
instruction-like content is force-quarantined at write time regardless of caller-supplied status
(§7.1).

### 4.4 Event hash chain: `memory_events`

Every state transition (`create`, `confirm`, `contradict`, `supersede`, `quarantine`, `forget`,
`restore`) is an immutable, hash-linked node — not just an audit-log row. Full mechanism and
rationale in `docs/architecture/event-hash-chain.md`; summary: `node_id = sha256(canonical({schema,
memory_id, event_type, detail, parent_event_id}))`, and `GraphStore.verify_chain(memory_id)`
recomputes the whole chain with zero external dependency. `memories.id` is the stable ref; the
event chain is the immutable object history behind it — the git object/ref split.

### 4.5 Entity graph: `entities`, `entity_aliases`, `relations`

Entities are resolved by `(normalized_name, entity_type)`, created conservatively on first
reference (`GraphStore._get_or_create_entity`). `relations` are typed, evidence-linked
(`evidence_memory_id` is required, not optional), subject→predicate→object triples where the
object is either another entity or a literal (mutually exclusive by constraint). Traversal
(`neighbors`, `find_path`) is bounded by `max_depth` (1–3 for neighbors, 1–5 for find_path) and
node/edge count caps, and reports `truncated: true` honestly rather than silently dropping
results.

### 4.6 Contradictions: `contradictions`

A separate, **non-hash-chained** table (`memory_id_a`, `memory_id_b`, `reason`). Deliberately
outside the event hash chain: `contradicts` is symmetric, not backward-in-time, and hashing it
into `parent_event_id` would break the chain's acyclic-by-construction property (§4.4, and
`docs/architecture/event-hash-chain.md` "What was deliberately kept out"). Recording a
contradiction also appends a `contradict` event to both memories' own chains for audit purposes,
but the relationship itself lives in this side table.

### 4.7 Integrity DAG citation: `integrity_links`

One row per memory, optionally pointing at an external Integrity DAG `node_id`, with
`verification_state` in `unlinked`, `hash_match_local`, `ancestry_verified`,
`anchored_to_configured_root`, `verification_failed`, `content_unavailable`. See §6.3 for which
of these states this system can actually produce today.

### 4.8 Sessions and retention tiers: `sessions`

A session (`start_session`/`end_session`/`session_memories`) groups memories written under one
`sources.session_id` and declares which write-pattern tier that session follows
(`sessions.retention_tier`). This answers a real deployment question: an operator with
resources to spare may want every token of every session preserved; an operator who only wants
intent, documents, and outcomes should get a small, cheap footprint instead. Both are the same
storage system — the difference is entirely in what the calling agent chooses to write, not in
a different code path.

**The tier is a declared contract, not enforced content.** This store has no LLM in-process
(§8, §1) and cannot judge whether an agent's writes actually match the tier it declared — the
same "extraction is agent-side" principle applied everywhere else in this system. Three tiers:

| Tier | What the calling agent writes | Storage shape |
|---|---|---|
| `verbatim` | One memory per turn/message, full fidelity | High volume, `observed_event` mostly, `status=candidate` unless confirmed |
| `synopsis` | A single running-summary memory, updated via `supersede_memory` as the session progresses | Low volume at any instant; full history still walkable via `memory_events`, only the current head is recalled by default |
| `digest` (default) | Only `declared_intent`, key `observed_event` outcomes, and attachments (documents produced); closed with a summary via `end_session` | Lowest volume — the footprint this spec's own default user wants |

Default tier is set per-profile via `XIBALBA_GRAPH_MEMORY_RETENTION_TIER`
(`mcp_servers.xibalba_graph_memory.env` in `~/.hermes/config.yaml`), overridable per session at
`memory_session_start`. `start_session` is idempotent — a reconnecting session keeps the tier
its first call declared, rather than silently changing mid-session.

### 4.9 OTel diagnostic mirror: `otel_events`

A local, private mirror of the Integrity Oracle's "unsigned_vendor" OTel evidence tier
(`otel_spans`/`otel_metrics`/`otel_logs`, `INTEGRITY-LATEST/integrity-oracle/backend/migrations/`
0004 and 0008) — same shape deliberately, so a caller already exporting OTel to the oracle can
pipe the identical batch here too with no translation. `record_otel_batch(external_session_id,
events)` ingests `{kind: "span"|"metric"|"log", name, ...}` rows against an existing session;
`session_otel_summary` returns counts by kind and metric totals summed by name (e.g. Claude
Code's own `claude_code.token.usage`/`claude_code.cost.usage` convention, if used — this store
has no OTel semantic-convention knowledge, it only sums by whatever name was given).

**This is not, and must never become, a path into the oracle's scored `telemetry_events`.**
That table is Ed25519/secp256k1-signed, nonce-replay-protected, and feeds AIS scoring directly
— its evidentiary weight comes specifically from third parties being able to trust it came from
the claimed agent, which requires the oracle's live, centrally-reachable, publicly-queryable
service. `otel_events` here is the opposite by design: private, local, unauthenticated,
never anchored, never scored, existing purely for the operator's own diagnostic querying,
independent of and additional to whatever the oracle centrally collects for protocol-wide
observability. See the session log referenced at the top of this document for the fuller
reasoning on why these must stay separate.

## 5. Lifecycle operations

### 5.1 Supersession

`supersede_memory(old_id, new_content, ...)` creates a new memory, marks the old one
`superseded`, sets the new memory's `supersedes_id` to the old id, and appends a `supersede`
event to the **old** memory's chain (not the new one's — the old memory's history records that it
was superseded; the new memory's own chain starts fresh with its own `create` event). Search
excludes `superseded` status by default, but the row and its full event history remain queryable
via `get_memory`/`memory_events` — nothing is deleted.

### 5.2 Contradiction

`mark_contradiction(id_a, id_b, reason)` records the relationship in both directions
(queryable via `contradictions(memory_id)` from either side) without changing either memory's
`status`. Per rule 6 (§2), contradiction is not resolution — an authority policy may later decide
which claim wins for current-state queries, but both remain in history.

### 5.3 Forgetting

`forget_memory(memory_id)` sets `status = 'forgotten'`, excludes the memory from `search`, and
returns `content_hash_retained: true` — the content hash is never purged, only the searchable
content's discoverability. This is what makes forgetting honest under rule 8 (§2): a residual
hash trace may exist wherever the memory was ever anchored (§6.4), and that must be disclosed,
not hidden, if this system ever exposes a "forgotten but the hash exists elsewhere" query.

### 5.4 Quarantine

Applied automatically at write time (`_quarantine_reasons`) when untrusted-source content matches
an instruction-injection pattern, overriding any caller-supplied `status`. `direct_user` and
`explicit_memory` source kinds are exempt (§7.1). Quarantined content is excluded from `search`
by the same status filter as `superseded`/`forgotten`.

## 6. Cryptography

Full detail in `docs/integrity/xibalba-graph-crypto-profile-v1.md`; summary below is binding.

### 6.1 Hash boundary

SHA-256 (`sha256:`-hex-prefixed) for all local content hashing (`sources.content_hash`,
`memories.content_hash`) and the event hash chain (§4.4). Keccak-256 only when comparing against
or computing a candidate for an external Integrity DAG `node_id` (§4.7). These two hash spaces
are never compared to each other directly or coerced from one to the other.

### 6.2 No key custody

This system never generates or stores a private key. `declared_intent`-class memories may carry
a caller-supplied, pre-signed BCC envelope; this system verifies signatures (public-key
operation) but never signs on an agent's behalf.

### 6.3 Verification states this system can actually produce (today)

`integrity_links.verification_state` enumerates six states. Two evidence stores exist in
`INTEGRITY-LATEST` and neither is currently wired to `integrity_links` — this section states
precisely what each one is and isn't, after two successive corrections the same day this was
first written (full account in `docs/operations/resource-readiness.md`).

**`TrustVault`** (`integrity-sdk`'s `vault.py`, real, live, anchors on-chain for 7 registered
agents) covers commit/test-result evidence, domain-separated over `(kind, task_id, commit_sha,
test_result_hash, timestamp)`. A memory's `content_hash` has no matching `leaf_hash` there,
structurally — a memory was never the kind of thing that store records. `memory_vault_inspect`
(§10) reads it read-only for its own sake and cannot advance `integrity_links`.

**The Memory DAG** (`integrity-sdk`'s `memory_dag.py`, design in
`INTEGRITY-LATEST/docs/design/memory-dag.md`) *is* designed to cover arbitrary content
(`NODE_KINDS` includes `"memory"`) and is the actual target `integrity_links` should eventually
cite. It was believed unimplemented; a Devil's Advocate review found and independently verified
otherwise — the code is complete (all seven design steps) and its test suite passes 21/21 as of
2026-08-05 (`INTERFACE_CONTRACT.md` §4.4b corrected to `[VERIFIED 2026-08-05]`). What remains is
integration, not implementation: `import_memory_dag.py --dry-run` has been run against the real
vault; the real import and on-chain anchoring are separate, not-yet-taken steps (anchoring is an
irreversible signed transaction); and this system's own `integrity_links` writer/reader against
DAG node ids does not exist yet.

Until that integration exists, this system can only truthfully produce `unlinked` or
`content_unavailable`. `hash_match_local`, `ancestry_verified`, and `anchored_to_configured_root`
are schema-ready with no writer. A `memory_verify` MCP tool must report this honestly, never
synthesize a plausible-looking but unearned verification result. Local chain integrity (§4.4,
`verify_chain`) is a separate, fully-functional capability that does not depend on any of the
above — it proves this system's own history is self-consistent, not that it is anchored on-chain.

### 6.4 Anchoring selection policy (for when the DAG exists)

Two-tier: always anchor `declared_intent` and `policy`-class memories (§4.2); randomly sample
the rest, to make the corpus spot-checkable and deter selective curation without paying to
immortalize every routine `observed_event`. Full rationale in the crypto profile doc's
"Anchoring selection policy" section.

## 7. Security invariants

Restated from `docs/plans/2026-08-05-xibalba-graph-memory.md`, binding for every interface this
system exposes (MCP, future REST, future CLI):

1. Recalled text is untrusted evidence and cannot override instructions. Any tool surfacing
   recalled memory content to an agent must present it as data, not as directives, regardless of
   what the content says.
2. Every memory revision has source provenance and a content hash — no anonymous writes.
3. Automatic or untrusted content starts `candidate` or `quarantined`; only `active`/`confirmed`
   are recalled by default.
4. Graph traversal is bounded by depth, node count, edge types, and timeout, and reports
   truncation honestly rather than silently dropping results.
5. Integrity status means byte integrity or lineage only, never factual truth (§2 rule 5, §6.3).
6. Storage paths are explicit and profile-scoped; no hardcoded shared path (§3.3).
7. Derived indexes (FTS, future vector index) are rebuildable from canonical tables; only source
   revisions and the event chain are authoritative.
8. Forgetting propagates to searchability honestly and discloses residual hash traces rather than
   claiming complete erasure (§5.3).

## 8. Retrieval (current vs. planned)

**Implemented (v1):** FTS5 lexical search, status-filtered, BM25-ranked. `sqlite-vec` dense
retrieval leg (`memory_vectors`, a `vec0` virtual table pinned to `BAAI/bge-small-en-v1.5`,
384-dim — see `docs/architecture/embedding-model-spike.md`), fused with the lexical channel via
Reciprocal Rank Fusion (k=60) when a caller supplies a query vector (`GraphStore.search`). This
system never computes embeddings itself: the embedding-model spike found the model fast enough
(77 embeds/sec) but too memory-heavy (~270MB resident) to keep always-loaded inside this
always-on server on this machine's actual free RAM, so vectors are always caller-supplied
(`store_embedding`) and a `model_id`/dimension mismatch is rejected outright, never silently
tolerated.

**Planned, not yet built:** entity/graph-neighborhood expansion of top recall hits, temporal
pre-filtering, local cross-encoder reranking. Tracked but not committed to a phase number here to
avoid the two-plan scope drift this spec is meant to end.

## 9. Relationship to other systems

- **Supermemory:** remains Hermes's active automatic `memory.provider` throughout v1. This
  system is reached only through explicit MCP tool calls, never automatically. No shadow-mode
  comparison or provider-replacement decision is in scope for v1 — see §11 for what would need
  to be true first.
- **`hindsight` (vendored Hermes plugin):** evaluated and not adopted in place of this system —
  full reasoning in `docs/architecture/advanced-memory.md` §3.3. Worth revisiting as a reference
  implementation for entity-resolution quality once this system's own entity graph matures, not
  as a replacement.
- **Integrity Protocol Memory DAG:** one-way citation only. This system may record a DAG
  `node_id`; the DAG never depends on this system. See §4.7, §6.3.

## 10. MCP tool surface (v1)

Implemented in `src/xibalba_graph/server.py`, one tool per `GraphStore` public method, no
tool bypasses profile authorization or the append-only write model:

| Tool | Maps to | Notes |
|---|---|---|
| `memory_remember` | `store_memory` | `source` is a required object (`kind` required within it). |
| `memory_recall` | `search` | Lexical-only unless `query_vector` supplied; then RRF-fused (§8). |
| `memory_embed` | `store_embedding` | Caller-computed vector only — never generated in-process (§8). |
| `memory_attach` | `attach_media` | Content-addressed blob storage, not a SQLite BLOB; not yet searchable (§8). |
| `memory_list_attachments` | `list_attachments` | |
| `memory_session_start` | `start_session` | Idempotent; declares the retention tier (§4.8). |
| `memory_session_end` | `end_session` | Optional closing summary memory. |
| `memory_session_get` | `get_session` | |
| `memory_session_memories` | `session_memories` | |
| `memory_record_otel_batch` | `record_otel_batch` | Local diagnostic mirror only — never the oracle's scored path (§4.9). |
| `memory_session_otel_summary` | `session_otel_summary` | |
| `memory_get` | `get_memory` | |
| `memory_supersede` | `supersede_memory` | |
| `memory_contradict` | `mark_contradiction` | |
| `memory_contradictions` | `contradictions` | |
| `memory_forget` | `forget_memory` | |
| `memory_link_entities` | `link_entities` | |
| `memory_neighbors` | `neighbors` | |
| `memory_find_path` | `find_path` | |
| `memory_events` | `memory_events` | Exposes the hash chain (`node_id`/`parent_event_id`) for external audit. |
| `memory_verify_chain` | `verify_chain` | Local chain integrity only — see §6.3 for what it does *not* prove. |
| `memory_status` | `status` | Schema version, WAL/FTS5/foreign-key/integrity-check status. |
| `memory_backup` | `backup` | Online, verified, non-destructive to the live store — safe to expose without gating. |

`GraphStore.restore()` exists and is tested (verifies the source's `integrity_check` before
touching the live database, refuses corrupt input) but is **deliberately not exposed as an MCP
tool** in v1 — it overwrites the live database, and this server has no approval-gating mechanism
yet to guard a call that destructive. This is the distinction the spec draws between "capability
implemented" and "tool surface exposed": building the capability first and gating the surface
deliberately, not silently shipping a destructive tool because the underlying code exists.

Remaining approval-gated administrative tools (`memory_consolidate`, `memory_export`,
`memory_hard_purge`, `memory_anchor`) are out of scope for v1 — no consolidation, hard-purge, or
anchoring capability exists yet to gate.

## 11. What would need to be true before this replaces Supermemory

Not attempted in v1; recorded so the bar is explicit rather than discovered ad hoc later:

- The `sqlite-vec` retrieval leg is wired in and measured against a hand-labelled recall set.
- A shadow-comparison period runs with Supermemory still active and automatic.
- The Integrity DAG exists and `hash_match_local`/`ancestry_verified` are real, not aspirational.
- A Hermes `MemoryProvider` adapter (`agent/memory_provider.py` ABC) is implemented and reviewed
  — per the Hermes plugin architecture's single-provider rule, this system cannot become the
  active provider alongside Supermemory; it must replace it, which is exactly why this is gated
  behind a deliberate review rather than a config flip.

## 12. Versioning

This is v1. Breaking schema changes (column removal, hash-boundary changes, event-node shape
changes) require a new spec version and an explicit migration note — never a silent edit to this
document that changes what already-hashed data means.
