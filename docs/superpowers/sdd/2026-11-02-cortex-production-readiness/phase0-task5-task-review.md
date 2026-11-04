# Phase 0 Task 5 — task review

Reviewer: task reviewer (read-only). Range reviewed: `d946fc1..HEAD`
(`7f96180`, `8a38002`, `ef9da85`, `b115f2f`). No code was changed.

## Verdict A — Spec compliance: **PASS (with one deviation, non-blocking)**

Everything the brief and the two controller corrections required is present, and both
controller rulings hold up under reading.

Checked and confirmed:

| Requirement | State |
|---|---|
| Un-`fixme` both disabled tests, re-home selectors | done (`managed.spec.ts:51`, `:109`) |
| Keep the disabled-until-DIDs rule | done, and **strengthened** — now asserts disabled→enabled, which the old test never did |
| Keep the `agent_ids` request-body assertion | done (`managed.spec.ts:~88`) |
| Keep the key-never-in-`localStorage` assertion | done |
| `git rm` the three second-UI files | done (but see Finding 4 for *which* commit) |
| Remove every `xc-managed-*` outside `BillingPage` | **verified by me**: `grep -rn "xc-managed-" viewer/src` is silent; `managed.css` was imported only by `ManagedApp.tsx`, so the deletion orphans nothing — `HostedLanding` already uses `xc-landing-grid`/`xc-kv`/`xc-landing-card` |
| Prove the one-app property can fail | done, via a substituted test (Ruling 2) |
| Report why each dropped assertion was markup, not behaviour | done, six entries, all accurate |

**Ruling 1 (rename `managed` → `hosted` rather than remove): CORRECT.** Confirmed
`HostedLanding.tsx:122` is the only remaining caller and is live; the prop drives the hosted
eyebrow/lead/CTA/`how` copy, the hosted `primitives` and `facts` arrays, and
`ProductSections showPricing={!hosted}` (`Landing.tsx:124`). Removing it would have deleted the
hosted landing's copy and re-shown the self-hosted pricing section next to the hosted plan
cards. The rename is the minimal safe change and all call sites were updated
(`grep -rn "<Landing" src` → 2 callers, both correct). *Nit only:* `hosted` now collides
nominally with `useConsole().hosted`, which is a session-capability flag, not a copy variant.
Not worth a change.

