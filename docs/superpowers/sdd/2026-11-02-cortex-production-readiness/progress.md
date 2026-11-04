# SDD ledger — plan: docs/superpowers/plans/2026-11-02-cortex-production-readiness.md

Spec: docs/superpowers/specs/2026-10-26-cortex-account-and-agent-registration-design.md (read; reachable)
Worktree: /mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design
Branch: docs/account-registration-design, tip 162be29 at ledger creation
Execution: subagent-driven, per-phase review gates (operator choice 2026-11-03)

## Pre-flight conflict scan

Pairs sharing a file or interface:

| A | B | A produces / B consumes | Finding |
|---|---|---|---|
| P1-T2 | P1-T3 | both modify `accounts.py` | OK, sequential. T3 must keep T2's scope narrowing; T3 Step 4 already says earlier tests stay green |
| P1-T1 | P1-T2 | T1's `test_a_session_today_carries_every_known_scope` is replaced by T2 | OK, T2 Step 1 says replace in the same commit so the removal is visible |
| P1-T4 | P5-T1 | T4's ingest test xfails until P5-T1 exists | OK, `strict=True`; P5-T1 Step 4 removes the marker. Phase order holds |
| P3-T3 | P5-T1, P5-T3 | P3 builds limit enforcement; P5 calls it on two new routes | OK, P3 precedes P5 |
| P0-T5 | P2-T4 | P0 deletes `ManagedApp`; P2-T4 re-homes the DID-key assertion that drives it | **CONFLICT — ruled below** |
| P2-T1,T3,T4 | each other | all touch `registration.spec.ts` + `AgentsPage.tsx` | OK, sequential within phase |
| P5-T1 | P5-T3 | both modify `managed/api.py` | OK, sequential |
| P5-T1 | P5-T4 | T4 compares REST against the connector transport | OK, T4 follows T3 |
| P1-T1 | P1-T4, P5-T1 | T1 creates `conftest.py`; later tasks add fixtures | OK, Global Constraints says the first user creates each |

Each task against itself:

| Task | Self-consistent? |
|---|---|
| P0-T5 | Yes — assertions precede deletion, which is the stated point |
| P1-T1 | Yes — characterisation tests, and the "expect PASS" is called out so it is not mistaken for a broken TDD step |
| P1-T2 | Yes |
| P1-T3 | Yes — names all three cookie `max_age` sites |
| P1-T4 | Yes — no-implementation-expected is stated |
| P1-T5 | Yes |
| P2-T1..T5 | Yes |
| P3-T1..T3 | Yes |
| P3-T4 | Not dispatchable by design — operator credential handover |
| P5-T1, T2 | Yes |
| P5-T3 | Step 0 is a blocking Devil's Advocate gate, not implementation |
| P5-T4 | Yes |
| P5-T5, T6 | Yes |
| **Fixture gap** | P5-T3 names `connector_app`, `key_a`, `key_b`, which no earlier task creates — **ruled below** |

Ruling: P0-T5 must re-home the DID-bound API-key assertion as part of the deletion, not leave it to P2-T4 — deleting ManagedApp strands `managed.spec.ts`'s "Create API key stays disabled until Agent DIDs is filled" check, and that exact check is what hung PR #72's CI for 90s twice, so losing it even temporarily is the specific regression this codebase has already paid for. P2-T4 then verifies it still holds and adds the `agent_ids` assertion. — Costs if wrong: P0 grows by one test move; P2-T4 shrinks. No code risk.

Ruling: P5-T3 Step 1 creates `connector_app`, `key_a` and `key_b` in `tests/conftest.py`, same rule as every other fixture. — Costs if wrong: nothing; it is the Global Constraints rule applied to a task that did not restate it.

Ruling: Phase 4 appears after Phase 5 in the document. Left as-is — it is labelled "Deferred production hardening" and dispatches nothing. — Costs if wrong: a reader's momentary confusion.

## Progress

Phase 0 Task 5: BASE=162be29. Brief at phase0-task5-brief.md (P0 plan's task 5 + 7
controller additions). Dispatch held until the full-suite Playwright baseline finishes —
it binds ports 25190/28420/28431 and a concurrent run would fail on port conflicts.
Baseline command: `CI=true npx playwright test --reporter=line`, output to
/tmp/claude-1000/-home-xibalba/f3f54e1a-35e8-4637-8678-da626f86292a/scratchpad/pw-baseline.txt
Ruling: the README tool count is 89, not 80. tests/test_server.py::test_all_tools_are_advertised
asserts 89 unique names, matches server.py's 89 @server.tool decorators, and passes. Phase 5
Task 6 Step 1 marked done by the controller; README.md:164 and :336 are wrong by nine.
— Costs if wrong: a wrong number in the README, caught by the same test.

