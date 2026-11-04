# SDD run evidence

The briefs, reports, reviews and progress ledgers produced by the spec-driven-development runs
behind the plans in `docs/superpowers/plans/`. One directory per run, named after the plan it
belongs to; each directory's `plan-path` names that plan.

## Why this is in git

These reports are the cited evidence base for the Cortex production-readiness work. Until now they
existed **only** inside one `/mnt/storage` worktree, and they were *ignored rather than untracked*:
the run directory carried its own `.gitignore` containing `*`, so the directory ignored itself,
`git status --untracked-files=all` reported nothing, and `git add` could not stage them without
`-f`. Nothing warned anyone, and retiring that worktree would have destroyed the whole evidence
base silently.

A plan that cites evidence and evidence that lives in one untracked directory are not the same
thing. These are now tracked.

## What is here, and what is not

Committed: every brief, report, review package and progress ledger — the analysis, which cannot be
regenerated.

Not committed: the `review-*.diff` blobs each run captured, about 280K. Each is literally
`git diff A..B` where both endpoints are commits in this repository, so committing them would
duplicate git history. The ranges themselves are the part worth keeping, so each run directory has
a `review-ranges.md` listing every range with the command to regenerate it. All 12 ranges in the
p0 run were checked and both endpoints resolve.

## Two corrections to how this evidence is cited

The ecosystem plan cites `phase0-task5-report.md` and `phase5-task1-report.md` for "a 198/198
Playwright baseline and nine recorded mutation proofs". Verified against the files:

1. **The nine mutation proofs are in `phase1-task5-report.md`, not `phase0-task5-report.md`.**
   They are real and enumerated `M1` through `M9`. The 198-test baseline *is* in
   `phase0-task5-report.md` ("198 passed"). `phase0-task5-report.md` records one mutation
   experiment of its own (3 passed, 2 failed) plus a follow-up single-test check — not nine.

2. **`phase1-task5-report.md` has a hole, recorded in the run's own ledger.** It ends at line 222
   in a literal `FULL_SUITE_PLACEHOLDER`: the agent was killed by a five-hour limit while running
   the full Playwright suite, so the whole-suite result was never filled in. Everything else in
   that report is backed by quoted output. The run also recorded one claim it could **not** prove
   able to fail — the hosted gate change itself — and said so rather than asserting the proof.

Treat the baseline and the nine proofs as real, and the full-suite line as missing. Do not quote
that report as a clean whole-suite pass.

## Related

`progress.md` in each run is the ledger, and it is the authority on what a run actually did. The
plans' checkboxes are not: the 2026-11-02 ledger says so in as many words — "the plan's checkboxes
are still unticked and are NOT evidence of anything — the ledger is."
