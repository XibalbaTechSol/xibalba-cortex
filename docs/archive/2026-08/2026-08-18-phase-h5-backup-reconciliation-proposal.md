# Phase H5 close-out — Merkle root reconciliation for backup/restore — go/no-go proposal

**Status:** built and tested, authorized as scoped, with one real, disclosed scope reduction
made during implementation: this closes LIVE-vs-`destination` comparison only (the ability to
prove an existing backup file matches the live store's *current* state) — it does NOT persist a
backup-time "sidecar" root for later comparison against a `restore()`-time state (proving a file
matches what the store looked like *when the backup was taken*, including after it has traveled
to another machine). That's real, separable follow-on work, named explicitly in
`GraphStore.reconcile_backup`'s own docstring rather than silently narrowed.

Added: `GraphStore.reconcile_backup()` (new), `backup(reconcile=True)` (now calls it by
default), a new `backup_reconciliations` table, three new domain-separated Merkle tags
(`backup.memories`/`backup.entities`/`backup.relations` in `events.py`'s `MERKLE_DOMAINS`,
distinct from `projection_checkpoint`'s tags even though both read the same canonical
`memories`/`entities`/`relations` tables), and a new MCP tool `memory_backup_reconcile`. Tests:
`tests/test_store.py`'s `test_reconcile_backup_catches_a_mutated_copy` (a tampered-but-
structurally-valid backup file — passes `PRAGMA integrity_check`, fails reconciliation) and
`test_reconcile_backup_domain_separation_from_projection_checkpoint`; `tests/test_server.py`
extended for the new tool. Full suite green (exit 0, all green, no failures).

Written after reading `GraphStore.backup`/`restore` (`src/xibalba_cortex/store.py`),
`reconcile_projection_checkpoint`, the `projection_reconciliations` write path, and every
`domain_merkle_root`/`domain_merkle_proof` call site in `src/` (2026-08-18).

## Why this slice, and why now

`IMPLEMENTATION_PLAN.md`'s Phase H5 (Merkle evidence services) is the phase actively in flight —
the last two commits on this branch (`32b1b1c`, `ddf46cf`) both touched it. Four of its six items
are done; two remain:

- [ ] Add root comparison and reconciliation APIs for backups and hybrid projections.
- [ ] Record root/leaf citations on derived proposals and retrieval traces.

This proposal is the first of those two, narrowed further than its own checkbox text after
verifying the code: **the "hybrid projections" half is already built.**
`reconcile_projection_checkpoint` (store.py) recomputes a projection's root from canonical data,
compares it against the latest stored checkpoint via `projection_reconcile.reconcile_projection`,
persists the comparison to `projection_reconciliations`, and marks a mismatched checkpoint
`degraded` rather than silently continuing to serve it. That is real, working root-comparison and
reconciliation, not a gap. **The backup half is not built** — `backup()`/`restore()` verify only
`PRAGMA integrity_check` and `schema_version`; neither computes nor compares any domain-separated
Merkle root. A restored backup is proven to be an uncorrupted SQLite file, never proven to be
byte-identical, at the memory/evidence-domain level, to the store it was taken from.

## What this is NOT

- **Not** the second H5 checkbox (root/leaf citations on proposals and retrieval traces) — that
  is separable, touches different tables (`extraction_proposals`, `retrieval_traces`), and would
  be its own proposal if pursued next.
- **Not** H6 (viewer/operator workflow) or the Hybrid acceptance gate — both untouched, both
  larger, both come after H5 closes.
