# Cortex managed GraphStore on Supabase: design

**Status:** design proposal for the hosted managed edition; no schema or runtime
change is included here.  
**Authority:** operator direction is Supabase for the ecosystem backend. The
existing local operator edition remains SQLite-backed. This document scopes
the change to managed hosted tenants and does not reverse that local-store
decision.  
**Current blocker:** Render's live managed service still selects SQLite for
control storage and compatibility auth. Complete migration-plan gate A2 before
starting a hosted GraphStore cutover.

## Existing managed store and evidence boundaries

`ManagedControl.store()` creates one `GraphStore` database under
`CORTEX_MANAGED_HOME/tenants/<tenant-id>/graph-memory.sqlite3` per managed
tenant. Each database contains one `deployment_profile` row and uses the
tenant ID as its `profile_id`; that isolation currently comes from separate
files and server-side path validation. There is no `tenant_id` column in the
canonical SQLite rows.

`GraphStore` compound mutations use `_atomic_write` and SQLite transactions;
some compound operations explicitly use `BEGIN IMMEDIATE`. Its online backup
uses SQLite's backup API and reconciliation recomputes canonical Merkle roots
for memories, entities, and relations. Local SQLite also provides FTS5 and
`sqlite-vec`. These behaviors are requirements to preserve or replace with
equivalent evidence, not implementation details to silently discard.

The managed request surface currently calls `agent_workspaces`, `counts`,
`get_memory`, `graph_payload`, `has_agent_partition`,
`import_structured_bundle`, `ingest_agent_turn`, `list_memories`,
`list_sessions`, `search`, `storage_agent_id`, `store_memory`, and
`verify_chain`. This is the statically observed direct method set from the
managed package; finish the inventory by tracing delegated helpers and worker
entry points before finalizing the interface.

At the current managed construction site, inference and embedding features are
disabled. The managed package does not start a GraphStore background worker;
the repository's worker entry points open local `GraphStore` instances from
operator-supplied homes. Task, retry, embedding, and projection tables remain
part of the schema inventory for future managed use and faithful exports, but
moving worker execution into hosted service processes is a separate rollout
gate.

`GraphStore` also keeps an `identity_salt` file beside each database and uses it
to HMAC pseudonymous agent IDs. Hosted storage must preserve that pseudonym
stability across restarts. Decide whether the hosted profile uses a durable,
tenant-scoped secret stored outside Postgres or a versioned server-side key
derivation design. Never regenerate the salt on a normal start or put it in
the tenant data export as plaintext.

The existing operator edition has many direct `GraphStore` consumers outside
the managed API. It must retain the SQLite implementation and its path-based
behavior. The managed service must move behind a narrow store interface so
hosted requests stop constructing SQLite files while local callers continue
to use `GraphStore` unchanged.

## Canonical hosted data inventory

The current SQLite schema contains these durable domains. All tenant-owned
records must be explicitly scoped in the hosted schema, including operational
and integrity records that may look secondary.

| Domain | Current relations |
| --- | --- |
| Source and memory | `sources`, `memories`, `memory_events`, `contradictions`, `integrity_links` |
| Knowledge graph | `entities`, `entity_aliases`, `memory_entities`, `relations`, `meta_nodes`, `meta_edges` |
| Sessions and evidence | `sessions`, `otel_events`, `exchanges`, `exchange_memories`, `exchange_tool_calls`, `exchange_context_memories`, `decision_trace_events` |
| Inference and governance | `memory_inference_tasks`, `decision_trace_advisory_tasks`, `para_classifications`, `extraction_proposals`, `telemetry_event_dedupe`, `telemetry_health`, `agent_devices` |
| Attachments and vectors | `attachments`, `embeddings_meta`, `embedding_failures`, `embedding_models`, per-model vector relations |
| Retrieval and reconciliation | `retrieval_traces`, `projection_checkpoints`, `projection_reconciliations`, `backup_reconciliations` |
| SQLite-only bookkeeping | `schema_migrations`, `deployment_profile`, `memory_fts` virtual table |

`memory_fts` is a derived search index, not canonical evidence. Replace FTS5
with a Postgres full-text projection over canonical memory content; rebuild it
from `memories` and verify result behavior. Replace each `sqlite-vec` virtual
table with a tenant-scoped pgvector relation keyed by memory and model. Keep
`embeddings_meta` authoritative only for model/revision/hash metadata; vector
values remain a separately verifiable projection.

