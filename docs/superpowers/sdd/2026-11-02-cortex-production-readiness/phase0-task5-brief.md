### Task 5: One app root — delete the second UI

**Files:**
- Modify: `viewer/src/main.tsx`
- Modify: `viewer/src/console/ConsoleApp.tsx` (resolve destinations from the server)
- Modify: `viewer/src/console/Landing.tsx` (drop the `managed` prop)
- Delete: `viewer/src/console/ManagedApp.tsx`
- Delete: `viewer/src/console/ManagedLenses.tsx`
- Delete: `viewer/src/console/managed.css`
- Test: `viewer/src/console/nav.test.ts`, `viewer/e2e/design-system.spec.ts`,
  `viewer/e2e/managed.spec.ts`

**Interfaces:**
- Consumes: `destinationsFrom` and `tabsFor` from Task 2, `BillingPage` from Task 3,
  the `destinations` field from Task 1.
- Produces: nothing later tasks consume; this is P0's deliverable.

- [ ] **Step 1: Write the failing tests**

Add to `managed.spec.ts`, replacing assertions that named `xc-managed-*` layout: after
sign-in at `/managed`, the console shell is present and the rail lists Billing.

```ts
await expect(page.locator('.xc-shell')).toBeVisible()
await expect(page.getByRole('button', { name: /^Billing\b/ })).toBeVisible()
await expect(page.locator('.xc-managed-inner')).toHaveCount(0)
```

- [x] **Step 2: Run them and confirm they fail**

Run: `cd viewer && npx playwright test e2e/managed.spec.ts --project=desktop`
Expected: FAIL — `.xc-shell` absent at `/managed`, because `ManagedApp` renders
`.xc-managed-inner` instead.

- [x] **Step 3: Boot one app and consume the declaration**

In `main.tsx`, delete the `managed` constant and the conditional import; always render
`ConsoleApp`. In `ConsoleApp.tsx`, read `destinations` from the session payload, resolve it with
`destinationsFrom`, and pass that list to `destinationsIn`, `primaryDestinations` and
`tabsFor`, and `builtFrom(list)` to `parseRoute`.

- [ ] **Step 4: Delete the second UI**

```bash
git rm viewer/src/console/ManagedApp.tsx viewer/src/console/ManagedLenses.tsx \
       viewer/src/console/managed.css
```

Then remove `Landing.tsx`'s `managed` prop and every remaining `xc-managed-*` reference
outside `BillingPage`.

- [ ] **Step 5: Confirm the suite — including Task 4's red test — is green**

Run: `cd viewer && npm run build && npm run lint && npx vitest run && npx playwright test --project=desktop`
Expected: PASS, and specifically `-g "hosted workspace"` now green. If it is still red,
the violations are real grammar bugs in the consolidated UI: fix the UI, never the sweep.

- [ ] **Step 6: Confirm no managed layout class survives**