- **Not** a change to the frozen v1 surface. `SPECIFICATION.md` freezes the store schema,
  hash-chain format, and MCP core tool contract as of 2026-08-12; a new backup-reconciliation
  table and one new MCP tool are additive, the same category `memory_retrieval_trace_evidence`
  and friends landed in as (per `50af17c`'s "Additive only, so the v1 frozen surface is
  unaffected").
- **Not** a fix to the concurrent, unrelated Codex-backfill work currently uncommitted in this
  worktree (`src/xibalba_cortex/codex_mcp_backfill.py`) — different subsystem, not touched here.

## Scope: the slice itself

- A new `GraphStore` method, `reconcile_backup(destination_or_source, *, domains=None)`, that
  follows the exact pattern `reconcile_projection_checkpoint` already proves: recompute each
  named domain's root from the target database's canonical data (`exchange_batch`,
  `retrieval_trace`, `projection_checkpoint`, and the base memory-event hash chain via the
  existing `memory_verify_chain` machinery) and compare each against the same domain's root
  computed from the live store at the same point, persisting the result the same way
  `projection_reconciliations` does — new `backup_reconciliations` table, not a reused one
  (different subject: a whole-database snapshot, not one projection).
- Wire it into `backup()`: compute and persist domain roots from the *live* store at backup time,
  store them alongside the backup manifest (a small sidecar record, not inside the SQLite file
  itself, so the roots exist even if the copy is later found corrupt).
- Wire it into `restore()`: after the existing `PRAGMA integrity_check` gate (unchanged — still
  refuse a corrupt file first, cheapest check first), recompute the same domains' roots from the
  restored database and compare against the sidecar record from backup time. Mismatch is
  surfaced in the return value, not silently swallowed — `restore()` already refuses on a failed
  integrity check; extend that same fail-loud posture rather than inventing a softer one for this
  new check.
- One new MCP tool, `memory_backup_reconcile` (or fold into existing `memory_backup` — check
  which reads better against the existing ~60-tool naming convention before implementing),
  thin delegation to the new store method, matching the one-line `@server.tool()` pattern the
  packaging-blocker commit used for its three additions.
- Tests: a backup/restore round-trip where nothing changed (all domains equal), one where a
  domain was mutated between backup and restore (each domain independently, not just one),
  and — mirroring H5's existing adversarial-test discipline for reordering/omission/mutation/
  duplicate-leaves/profile-mismatch — the same attack shapes applied to a restored backup rather
  than a live projection.

## Explicitly deferred — not attempted here

- Root/leaf citations on `extraction_proposals` and `retrieval_traces` (H5's second checkbox) —
  separate proposal.
- Any change to `reconcile_projection_checkpoint` itself — it already works; this slice reuses
  its pattern, not its code path.
- H6 viewer surfacing of backup-reconciliation results — real, useful, but a viewer/UI slice,
  not a store/MCP slice.
- A retention/scheduling policy for how often backups run or how long sidecar root records are
  kept — operational decision, out of scope for the API itself.

## Acceptance criteria

- Real tests, passing, proving: (a) an unmutated backup/restore round-trip reports all domains
  `equal: true`; (b) a domain mutated between backup and restore is caught and reported, not
  silently accepted; (c) `restore()`'s existing corrupt-file refusal is unchanged — this slice
  adds a check, it does not relax the existing one; (d) the new MCP tool round-trips through a
  real MCP client the same way the existing evidence tools are tested.
- `IMPLEMENTATION_PLAN.md`'s H5 checkbox updated to reflect the precise scope actually closed
  (backups only) rather than checked off wholesale against text that also named projections,
  which were already done before this slice existed.
- `docs/wiki/` entries this touches (backup/restore, Merkle evidence) updated in the same change,
  per this repo's own `.agents/AGENTS.md`-style discipline of not letting docs drift from code.
- `uv run pytest -q` clean, no regression to the currently-known-clean baseline.

## Real risks

- **Lower blast radius than the Solidity work in `integrity-core`** — this is local SQLite +
  Python, no external system, no deployment, no shared state with other agents. The main risk is
  scope creep into H6/viewer work, not correctness risk to a live protocol.
- **Sidecar root storage location is a real design decision, not a neutral default.** Storing it
  inside the same destination file couples the proof to the artifact it's proving something about
  — if the file's corrupted, its own claimed roots are untrustworthy too. Storing it separately
  (e.g. alongside the backup path, or back in the live store's own `backup_reconciliations` table)
  avoids that but means a backup taken to a different machine loses its comparison baseline unless
  the sidecar record travels with it. This needs a real answer before implementation, not an
  implicit one.
- **`memory_verify_chain`'s exact API for "give me this domain's current root, not just verify
  it"** hasn't been checked against what this slice needs — if it doesn't already expose a
  root-only accessor, this slice may need a small addition there too, discovered during
  implementation rather than fully scoped here.

## Decision needed

1. **Authorize as scoped above** — backup/restore root reconciliation, reusing the projection
   pattern, new sidecar storage, new MCP tool.
2. **Authorize with changes** — e.g. different sidecar-storage location, or fold into the
   existing `memory_backup` tool instead of adding a new one.
3. **Not yet** — stay at proposal stage; do the proposals/retrieval-trace citation half of H5
   first instead, or revisit later.
