# Xibalba Cortex — Specification v1

Status: normative v1 plus additive hybrid extensions, 2026-08-13. This is the authoritative reference for this project — where
this document and any other doc under `docs/` disagree, this document wins, and the other
document should be corrected. Supersedes scattered decisions across
`docs/archive/2026-08-06/2026-08-05-xibalba-cortex.md`, `docs/plans/2026-08-05-xibalba-advanced-memory.md`,
`docs/architecture/advanced-memory.md`, `docs/architecture/event-hash-chain.md`, and
`docs/integrity/xibalba-cortex-crypto-profile-v1.md`, which remain as historical design records.
For the narrative of how the Integrity Protocol coupling decisions in section 6 were reached —
including two corrected mistakes worth reading before extending that section — see
`docs/session-log/2026-08-05-integrity-coupling-session.md`.

> **Audit status — 2026-08-06:** Current implementation and verification are tracked in [`docs/audits/2026-08-06-status.md`](../docs/audits/2026-08-06-status.md). The normative model remains authoritative for intended behavior; the audit ledger distinguishes implemented, partial, planned, blocked, and unverified work. The active local worktree contains uncommitted runtime/controller/viewer changes that require separate review before they become a default-branch capability claim.

## 1. Purpose and scope

A local, single-user, provenance-aware memory system for Hermes Agent, exposed as a Model
Context Protocol (MCP) server. It provides recall (semantic + lexical retrieval over an agent's
own history) and a typed entity/relationship graph, while keeping every stored fact traceable to
its source and every historical revision inspectable rather than silently overwritten.

**In scope:** local storage, provenance, lexical + vector recall, entity/relationship graph,
supersession/contradiction/forgetting lifecycle, local tamper-evident history (event hash
chain), one-way citation into the Integrity Protocol's Memory DAG when it exists.

**Out of scope for frozen v1:** multi-tenant serving, the Integrity Protocol's on-chain anchoring mechanism itself (consumed, not implemented, here), and replacing Supermemory without a measured shadow period.

**Additive hybrid scope:** Cortex may be configured as local-only or hybrid. SQLite remains the canonical evidence store. Native agent harnesses perform extraction and inference through the queue contract. Local embedding workers produce versioned vector projections. Remote inference, vector, reranking, backup, or synchronization providers are optional, rebuildable projections or explicitly configured fallbacks; they are never canonical writers.

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

### 3.3 Configurable provider boundary

Provider selection is configuration, not storage authority. The implementation must expose additive provider contracts for inference, embeddings, retrieval, and optional projections without changing frozen v1 MCP tool semantics.

The supported posture is:

| Mode | Inference | Embeddings | Canonical store |
|---|---|---|---|
| `local` | native agent harness through the local MCP queue | local model worker | profile-local SQLite |
| `hybrid` | native harness or explicitly configured fallback | local model worker, optional remote projection | profile-local SQLite |
| `remote-inference` | explicitly configured remote provider | local model worker by default | profile-local SQLite |

A provider may return a result or a degraded/unavailable state. It must not bypass source-hash validation, profile isolation, append-only writes, task ownership, or promotion policy. Remote projections must be rebuildable from canonical tables and reconciled by content hash and Merkle checkpoints before they are used for retrieval.

Configuration precedence is built-in defaults, profile configuration, environment overrides, command-line overrides, then task-scoped provider selection. Effective configuration must be inspectable with secrets redacted. No provider credential, token, or connection string belongs in the SQLite database or graph-memory content.

### 3.5 Native-harness inference boundary

Cortex does not embed a language model in the deterministic MCP server. It queues typed tasks whose evidence scope, subject, source-content snapshot hash, output schema, promotion policy, and retry policy are explicit. A native agent harness claims a task, reads only the permitted evidence, emits schema-valid JSON, and completes through the queue API. Extraction, entity resolution, contradiction detection, summarization, PARA classification, and consolidation are derived proposals until an explicit acceptance policy applies them.

At-least-once task recovery is permitted; exactly-once model execution is not claimed. Derived writes must therefore be idempotent and source-hash guarded.

### 3.6 Local embedding boundary

Embedding generation is performed by a bounded, short-lived local worker rather than the always-on MCP server. Each vector is associated with model identifier, revision, dimension, normalization, distance metric, worker version, and the source memory content hash. Wrong dimensions, non-finite values, and zero-norm vectors are rejected before persistence. A model change creates a new versioned vector projection; vectors from incompatible spaces must never be silently mixed.