`attach_media()` writes content-addressed bytes beneath
`<GraphStore home>/blobs/sha256/<first-two-hash-chars>/<sha256>`, then records
that local path in `attachments.storage_locator` in the same operation as its
`attach_media` event. In managed hosting, the bytes therefore live beneath the
per-tenant local home and disappear with Render's ephemeral filesystem. The
target is a private Supabase Storage bucket with tenant-scoped paths, recorded
content hash and byte length, and a verification pass. A row copy alone does
not migrate attachment bytes. Keep `storage_locator` out of the canonical
evidence payload or define a path-independent locator before changing it.

## Target boundary and ownership

1. Keep the tables in a non-exposed `cortex` schema. Do not expose canonical
   memory, telemetry, inference, or integrity tables through the Supabase Data
   API. Browser clients use Supabase Auth; all GraphStore reads and writes go
   through the Cortex server.
2. Resolve each request's verified Supabase subject through the existing
   `cortex.tenant_memberships` authorization mapping. Derive `tenant_id` on
   the server. Never accept tenant ownership from request JSON, user-editable
   metadata, or an email match.
3. Add `tenant_id` to every tenant-owned relation. Use tenant-aware foreign
   keys and uniqueness constraints (for example `(tenant_id, id)` and
   `(tenant_id, source_id)`); make relationship columns carry the tenant key
   so the database itself rejects cross-tenant references.
4. Enable and force RLS for tenant-owned relations. Policies must compare the
   row's tenant key with a transaction-local tenant context set only after
   server-side membership validation. Revoke `anon` and `authenticated`
   access to the `cortex` schema and grant no direct client write path.
5. Give the Cortex runtime a dedicated least-privilege database role, separate
   from the migration owner. Do not use a Supabase service-role/secret key in a
   browser. Runtime role grants should cover only required operations and
   tables. Confirm how the selected Supabase connection role interacts with
   RLS before implementation; a superuser or `BYPASSRLS` connection would make
   the policies ineffective as a guard against application query mistakes.
6. Keep billing, account identity mapping, and GraphStore records in their
   respective existing domains. Supabase Auth subject identity is not a
   substitute for product tenant membership or agent-level visibility.
7. Preserve the existing agent-scope rules inside each tenant: blank
   `agent_id` is intentionally shared, while a non-empty `agent_id` is private
   to that agent. Tenant RLS alone does not implement this second authorization
   layer; query filters and relationship checks must preserve it.

RLS is defense in depth for the trusted Cortex server. Because the server role
sets tenant context, it is not a boundary against a compromised server
credential. The API must continue to authenticate and authorize before opening
the store, and no SQL path may derive the tenant from an untrusted client
parameter.

## Data types, indexes, and transaction behavior

- Preserve existing opaque text IDs in the first migration to avoid changing
  canonical hashes and public references. Use `timestamptz` for new timestamp
  columns; retain existing serialized timestamps until a separately reviewed
  canonicalization change is justified.
- Store structured JSON as `jsonb` where the application needs structured
  querying; do not rewrite canonical hash inputs as a side effect. The bytes
  used for content and event hashes must remain exactly defined by the current
  canonical JSON profile.
- Use `bytea` only where binary evidence belongs in Postgres. Prefer private
  Supabase Storage for attachment bytes and verify the object against the
  database hash.
- Preserve explicit `CHECK`, `UNIQUE`, and foreign-key semantics from SQLite.
  Add indexes for tenant-qualified foreign keys and observed query prefixes;
  validate representative plans before rollout. Avoid one-table-per-tenant
  schemas or dynamic table names.
- Preserve atomicity for memory creation plus source/event/graph relations and
  for exchange creation plus its memory/tool/context links. These operations
  must commit as one short Postgres transaction. Do not hold a transaction
  open across embedding generation, model calls, object storage, or network
  requests.
- Replace SQLite's one-writer process lock and `BEGIN IMMEDIATE` capacity
  guard with database transactions and explicit concurrency control. Enforce
  quotas atomically per tenant, using a tenant-scoped row lock or a conditional
  counter update; do not assume application-process locks coordinate Render
  instances.
- The current Render service does not support IPv6. Supabase direct Postgres
  endpoints on the Free plan require IPv6, so the deployment must use an IPv4
  shared-pooler endpoint unless the Supabase project has an IPv4 add-on. Start
  with the session pooler for this persistent Render service. Evaluate the
  transaction pooler only after configuring psycopg for its limits (including
  prepared statements and transaction-local session state) and measuring the
  current connect-per-store-operation pattern. Size connections against the
  Render instance/worker count and Supabase database limits. Keep migrations
  and long-running reconciliation jobs off the request connection path.

