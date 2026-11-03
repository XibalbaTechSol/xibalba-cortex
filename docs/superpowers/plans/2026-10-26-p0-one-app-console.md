# P0 — One App, And It Is The Console: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the second UI so that one application — the console — serves both the
self-hosted and hosted editions, with the hosted edition's navigation narrowed to the
destinations its server declares.

**Architecture:** `main.tsx` stops choosing between two app roots and boots `ConsoleApp`
unconditionally. The hosted server declares which destinations it can serve; `nav.ts`
resolves that list through the filter it already has, so no new gating concept is
introduced. Managed's one genuinely distinct surface — plans and billing — becomes an
ordinary console page. The Industry grammar sweep is extended to `/managed` first, proved
red against today's UI, and turns green when the consolidation lands.

**Tech Stack:** TypeScript, React 18, Vite; Python 3.12 with Starlette; Playwright and
Vitest.

**Spec:** `docs/superpowers/specs/2026-10-26-cortex-account-and-agent-registration-design.md`

## Global Constraints

- One application root. `viewer/src/main.tsx` must contain no edition branch selecting a
  component; `VITE_CORTEX_EDITION` may select configuration only.
- A destination is declared in exactly one place (`ALL_DESTINATIONS` in
  `viewer/src/console/nav.ts`) and appears in all three layouts; it must not be listed
  anywhere else.
- No new CSS namespace. Reuse Industry primitives (`xc-win`, `xc-btn`, `xc-field`,
  `xc-input`, `xc-title`, `xc-copy`); `xc-managed-*` layout classes are deleted, not moved.
- Type scale is fixed: 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 25, 32, 42 px. Icon stroke
  width is `1.5`. Everything is square. These are asserted by the existing sweep.
- The managed **backend** is untouched: `/api/managed/*` routes, tenants, entitlement,
  Stripe and the Render pilot all stay. Only UI code is removed.
- Self-hosted behaviour must not change. A server that declares no destination list gets
  every `BUILT` destination, exactly as today.
- Every check added here must be proved able to fail before it is made to pass.

## Review Focus

These are the conditions the spec implies but that no task's happy path exercises. Each
line's test is added to the task that owns the code.

1. **The server declares a destination the client does not know** (a newer server, an
   older bundle). The unknown id must be ignored, not crash the rail — Task 2.
2. **The server declares an empty list.** The console must still render its shell rather
   than a navigation-less blank frame — Task 2.
3. **The declaration request fails or returns no list** (offline, 500, old server). The
   client must fall back to every `BUILT` destination rather than hiding everything —
   Task 2.
4. **A hash route is entered for a destination the server did not declare** (a bookmark,
   `#operations` on hosted). It must resolve to a defined surface, not an empty workspace
   — Task 5.
5. **A tab strip whose peers are partly undeclared** (`settings` present, `operations` and
   `agents` not). `PAGE_TABS` must not render a tab that goes nowhere — Task 2.

---

### Task 1: The hosted server declares its destinations

**Files:**
- Modify: `src/xibalba_cortex/managed/api.py` (the `me` handler)
- Test: `tests/test_managed_service.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /api/managed/me` response gains
  `"destinations": list[str]` — the destination ids this edition can serve. Fixed value
  for the hosted edition:
  `["graph", "timeline", "memories", "recall", "settings", "agents", "billing"]`.
  Chosen because the hosted API serves graph, timeline, memories, keys, plans and
  billing; it has no `entities`, `sessions`, `operations`, `review` or `integrity`
  endpoints.

- [x] **Step 1: Write the failing test**

```python
def test_me_declares_the_destinations_this_edition_serves(managed_client):
    body = managed_client.get_json("/api/managed/me")
    assert body["destinations"] == [
        "graph", "timeline", "memories", "recall", "settings", "agents", "billing",
    ]
```