### 3.7 Merkle-root capabilities

Merkle roots and hash-chain heads may be used for local tamper-evident checkpoints, inclusion proofs, backup comparisons, projection reconciliation, retrieval-trace citations, and derived-proposal evidence references. A root proves only the committed bytes and structure covered by its declared profile. It does not prove truth, completeness, authorization, identity ownership, external anchoring, or successful execution.

### 3.3 Deployment model

One profile-local SQLite file per Hermes profile, behind one MCP stdio server process
(`src/xibalba_cortex/server.py`). Network-reachable transports are optional adapters with their own authentication and loopback/TLS boundary; they do not change the canonical store. SQLite WAL provides concurrent readers and one writer, while MCP stdio serializes calls at the protocol layer before they reach the database. Storage path is always explicit and derived from the configured Hermes home (`hermes_home` kwarg convention used by Hermes memory-provider plugins) — never a hardcoded `~/.hermes` path.

## 4. Data model

Schema lives in `src/xibalba_cortex/store.py::_SCHEMA`. This section is the narrative reference;
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
profile's configured default changes. Set via `XIBALBA_CORTEX_IDENTITY_MODE` in
`mcp_servers.xibalba_cortex_memory.env`; surfaced at runtime via `memory_status`.

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

Default tier is set per-profile via `XIBALBA_CORTEX_RETENTION_TIER`
(`mcp_servers.xibalba_cortex_memory.env` in `~/.hermes/config.yaml`), overridable per session at
`memory_session_start`. `start_session` is idempotent — a reconnecting session keeps the tier
its first call declared, rather than silently changing mid-session.

### 4.9 OTel diagnostic mirror: `otel_events`

