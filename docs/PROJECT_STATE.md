# Cortex project state

**This is the single resume authority.** Update this file when a gate changes,
when a verification command produces new evidence, or when a blocker is resolved.
Do not create another numbered roadmap. The detailed production plan is reference
material; its gate IDs map to this state.

**Last verified:** 2026-09-04  
**Repository:** `/home/xibalba/Projects/xibalba-cortex`  
**Branch:** `main`  
**Commit:** `05eeeca` (storage ADR/drill merged)  
**Local-only residue:** pre-existing untracked `LICENSE` (preserve; do not stage)

## Resume in one sentence

Run the Drive-enabled test suite, then begin Gate 4 connector hardening; Gate 2
and real-tenant gates require external work.

## Gate ledger

| ID | Gate | State | Evidence / blocker |
|---|---|---|---|
| G1 | Tenancy foundation | **LOCAL PASS** | Token lifecycle, onboarding, profile isolation, and concurrent validation are implemented and tested. |
| G2 | Standalone deployability | **BLOCKED EXTERNALLY** | `integrity-sdk` is a local `../integrity-core` dependency; a published package or approved git dependency is required. |
| G3 | Storage and durability | **LOCAL PILOT PASS** | SQLite per-tenant decision and two-profile backup/restore drill; see `docs/architecture/2026-09-04-storage-architecture-decision.md` and `~/Documents/CORTEX_STORAGE_DRILL_2026-09-04.json`. This is not HA/PITR proof. |
| G4 | Connector hardening | **NEXT** | Add rate limits, retry/backoff, and per-tenant credential custody for production-tier connectors. |
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

## Canonical references

- `docs/PRODUCTION_READINESS_PLAN.md` — gate definitions and rationale.
- `docs/architecture/2026-09-04-storage-architecture-decision.md` — current pilot storage ADR.
- `README.md` — user-facing install/test/status instructions.
- `~/Documents/CORTEX_*_2026-09-04.json` — append-only local evidence artifacts.
