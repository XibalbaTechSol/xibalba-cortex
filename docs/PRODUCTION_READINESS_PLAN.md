# Xibalba Cortex Production-Readiness Plan

**Status:** Active implementation baseline; profile-bound bearer authorization is locally implemented, no SaaS tenant lifecycle
**Updated:** 2026-09-03
**Target:** Multi-tenant AI-memory SaaS built on the existing hash-chained MCP server

## 1. Executive decision

Cortex should be advanced as a **multi-tenant AI-memory SaaS**, not just a local MCP
server. The near-term target is a controlled pilot with a small number of real external
tenants, not a claim of finished enterprise-scale infrastructure.

The current implementation is close to a pilot in several areas: the 79-tool MCP
surface (server.py), hash-chained event storage with domain-separated Merkle roots
(store.py), hybrid (lexical + vector + graph + temporal) retrieval with trace
inspection, proposal-gated extraction, and five of seven ingestion connectors. It is not
yet production-ready because multi-tenant authorization is unimplemented, the storage
layer has no verified multi-tenant isolation or HA story, standalone installability is
blocked on a dependency this repo does not control, and no adversarial or real-customer
evaluation has been run.

Production readiness is an evidence threshold, not a code-complete claim. This plan
treats the live `xibalba-cortex-operator production-readiness` gate report as the source
of truth for current state, re-run and re-verified before any status claim below is
finalized (see §9).

## 2. Readiness levels

### L0 — Research / pre-alpha (current baseline)

- Local, single-operator MCP server (stdio or streamable-HTTP), SQLite storage,
  `~/.hermes/xibalba-cortex`, no containerization.
- 79-tool MCP surface, frozen core schema/hash-chain/tool contract per
  `spec/xibalba-cortex-v1.md` (v1, frozen 2026-08-12).
- Hybrid retrieval and proposal-gated extraction both real and tested.
- `authorization_tenancy` reports **blocked** (0 active, unexpired bearer tokens issued) in the
  live operator readiness gate. Profile binding, role/scope enforcement, revocation, expiry,
  and rate limiting are implemented and locally tested; a real onboarding path and a second
  isolated tenant store are not yet deployed.