- [x] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/test_managed_service.py -k declares_the_destinations -q`
Expected: FAIL — `KeyError: 'destinations'`.

- [x] **Step 3: Add the key to the `me` handler in `src/xibalba_cortex/managed/api.py`**

Define the list as a module-level constant beside the route table so it is greppable from
one place.

- [x] **Step 4: Run it and confirm it passes**

Run: `uv run pytest tests/test_managed_service.py -k declares_the_destinations -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/xibalba_cortex/managed/api.py tests/test_managed_service.py
git commit -m "feat(managed): declare the destinations this edition serves"
```

---

### Task 2: `nav.ts` resolves a server-declared set

**Files:**
- Modify: `viewer/src/console/nav.ts`
- Test: `viewer/src/console/nav.test.ts`

**Interfaces:**
- Consumes: the `destinations` ids from Task 1.
- Produces:
  - `ALL_DESTINATIONS` gains
    `{ id: 'billing', kind: 'page', label: 'Billing', group: 'system', hint: 'Plan, usage and invoices' }`,
    and `PageId` gains `'billing'`.
  - `TAB_LABEL.billing = 'Billing'`; `PAGE_TABS` lists `billing` as a peer of
    `settings` / `operations` / `agents`.
  - `export function destinationsFrom(ids: readonly string[] | null | undefined): readonly Destination[]`
    — `null`/`undefined`/empty returns `DESTINATIONS` unchanged; otherwise
    `ALL_DESTINATIONS` filtered to ids that are both declared and `BUILT`.
  - `tabsFor` **already exists** as `tabsFor(page: PageId): readonly PageId[]`
    (`nav.ts:103`). Widen it to
    `tabsFor(page: PageId, list: readonly Destination[] = DESTINATIONS): readonly PageId[]`,
    filtering `PAGE_TABS[page]` to members present in `list`. Do not add a second
    function.

Two seams already exist and must be reused rather than duplicated:

- `destinationsIn(group, list = DESTINATIONS)` and
  `primaryDestinations(list = DESTINATIONS)` already take the list — unchanged.
- `parseRoute(hash: string, built: ReadonlySet<DestinationId> = BUILT): Route`
  (`nav.ts:128`) already resolves a hash against a set of available destinations. Review
  Focus item 4 is satisfied by passing a **narrowed** set, not by writing a new resolver.
  Add `export function builtFrom(list: readonly Destination[]): ReadonlySet<DestinationId>`
  so callers can hand `parseRoute` the declared set.

- [x] **Step 1: Write the failing tests**

```ts
test('an empty or absent declaration keeps every built destination', () => {
  expect(destinationsFrom(null)).toEqual(DESTINATIONS)
  expect(destinationsFrom([])).toEqual(DESTINATIONS)
})

test('an unknown declared id is ignored rather than rendered', () => {
  const ids = ['graph', 'wormhole']
  expect(destinationsFrom(ids).map((d) => d.id)).toEqual(['graph'])
})

test('a declaration narrows to the intersection with BUILT, in canonical order', () => {
  const ids = ['settings', 'graph', 'billing']
  expect(destinationsFrom(ids).map((d) => d.id)).toEqual(['graph', 'settings', 'billing'])
})

test('a tab strip drops peers the server did not declare', () => {
  const list = destinationsFrom(['settings', 'billing'])
  expect(tabsFor('settings', list)).toEqual(['settings', 'billing'])
})

test('an undeclared hash route resolves against the narrowed set', () => {
  const list = destinationsFrom(['graph', 'memories'])
  expect(parseRoute('#operations', builtFrom(list)).id).toBe('graph')
})

test('billing is a system destination with a tab label', () => {
  expect(ALL_DESTINATIONS.find((d) => d.id === 'billing')?.group).toBe('system')
  expect(TAB_LABEL.billing).toBe('Billing')
})
```

- [x] **Step 2: Run them and confirm they fail**

Run: `cd viewer && npx vitest run src/console/nav.test.ts`
Expected: FAIL — `destinationsFrom is not a function`.

- [x] **Step 3: Implement `destinationsFrom`, `builtFrom`, the widened `tabsFor`, and the `billing` destination in `viewer/src/console/nav.ts`**

Order comes from `ALL_DESTINATIONS`, not from the server's array, so the rail cannot be
reordered by a payload.

- [x] **Step 4: Run them and confirm they pass**

Run: `cd viewer && npx vitest run src/console/nav.test.ts`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add viewer/src/console/nav.ts viewer/src/console/nav.test.ts
git commit -m "feat(viewer): resolve destinations from a server declaration"
```

---

### Task 3: Billing becomes an ordinary console page

**Files:**
- Create: `viewer/src/console/pages/BillingPage.tsx`
- Create: `viewer/src/console/billing.ts`
- Create: `viewer/src/console/billing.test.ts`
- Modify: `viewer/src/console/pages/PageHost.tsx` (route `billing` to the new page)

**Interfaces:**
- Consumes: `Page` from `viewer/src/console/pages/Page.tsx`, the same wrapper
  `SettingsPage` and `AgentsPage` use.