Ruling: do NOT take a full-suite Playwright baseline before Phase 0 Task 5. The full suite
is 197 tests and reached only 54 in ~25 min (~2h total); Task 5 Step 5 needs a full run
AFTER the deletion anyway, so a full pre-baseline would cost 3+ hours of Playwright to
learn something Step 2 establishes in minutes. Instead: (a) partial full-suite evidence
recorded below, (b) a targeted baseline of the two specs Task 5 touches, (c) the single
full-suite run happens once, at Step 5, where it actually gates the commit.
— Costs if wrong: if an unrelated spec is already red, Step 5's full run attributes it to
the deletion. Mitigated by the partial evidence: 54/197 across actions, auth, chain-rail,
collapsed-logo and console spec files, ZERO failures. (The 174 grep hits for "failed" are
all inside `integrity_sdk` oracle connection warnings — localhost:8080 is not running —
not test results.)

Targeted baseline (managed.spec.ts + design-system.spec.ts, CI=true, all projects):
42 passed, 2 skipped, 0 failed, 6.0m, exit 0.

Ruling: Phase 0 Task 5's Steps 1-2 as written are STALE and the brief now says so. Step 3
already landed, so /managed already renders the console: design-system.spec.ts:727 sweeps
the hosted workspace at 390/1280/1600px and passes, and managed.spec.ts drives the console
for 11 tests. The planned "write assertions, confirm they fail" cannot fail, so the brief
replaces it with a source-side mutation (temporarily restore the edition fork in main.tsx,
confirm the sweep and re-homed tests go red). ManagedApp.tsx is orphaned dead code.
— Costs if wrong: the deletion is cleanup rather than behaviour change, so the mutation is
the only thing proving the one-app property at all. If the mutation is skipped, the suite
proves nothing and we would not know.

Finding (upgrades ruling 1): the DID-bound API-key coverage is not merely at risk, it is
ALREADY disabled. managed.spec.ts:51 and :98 are both `test.fixme` — the "2 skipped" above.
They assert ManagedApp's classes (.xc-managed-results, .xc-managed-key). The console
implements both behaviours already (AgentsPage.tsx:155-182 preserves the identical
`disabled={busy || !dids.trim()}` rule; READ_ONLY_WORKSPACE lives in console/billing.ts), so
only selectors are stale. Task 5 now owns un-fixme-ing both, and the brief requires a
written justification for every assertion dropped.

Phase 0 Task 5: implementer dispatched (sonnet, multi-file + e2e integration). BASE=d946fc1.
Report will land at phase0-task5-report.md

Ruling: execution order amended to Phase 0 -> P5 T1,T2 -> P1 -> P2 -> P3 -> P5 T3-T6, on
operator instruction, to reach a deployable test build sooner. Verified the reorder breaks
no dependency: ManagedControl.consume already enforces writes/retrievals atomically with
idempotency, max_memories rides GraphStore quotas via control.store(), and routes already
call all of it (api.py:161,369,378,405,426; LimitExceeded mapped at :491/:534). So P5 T1
calls existing machinery rather than waiting on P3 T3.
— Costs if wrong: if the reorder misses something, auth hardening lands after a route is
already publicly reachable. Mitigated: the route is bearer-token-only, tenant-scoped by
control.store()'s path validation, and metered by consume(). It adds no new auth surface.

Finding: Phase 3 Task 3 is ALSO mostly already implemented, same pattern as Phase 1. Its
remaining value is the three proved-able-to-fail tests, not the enforcement.

Finding: control.store() (control.py:216-229) already validates the tenant id shape, rejects
a symlinked tenant root and rejects a resolved path escaping the storage root. That is P5
T2's isolation, already hardened. T2 narrows to proving the tenant comes from the TOKEN and
never the payload.

Ruling: P5 T1 now creates tests/conftest.py with the managed_app and api_key fixtures
(was P1 T4, which now runs later and reuses them). P1 T4's xfail(strict=True) inverts into
an ordinary passing test, since the ingest route will already exist.
— Costs if wrong: a fixture defined twice, caught immediately by pytest.

## Stripe live-credential validation 2026-11-03 (test mode, acct_1RjOWGR0CCZIV2Rk)

Driven against a locally-run managed service on 127.0.0.1:8440 with a throwaway data
home, using the operator's `sk_test_` key. No credential committed, printed into the
repo, or retained in tree.

Verified end to end, each through the real HTTP surface:

