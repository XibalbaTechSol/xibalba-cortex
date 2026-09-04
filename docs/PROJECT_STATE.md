# Cortex project state

**This is the single resume authority.** Update this file when a gate changes,
when a verification command produces new evidence, or when a blocker is resolved.
Do not create another numbered roadmap. The detailed production plan is reference
material; its gate IDs map to this state.

**Last verified:** 2026-09-04  
**Repository:** `/home/xibalba/Projects/xibalba-cortex`  
**Branch:** `main`  
**Commit:** `880e383` (state-checkpoint refresh merged)  
**Local-only residue:** pre-existing untracked `LICENSE` (preserve; do not stage)

## Resume in one sentence

A real, reproducible sustained-load hang was found under the inference-task
harness (see "Open finding" below) — investigate that before extending Gate 4
connector hardening; Gate 2 and real-tenant gates still require external work.

## Open finding: sustained-load worker hang (not yet root-caused)

`xibalba_cortex.tenant_inference_validation` (2 profiles, 4 processes/profile)
completed cleanly and quickly at 50/100/150 tasks-per-process (13.5s at 150,
linear scaling, repeatable). At 200 tasks-per-process it hung three separate
times, each run killed only by an external `timeout`. Process inspection during
one hang showed 6 of 8 workers had already exited (zombie/defunct) while 2 were
still alive in `futex_do_wait`; the harness's `process.join(timeout_seconds)`
loop joins workers **sequentially, each with its own full timeout**, so one slow
worker blocks the loop from ever reaching its already-finished siblings — this
masks completion and burns the whole time budget on one process. Both SQLite's
`PRAGMA busy_timeout` and the Python driver's own `timeout=` are set to a
consistent 30s (`store.py`), so a hang past 100s+ is not explained by the known
busy-timeout fix alone. The test profiles were also never reset between
calibration attempts, so cumulative row count (not just per-run task count) is
a live suspect and not yet ruled out.

**Not yet done:** isolating whether the hang is task-count-per-run or
cumulative-table-size driven (rerun against fresh profiles at each size);
instrumenting the specific stuck worker (which query, which lock) rather than
inferring from `ps` state; and fixing the harness's sequential-timeout join
loop regardless of root cause, since it hides exactly the failure mode a
sustained-load test exists to catch. Do not mark Workstream A/G "sustained
workload" verification complete until this is resolved — this is a real,
reproduced problem, not a flaky test.

## Gate ledger

| ID | Gate | State | Evidence / blocker |
|---|---|---|---|
| G1 | Tenancy foundation | **LOCAL PASS** | Token lifecycle, onboarding, profile isolation, and concurrent validation are implemented and tested. |
| G2 | Standalone deployability | **BLOCKED EXTERNALLY** | `integrity-sdk` is a local `../integrity-core` dependency; a published package or approved git dependency is required. |
| G3 | Storage and durability | **LOCAL PILOT PASS** | SQLite per-tenant decision and two-profile backup/restore drill; see `docs/architecture/2026-09-04-storage-architecture-decision.md` and `~/Documents/CORTEX_STORAGE_DRILL_2026-09-04.json`. This is not HA/PITR proof. |
| G4 | Connector hardening | **IN PROGRESS** | Shared retry/rate-limit/credential-boundary primitives and Google Drive wiring are implemented and tested. Next: inbound OTLP/webhook throttling and connector-level retry evidence for the remaining production-tier paths. |
| G5 | Real-data evaluation | **OPEN / EXTERNAL** | Requires a real pilot tenant's traffic; synthetic benchmark is not pilot proof. |
| G6 | Governance and audit | **OPEN** | Define and independently run provenance-export verification. |
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