- Produces:
  - `billing.ts` defines its own payload type, since `api.ts` has none:
    `export interface Plan { id: string; name: string; monthly_cents: number; max_memories: number; writes_per_month: number; retrievals_per_month: number }`
    — the shape `/api/managed/plans` already returns.
  - `export function planRows(plans: Plan[], currentPlanId: string): PlanRow[]`
    where `PlanRow = { id: string; name: string; price: string; current: boolean; limits: Array<{ label: string; value: string }> }`.
    Price is formatted from `monthly_cents` as `$<n> / month`.
  - `export function upgradeRefusal(billingConfigured: boolean, planId: string): string | null`
    — the reason an upgrade control is unavailable, or `null` when it is available.
  - `BillingPage.tsx`: `export function BillingPage(): JSX.Element`.

The logic lives in `billing.ts` so it is unit-testable without a DOM, matching
`access.ts`, `account.ts` and `agents.ts` in this codebase.

- [x] **Step 1: Write the failing tests**

```ts
test('plan rows carry a formatted price and mark the current plan', () => {
  const plans = [
    { id: 'free', name: 'Free', monthly_cents: 0, max_memories: 1000, writes_per_month: 250, retrievals_per_month: 1000 },
    { id: 'pro', name: 'Pro', monthly_cents: 2900, max_memories: 25000, writes_per_month: 5000, retrievals_per_month: 25000 },
  ]
  const rows = planRows(plans, 'free')
  expect(rows.map((r) => r.price)).toEqual(['$0 / month', '$29 / month'])
  expect(rows.map((r) => r.current)).toEqual([true, false])
})

test('an upgrade is refused with a reason when billing is unconfigured', () => {
  expect(upgradeRefusal(false, 'free')).toBe('Paid subscriptions are not available yet.')
  expect(upgradeRefusal(true, 'free')).toBeNull()
})
```

- [x] **Step 2: Run them and confirm they fail**

Run: `cd viewer && npx vitest run src/console/billing.test.ts`
Expected: FAIL — module not found.

- [x] **Step 3: Implement `billing.ts`, then `BillingPage.tsx`**

`BillingPage` renders through `Page` with eyebrow `System` and title `Billing`, and uses
only Industry primitives. It calls the existing `/api/managed/{plans,checkout,portal}`
routes. Carry over the copy `Paid subscriptions are not available yet.` verbatim from
`ManagedApp.tsx` so the unconfigured state reads the same.

- [x] **Step 4: Run them and confirm they pass**

Run: `cd viewer && npx vitest run src/console/billing.test.ts`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add viewer/src/console/billing.ts viewer/src/console/billing.test.ts \
        viewer/src/console/pages/BillingPage.tsx viewer/src/console/pages/PageHost.tsx
git commit -m "feat(viewer): make billing an ordinary console page"
```

---

### Task 4: The grammar sweep covers `/managed`, and is proved red first

**Files:**
- Modify: `viewer/e2e/design-system.spec.ts`

**Interfaces:**
- Consumes: `grammarSweep(page)` at `design-system.spec.ts:266`, and the signed-in
  managed fixture from `viewer/e2e/managed.spec.ts`.
- Produces: nothing other tasks consume.

This task's test is **expected to fail on completion** and is the gate Task 5 must turn
green. Do not weaken it to make it pass here.

- [x] **Step 1: Write the test**

Follow the shape of `the public landing keeps its grammar at ${width}px`
(`design-system.spec.ts:680`), which sweeps a path rather than a hash route:

```ts
for (const width of [390, 1280, 1600]) {
  test(`the hosted workspace keeps its grammar at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 })
    await managedFixture(page, { signedIn: true })
    await page.goto('/managed')
    await expect(page.locator('.xc')).toBeVisible()
    await page.evaluate(() => document.fonts.ready)
    const problems = await grammarSweep(page)
    expect(problems, problems.join('\n')).toEqual([])
  })
}
```

- [x] **Step 2: Run it and record the failure**

Run: `cd viewer && npx playwright test e2e/design-system.spec.ts -g "hosted workspace" --project=desktop`
Expected: FAIL. Record the violation list in the commit message — it is the evidence the
check can fail, and the baseline Task 5 is measured against.

- [x] **Step 3: Commit the red test**

```bash
git add viewer/e2e/design-system.spec.ts
git commit -m "test(e2e): sweep the hosted workspace for Industry grammar

Red on purpose: /managed has never been swept, so grammarSweep appears 5 times
across the suite and /managed 0 times. Recorded violations: <paste list>."
```

---

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

- [x] **Step 1: Write the failing tests**

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
| 5 — one app root, delete the second UI | **steps 1-3 done, 4-7 NOT done** | `1d07f89`, `096a205`; `main.tsx` boots `ConsoleApp` unconditionally |

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