| Check | Result |
| --- | --- |
| `/readyz` billing gate with real keys + prices | `billing_configured: true`, `stripe_sandbox: ready` |
| `POST /api/managed/checkout` (cookie auth + CSRF + Origin) | HTTP 200, real `cs_test_…` session issued |
| Webhook with tampered `v1` signature | HTTP 400 `invalid Stripe signature` |
| Webhook `customer.subscription.created`, genuine active sub | HTTP 200; tenant `free/free` → `pro/active` |
| Same event id replayed | HTTP 200 `duplicate: true`; exactly one `stripe_events` row |
| Event for a customer belonging to no tenant | HTTP 200 `ignored: true`; no entitlement change |
| Event with `livemode: true` against a test deployment | HTTP 400 `Stripe event mode does not match deployment` |
| `customer.subscription.deleted` after a real Stripe cancel | tenant → `status: canceled`; `/me` `writable: false` |
| `POST /api/managed/memories` while canceled | HTTP 403 read-only refusal |
| `GET /api/managed/memories` while canceled | HTTP 200 — reads and export retained |

Finding 1 — **signup is not atomic (genuine defect, pre-existing).**
`ManagedControl.register` creates the account row and the tenant row, then calls
`send_verification`. When delivery raises — e.g. `EmailDeliveryError:
CORTEX_SMTP_HOST and CORTEX_SMTP_FROM are required` at `control.py:110` —
the request fails with HTTP 503 but both rows persist. Re-registering the same
address then fails with `an account with that email already exists`, so a user who
signs up while mail is misconfigured is permanently unable to retry with that
address and has no verified account. Reproduced: orphan account
`email_verified=0, approval_status='pending'` with a matching `free` tenant row.
Ruling: fix belongs in Phase 2 (registration), which already owns `register`.
Either roll back both rows on delivery failure, or create them `pending` and make
re-registration of an unverified address resend rather than conflict. Cost if
wrong: a Phase 2 task grows by one test plus a transaction boundary.

Finding 2 — **`CORTEX_MANAGED_ALLOW_SIGNUP` requires the literal `true`.**
`1` does not enable registration; `/readyz` reports registration unavailable with
no hint that the value was the problem. Ruling: record as a P3b deployment note so
the Render env is set to `true`, and have Phase 2 accept the usual truthy set.
Cost if wrong: a one-line config parse change.

Finding 3 — **portal configuration `subscription_update.products` persisted as `null`.**
`bpc_1UXbVnR0CCZIV2RkiOTIzvJY` is active and default, and `POST /api/managed/portal`
issues a real `bps_…` session, but tier switching may not list Pro/Team. Not
blocking: the portal opens and billing works. Ruling: Phase 3 adds the assertion
that the configuration lists both plan products.

## Merge-readiness survey 2026-11-03 (read-only; no rebase performed)

Branch `docs/account-registration-design`: **39 ahead, 8 behind `origin/main`.**
Upstream tracks `origin/docs/account-registration-design`, not `origin/main` — the
WORKFLOW constraint holds, nothing to fix.

The 8 incoming commits are the PR #74 squash lineage and they touch exactly **two files**,
both docs:
- `docs/superpowers/plans/2026-10-26-p0-one-app-console.md`
- `docs/superpowers/specs/2026-10-26-cortex-account-and-agent-registration-design.md`

Neither file existed at the merge base, so both sides *created* them. A rebase will
therefore raise an **add/add conflict on both**, and on no other path. No source file
conflicts.

Resolution, determined by content comparison and settled now so the rebase is mechanical:
**keep ours for both files.** Our versions are main's content plus our amendments (plan
468 vs 397 lines, spec 461 vs 365). The lines present only on main are precisely the
statements we deliberately superseded, plus unticked checkboxes we ticked:
- "PR #73 (`local` -> `main`, OPEN, MERGEABLE)" and "**P0 is blocked on it**" — PR #73
  merged 2026-10-26T07:52:26Z; we cleared that blocker.
- "not yet planned or implemented" — false by the time we read it; P0 was mostly built.
- The two stale capability-table rows PR #73 made obsolete.
- `- [ ]` step lines that our execution-status pass turned into `- [x]`.

Ruling: at merge time, rebase onto `origin/main` and resolve both add/add conflicts by
taking our side wholesale, then re-read the two files to confirm no main-only *substantive*
line was dropped — the list above is the complete set to check against. Cost if wrong: a
docs paragraph is lost and has to be restored from `origin/main`, which stays available.

Not performed now: a rebase rewrites the working tree, and the Phase 0 Task 5 implementer
is live in it.

**Also unresolved and NOT addressed by this survey:** local green is not CI green. The
`integrity-core` base checkout is 3,662 insertions ahead of the SHA that Cortex CI pins
(`4ddaae1965635224958e147f6eaaead06e3cdc41`), so the sibling-symlink arrangement that makes
e2e run locally does not reproduce CI's dependency. Confirm against CI, not locally, before
claiming the suite passes.

## Phase 0, Task 5 — implementer reported DONE_WITH_CONCERNS 2026-11-03