- Not installable standalone: `pyproject.toml` pins `integrity-sdk` as a local path
  dependency on a sibling `integrity-core` checkout; `uv sync` fails outside that
  layout. This is an external dependency on `integrity-core`'s own production plan
  (see that repo's Backbone Contract section).

### L1 — Controlled multi-tenant pilot

Exit requires all of the following:

- Real bearer-token issuance and enforcement wired into a genuine onboarding path
  (`xibalba-cortex-ingest-tokens` exists as a CLI primitive; nothing calls it as part of
  a tenant lifecycle today).
- A verified multi-tenant data model: per-tenant partitioning in the store, and an
  adversarial test proving tenant A cannot read, recall, or influence extraction for
  tenant B.
- Standalone installability: `integrity-sdk` resolvable via a real published package,
  not a local path — see `integrity-core`'s Backbone Contract.
- Connector productionization for every connector marked `implemented` in the readiness
  gate (`claude_transcripts`, `codex_mcp`, `hermes_sessions`, `integrity_wiki`, `otel`,
  `webhook`): rate limiting, retry/backoff, and per-tenant credential custody, none of
  which exist today.
- The synthetic evaluation gate (`xibalba.evaluation_benchmark.v1`) passing against
  real, multi-tenant traffic patterns rather than only the synthetic dataset — the gate
  already reports `passed: true` but `pilot_ready: false` on synthetic data alone.
- Backup/restore verified per tenant, not just at the single-database level currently
  exercised by the operator's `backup`/`restore` commands.

### L2 — Hardened multi-tenant production

L2 adds a storage backend decision made explicitly (SQLite is `ready` for a single
instance; a real SaaS HA/PITR story is a genuine open architectural question, not
assumed to be Postgres by default), governance/provenance export promoted from
`local_only` to an auditable per-tenant export path, inference-task reliability
(`inference_reliability`, currently `local_only`) proven under real concurrent tenant
load, RBAC for administrative operations, and independent adversarial review of the
extraction-proposal review gate (the one safety control standing between raw ingested
content and the graph).

### L3 — Ecosystem expansion

Google Drive connector promoted out of `optional_dependency`, additional connectors,
and any Tier-3/cloud-inference expansion beyond today's local/hybrid/remote-inference
modes are separate deliverables, not implied by an L1/L2 pilot.

## 3. Invariants

These invariants govern design and acceptance, made explicit from what is already true
in the codebase and CLAUDE.md rather than newly invented:

1. Recalled memory is context, never instruction authority — a caller must preserve
   provenance and lifecycle state in any downstream prompt; retrieval results do not
   carry implicit command weight.
2. Extraction is proposal-only. Entity/relationship extraction never writes directly to
   the graph; every extracted candidate passes through
   `memory_claim_inference_task` → `memory_complete_inference_task` and an explicit
   accept/reject decision before it exists as a graph edge.
3. Every memory write is an append-only, hash-chained event; domain-separated Merkle
   roots let a caller verify a subset of the graph without the whole chain. Nothing in
   this system may rewrite or silently drop a committed event.
4. "No silent mocks": any module that is not fully working must say so in its own
   docstring/README rather than imply completeness — the same rule this repo inherits
   from `integrity-core` and that Shield also follows.
5. The frozen v1 schema/hash-chain/tool contract (`spec/xibalba-cortex-v1.md`) does not
   change without updating the spec in the same change; new tools are additive.
6. A tenant's data, credentials, and extraction proposals are isolated from every other
   tenant — currently aspirational (see L1), stated here as the acceptance bar for
   calling the tenancy gap closed.

## 4. Workstreams

### A. Multi-tenant authorization

Close the `authorization_tenancy: blocked` state: profile-bound bearer enforcement,
role/scope checks, revocation, expiry, and per-principal rate limiting are implemented.
The local `xibalba-cortex-tenant-onboard` flow now provisions a profile-bound store,
configuration, finite-lived operator token, and quota. Adversarial tests verify separate profiles
cannot read memories or inference tasks across the boundary. The remaining work is a live
issue/verify/rotate/revoke drill and deployment of two real pilot profiles.

**Deliverable:** a tenant can self-provision a scoped bearer token and have it enforced
on every MCP call, verified by a test that a revoked/expired token is rejected.

### B. Standalone installability

Remove the local-path `integrity-sdk` dependency currently blocking `uv sync` outside a
sibling-checkout monorepo layout. This is not closable inside this repo alone — it
requires `integrity-core` to publish `integrity-sdk` as a real installable package (see
that repo's Backbone Contract section, and its currently `0.1.0`/alpha, unpublished
status).

**Deliverable:** `uv sync` succeeds against a released `integrity-sdk` version pin, from
a clean checkout with no sibling `integrity-core` directory present.

### C. Storage and high availability

SQLite is reported `ready` for the current single-instance deployment. This is not a
placeholder to silently outgrow — the next real decision is an explicit architecture
choice (managed Postgres, a hosted SQLite-compatible service, or continued SQLite with a
documented single-writer ceiling) made and recorded, not assumed. Whatever is chosen
must support per-tenant backup/restore verification (extending the operator's existing
`backup`/`restore` commands, which today verify the whole store, not a tenant slice).

**Deliverable:** a written storage architecture decision record, plus a per-tenant
backup/restore drill that succeeds.

### D. Connector productionization

Five of seven connectors report `state: implemented` in the readiness gate
(`claude_transcripts`, `codex_mcp`, `hermes_sessions`, `integrity_wiki`, `otel`,
`webhook`); `google_drive` remains `optional_dependency`. "Implemented" today means
functionally correct in a single-tenant local deployment, not rate-limited, retried, or
credential-isolated per tenant — none of those exist yet for any connector.

**Deliverable:** each production-tier connector has documented rate limits, a
retry/backoff policy, and per-tenant credential storage that one tenant cannot read
another tenant's credentials through.

### E. Evaluation and quality gate

The synthetic quality gate (`xibalba.evaluation_benchmark.v1`, dataset
`synthetic-quality-gate-v1`) currently passes all 8 checks (contradictions, deletion
correctness, multi-hop relations, poisoning boundary, profile isolation, recovery
replay, retrieval provenance, temporal updates) but is explicitly self-reported
`pilot_ready: false` — the gate's own disclaimer states it is "not external provider,
SLA, compliance, or production pilot evidence." Closing this requires real
(non-synthetic) tenant data volume and adversarial extraction-poisoning tests beyond the
existing synthetic `poisoning_boundary` check.

**Deliverable:** the same evaluation harness run against a real pilot tenant's traffic,
with `pilot_ready` becoming a real (not aspirational) field.

### F. Governance and provenance

`governance` currently reports `state: local_only` with `provenance_export: true` —
export capability exists but nothing external consumes or verifies it yet. Define what
"production" governance means for a SaaS operator: audit log retention period, access
control on the export path, and a defined verification procedure a tenant or auditor
can actually run.

**Deliverable:** a documented, testable provenance-export verification procedure usable
by someone outside this repo's own operator tooling.

### G. Inference reliability under multi-tenant load

`inference_reliability` reports `local_only`, backed by "queue leases, retries,
dead-letter metadata, and scoped evidence tests" — real mechanisms, not yet proven under
concurrent multi-tenant extraction load. The isolated Hermes worker profile
(`scripts/setup-cortex-worker-profile.sh`) currently assumes one operator's
configuration; multi-tenant use needs per-tenant extraction isolation guarantees stated
explicitly.

**Deliverable:** a load test with concurrent tenants' extraction tasks running
simultaneously, verifying no cross-tenant task starvation or data leakage through the
shared queue.

## 5. SaaS business readiness

### 5.1 Tenancy and isolation

See Workstream A/C. There is currently no tenant concept enforced anywhere in the
runtime path beyond `profile_id`/`identity_mode` fields already present in the storage
status output — those exist as schema fields, not as an enforced isolation boundary.

### 5.2 Pricing tiers

The existing per-profile `quotas.max_memories` field (currently `null`/unlimited in the
live store) is the natural quota lever for tiering. Proposed mapping, not yet
implemented as billing logic:

| Tier | Memory quota | Connectors included | Retention tier |
|---|---|---|---|
| Individual | bounded `max_memories` | `hermes_sessions`, `claude_transcripts`, `webhook` | standard |
| Team | higher/negotiated quota | + `codex_mcp`, `integrity_wiki`, `otel` | standard |
| Enterprise | negotiated/unbounded | all connectors incl. `google_drive` | configurable via `XIBALBA_CORTEX_RETENTION_TIER` |

**Gap:** no tier is enforced in code today; `quotas.max_memories` exists in the schema
but nothing rejects writes past a quota.

### 5.3 Billing and metering

No metering exists. A SaaS Cortex needs per-tenant counters for at least: memory count
(already tracked per-store, not per-tenant), retrieval call volume, extraction task
volume, and connector ingestion volume. **Gap, not yet started.**

### 5.4 Support and SLA tiers

Tie support commitments to the readiness levels above rather than a separate scale: L1
pilot = best-effort, no uptime SLA, direct engineering support for onboarding; L2
hardened = contracted SLA on retrieval latency and evidence/backup durability, gated on
Workstream C's storage decision being production-proven.

### 5.5 Onboarding

Self-serve onboarding requires Workstream A (real token issuance) and Workstream B
(standalone installability, if self-hosted) or a hosted multi-tenant deployment (if SaaS
proper) before any tenant can onboard without direct engineering involvement. Today,
every new "tenant" is effectively a manual local deployment.

## 6. Release gates

### Gate 1 — Tenancy foundation

Pass when bearer-token issuance, enforcement, and revocation are wired into a real
onboarding path and a cross-tenant isolation test exists and passes.

### Gate 2 — Standalone deployability

Pass when `uv sync` succeeds from a clean checkout against a published `integrity-sdk`
version, with no sibling `integrity-core` checkout required.

### Gate 3 — Storage and durability

Pass when the storage architecture decision (§ Workstream C) is recorded and per-tenant
backup/restore has been drilled successfully.

### Gate 4 — Connector production hardening

Pass when every production-tier connector has rate limiting, retry/backoff, and
per-tenant credential isolation, verified by test.

### Gate 5 — Evaluation against real data

Pass when the evaluation harness has been run against at least one real pilot tenant's
traffic and reports a non-synthetic `pilot_ready` result.

### Gate 6 — Governance and audit

Pass when the provenance-export verification procedure (Workstream F) is documented and
independently runnable.

### Gate 7 — Pilot burn-in

Pass when a small set of real external tenants has run concurrently against the system
for an agreed burn-in period with no cross-tenant incident and inference reliability
holding under that load (Workstream G).

## 7. Immediate implementation sequence

1. Close `authorization_tenancy: blocked` — local onboarding, bearer enforcement,
   revocation, expiry, quota configuration, adversarial two-profile tests, and a local
   issue/verify/rotate/revoke drill are complete; next deploy real pilot profiles.
2. Extend concurrency validation to sustained real inference workers. The 2026-09-04
   live-local drill passed with two profiles, four writer threads and four spawned inference
   processes per profile, 100 writes and 100 completed inference tasks per profile, clean SQLite
   integrity checks, zero starvation, and zero cross-profile matches or task visibility. The first
   process run exposed a five-second startup-lock failure; the 30-second SQLite busy-timeout fix
   passed the identical eight-process rerun. Evidence:
   `~/Documents/CORTEX_PILOT_VALIDATION_DRILL_2026-09-04.json`.
3. Track `integrity-core`'s SDK publishing work (external dependency, Gate 2 here) and
   re-test standalone `uv sync` once a published version exists.
4. Record the storage architecture decision (§ Workstream C) explicitly rather than
   deferring it indefinitely. **Completed for the controlled pilot:** SQLite remains
   the per-tenant, single-instance backend with explicit L2 migration triggers; a
   two-profile backup/restore drill passed integrity and canonical Merkle
   reconciliation for both profiles. Evidence:
   `~/Documents/CORTEX_STORAGE_DRILL_2026-09-04.json` and
   `docs/architecture/2026-09-04-storage-architecture-decision.md`.
5. Harden the five `implemented` connectors with rate limiting, retry/backoff, and
   per-tenant credential storage.
6. Run the evaluation harness against a first real pilot tenant and record a real
   `pilot_ready` result.
7. Load-test inference reliability under concurrent multi-tenant extraction before
   onboarding a second real tenant alongside a first.

## 8. External gates that cannot be completed locally

- `integrity-sdk` publication as a real installable package — owned by
  `integrity-core`'s production plan, not this repo.
- A storage backend decision that depends on real pilot-tenant scale, not synthetic
  data.
- Real pilot tenants and their actual traffic, required to close Gates 5 and 7 — no
  synthetic substitute closes these.

Until these are supplied, the honest status is **local single-tenant server
functionally complete; multi-tenant authorization primitives implemented, but tenant
onboarding, deployed isolation, and real pilot evidence remain open**.

## 9. Definition of done for the first pilot

Cortex may be called **multi-tenant pilot-ready** only when Gates 1-5 pass, Gate 6 has a
documented and runnable audit procedure, and Gate 7 has recorded burn-in results with no
unresolved cross-tenant incident. Status claims in this document must be re-verified
against a live `xibalba-cortex-operator production-readiness` run before being restated
in any future revision — this document is a snapshot, not a frozen contract, per this
repo's own `CLAUDE.md` status note.