A local, private mirror of the Integrity Oracle's "unsigned_vendor" OTel evidence tier
(`otel_spans`/`otel_metrics`/`otel_logs`, `integrity-core/integrity-oracle/backend/migrations/`
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

**Correlation with memories (`prompt_id`, `memory_id`).** `sources.prompt_id` and
`otel_events.prompt_id`/`otel_events.memory_id` (added 2026-08-05) link a stored memory to the
OTel telemetry for the turn that produced it. Two link strengths:

- **Weak / automatic**: a memory's `source.prompt_id` matched against `otel_events.prompt_id`.
  This is Claude Code's own turn-correlation key — its real OTel documentation
  (`code.claude.com/docs/en/monitoring-usage`) states `prompt.id` is "a UUID v4 identifier
  linking all events produced while processing a single user prompt," present on
  `claude_code.user_prompt`, `claude_code.api_request`, and `claude_code.tool_result`. Passing
  the same value through both `memory_remember`'s `source.prompt_id` and
  `record_otel_batch`'s per-event `prompt_id` requires no new identifier scheme.
- **Strong / asserted**: `otel_events.memory_id`, an explicit foreign key, database-enforced —
  an unknown `memory_id` rejects the whole batch atomically (`sqlite3.IntegrityError`), not a
  silently-ignored row.

`memory_otel_events(memory_id)` returns the union of both, deduplicated. Before this existed,
`otel_events` and `memories` shared only `session_id` — correlated by coincidence of timing, not
by anything queryable per-turn. This closes that gap.

**Claude Code's real OTel surface** (verified against its own docs, not assumed): `record_otel_batch`
accepts these event names directly, no translation needed —

| Event | Kind | Carries LLM text? | Notes |
|---|---|---|---|
| `claude_code.user_prompt` | log | Yes — `prompt` attribute, **redacted by default** | Opt-in: `OTEL_LOG_USER_PROMPTS=1` |
| `claude_code.assistant_response` | log | Yes — `response` attribute, **redacted by default** | Opt-in: `OTEL_LOG_ASSISTANT_RESPONSES=1`; v2.1.193+ |
| `claude_code.api_request` | log | No | `model`, `cost_usd`, `duration_ms`, all 4 token-type counts, `request_id` |
| `claude_code.tool_result` | log | No (tool I/O opt-in separately) | `tool_name`, `success`, `duration_ms`; `tool_input`/`tool_parameters` behind `OTEL_LOG_TOOL_DETAILS=1` |
| `claude_code.token.usage` | metric | No | broken down by `type` (input/output/cacheRead/cacheCreation) |
| `claude_code.cost.usage` | metric | No | USD, per request |

`claude_code.user_prompt`/`claude_code.assistant_response` are the literal answer to "does this
system capture LLM text content as OTel telemetry" — they exist upstream, redacted by default
for privacy, and this store has no opinion on whether to enable the redaction-lifting env vars;
that's an operator/deployment decision, not something `xibalba-cortex` should default on
behalf of. Standard attributes present on every Claude Code event/metric —
`session.id`, `organization.id`, `user.account_uuid`, `user.id` (anonymous fallback),
`user.email` — are real identity data available for `source.agent_id` today, distinct from and
in addition to a `did:integrity:...` value.

### 4.10 Raw body ingestion (`raw_body_ingest`) — Path A of raw LLM text capture

`src/xibalba_cortex/raw_body_ingest.py` (console script
`xibalba-cortex-raw-ingest`) ingests the untruncated Anthropic Messages API
request/response bodies Claude Code writes to disk when configured with
`CLAUDE_CODE_ENABLE_TELEMETRY=1 OTEL_LOG_RAW_API_BODIES=file:<dir>` — the direct answer to
"capture raw LLM input and output text," verified against Claude Code's own documentation,
not assumed.

**Deliberately outside the MCP server.** This is push-based background capture (Claude Code
writes files on its own schedule), not agent-initiated action, so it runs as a separate
polling process (`--once` for a single scan, otherwise polls every `--poll-interval` seconds),
the same reasoning that keeps Path B (§4.9 addendum, not yet built) as its own component
rather than an MCP tool.

**What it captures, honestly, and what it can't yet:** each `<uuid>.request.json` ingests only
the *last* message in the array as a memory (the request body carries full conversation
history per Claude Code's docs; earlier turns were already ingested from their own prior
request file). Each `<request_id>.response.json` ingests its text content the same way,
reporting any non-text blocks (`tool_use`, etc.) as `skipped_blocks` rather than silently
dropping them unremarked. Both are stored with `status=candidate` (automatic content, per
security invariant 3, §7) and `message_id` set to the file-derived identifier.

**The pairing gap is real and stated, not hidden.** Request files are named by a fresh UUID;
response files by the Anthropic API's own `request_id` — different schemes, with no shared
key in the files or filenames alone. Every memory this ingests lands under a fixed synthetic
session (`raw-capture-unattributed`), not a real Claude Code session, because that attribution
genuinely isn't available without Path B's OTLP event stream (which carries both identifiers
via `client_request_id`/`request_id`). Path B, when built, is expected to retroactively
correlate these memories rather than requiring re-ingestion.

### 4.11 OTLP receiver (`otlp_receiver`) — Path B, two endpoints, two conventions

`src/xibalba_cortex/otlp_receiver.py` (console script `xibalba-cortex-otlp-receiver`) is
a minimal stdlib-only (`http.server`, no `opentelemetry-proto`/grpc dependency) HTTP receiver
serving two fixed OTLP paths on one port, each a genuinely different signal and convention:

**`/v1/logs` — Claude-Code-specific.** Enable with:

```
CLAUDE_CODE_ENABLE_TELEMETRY=1
OTEL_LOGS_EXPORTER=otlp
OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/json
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:4318/v1/logs
OTEL_LOG_USER_PROMPTS=1
OTEL_LOG_ASSISTANT_RESPONSES=1
```

Routes decoded log records by `eventName` (a real OTLP JSON top-level field per the spec,
confirmed before building against it — `otel.event.name` attribute as fallback for older
exporters): `claude_code.user_prompt`/`claude_code.assistant_response` (text-bearing) become
memories; `claude_code.api_request`/`claude_code.tool_result` (structured, no text) become
`otel_events` rows via the same `record_otel_batch` path §4.9 already defines. Redacted
prompts/responses (the `prompt`/`response` attribute absent when Claude Code's own redaction
defaults are active) are counted and skipped, never stored as an empty memory. Every event
carries `session.id`, `prompt.id`, and `message.uuid` — used directly for
`source.session_id`/`source.prompt_id`/`source.message_id`, giving these memories genuine
attribution `raw_body_ingest` structurally couldn't provide alone. `user.account_uuid`
(falling back to `user.id`) feeds `source.agent_id` through the existing `identity_mode`
pipeline (§4.1a).

**`/v1/traces` — the universal path, any vendor honoring the OpenTelemetry GenAI semantic
convention.** Verified against the live spec registry before building against it (`gen_ai.*`
attributes, CNCF-backed, exited experimental for client spans in early 2026) — confirmed that
Gemini CLI, OpenAI's Codex CLI, and Claude Code all support OTLP export, with `gen_ai.*` the
convention specifically designed to stay consistent regardless of vendor. `gen_ai.provider.name`
(`openai`, `anthropic`, `gcp.gemini`, ...) identifies which one produced a given span — one
receiver, many vendors, instead of a bespoke adapter per harness. This data rides on **spans**,
a different OTLP signal/payload shape than `/v1/logs` (`resourceSpans`/`scopeSpans`/`spans`,
not `resourceLogs`/`logRecords`) — a real structural difference, not a naming variation, so it
needed its own parser (`parse_otlp_spans_json`) rather than reusing the logs one.

`gen_ai.input.messages`/`gen_ai.output.messages`/`gen_ai.system_instructions` decode to
memories (role from the message; `system_instructions` as `role=system` — naturally deduped
against repeats via `find_memory_id_by_content`, since a static system prompt hashes
identically call after call). `tool_call`-type message parts become `otel_events`
(`kind=span`). `gen_ai.request.model`/`usage.input_tokens`/`usage.output_tokens`/
`response.finish_reasons`/`provider.name` become one `otel_events` row (`kind=log`,
`name="gen_ai.chat"`). The span's own `trace_id` doubles as `prompt_id` for exchange-building
compatibility — gen_ai spans don't carry a separate Claude-Code-style `prompt.id`, and
`trace_id` is the convention's own natural per-invocation correlation key, so reusing it avoids
inventing a second identifier scheme. Same content-hash dedup as `/v1/logs` and Path A/C: a
span describing text already captured elsewhere reuses that memory.

**Scope, stated plainly:** `/v1/metrics` (a third OTLP signal, `resourceMetrics`/`dataPoints`)
is handled by neither endpoint; `claude_code.token.usage`/`claude_code.cost.usage` still
require `memory_record_otel_batch` directly, unchanged from before this module existed.

**Hermes and OpenClaw, researched, not built against.** `~/.hermes/hermes-agent`'s own codebase
was checked directly for OTel instrumentation before assuming any — none found under that name;
Hermes's session/telemetry format, if adapted, would need its own schema inspection the same
way Claude Code's transcript format was (§4.13), not a guess. OpenClaw is a real meta-harness
(ACP-based) that runs Claude Code, Cursor, and Copilot as backends — when it runs Claude Code,
that constituent tool's own OTel export already flows through this receiver unchanged; OpenClaw's
own ACP-level activity is a separate protocol (Agent Client Protocol, not OTLP) and would need
its own adapter, not attempted here.

### 4.12 Cross-path deduplication and linkage (Path A ↔ Path B)

No separate backfill job — both paths dedupe against each other by content at ingestion time,
via `GraphStore.find_memory_id_by_content()`. Whichever path sees a given prompt/response text
*first* (in practice usually Path A, since raw body files are written synchronously while OTLP
export batches on a timer) creates the memory; whichever sees it *second* — with typically
richer attribution, since Path B always carries a real `session.id`/`prompt.id` — reuses the
existing memory rather than duplicating it, and links its richer telemetry to that memory via
`otel_events.memory_id`.

**This does not rewrite the original memory's own provenance**, deliberately, consistent with
`sources` being immutable everywhere else in this system: a memory first captured by Path A
keeps `source.session_id = raw-capture-unattributed` forever — an honest record of what was
knowable at the moment it was first observed, not silently corrected after the fact. What
changes is that `memory_otel_events(memory_id)` on that same memory now surfaces the real
session, `prompt_id`, and telemetry — discoverable through the evidence trail rather than by
mutating history. Two-pass processing inside `otlp_receiver.ingest_log_records` (text events
resolved before telemetry events) makes this correct regardless of record order within one
OTLP export batch, which is not a documented ordering guarantee.

### 4.13 Transcript ingestion (`transcript_ingest`) — Path C, the richest single source

`src/xibalba_cortex/transcript_ingest.py` (console script
`xibalba-cortex-transcript-ingest`) ingests Claude Code's own session transcript JSONL
(`~/.claude/projects/<project>/<session-uuid>.jsonl`) — schema verified by direct structural
inspection of real transcript files on this machine before building against it, not assumed
from documentation. This is the most complete of the three paths for "an entire session
including context window and tool calls," for three structural reasons Paths A/B don't share:

- **No env vars, no redaction.** Claude Code always writes these locally as part of normal
  operation; nothing needs to be opted into upstream, unlike `OTEL_LOG_USER_PROMPTS`/
  `OTEL_LOG_ASSISTANT_RESPONSES`/`OTEL_LOG_RAW_API_BODIES`.
- **Tool calls have an unambiguous correlation key.** A `tool_use` block's `id` matches its
  `tool_result` block's `tool_use_id` directly — no request-file-uuid-vs-response-file-
  request_id mismatch like Path A's. Both become `otel_events` (`kind=span`), sharing that id
  as `span_id`/`parent_span_id`, a real parent-child span pair.
- **Context window data is native, not inferred.** Every assistant record's `message.usage`
  (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_tokens`) becomes
  an `otel_events` row (`kind=metric`, `name="context_window.tokens"`) — the actual composition
  of the context window at that specific turn, not a session-level aggregate.

Routing: `user`-type records with plain-string content and `assistant`-type `text`/`thinking`
content blocks become memories (`thinking` tagged via `source.metadata.block_type` — genuine
reasoning trace, kept distinct from output text, not discarded). `tool_use`/`tool_result`
blocks and per-turn token usage become `otel_events`, never memories — consistent with every
other ingestion path's rule that structured/non-LLM-text data doesn't belong in `memories`.

**No content truncation cap, deliberately — unlike Path A's inherited 60KB OTel limit.** This
is local disk, not a network export; full fidelity is the actual point of this path. Revisit
only if disk usage becomes a measured problem, not preemptively.

**Incremental, not full-rescan.** Transcripts are append-only and can grow large;
`<home>/transcript_ingest_state.json` tracks a per-file line offset so repeated runs (e.g.
polling an in-progress session) only process newly appended lines.

**Deduplicates against Path A/Path B the same way they dedupe against each other** — via
`GraphStore.find_memory_id_by_content()`. Whichever path captures a given piece of text first
wins the memory row; later paths reuse it and attach their own evidence via `otel_events`
rather than creating a third copy.

### 4.14 Exchanges: a session's complete memory as a Merkle-chained sequence

Every ingestion path (explicit `memory_remember` calls, Path A/B/C) leaves a session's data as
memories and `otel_events` correlated by `session_id`/`prompt_id`/`memory_id` — queryable, but
still a flat set. `exchanges` (`GraphStore.record_exchange`/`get_exchange`/`session_exchanges`/
`verify_exchange_chain`, built automatically by `src/xibalba_cortex/exchange_builder.py`'s
`build_session_exchanges`) turns that into the session's actual turn-by-turn shape: one row per
prompt→response exchange, in order, each carrying its own prompt/response memories, linked
tool calls, context-window token usage, and optional explicit context contributions.

`GraphStore.record_model_exchange` is the preferred high-fidelity path for an agent harness: it
stores the user prompt, the full model response, and every supplied context contribution as
separate provenance-bearing memories, then appends the exchange. A context contribution may
reference an existing `memory_id` or supply fresh `content`; either way, the exchange records
`contribution_id`, `context_kind`, optional `relevance`, metadata, and the contributing memory's
content hash.

**The novel part, not just a view over existing tables:** each exchange is a node in a local
Merkle chain, the exact same content-addressed, backward-linked pattern already proven for
`memory_events` (§4.4) and explored for the Integrity Protocol's own Memory DAG — applied one
level up. `node_id = sha256(canonical({schema, session_id, sequence_number,
prompt_memory_ids, prompt_content_hashes, response_memory_ids, response_content_hashes,
tool_call_otel_event_ids, context_contributions?, parent_node_id}))`. `context_contributions` is
included only when present and commits to each contribution's memory id, content hash,
contribution id, kind, and relevance. `verify_exchange_chain` recomputes the whole sequence and
checks parent linkage — reordering, forging, dropping an exchange, or mutating a recorded
context contribution is detectable by recomputation alone, the same tamper-evidence guarantee
`verify_chain` gives a single memory's revision history, now covering a session's complete
structure. `session_merkle_root`/`memory_session_merkle_root` returns the current head node as
`root_node_id`, plus exchange count and verification state. This is a local, unanchored chain
(no on-chain commitment, no relationship to the Integrity Protocol's Memory DAG or TrustVault —
see §4.9's boundary, which applies here identically); its head `node_id` is structurally the
right shape to anchor later if that's ever wanted, but nothing does that today.

`session_merkle_evidence` and `GET /api/session/{id}/merkle-proof?index=` expose a separate
batch-inclusion profile identified as `xibalba.exchange_batch.merkle.v2`. Its leaf preimage is
`SHA-256("xibalba.exchange_batch.v2" || 0x00 || "leaf" || 0x00 || uint64be(index) ||
payload_hash)`. Internal sibling pairs retain the historical lexicographic ordering rule;
unpaired odd-width nodes are promoted unchanged; the final inner root is wrapped as
`SHA-256("xibalba.exchange_batch.v2" || 0x00 || "root" || 0x00 || inner_root)`. The proof JSON
contains `domain`, `index`, `payload_hash`, `siblings`, and `root`. Verifiers fail closed on
malformed input. Position commitment prevents permutation ambiguity, but the proof does not
authenticate the response envelope's `session_id` or `exchange_count` and therefore does not
prove chronology, completeness, truth, authorization, ownership, or external finality.

**Residual construction note (reviewed 2026-08-17, not fixed by design — see below).**
`merkle_parent`'s internal-node combination (`events.py`) carries no domain tag and no tree-level
marker, and the odd-width promotion above (`level[-1]` carried forward unhashed) is structurally
the same *shape* as Bitcoin's CVE-2012-2459 padding ambiguity: nothing in a promoted node's own
hash value distinguishes "this arrived via promotion" from "this is a genuine parent-combination
output." An adversarial review of a proposed fix (domain-tagging internal nodes + committing
leaf count into the wrapped root) found: (1) the disclosed ambiguity is **not practically
exploitable today**, because `verify_domain_merkle_proof` recomputes each leaf from its
committed `(domain, index, payload_hash)` via `domain_leaf`'s own "leaf" tag *before* any sibling
folding — an attacker cannot place a chosen value directly into leaf position, unlike Satoshi's
original bug where `hash(C,C)` was computable for free from public data with zero cryptographic
work. Reproducing an equivalent free collision here would require breaking SHA-256 preimage
resistance against a specific tagged target, not merely choosing convenient leaf content. (2) The
specific proposed fix was itself flawed — a domain tag on internal nodes provides cross-*domain*
separation, not the cross-*level* separation its own rationale claimed, since the preimage
carries no height. (3) A leaf-count commitment would force a breaking wire-format change to this
v2 profile (a new field in the proof JSON) plus a migration of the two OTHER domains that persist
their roots to storage (`projection_checkpoint` in `projection_checkpoints.root_hash`,
`retrieval_trace` in `retrieval_traces.root_hash`) — `reconcile_projection_checkpoint` would raise
an unhandled `ValueError` on every pre-existing checkpoint the moment `domain_merkle_root`'s
output changed, indistinguishable from real tampering, and `retrieval_trace_evidence` would
silently diverge from its own stored `root_hash` with no error at all. **Decision: left
unfixed.** If a future change bumps this construction anyway (e.g. adopting RFC 6962's
recursive-split tree, which needs no padding/promotion step and binds leaf count to shape
implicitly), do it as a deliberate v3 profile with an explicit migration plan for both persisted
root columns above — not as an in-place patch to `merkle_parent`.

**Grouping rule** (`build_session_exchanges`): a memory with `source.role == "user"` starts a
new exchange; everything after it (assistant text/thinking memories, tool calls, context-window
metrics correlated by `prompt_id` or `memory_id`) accumulates into that exchange until the next
`user`-role memory. Session summary memories (`evidence_class == "summary"`, written by
`end_session`) are excluded — a session-level artifact, not a turn. Not idempotent: call once
after a session's data is fully ingested, not on a poll loop — re-running duplicates every
exchange, since exchanges are derived from current data at call time, not tracked
incrementally like `transcript_ingest`'s line offset.

### 4.15 Hermes Observer adapter (`hermes_observer`) — Path D, native ingestion for the Hermes Agent

Paths A/B/C all capture Claude Code, which is instrumented with OTel. The Hermes Agent
(`~/.hermes/hermes-agent`) is not — confirmed by grepping its runtime code, not assumed — but
ships its own typed, in-process callback contract instead: "Observer Hooks"
(`telemetry_schema_version = "hermes.observer.v1"`, documented in
`~/.hermes/hermes-agent/docs/observability/README.md`, and already used by Hermes's bundled
NeMo Relay/Langfuse plugins via a `register(ctx)` / `ctx.register_hook(name, fn)` pattern).
`HermesObserverAdapter` (`src/xibalba_cortex/hermes_observer.py`) maps that contract onto the
same `GraphStore` API every other path uses — no new grouping logic, no new schema.

**Why this is a better fit than adding a fourth OTLP endpoint, not a fallback:** Hermes hooks
fire in-process with real typed correlation IDs already attached (`session_id`, `turn_id`,
`api_request_id`, `tool_call_id`) — no HTTP server, no OTLP JSON decoding, no redaction flags
to enable upstream. `turn_id` is reused as `prompt_id` the same way Claude Code's real
`prompt.id` (Path B `/v1/logs`) and a gen_ai span's own `trace_id` (Path B `/v1/traces`) are
reused rather than invented — `exchange_builder.build_session_exchanges` (§4.14) works
unmodified over Hermes-sourced sessions for the same reason it already works across A/B/C.

**Hook coverage — only the *_end/post_* member of each pre_*/post_* pair is mapped.** The
pre_* hook fires before the same data exists (a tool hasn't run yet, a response hasn't
arrived yet); instrumenting both would capture nothing additional twice, not more:

| Hermes hook | GraphStore call |
|---|---|
| `on_session_start` / `on_session_end` | `start_session` / `end_session` |
| `post_llm_call` | `store_memory` for `user_message` + `assistant_response`, each with `source.prompt_id = turn_id` |
| `post_api_request` | `otel_events`, `kind=log`, `name="hermes.api_request"` |
| `api_request_error` | `otel_events`, `kind=log`, `name="hermes.api_request_error"` |
| `post_tool_call` | `otel_events`, `kind=span`, `name=f"tool_call.{tool_name}"`, parented to `turn_id` |
| `post_approval_response` | `otel_events`, `kind=log`, `name="hermes.approval"` — a security-relevant decision, part of a session's complete memory, not just LLM output |
| `subagent_start` / `subagent_stop` | `otel_events` on the **parent** session, `kind=log` |

**Simplification, stated plainly, not silently:** `subagent_start`/`subagent_stop` do not build
a parent/child session schema (`sessions` has no parent-session foreign key today) — delegation
is recorded as an event on the parent session instead, with the child's ids carried in
`attributes`. Same content-hash dedup as A/B/C (`find_memory_id_by_content`): if Hermes and
Claude Code ever produce the same text (e.g. a shared subagent transcript), the second path to
see it reuses the existing memory rather than duplicating it, per §4.12's rule.

**Wiring is deliberately two separate steps.** This module is pure, dependency-free,
Hermes-independent, and lives in this repo like every other ingestion path. Actually registering
it as a running Hermes plugin means writing a `register(ctx)` shim and `plugin.yaml` into
`~/.hermes/hermes-agent/plugins/observability/xibalba_cortex_memory/` — a different project's
codebase — which is not done by this module and is a distinct, explicitly-flagged action, not
implied by building the adapter.

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
an instruction-injection pattern, overriding any caller-supplied `status`. `direct_user`,
`direct_model_response`, and `explicit_memory` source kinds are exempt (§7.1). Quarantined
content is excluded from `search` by the same status filter as `superseded`/`forgotten`.

### 5.5 Harness inference queue: `memory_inference_tasks`

Xibalba Cortex does not run an LLM in-process for summaries, metadata extraction, entity
extraction, relation extraction, contradiction detection, or consolidation. Instead,
`memory_inference_tasks` is a local queue for the user's agent harness. The store records the
subject (`memory`, `exchange`, `session`, or `context_bundle`), the task type, canonical JSON
input, lifecycle status (`pending`, `claimed`, `completed`, `failed`, `cancelled`), and
structured output/error.

The corresponding subagent contract is exposed by `memory_inference_subagent_manifest`: a
worker named `xibalba-memory-inference` claims tasks, reads only the explicit task input and
referenced memory evidence, returns structured JSON, and writes durable accepted facts through
normal memory tools (`memory_remember`, `memory_link_entities`, `memory_contradict`,
`memory_supersede`). This keeps the free local product deterministic and lightweight while
leaving a clean upgrade path for cloud inference that implements the same queue contract.

## 6. Cryptography

Full detail in `docs/integrity/xibalba-cortex-crypto-profile-v1.md`; summary below is binding.

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
`integrity-core` and neither is currently wired to `integrity_links` — this section states
precisely what each one is and isn't, after two successive corrections the same day this was
first written (full account in `docs/operations/resource-readiness.md`).

**`TrustVault`** (`integrity-sdk`'s `vault.py`, real, live, anchors on-chain for 7 registered
agents) covers commit/test-result evidence, domain-separated over `(kind, task_id, commit_sha,
test_result_hash, timestamp)`. A memory's `content_hash` has no matching `leaf_hash` there,
structurally — a memory was never the kind of thing that store records. `memory_vault_inspect`
(§10) reads it read-only for its own sake and cannot advance `integrity_links`.

**The Memory DAG** (`integrity-sdk`'s `memory_dag.py`, design in
`integrity-core/docs/design/memory-dag.md`) *is* designed to cover arbitrary content
(`NODE_KINDS` includes `"memory"`) and is the actual target `integrity_links` should eventually
cite. It was believed unimplemented; a Devil's Advocate review found and independently verified
otherwise — the code is complete (all seven design steps) and its test suite passes 21/21 as of
2026-08-05 (`INTERFACE_CONTRACT.md` §4.4b corrected to `[VERIFIED 2026-08-05]`). What remains is
integration, not implementation: `import_memory_dag.py --dry-run` has been run against the real
vault; the real import and on-chain anchoring are separate, not-yet-taken steps (anchoring is an
irreversible signed transaction). This system now has a read-only verifier for cited DAG node ids:
`GraphStore.verify_integrity_link`, `memory_verify_integrity_link`, and the operator
`verify-integrity-link` command compare a local memory's Keccak content hash against a real
`memory_nodes.jsonl` node and write the result to `integrity_links`.

Today this system can truthfully produce `unlinked`, `content_unavailable`,
`verification_failed`, and `hash_match_local`. `hash_match_local` means byte lineage only: the
cited DAG node exists and its `content_hash` equals the Keccak hash of the local memory content.
It does not prove truth, authorization, completeness, ancestry to a configured root, or on-chain
anchoring. `ancestry_verified` and `anchored_to_configured_root` remain schema-ready but have no
writer in this repository. Local chain integrity (§4.4, `verify_chain`) is a separate,
fully-functional capability that does not depend on any of the above — it proves this system's own
history is self-consistent, not that it is anchored on-chain.

### 6.4 Anchoring selection policy (for when the DAG exists)

Two-tier: always anchor `declared_intent` and `policy`-class memories (§4.2); randomly sample
the rest, to make the corpus spot-checkable and deter selective curation without paying to
immortalize every routine `observed_event`. Full rationale in the crypto profile doc's
"Anchoring selection policy" section.

## 7. Security invariants

Restated from `docs/archive/2026-08-06/2026-08-05-xibalba-cortex.md`, binding for every interface this
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

Implemented in `src/xibalba_cortex/server.py`, one tool per `GraphStore` public method, no
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
| `memory_otel_events` | `memory_otel_events` | Correlated telemetry for one memory — weak (`prompt_id`) + strong (`memory_id`) link, deduplicated (§4.9). |
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
| `memory_build_session_exchanges` | `exchange_builder.build_session_exchanges` | Not idempotent — call once per session after ingestion completes (§4.14). |
| `memory_record_model_exchange` | `record_model_exchange` | Preferred harness write path for prompt, full response, and explicit context contributions (§4.14). |
| `memory_session_exchanges` | `session_exchanges` | A session's complete memory, walked turn by turn. |
| `memory_session_merkle_root` | `session_merkle_root` | Current local exchange-chain root/head node (§4.14). |
| `memory_verify_exchange_chain` | `verify_exchange_chain` | Local Merkle-chain tamper-evidence over a session's exchange sequence — see §4.14 for what it does and doesn't prove (same boundary as §6.3). |
| `memory_inference_subagent_manifest` | static manifest | Harness-facing contract for the `xibalba-memory-inference` worker (§5.5). |
| `memory_request_inference` | `request_inference_task` | Queue a deterministic inference task for the user's harness or future cloud worker (§5.5). |
| `memory_inference_tasks` | `list_inference_tasks` | List queued/claimed/completed/failed tasks. |
| `memory_claim_inference_task` | `claim_inference_task` | Claim a pending task. |
| `memory_complete_inference_task` | `complete_inference_task` | Complete or fail a task with structured output/error. |

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
