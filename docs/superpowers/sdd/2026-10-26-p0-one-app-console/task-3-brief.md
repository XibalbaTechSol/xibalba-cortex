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

- [ ] **Step 1: Write the failing tests**

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

- [ ] **Step 2: Run them and confirm they fail**

Run: `cd viewer && npx vitest run src/console/billing.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `billing.ts`, then `BillingPage.tsx`**

`BillingPage` renders through `Page` with eyebrow `System` and title `Billing`, and uses
only Industry primitives. It calls the existing `/api/managed/{plans,checkout,portal}`
routes. Carry over the copy `Paid subscriptions are not available yet.` verbatim from
`ManagedApp.tsx` so the unconfigured state reads the same.

- [ ] **Step 4: Run them and confirm they pass**

Run: `cd viewer && npx vitest run src/console/billing.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add viewer/src/console/billing.ts viewer/src/console/billing.test.ts \
        viewer/src/console/pages/BillingPage.tsx viewer/src/console/pages/PageHost.tsx
git commit -m "feat(viewer): make billing an ordinary console page"
```

---