Run: `grep -rn "xc-managed-" viewer/src | grep -v BillingPage`
Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(viewer): one app, and it is the console"
```

---

## Execution status — recorded 2026-11-02

Checkboxes above were never ticked as the work was done, which is why the spec's status line
read "not yet implemented" when in fact most of P0 had landed. Reconstructed from
`git log main..HEAD` and verified against the working tree:

| Task | State | Evidence |
|---|---|---|
| 1 — hosted server declares its destinations | **done** | `b2b459e` |
| 2 — `nav.ts` resolves a server-declared set | **done** | `e84105e`, `35c31c0`; `state.tsx:128` calls `builtFrom` |
| 3 — billing becomes an ordinary console page | **done** | `d084ec2`, `f1527dc` |
| 4 — grammar sweep covers `/managed`, proved red first | **done** | `aa85a65`, `1238e8d` |
| 5 — one app root, delete the second UI | **step 3 done; steps 1, 2 and 4-7 NOT done** | `1d07f89`, `096a205`; `main.tsx` boots `ConsoleApp` unconditionally |

Correction: an earlier revision of this section ticked Task 5 steps 1-3. Step 3 (boot one
app, consume the declaration) did land. **Step 1 did not** — `grep -n -e 'xc-shell' -e
'xc-managed-inner' viewer/e2e/managed.spec.ts` returns nothing, so the replacement
assertions were never written, and step 2's recorded failure never happened either. The
three `ManagedApp.tsx` mentions still in that file are explanatory comments, not
assertions. Step 1 is therefore the next action, before the deletion, exactly as ordered.

Work landed on the branch that this plan did not call for, and which P1 should account for
rather than re-specify: the hosted data layer (`hostedApi.ts`, `89f3c37`, with the
self-hosted wire contract recorded first in `a23b01e`), API keys and bulk export re-homed
into the console (`c1287a2`), and capability gating in Recall and MemoriesPage (`513ffcf`).

### Resume point: Task 5, Step 4

Still true in the working tree, so the deletion has genuinely not happened:

- `ManagedApp.tsx` (22 KB), `ManagedLenses.tsx` and `managed.css` are all present.
- `Landing.tsx:38` still takes a `managed` prop and branches on it ten times.
- `grep -rn "xc-managed-" viewer/src | grep -v BillingPage` returns ~70 lines, so Step 6's
  check fails today, as it should before the deletion.
- Nothing imports `ManagedApp` or `ManagedLenses` any more: the only surviving references are
  three explanatory comments and `e2e/managed.spec.ts`, which still asserts against
  `ManagedApp.tsx:177` and `:209`. Step 1's replacement assertions are therefore the real
  precondition for the deletion, not an afterthought.

### Blocker cleared

The "Blocked on" section below is satisfied: **PR #73 merged** into `main` at
2026-10-26T07:52:26Z, and `viewer/src/agent0_wallet.ts` and
`src/xibalba_cortex/agent0_integration.py` are both present on this branch. Task 5 may begin.

### Suite state, measured 2026-11-02

- `npx tsc -b` — clean.
- `npx oxlint` — clean (13 pre-existing warnings, 0 errors).
- `npx vitest run` — **368 passed / 368**, after `e9b8819`. One test was red: the WIP commit
  moved the method and path off `HostedUnsupported.message` (which `useAsync` and
  `MemoriesPage` render into a user-visible callout) onto `.call`, and the test still asserted
  the old route-naming message. The test now asserts both halves and was proved able to fail.
- `npx playwright test` — **blocked on local layout, not on code.** `pyproject.toml`'s
  `[tool.uv.sources]` makes `integrity-sdk` an editable path dependency at
  `../integrity-core/integrity-sdk`, and CI satisfies it by checking both repos out as
  siblings. A worktree under `worktrees/xibalba-cortex/<topic>` has no such sibling, so
  `uv run` fails metadata generation before any browser starts.

  **To run the suite from a cortex worktree**, create the sibling the layout assumes:

      ln -sfn /home/xibalba/Projects/integrity-core \
              /mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/integrity-core
      test -f .../worktrees/xibalba-cortex/integrity-core/integrity-sdk/pyproject.toml

  That is the same assertion CI makes (`ci.yml:57`). It is a read-only import path — the
  venv's editable install already resolves there — and the integrity-core base must be
  confirmed still clean afterward. `E2E_PYTHON` overrides `uv run python` for the API server
  but does not help on its own, because `viewer/vite.config.ts` also shells out to
  `uv run xibalba-cortex-ingest-tokens`.

## Blocked on

`agent0_wallet.ts` and `agent0_integration.py` exist only on `origin/local` (PR #73, open
and mergeable) and not on `main`. Task 5 deletes `ManagedApp.tsx`, which PR #73 also
edits. **Merge PR #73 before starting Task 5**, or carry those two files onto this branch
first. PR #73's `ManagedApp` changes are discarded as the duplicate they are; its
`AgentsPage` ERC-8004 directory is what survives.

---

## Controller additions (2026-11-03) — these bind as hard as the text above

**1. Steps 1 and 2 are NOT done.** An earlier status pass wrongly ticked them. Verified:
`grep -n -e 'xc-shell' -e 'xc-managed-inner' viewer/e2e/managed.spec.ts` returns nothing.
The three `ManagedApp.tsx` mentions in that file are explanatory comments, not assertions.
**Step 3 IS done** — `viewer/src/main.tsx` already boots `ConsoleApp` unconditionally and
`state.tsx:128` already calls `builtFrom`. Do not redo Step 3.

**2. Re-home the DID-bound API-key assertion as part of this task.** `managed.spec.ts`
asserts that "Create API key" stays disabled until the Agent DIDs textarea has a value
(`ManagedApp.tsx:209`, `!agentDids.trim()`). Deleting `ManagedApp.tsx` strands that check.
Move it onto the console's API-keys surface in the same commit as the deletion — API keys
were already re-homed into the console by commit `c1287a2`. **Do not simply delete it.**
This exact check hung PR #72's CI for 90 seconds twice; losing it is a regression this
codebase has already paid for once.

**3. Do not run Playwright until the controller tells you the baseline has finished.**
A full-suite baseline run is in flight and binds ports 25190, 28420 and 28431. A second
concurrent run will fail on port conflicts and waste a long cycle. Ask if unsure.

**4. e2e prerequisite, already satisfied — do not re-create it.** The sibling
`integrity-core` symlink at
`/mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/integrity-core` exists. Without it
`uv run` fails metadata generation for the `integrity-sdk` editable path dependency.

**5. Run what CI runs**, not a single project:
`npm run build && npx oxlint src e2e && npx vitest run --maxWorkers=1 && CI=true npx playwright test`
A `--project=desktop` run skips the rail and phone projects this branch added tests for.

**6. Step 6's check must come back silent:**
`grep -rn "xc-managed-" viewer/src | grep -v BillingPage` — no output. There are ~70 such
references today, including all of `managed.css` and `ManagedLenses.tsx`.

**7. Vitest must stay at 368/368 or better.** That is the current measured state.

---

## Controller correction 2026-11-03 — Steps 1-2 as written are STALE. Read this before acting.

Measured, not assumed. Targeted baseline `CI=true npx playwright test e2e/managed.spec.ts
e2e/design-system.spec.ts`: **42 passed, 2 skipped, 0 failed, 6.0m.**

**Step 3 already landed, which invalidates Steps 1-2's premise.** `main.tsx` boots
`ConsoleApp` unconditionally, so **`/managed` already renders the console**. The brief above
says Step 1's new assertions must fail because "`ManagedApp` renders `.xc-managed-inner`".
They will **not** fail — `design-system.spec.ts:727` already sweeps the hosted workspace at
390/1280/1600px and **passes**, and `managed.spec.ts` already drives the console at
`/managed` for 11 tests. `ManagedApp.tsx` is **orphaned dead code**: nothing imports it.

**So the deletion is low-risk cleanup. The real work is the 2 skipped tests.** Both are
`test.fixme` in `e2e/managed.spec.ts` — coverage silently disabled when the console took over
`/managed`, because they assert `ManagedApp`'s classes:

1. **`managed.spec.ts:51`** — stores and searches memory, then creates and revokes an API key.
   Asserts `.xc-managed-results` and `.xc-managed-key`.
2. **`managed.spec.ts:98`** — read-only subscriptions retain export and search without
   permitting writes. Asserts `Save memory` disabled, `Search / list` and `Export memories`
   enabled, and read-only copy visible.

**The console already implements both behaviours** — only the selectors are stale.
`AgentsPage.tsx:155-182` is the re-homed API-keys surface and it preserves the exact rule
that mattered:

- `<label className="xc-field">Agent DIDs` wrapping a `textarea.xc-input--mono`, `required`
- `Create API key`, `disabled={busy || !dids.trim()}` — **the same disabled-until-filled rule
  as `ManagedApp.tsx:209`**, which is the check that hung PR #72's CI for 90s twice
- `Show API keys`; the issued key renders as `code.xc-mono` inside
  `div[aria-label="New API key"]`; each row has `Revoke key`
- read-only copy comes from `READ_ONLY_WORKSPACE` in `src/console/billing.ts`

### Your task, restated

1. **Un-`fixme` both tests and re-home their selectors onto the console's surfaces.** Keep
   every assertion that tests behaviour — especially the disabled-until-DIDs-filled one and
   the `agent_ids` request-body assertion (`{label: 'agent', agent_ids: [...]}` de-duplicated
   and split on newlines/commas) and the assertion that the key never reaches `localStorage`.
   Drop only assertions about markup the console legitimately does not have. **For every
   assertion you drop, say in the report why it tested markup and not behaviour.** Deleting
   an inconvenient assertion is the failure mode here.
2. **Delete the dead code:** `git rm viewer/src/console/ManagedApp.tsx
   viewer/src/console/ManagedLenses.tsx viewer/src/console/managed.css`. Then remove
   `Landing.tsx`'s `managed` prop and all ~10 branches on it (`Landing.tsx:38-114`), and
   every remaining `xc-managed-*` reference outside `BillingPage`.
3. **Prove the one-app property can fail.** Since the assertions pass already, the mutation
   is on the source: temporarily restore the edition fork in `main.tsx` so `/managed` boots
   `ManagedApp`, confirm the hosted grammar sweep and your re-homed tests go **red**, then
   restore. Record the command and the failure in your report. Without this, the suite
   proves nothing about the property — a passing sweep that cannot fail has measured nothing.
4. **Verify:** `grep -rn "xc-managed-" viewer/src | grep -v BillingPage` must be **silent**.
5. **Run what CI runs:** `npm run build && npx oxlint src e2e && npx vitest run --maxWorkers=1
   && CI=true npx playwright test`. Vitest must stay at **368/368 or better**. The full
   Playwright suite is 197 tests and takes ~2h — start it, let it run, do not kill it.
6. Commit. Use `git rm`, not `rm`.

**Playwright is now free** — the baseline has finished. No other run is in flight.
