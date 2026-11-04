# Review ranges — 2026-11-02-cortex-production-readiness

The SDD run captured a `git diff` for each review round. Those `.diff` files are
**not** committed: every endpoint below is a commit in this repository, so each diff
is reproducible on demand and committing it would duplicate git history.

Regenerate any row with:

```
git diff <from>..<to>
```

| # | From | To | Both commits resolve |
|---|---|---|---|

Captured 0 review rounds.

## Commit provenance for the Phase 2–3 ledger entries

The ledger entries appended for Phase 2 Tasks 3–5 and Phase 3 Tasks 1–3 cite
per-task commits. Those commits are **not ancestors of `main`**: the work landed
as a squash merge (`33b3e964`, PR #96), and GitHub deleted the branch on merge.
Nothing on `main` reaches them, so the citations are recorded here with the ref
that does.

Recover every one of them with:

```
git fetch origin refs/pull/96/head    # the 8 Phase 2-3 task commits
git fetch origin refs/pull/97/head    # the hermetic-sidecar test fix
```

GitHub retains `refs/pull/<n>/head` permanently, including after branch deletion.

Three of the cited SHAs resolve on the machine that ran the plan but appear
nowhere on the remote. They are **pre-rewrite** commits: `.superpowers/` scratch
was committed by a `git add -A`, then stripped with `git filter-branch`, which
rewrote every commit that carried it and gave it a new SHA. The ledger recorded
the original. Each is listed with the surviving commit of identical content and
subject, verified by matching subject against `refs/pull/96/head`:

| Ledger cites | Survives as | Subject |
|---|---|---|
| `055a928` | `5bd4547` | test(billing): close the four real gaps in Phase 3 Tasks 1 and 2 |
| `d02babd` | `da45463` | test(console): the DID-bound API key path, asserted in Phase 2's own file |
| `f6d1b2f` | `a8c6764` | fix(enrollment): a code enrolls an agent, and may not do three other things |

The other five cited SHAs (`bb1fe1d`, `bd9bade`, `328b86c`, `73fb4b1`,
`8737eb3`) predate or postdate the rewrite and are reachable from
`refs/pull/96/head` unchanged.

The three left-hand SHAs will stop resolving once the worktree that produced them
is retired and git garbage-collects. That is expected; the right-hand column is
the durable citation.