Commits: `8a38002` (tests), `b115f2f` (controller's prop rename). The file deletions are in
`7f96180` because a concurrent docs commit of mine swept in the implementer's staged
`git rm` — branch content is right, attribution is wrong. Noted, not rewritten: rewriting
history to fix a co-author line is not worth the rebase.

Implementer verification: build OK, oxlint 0 errors (12 pre-existing warnings),
vitest 368/368, full `CI=true npx playwright test` **198 passed / 0 failed / 0 skipped**
(30.4m), and `grep -rn "xc-managed-" viewer/src | grep -v BillingPage` silent.

**Ruling 1 — Landing's `managed` prop: keep the behavior, fix the name.**
The brief was wrong. It assumed `ManagedApp` was the prop's only caller; in fact
`HostedLanding.tsx:122` renders `<Landing managed>`, and the prop selects the hosted
landing's copy and suppresses the self-hosted pricing section via
`ProductSections showPricing={!managed}`. Removing it would have deleted working hosted
content and broken the plans tests, buying nothing: the prop is a copy switch inside the
one console app, not an edition fork, so P0's "one app, and it is the console" was already
satisfied. Renamed `managed` → `hosted` in `Landing.tsx` and `HostedLanding.tsx` so the
name describes the deployment rather than the retired edition. No unit test referenced it;
no DOM changed. Re-verified after the rename: tsc clean, build OK, oxlint 0 errors,
vitest 368/368, `managed.spec.ts` 15/15. Product prose still reads "managed memory",
which is correct — the product kept its name; the second UI is what retired.
Cost if wrong: a prop name, revertable in one commit.

**Ruling 2 — accept the substituted mutation and the test it forced.**
The brief's mutation (restore the edition fork) did **not** turn the hosted grammar sweep
red: the sweep passed at 390, 1280 and 1600px with `ManagedApp` restored. That is the
vacuous-check failure mode in this repo's own standing lesson, caught rather than papered
over. The implementer added `the hosted workspace is the console shell, not a second app`,
which does go red under the mutation (`.xc-shell` absent). Accepted: a check that cannot
fail is not evidence, and the replacement was shown able to fail. Its deviation from the
brief — asserting the Billing tab in the Settings tab strip rather than a rail button,
because Billing is not a rail button on the default layout — is a correction to the brief,
not a shortfall.

## Read-only-base audit 2026-11-03

`xb-wt doctor`:
```
ok   integrity-core     main, clean
ok   xibalba-cortex     local (pinned), clean
note xibalba-cortex     local is 0 ahead / 12 behind origin/main (as of last fetch)
ok   xibalba-shield     main, clean
ok   integrity-console  main, clean
```

**`xibalba-cortex`'s declared base branch is `local`, not `main`** — the pinned case
CLAUDE.md warns about, and it is declared, so it is not drift. It does not change the merge
target: feature branches still merge to `main` (PR #74 did), and the rebase plan recorded
above is unaffected.

The e2e sibling symlink `../integrity-core -> /home/xibalba/Projects/integrity-core` points
at the **read-only base**, so it was worth confirming the editable `integrity-sdk` path
dependency did not write into it. It did not: `git status --porcelain` is empty, the base is
still on `main`, and the two build artifacts present (`integrity-sdk/build`,
`integrity-sdk/integrity_sdk.egg-info`) are both gitignored
(`integrity-sdk/.gitignore:10` and `:8`) and predate this work — 2026-09-08 and 2026-10-26
against today's 2026-11-03. No drift, no accidental deploy.

**CI fidelity gap, unchanged and still unresolved:** that sibling is at `d460736cc499`,
while `.github/workflows/ci.yml:47` pins `integrity-core` at
`4ddaae1965635224958e147f6eaaead06e3cdc41`. A local `pytest` run therefore resolves
`integrity-sdk` from a different revision than CI does. Local green is evidence the branch
works against a *newer* SDK; it is not evidence CI passes. The workflow comment is explicit
that the pin must be bumped in the same PR as any code importing a newly added SDK symbol,
never in a follow-up.

## Python suite on this branch 2026-11-03

First run: 4 failures. **None is caused by this branch**, which changed exactly two Python
files — `src/xibalba_cortex/managed/api.py` and `tests/test_managed_service.py` — out of 39
changed files (18 ts, 15 tsx, 3 md, 2 py, 1 css). Neither the failing tests nor the code
they exercise is among them.

| Failure | Cause | Resolution |
| --- | --- | --- |
| `test_otel_core::test_official_otlp_exporters_construct_for_http_and_grpc` | optional OTLP exporter dep absent; CI runs `uv sync --extra otel --extra managed` and I had not | **passes** after syncing the extras |
| `test_hermes_observer::test_runtime_telemetry_omits_unconfigured_agent_id` | host leakage: `~/.xibalba/` exists here (`agents.json`, `did/`), so an agent identity resolves from HOME even though the test deletes `XIBALBA_AGENT_ID` | **passes** with `HOME` pointed at an empty dir |
| `test_stdio_principal::test_stdio_fails_closed_without_an_agent_identity` | same host leakage | **passes** with isolated `HOME` |
| `test_store::test_memory_vectors_migrates_existing_l2_table_to_cosine_preserving_data` | unresolved; `sqlite3.OperationalError: SQL logic error` at `tests/test_store.py:678`, on `DROP TABLE memory_vectors` | still red; pre-existing |

With the extras installed and `HOME` isolated, the suite is green **except** that one.

**Finding — two identity tests are non-hermetic, and that is a latent trap, not just noise.**
They delete `XIBALBA_AGENT_ID` but do not isolate `$HOME`, so they only assert what they
claim on a machine with no agent identity. They pass in CI and pass on a clean checkout,
while silently testing nothing on any developer machine that has run the agent — which is
every machine that would actually run them. Ruling: out of scope for this plan (this branch
did not touch them), but worth a follow-up that points identity resolution at a tmp home via
a fixture. Cost if wrong: nothing now; the tests keep behaving as they do today.

**On the sqlite failure, two hypotheses were tested and both were WRONG** — recorded so the
next person does not repeat them:
1. "Newer SQLite cannot drop a `vec0` virtual table." False. Probed directly on host sqlite
   3.53.1 with sqlite-vec 0.1.9: create, insert, `DROP TABLE` all succeed.
2. "The drop fails because a second connection does it while `GraphStore` holds the first
   open." False. Probed: dropping from a second connection with the first still open
   succeeds.
The real cause is therefore something specific to the store's own `memory_vectors`
definition or connection state, not a generic sqlite-vec interaction. Not pursued further:
it is pre-existing, unrelated to this plan, and diagnosing it is its own task.

### Task 5: complete

Commits: `8a38002` (implementer's re-homed tests), `7f96180` (file deletions, swept in by a
concurrent docs commit — attribution wrong, content right), `b115f2f` (prop rename per
Ruling 1), `40a48d2` (review fix round 1), `6fe4e90` (dangling-reference fix).

Task review (Opus): **spec compliance PASS**, quality NEEDS FIXES with one blocking.
Scoped re-review (Sonnet): **both findings ADDRESSED, confirmed by reading code.**

**Ruling 3 — removed an assertion that could not fail, rather than keep it for appearances.**
`managed.spec.ts:122` asserted no `POST` to `memories` in a test that attempts no write, and
`hostedApi.ts:354` refuses hosted writes client-side before the network, so it held with or
without the gate. `hosted-paths.spec.ts` already declines that same assertion in a comment and
points at the real gate. Removed; the orphaned `calls` binding went with it. The gate on the
CALL is genuinely proved in `hostedApi.test.ts`,
`describe('the hosted write gate (finding 4)')`, which attempts a write under a read-only
subscription and asserts `READ_ONLY_WORKSPACE`, status 402 and an empty call list, with a
converse case issuing `POST /api/managed/memories` when active. No coverage lost.

**Ruling 4 — reordered the gate assertions after measuring, not after reasoning.**
The reviewer raised the loading-transient concern as *plausible*. Running the discriminating
mutation (`writable: true`) showed something worse and definite: the test died at the
`'Read only.'` note, so the two absence assertions below it were **never reached** and had
never been proved able to fail — the ordering trap `hosted-paths.spec.ts` documents. Absences
now come first; the same mutation dies on `'New memory'`. That also settles the transient:
`toHaveCount(0)` would pass instantly during loading, so it can only fail because the export
assertion above it already waited for the workspace to render. The note is now unproven
against *that one* mutation but remains a live assertion that fails if the note is removed or
renamed, and it was separately shown able to fail during the first mutation run.

**Ruling 5 — fixed a comment that cited coverage by a name the repo does not contain.**
Both specs pointed at "src/hostedApi.test.ts (mutation M2)". Grep found `M2` nowhere but in
those two comments; the label came from a review document. The coverage exists, so nothing was
missing, but a reader searching for it found nothing. Both comments now name the real
`describe` block. Cost if wrong: a comment, revertable.

### Out-of-plan work completed 2026-11-03: landing logo resolution

User-reported: the Cortex logo read soft on the landing page. Commit `c137525`.

Diagnosed as density, not asset quality: `cortex-lockup-hero.png` is 560x520 and was painted
at 420px, so 1.33x — under 2x on HiDPI. **Regeneration cannot fix it.** The asset already
holds every pixel the master has: `cortex-brain-compact-transparent.png` carries a 549x509 ink
bbox inside its 1280x670 canvas (measured independently, twice, agreeing within 2px), so the
shipped asset samples it at ~1.0:1. A dispatched agent measured an 840px export as
interpolation — mean alpha delta 1.55/255 against a plain LANCZOS resize of the 560, 97.4% of
pixels within 16 — and correctly refused to ship it.

Operator chose: cap the mark at 280px, where 560/280 is exactly 2.00x. Implemented, which also
made the narrow-viewport override redundant (removed).

**It fixed an unreported second case.** `landing.spec.ts` now asserts
`naturalWidth / renderedWidth >= 2` as a ratio, so the guard survives a change to either the
asset or the cap. Proved able to fail by restoring the 420px cap — and it went red at
**1.944x on a 320px viewport**, not the expected 1.33x, because there the mark is
container-bound at 288px. Small mobile was therefore also marginally soft. The 280px cap
covers it.

The old desktop floor `width < 600 ? 220 : 380` encoded the previous 420px cap, so it is now a
single floor of 220 at every width. Both the CSS and the test carry a note that the cap may be
raised only with a vector or genuinely >=840px export of the same lockup.

`cortex-mark.png` (256x256) was found to have no `src` reference anywhere in `src/` — a dead
asset. Left in place; deletion was outside the brief.

### Phase 1 Task 1 — characterise session auth (2026-11-03, inline execution)

Task 1: Ruling: the plan says *create* `tests/conftest.py`; it already exists, created by
Phase 5 Task 1 under the amended execution order. Extended it with `tmp_home` and
`frozen_clock` instead of creating it. Cost if wrong: nil — the plan itself moved fixture
ownership to Phase 5 Task 1.
Task 1: Ruling: `frozen_clock` patches `datetime` in **both** `accounts` and `ingest_tokens`.
Expiry is written as an absolute `expires_at` by one module and compared by the other, so
shifting one alone would expire a session the issuer never dated. Cost if wrong: a test could
miss a real expiry bug that only shows when the two clocks disagree.
Task 1: three mutation proofs, each reding exactly one test as the plan predicts — dropped
`expires_at` comparison -> expiry test only; no-op `revoke_account_session` -> revocation test
only; role-narrowed scopes (Task 2 previewed) -> the scope-gap test only.
Task 1: complete (commits f474054..742a99c, tests: uv run pytest tests/test_account_sessions.py -> 3/3 pass)

Task 2: Ruling: the plan asserts a read-only session "holds memory:write". It does not —
both readers of scopes_json (ingest_tokens.py:158 and :204) pass it through effective_scopes,
which intersects with the role, so the plan's test passed before any implementation existed.
Retargeted the test at the STORED row, where the over-grant is real, and kept the effective
assertion as a regression guard. Cost if wrong: nil — the narrowing is strictly tighter than
before, and an admin test pins that "*" still expands.
Task 2: Ruling: no "viewer" role exists in ROLE_SCOPES (reader/writer/operator/reviewer/admin);
the plan's VIEWER_EMAIL is `reader`, the narrowest real role. Cost if wrong: the test names a
different role than intended, but it is the only role granting read without write.
Task 2: Finding (not fixed, outside this task): effective_scopes resolves against the session's
STORED roles_json, so demoting an account's role does not narrow a session already issued —
the holder keeps the old authority until expiry or revocation. Belongs with Task 3's rotation.
Task 2: complete (commits 742a99c..b031c52, tests: uv run pytest -> all green except the known-local
test_store sqlite_vec case, which CI run 41622243259 passed, proving it local-only)

### Milestones 2026-11-03
CI run 41622243259 (workflow_dispatch on branch HEAD): **both jobs success** — first CI green
this branch has had. Playwright at current tip: 198 passed (31.6m). PR #75 open as a draft.

Task 4: Ruling: the test already existed, written by Phase 5 Task 1 in test_managed_ingest.py
before test_managed_keys.py existed, and its report flagged the duplicate. Moved it to the
planned home rather than writing a second copy, and wrote no xfail marker — under the amended
order the ingest route exists, so the plan's strict xfail would have failed the suite. Cost if
wrong: a test lives in a different file than a reader expects; a comment points at it.
Task 4: mutation proof — making the token query stop consulting revoked_at reds it.
Task 4: complete (commits b031c52..8f071c1, tests: uv run pytest tests/test_managed_keys.py tests/test_managed_ingest.py -> 11/11 pass)
Task 3: HELD — not started. It shortens the session TTL on the one path that can sign out
every pilot user, and neither plan nor spec names a lifetime ("short-lived" only). Operator
asked for a number, and SOUL.md reserves Devil's Advocate for security/identity boundary
changes. Proceeding to Task 5, which is independent.

Task 5: Steps 1-5 complete (commit c442d41): nine auth rows in hostedApi.ts, vitest 372/372,
tsc clean, mutation (drop the login row) reds the mapping test. Steps 6-7 (401 reset +
deleting the HostedLanding duplicate surface) DELEGATED to a subagent, operator-authorised.
Task 5: Ruling: none of the auth rows carries `write: true`. That flag refuses a call when the
subscription is not writable, and authenticating is not a workspace write — a read-only
subscription must still be able to sign in and out. hostedFetch attaches CSRF and an
Idempotency-Key to every POST anyway. Cost if wrong: nil; the guard it skips is an entitlement
check, not an auth check.
Task 5: Ruling: /api/auth/csrf stays unmapped, with a test pinning that. Managed carries its
CSRF token in the login and me payloads; mapping it would invent a route. Cost if wrong: a
hosted caller that needs a standalone CSRF fetch would fail loudly rather than silently.

Task 3: PARTIAL (commit 123384f). Rotation + one-constant TTL plumbing landed with four
mutation proofs. The SHORTENING IS NOT DONE, deliberately:
Task 3: Ruling: left ttl at 24h. The plan pairs "shorten" with "add rotation so shortening is
survivable", but rotation has NO caller — no client code calls it and no route exposes it. A
shorter TTL with no caller does not become survivable; it just signs pilot users out ~3x more
often, against the constraint "no pilot user is signed out by a migration" in spirit. The
lifetime is also unnumbered in both plan and spec ("short-lived" only), so the number is an
operator decision. Cost if wrong: the phase's "TTL is short" clause stays open; nothing
regresses, and the plumbing means the change is now a one-line constant edit.
Task 3: BLOCKER: the Devil's Advocate review SOUL.md requires for an authentication-boundary
change cannot be run — the connector authenticates but the engine returns ENGINE_NOT_IN_PLAN
(needs a paid plan or trial). I earlier told the operator this gate was unblocked by the
authentication; that was wrong. Phase 5 Task 3's DA gate is blocked the same way.
Task 3: Finding: MUT B (rotation skipping verify_token_record) left
test_rotating_a_revoked_session_is_refused GREEN — account_for_token already rejects a revoked
row, so that test was doubly guarded and unproven until MUT E dropped both guards. A mutation
that reds only some of the tests it should is itself a finding.

Bootstrap account (operator's chosen unblock path, not a numbered plan task):
`xibalba-cortex-operator bootstrap-account` — create + approve + set role in one step, no email.
7 tests, all RED first on "unknown command: bootstrap-account" except the argv-refusal
characterisation (argparse already rejects --password; a passing first run is correct there).
Six mutation proofs, each redding the expected test: A drop approve_account, B drop
set_account_role, C drop the role guard, D invent a password when none is supplied, E treat an
existing account as new (password reset), F leak the password into the auth-event detail.
Finding: MUT A redded ONLY the idempotency test, not the fresh-account sign-in test. The
`accounts` schema defaults are already email_verified=1 / approval_status='approved', and
`create_account` does not override them, so `approve_account` earns its place only on the
repair path — rescuing the pending account `managed/control.py:99` leaves behind. The
fresh-account assertion is therefore double-guarded and does not prove approval happens.
Ruling: left it in. It documents the intent and is the assertion that would catch a future
schema-default change. Cost if wrong: one test that passes for two reasons instead of one.
Two accounts.py additions were needed and are public, not private helpers: `set_account_role`
(validates against ROLE_SCOPES, because `issue_account_session` silently falls back to
"operator" for an unknown role) and `account_status` (the sign-in gating fields;
`active_account_by_email` returns identity fields only, so callers were reading the table).
Suite: 2 failures, both pre-existing and unrelated. test_store.py sqlite_vec DROP TABLE on a
vec0 virtual table is the established local-only failure (CI's pytest job passes).
test_local_api.py context_assemble is the established load-sensitive one; it passes alone.

AUDIT 2026-11-03 (operator asked for one before continuing):
Phase 1 is MERGED and DEPLOYED. PR #76 merged externally 13:35:35Z carrying Tasks 1-5 and the
bootstrap command; origin/main is now 29 commits past it and Render auto-deploys every merge
(cortex-managed-pilot deploy for b4d5e23 live 14:26Z; 66d0eeb in progress at audit time). The
plan's checkboxes are still unticked and are NOT evidence of anything -- the ledger is.
Task 5: complete. Steps 1-5 in c442d41, Steps 6-7 in a1101a4, nine mutation proofs (M1-M9),
recorded in phase1-task5-report.md. That report ends in a literal FULL_SUITE_PLACEHOLDER: the
agent was killed by the 5-hour limit while running the full Playwright suite, so the one
unfilled line is the whole-suite result. Everything else in it is backed by quoted output.
The agent also recorded one thing it could NOT prove able to fail -- the hosted gate change
itself -- and said so rather than claiming the proof. Its converse IS measured.
README: audited, not taken on trust. The rewrite (cdba96c) is accurate where it cites, but
every citation was a file:line pair and NINE had already rotted against current main in the 29
intervening commits (store.py:4923 -> a dict literal; accounts.py:213 -> a blank line).
Ruling: stripped all 27 line numbers and kept the symbol names, which do not rot. Verified
15/15 symbols, 44/44 tool names, 66/66 paths, and the 54+27+8=89 family split counted from the
decorators. Cost if wrong: a reader navigates by grep instead of by line number.
Finding: a straight cherry-pick onto main DELETED main's two newer README sections
(b5a2ea7 production status, 97c0c90 retention policy) -- the most honesty-critical content in
the file. Spliced them back, and found the same drift class inside them: "80-tool MCP surface"
(it is 89), and an evidence citation to /home/xibalba/Documents/CORTEX_STORAGE_DRILL_*.json --
an absolute path in a maintainer's home directory, not in the repo, and NOT PRESENT on this
machine. Corrected both; the line now states it is unverifiable and names the reproducing
command. This is the third instance of the pattern the memory feedback_audit_docs_need_runnable
_evidence records. Opened as PR #85 rather than pushed to the shared branch.
Open operator decisions unchanged: the TTL number (Task 3 PARTIAL), the Devil's Advocate
plan/trial (ENGINE_NOT_IN_PLAN still blocks Phase 5 Task 3 Step 0), and the sk_test_ Stripe key
that wants rolling.

FULL_SUITE_PLACEHOLDER resolved: full viewer Playwright suite 206 passed / 0 failed in 24.1m.
Measured on current origin/main plus Phase 2 Task 1, NOT on the tree the Task 5 agent was
running when the limit killed it -- a stronger base, not the identical measurement. Recorded
as such rather than backfilled into that report as if it were the same run.

Phase 2 Task 1: complete (commit ce3996e, PR #86, tests: npx vitest run -> 387/387 and
CI=true npx playwright test -> 206/206). Gate fires on a definite zero only; hasAgents is
true/false/null and null does not gate. Eight mutation proofs (A-E behavioural, F-H on the
probe), each redding the expected test.
Finding: TWO of the eight mutations exposed defective tests of mine, not defective code.
(1) Asserting the graph canvas is ABSENT when a page is open cannot fail -- ConsoleApp renders
a page in a drawer over a still-mounted, still-visible lens, so the canvas is there either way.
(2) The negative test was racing: `.not.toHaveURL(/agents/)` and `toHaveCount(0)` pass
instantly against a URL that has not changed YET, and the gate fires ~1s later when the load
resolves. MUT C (guard removed) left it green through three separate runs before I added an
assertion to the mutation harness and proved the mutation really had applied -- the harness
itself was the third defect: a bare str.replace() no-ops silently when the pattern misses.
Ruling: every mutation script now asserts its own pattern count before writing. Cost if wrong:
a mutation that silently fails to apply reads as "the test cannot fail" and retires a real gap.
Regression caused and fixed in the same task: data.test.ts mocks `api` and had no `agents`, so
the new probe broke three existing tests. Its null case now carries an assertion, not a mock.

Phase 2 Task 2: complete (commit 233dfcc, PR #87, tests: uv run pytest tests/test_enrollment.py
-> 19/19). Twelve mutation proofs (A-L), each redding exactly the expected tests.
Task 2: Finding: MUT A (signature verification removed) reds ONLY the two malformed-signature
tests. The wrong-key tests -- INCLUDING the plan's own example test, whose name attributes them
to the signature -- are held by the DID-to-public-key fingerprint comparison instead.
did:integrity:<hex> is SHA-256 over the raw Ed25519 key, so without that comparison an attacker
signs the code with their own key, presents a victim's DID beside it, and the signature
verifies perfectly against the wrong identity. The plan's framing of its own test is wrong
about which mechanism protects it; both now exist and both are separately proven (MUT A, MUT C).
Task 2: Ruling: added a REDEEM route the plan's Files list does not name. Redemption cannot be
client-local -- the code table is server-side. It is deliberately unauthenticated: a
first-time-enrolling agent holds no bearer token and lacks the operator role, so the code plus
the signature IS the credential. Mitigated by the rate limit (10/60s/home), by uniform
refusals, and by keeping the ISSUE route operator-gated. Handled before the auth preamble as
/api/contact already is. Cost if wrong: an unauthenticated POST a flood could use to burn a
live code's remaining TTL.
Task 2: BLOCKER (same as Task 3 and Phase 5 Task 3): SOUL.md wants a Devil's Advocate review
before an identity-boundary change. ENGINE_NOT_IN_PLAN. The gate is UNMET, not passed.
Task 2: Finding: two more defective tests of my own, caught by mutations, same class as Task 1
-- a fixed-width window after a route marker swallowed the NEXT branch's gate call, and the
redeem branch is an `if ... return` before the auth preamble so splitting on the next
`elif parts ==` ran past it. Both windows now end where the branch ends. Three tasks in a row
have produced source-inspection tests that passed vacuously until a mutation was tried. The
pattern is mine, not the plan's: any test that locates code by offset rather than by boundary
should be assumed vacuous until a mutation says otherwise.