## Integrity, search, and background work

- Keep `memory_events.node_id`, parent links, exchange-chain nodes, decision
  trace hashes, content hashes, and Merkle leaf ordering as canonical evidence.
  Recompute and compare these values after import; a successful SQL insert is
  not integrity verification.
- Continue treating FTS and vector indexes as rebuildable projections. Record
  model key, revision, dimension, distance metric, and source content hash;
  verify vector count and dimensions before enabling vector reads.
- Keep inference and advisory tasks tenant-scoped. Claim work with a bounded
  lease and `FOR UPDATE SKIP LOCKED` or an equivalent atomic claim operation;
  make completion idempotent and verify the input snapshot hash before writing
  derived records.
- Preserve telemetry dedupe keys and ordering semantics within a tenant.
  Ensure retention and deletion behavior cannot cross a tenant boundary.

## Migration, reconciliation, and rollback

The accepted recreation of old profiles applies to the current ephemeral
pilot. It does not remove the requirements for a safe tenant migration path.

1. Freeze and version the source SQLite schema/canonicalization for the export.
   Use SQLite's online backup API, not a raw file copy. Record tenant ID,
   schema version, canonicalization version, export time, row counts, and
   per-domain Merkle roots in a manifest.
2. Export each canonical table in deterministic key order to a versioned,
   checksummed format. Exclude derived FTS/vector projections from canonical
   comparison, but include their source metadata and rebuild them after import.
   Include attachment objects and verify each hash/length.
3. Implement preview and idempotent apply. Import by dependency order in bounded
   batches, use tenant-scoped conflict keys, and never silently overwrite a
   row whose canonical hash differs. Persist batch progress and source
   manifest identity.
4. Reconcile every canonical table's count and deterministic row hashes;
   recompute memory and exchange chains, graph relationships, tenant-qualified
   foreign keys, attachment hashes, and projection metadata. Emit a signed or
   otherwise tamper-evident receipt with the source and target roots.
5. Keep source exports immutable until the operator accepts reconciliation.
   Cut over one tenant at a time behind an explicit backend flag. Before
   enabling writes, verify reads and authorization against the target.
6. Rollback before target writes by switching the tenant's backend flag back
   to its unchanged SQLite source. After target writes begin, stop writes,
   export the Postgres tenant snapshot through the same manifest format,
   import it into a fresh SQLite store, reconcile roots, and only then switch
   back. Do not point a live tenant at a stale SQLite snapshot and discard
   post-cutover writes.
7. Retain audit logs, migration manifests, and batch receipts. Rollback must
   never delete Auth users, memberships, canonical rows, or source backups.

## Required implementation gates

- Inventory exact schema migration versions, dynamic vector model tables,
  attachment byte paths, every managed route/worker, and the full set of
  `GraphStore` methods used by managed hosting.
- Define and review the store interface and table-by-table Postgres mapping.
- Implement migrations with RLS, grants, tenant-aware constraints, and a
  dedicated runtime role; inspect policies and grants from the live catalog.
- Implement the Postgres store and parity coverage for canonical writes,
  reads, idempotency, quota races, graph queries, events, task claiming,
  deletion, full-text search, vector search, backup/export, and reconciliation.
- Add preview/apply/reconcile/rollback tooling and exercise it on a disposable
  Supabase project before production tenants.
- Only claim the hosted GraphStore migration after production readiness,
  durable attachment handling, restart survival, and a tenant-level rollback
  drill are verified.

## Superseding context

`docs/architecture/advanced-memory.md` records SQLite as canonical for the
single-operator local deployment after a measured SQLite/DuckDB comparison.
That result remains valid for local Cortex. The operator's later ecosystem
direction selects Supabase as the hosted backend; this proposal therefore
keeps the local SQLite authority and defines a separate Postgres-backed
managed store. The prior benchmark did not measure PostgreSQL, so it is not
evidence that the hosted Postgres design meets production latency or cost
targets. Benchmark that workload before production rollout.

## Platform references checked for this proposal

- [Supabase Postgres connection methods and IPv4/IPv6 support](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase connection pooling and limits](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits)
- [Supabase Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Render IPv6 networking note](https://render.com/docs/troubleshooting-deploys)
- [Supabase changelog](https://supabase.com/changelog): reviewed current database changes; the API table auto-exposure change is avoided by keeping canonical GraphStore tables in a non-exposed schema.