**Ruling 2 (prescribed mutation didn't go red; added `.xc-shell` test): CORRECT, and the
substitute is a genuine tripwire.** Verified independently:
- `design-system.spec.ts:727-738` pins `.xc` plus "Sign out"-or-"Open operator profile
  settings". `git show 7f96180~1:viewer/src/console/ManagedApp.tsx` renders `<div className="xc">`
  (lines 139, 166, 167, 169) and its own sign-out control, so the sweep genuinely could not
  notice the second app. The implementer's Concern 2 is accurate, not an excuse.
- `.xc-shell` is rendered in exactly one place in the tree: `ConsoleApp.tsx:82`. The deleted
  `ManagedApp.tsx` contains no `xc-shell` at all. So under the recorded mutation the new test
  must go red, exactly as reported.

**Deviation:** the brief's Step 7 commit (`feat(viewer): one app, and it is the console`) does
not exist; the UI deletion rode in on a docs commit. See Finding 3.

## Verdict B — Task quality: **NEEDS FIXES — one blocking**

One assertion in the re-homed read-only test cannot fail, and the report records it as a
strengthening. That is precisely the defect class this codebase treats as a defect, and a
sibling test in this same suite documents the trap in a comment. Everything else is sound or
minor.

---

## Findings — CONFIRMED by reading code

### 1. BLOCKING — `managed.spec.ts:122` asserts something that cannot fail, and the report calls it a strengthening

**Where:** `viewer/e2e/managed.spec.ts:122`
```ts
expect(calls.filter((call) => call.path === 'memories' && call.method === 'POST')).toHaveLength(0)
```
**What is wrong:** the test never attempts a write. The write controls are absent (`New memory`
and `Import a document` are asserted at count 0 two lines earlier), so no POST could occur
whether or not the read-only gate exists. Worse, `hostedApi.ts:354` refuses hosted writes
client-side before the network, so even an attempted write would not reach `calls`. The
assertion holds under every mutation of the gate.

**Why it matters:** this is not a hypothetical. `viewer/e2e/hosted-paths.spec.ts:155-158`
already carries this exact decision, in a comment, in this same suite:

> *"Deliberately NOT asserting 'no POST memories': under read-only nothing here attempts a
> write, so that assertion holds with or without the gate. The gate on the CALL is proved in
> `src/hostedApi.test.ts` (mutation M2), where a write IS attempted."*

The new test adds back the assertion that an adjacent test refused, and
`phase0-task5-report.md:32` records it as *"writes refused, strengthened to 'no POST memories
reached the server'"*. A check incapable of failing has been reported as coverage. Standing
rule violated.

**Smallest fix:** delete the line and replace it with the same pointer comment
`hosted-paths.spec.ts` uses, and correct the report line. Two edits, no behaviour change. (The
real write-gate coverage already exists in `src/hostedApi.test.ts`; nothing is lost.)

### 2. Minor — the e2e comment claims de-duplication and comma-splitting that this test does not exercise

**Where:** `viewer/e2e/managed.spec.ts:77` (the comment) and `:72` (the `fill`); the body assertion it describes is `:79`
**What is wrong:** the input is `'did:integrity:test-agent-one\ndid:integrity:test-agent-two'`
— two distinct DIDs, one newline, no duplicate, no comma. The comment says *"de-duplicated and
split on newlines or commas"*. Only newline-splitting is exercised.
**Why it matters:** the comment overstates what goes red. Mitigating: the parser itself *is*
covered at unit level — `src/console/hostedWorkspace.test.ts:31` covers comma + whitespace +
blank runs and `:37` covers de-duplication — so no behaviour is unguarded. This is a misleading
comment, not lost coverage.
**Smallest fix:** change the fill to
`'did:integrity:test-agent-one\ndid:integrity:test-agent-two, did:integrity:test-agent-one'`.
The expected body is unchanged, and the comment becomes true.

### 3. Minor (history hygiene) — the production-UI deletion landed inside a docs commit whose message does not mention it

**Where:** commit `7f96180`, subject
`docs(plan): run Phase 5 Tasks 1-2 right after Phase 0 for an earlier test deploy`
**What is wrong:** that commit deletes `ManagedApp.tsx` (265 lines), `ManagedLenses.tsx` (61)
and `managed.css` (45) alongside a plan-document amendment. Its message describes only the
amendment. The brief's Step 7 commit never happened. The implementer discloses this at
`phase0-task5-report.md:3-5` and attributes it to a concurrent commit on a shared worktree.
**Why it matters:** `git log --oneline -- viewer/src/console/ManagedApp.tsx` points at a docs
commit; reverting the plan reorder would resurrect the second UI; `git bisect` on a viewer
regression lands on a commit that claims to touch no code. Nothing is functionally wrong.
**Smallest fix:** squash-merge the PR, or name the deletion explicitly in the PR body. Note that
`7f96180` is the *oldest* of the four commits in range, so `git commit --amend` cannot reach it —
rewording it would mean rebasing `8a38002`, `ef9da85` and `b115f2f` on a shared worktree, which is
not worth it. I did not change history.

### 4. Minor — `.xc-managed-inner` toHaveCount(0) is currently incapable of failing, and two of the shell test's three assertions were never reached by the recorded mutation

**Where:** `viewer/e2e/managed.spec.ts:217` (the vacuous one); `:215` is the proven assertion and `:216` the unreached one
**What is wrong:** `grep -rn "xc-managed-" viewer/src` is now silent, so the class exists nowhere
in the tree; the assertion is permanently true except under the specific restore-the-second-app
mutation (where `ManagedApp.tsx:169` does render it). And because the mutation reds the test at
`:215` (`.xc-shell`), neither `:216` (`.xc-page-tabs` Billing) nor `:217` (`.xc-managed-inner`)
was actually exercised red.
**Why it matters:** low. The `.xc-shell` assertion alone carries the property and is proven. The
Billing-in-page-tabs assertion is independently proven able to fail by the sibling test
`managed.spec.ts:248` ("hosted capabilities survive a declaration that dropped billing"), which
asserts count 0 under a narrowed destination list. So no coverage claim here is false — the
assertions are redundant, not vacuous-and-counted.
**Smallest fix:** none required. If anything, drop `:217` as noise.

### 5. Minor — the shell test's comment overclaims; `.xc-shell` is rail-layout-only

**Where:** `viewer/e2e/managed.spec.ts:207-211` (comment, specifically `:209`), vs `ConsoleApp.tsx:78-88`
**What is wrong:** `.xc-shell` renders only when `!phone && settings.shell === 'rail'`. The
comment calls it *"the thing only the console renders"* — true of the console vs the second app,
but not true across the console's own top-bar and phone layouts, each of which renders no
`.xc-shell`.
**Why it matters:** if the default shell ever changes to `topbar`, this test fails as a false
red rather than silently passing, so the failure mode is safe. Only the comment misleads.
**Smallest fix:** amend the comment to say "the rail shell, which the console's default layout
renders and no second app did".

### 6. Minor (docs accuracy, controller's own commits)

I checked `7f96180`'s factual claims against source rather than its style, as instructed. **All
verified accurate:**
- `ManagedControl.consume(tenant, meter, *, request_key=None, fingerprint="")` at
  `src/xibalba_cortex/managed/control.py:183`; the atomic
  `UPDATE usage SET amount=amount+1 … AND amount<?` + `rowcount`-guarded `LimitExceeded` at
  `control.py:200-202`; read-only refusal at `control.py:191-192`; idempotency via
  `request_key`+`fingerprint` with an `hmac.compare_digest` mismatch check at `control.py:193-198`.
- `max_memories` via `GraphStore` quotas in `control.store()` at `control.py:229`.
- Routes calling it at `api.py:161, 369, 378, 405, 426` — all five present and exact.
- `LimitExceeded` mapped at `api.py:491` (→429) and registered at `api.py:534`.
- Path-escape and tenant-id-shape validation at `control.py:216-224`.
- `tests/conftest.py` genuinely does not exist, as the amendment states.

`ef9da85` records a manual credentialed Stripe run. It is internally consistent and explicitly
says it is not a regression gate; it is unverifiable from the repo by construction, so I do not
grade it.

**One inaccuracy, inherited from the brief's controller note 5**, not from these commits:
*"A `--project=desktop` run skips the rail and phone projects this branch added tests for."*
`playwright.config.ts:64-68` defines exactly two projects — `desktop` (which `testIgnore`s only
`phone.spec.ts`) and `phone` (which `testMatch`es only `phone.spec.ts`). There is no `rail`
project, and `--project=desktop` skips nothing but `phone.spec.ts`. The implementer ran the full
suite anyway, so nothing was missed; the note should be corrected before it misleads a later task.

---

## Findings — PLAUSIBLE, need checking

### P0. Important if confirmed — the read-only test's absence assertions sit in a window where they could pass on a *writable* workspace

**Where:** `viewer/e2e/managed.spec.ts:111` (export), `:112` (the note), `:113-114` (the two absences)
**What is wrong:** `workspace.canWrite` is `selected?.writable === true` (`workspace.ts:190`),
and `selected` is `null` until `api.agents` resolves — which on hosted is `GET /api/managed/me`
reshaped by `workspaceFromMe` (`hostedApi.ts:133`, `:155-161`). Until that promise lands,
**every** hosted workspace, writable or not, renders the `role="note"` "Read only. …" text and
no `New memory` / `Import a document` buttons (`MemoriesPage.tsx:124-130`). The first assertion
in the test, `Export memories` enabled (`:111`), does **not** wait for the workspace — export
renders on `hosted` alone (`MemoriesPage.tsx:123`). I confirmed the code path (there is no
`loaded` gate anywhere in `MemoriesPage.tsx`); what I have **not** measured is whether Playwright
actually lands inside that window, which is why this sits under PLAUSIBLE.

**Why it matters:** if they resolve on the transient, the entitlement gate was never measured,
and the test would stay green with `writable: true`. Note that `hosted-paths.spec.ts:141`
has the same shape, so this is a pre-existing pattern rather than something newly invented —
but it is the pattern the implementer was asked to prove, and it was not proved: the recorded
mutation restored `main.tsx`'s edition fork, which reds this test for a completely different
reason (`New memory` never exists in `ManagedApp`), so it tells us nothing about the gate.

**Mutation that would prove it, and how to read it:** set `writable: true` in this test's fixture
(`managed.spec.ts:109`). The test cannot stay green either way — `:124` asserts
`This workspace is read-only.`, which `BillingPage.tsx:52` renders straight from
`me.entitlement.writable` and so is immune to the race. **Where it fails is the discriminator:**
red at `:112` (or `:113`/`:114`) means the entitlement gate is genuinely measured; red *only* at
`:124` means `:111-114` all passed on the loading transient. Alternatively run the mutation with
`:123-124` deleted, which makes the result unambiguous.

**Smallest fix:** move `:112-114` to *after* the search block (`:116-121`). That **narrows** the
window substantially rather than closing it — the agents fetch and the list fetch are independent,
so there is no happens-before — but it costs one block move and no new selectors. Closing it
properly would need a positive anchor that only appears once `api.agents` has resolved.

### P1. Search-filter assertions could in principle ride a loading transient — **mostly ruled out**

I checked this and it is largely safe: `MemoriesPage.tsx:90-94` passes `{ keepData: true }` to
`useAsync`, so during the search reload the *previous* rows (including `Seeded memory 0`) remain
rendered. The negative assertion `expect(list).not.toContainText('Seeded memory 0')` therefore
cannot pass on an empty transient — it must wait for the filtered payload. The fixture's own
filter (`managed-fixture.ts:58-59`) only applies when `q` is present, so the assertion really
does prove the console forwards `q`.
**Residual risk / mutation to confirm:** drop `'q'` from `keep` on `GET /api/memories` at
`src/hostedApi.ts:114` and re-run both re-homed tests. Expected red on both negative assertions.
If green, `keepData` is not doing what I read it to do. Cheap to run and worth one targeted run.

### P2. `Show API keys` → `Revoke key` click sequence may be order-dependent

`managed.spec.ts:81-82` clicks `Show API keys` then immediately `Revoke key`. `list()` and
`revoke()` both route through `run()`, which sets `busy` and disables `Revoke key`
(`AgentsPage.tsx:180`). Playwright's actionability wait should absorb this, and the full suite
passed, so this is a flake risk rather than a bug. Worth watching across CI runs rather than
changing now.

### P3. Overlap with an existing test

`managed.spec.ts:109` ("read-only subscriptions retain export and search without permitting
writes") substantially duplicates `hosted-paths.spec.ts:141` ("a read-only hosted subscription
offers no write control and says why"): both assert export enabled, `New memory` absent, and
read-only copy at `/managed#memories` on the same fixture. The new test adds the search-filter
check, `Import a document` absence, and the Billing-page `READ_ONLY_WORKSPACE` copy, so it is not
redundant — but the two should probably be consolidated when someone next touches either, with
the entitlement assertions living in one place. Not a defect in this task.

---

## Lost coverage from the six dropped assertions: none found

Each dropped assertion was re-homed onto a check I could trace to real behaviour:
- `Memory saved with a verifiable event history.` → `/Memory \S+ added to/` from
  `MemoriesPage.tsx:139`. Equivalent.
- `.xc-managed-results` → `getByRole('region', {name: 'Memory list'})` (`:61`, `:116`), the `aria-label` at
  `MemoriesPage.tsx:172`. Equivalent, and now a stronger claim because the search actually filters.
- `.xc-managed-key` → `[aria-label="New API key"] code` (`:75-76`), `AgentsPage.tsx:170-171`. Equivalent,
  and the revoke-clears-the-token path is real (`revoke()` calls `setToken('')`,
  `AgentsPage.tsx:151`).
- `Save memory` disabled → `New memory`/`Import a document` count 0 plus the `role="note"` copy.
  Behaviourally equivalent (the console removes rather than disables), subject to Finding 2.
- `Search / list` enabled → an actual executed search. Stronger.
- `getByLabel('Memory')` / `'Search memories'` → the console's own labels. Equivalent.

Two assertions are genuinely **new and valuable**: `Create API key` proved
`toBeDisabled()`→`toBeEnabled()` across the DIDs fill (`:71-73`) (the old test only clicked it, which is
how it burned 90s twice on PR #72), and `keys/revoke` POSTed exactly once (`:85`).

## Blocking summary

**Finding 1 blocks.** It is a one-line deletion (`managed.spec.ts:122`) plus a one-line report
correction. Nothing else in this diff needs to change before merge; **P0** should be investigated
in the same pass, because the fix is a block move and because the task's whole premise was proving
the checks can fail.

Count: **1 blocking** (F1); **5 minor, confirmed** (F2-F6); **1 important if confirmed,
plausible** (P0); **3 minor, plausible** (P1-P3).
