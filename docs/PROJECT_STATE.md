# Cortex project state

**This is the single resume authority.** Update this file when a gate changes,
when a verification command produces new evidence, or when a blocker is resolved.
Do not create another numbered roadmap. The detailed production plan is reference
material; its gate IDs map to this state.

**Last verified:** 2026-09-05  
**Repository:** `/home/xibalba/Projects/xibalba-cortex`  
**Branch:** `main`  
**Commit:** `9425f08` (Gate 6 provenance-export verification merged) + sustained-load deadlock fix on top, about to push  
**Local-only residue:** pre-existing untracked `LICENSE` (preserve; do not stage)

## Resume in one sentence

Gates 4 and 6 are closed for everything locally closable, and the previously
open sustained-load worker deadlock is now root-caused and fixed (see "Closed
finding" below) — sustained-load verification for Workstream A/G may now be
considered locally passed. Remaining items across G4/G6 are external or need
new design work: real Google Drive OAuth evidence, Hermes hook-watermark
verification (needs new instrumentation, not yet designed), and
`memory_export_provenance`'s missing scope/auth check (disclosed, not fixed).

## Closed finding: sustained-load worker deadlock (was open, now fixed)

Previously: `xibalba_cortex.tenant_inference_validation` hung reproducibly
(three separate runs) at 200 tasks/process while 50-150 completed cleanly.

Root cause, found via heartbeat instrumentation (not guessed): the harness
joined every worker process **before** draining `result_queue`.
`multiprocessing.Queue` writes through a background feeder thread into a
bounded OS pipe — the Python docs explicitly warn that a child which has
`put()` enough data will not finish exiting until it's flushed, so joining
first can deadlock exactly this way. Every worker's heartbeats showed all
real application work (including the queue put and `store.close()`) had
already succeeded; one stuck process was caught with a live
`QueueFeederThread` mid-exit — proving the hang was in Python's own
queue/subprocess-exit machinery, not application logic, the previously-fixed
`busy_timeout` path, or cumulative test-database growth (all three were
suspected and ruled out).

Fixed by draining the queue before joining processes. Verified: 200
tasks/process (previously hung every time) now completes in ~16s; 1,000
tasks/process (8,000 total tasks, 40x the original 25-task burst) completes
in ~75s, both `passed: true`, zero timeouts. Full details:
`docs/audits/2026-09-05-sustained-inference-deadlock-fix.md`. Opt-in
regression test at the exact reproducing scale:
`XIBALBA_RUN_SUSTAINED_INFERENCE_DRILL=1 uv run pytest tests/test_tenant_inference_validation.py`.

## Gate ledger

| ID | Gate | State | Evidence / blocker |
|---|---|---|---|
| G1 | Tenancy foundation | **LOCAL PASS** | Token lifecycle, onboarding, profile isolation, and concurrent validation are implemented and tested. |
| G2 | Standalone deployability | **BLOCKED EXTERNALLY** | `integrity-sdk` is a local `../integrity-core` dependency; a published package or approved git dependency is required. |
| G3 | Storage and durability | **LOCAL PILOT PASS** | SQLite per-tenant decision and two-profile backup/restore drill; see `docs/architecture/2026-09-04-storage-architecture-decision.md` and `~/Documents/CORTEX_STORAGE_DRILL_2026-09-04.json`. This is not HA/PITR proof. |
| G4 | Connector hardening | **LOCAL PASS** | Shared retry/rate-limit/credential-boundary primitives, Drive wiring, OTLP/local-API throttling, and profile-aware connector CLIs are implemented and tested. Real ingress throttle/retry drill passed (`docs/audits/2026-09-04-connector-throttle-retry-drill.md`). All four local-file connectors verified against a real tenant profile with permanent regression coverage (`tests/test_connector_tenant_profile_scoping.py`, `docs/audits/2026-09-04-local-connector-tenant-scoping-fix.md`) after finding and fixing a real bug: they always opened the store as `profile_id="default"`, never the tenant's own profile. `session_sync.finalize()` no longer crashes on a system with no local Hermes install (a second real bug, caught by CI itself, not local testing). Remaining, both out of scope for a local session: real Google Drive OAuth evidence (external) and Hermes hook-watermark verification (needs new instrumentation, not yet designed). |
| G5 | Real-data evaluation | **OPEN / EXTERNAL** | Requires a real pilot tenant's traffic; synthetic benchmark is not pilot proof. |
| G6 | Governance and audit | **LOCAL PASS** | Provenance-export verification is documented (`docs/operations/provenance-export-verification.md`) and independently runnable: `scripts/verify_provenance_export.py` has zero dependency on this package (stdlib only), verified as a real subprocess against a real exported bundle (`tests/test_verify_provenance_export.py`), including two tamper cases (memory content, root_hash). Correction: an earlier entry here claimed `memory_export_provenance` had no scope/auth check; that was checked against `server.py`'s per-tool decorators only and missed `BearerTokenAuth`'s transport-level `memory:read` baseline (`server.py`'s streamable-http `main()`, `auth_middleware.py`) that every tool call, including exports, already goes through — verified per-request, not just a connection handshake. No gap; corrected, not fixed. Retention-period policy (Workstream F's other named item) remains open. |
| G7 | Pilot burn-in | **OPEN / EXTERNAL** | Requires concurrent real tenants and an agreed burn-in period. |

## Verified local capabilities

- Full backend suite passes when the Drive extra is installed: `uv sync --extra drive && uv run pytest -q` (one pre-existing skip; warnings are non-blocking).
- Viewer build passes: `npm --prefix viewer run build`.
- Eight-process/two-profile inference drill passed with 200 total tasks, zero starvation, zero cross-profile visibility, and clean integrity checks; evidence is `~/Documents/CORTEX_PILOT_VALIDATION_DRILL_2026-09-04.json`.
- Authenticated Operations UI visibly renders the Production readiness card; verification was local-only and the temporary credential was revoked.

## Exact resume commands

```bash
cd /home/xibalba/Projects/xibalba-cortex
uv sync --extra drive
uv run pytest -q
npm --prefix viewer run build
uv run xibalba-cortex-operator production-readiness
```

For the human UI, follow `viewer/README.md`. For a second machine, clone
`xibalba-cortex` beside `integrity-core` until G2 is resolved, then run the same
commands in a fresh profile. Never describe these local results as external pilot,
SLA, compliance, HA, or production evidence.

## Checkpoint protocol

At the end of every work session, record: current commit, gate changed, exact
commands and outcomes, evidence paths, next action, and blockers. Commit this file
with the code/docs change and push it. Also store the same summary in Cortex as a
`summary` memory. After a power loss, read this file first; do not infer status from
old chat context or start a new plan.

## Context continuity contract

This repository uses one active execution ledger because chat history is not a
durable control plane. `PROJECT_STATE.md` is the contract between the operator,
Codex, and future sessions:

- No new roadmap or numbered plan may be created for work already represented by
  G1–G7. Add detail to the relevant gate row or link a dated evidence artifact.
- Every session ends with one checkpoint containing the current commit, verified
  commands/results, evidence paths, next action, and blockers. The checkpoint is
  committed and pushed, and a matching `summary` memory is stored in Cortex.
- A reboot is a normal event, not a reset: run `scripts/cortex-resume.sh`, inspect
  the gate ledger and live Git state, then continue the single `NEXT` item.
- Local, synthetic, CI, external-pilot, deployment, SLA, and compliance evidence
  must remain labeled separately. Passing tests never upgrades a weaker evidence
  class into production proof.
- When a gate is blocked by an external dependency, record the exact owner and
  unblock condition once; do not create duplicate plans around it.

The desired operator experience is therefore: **one ledger, one next action, one
checkpoint, one source of truth.**

## Canonical references

- `docs/PRODUCTION_READINESS_PLAN.md` — gate definitions and rationale.
- `docs/architecture/2026-09-04-storage-architecture-decision.md` — current pilot storage ADR.
- `README.md` — user-facing install/test/status instructions.
- `~/Documents/CORTEX_*_2026-09-04.json` — append-only local evidence artifacts.
