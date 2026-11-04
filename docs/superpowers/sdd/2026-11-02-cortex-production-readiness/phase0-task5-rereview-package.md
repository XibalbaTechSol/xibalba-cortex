# Scoped re-review package — Phase 0 Task 5 fix round 1

Fix commit only: 2b4a1ef..HEAD equivalent — the single commit shown below.

## Commit
```
40a48d2 test(viewer): make the read-only absences carry the gate, and drop a check that cannot fail
```

## Diff
```diff
40a48d29c34222bbb5f66ce26f0ccb7f060115c1
test(viewer): make the read-only absences carry the gate, and drop a check that cannot fail

Two review findings on the re-homed read-only test.

The "no POST memories" assertion could not fail. Nothing in the test attempts a
write -- the controls are asserted absent above it -- and hostedApi.ts:354 refuses
a hosted write client-side before the network, so it held with or without the
gate. hosted-paths.spec.ts:158-160 already records that exact refusal and points
at hostedApi.test.ts mutation M2, where a write IS attempted. Removed, with the
pointer carried over. No coverage is lost; the orphaned `calls` binding goes too.

The gate assertions were also in the order hosted-paths.spec.ts warns against.
With the read-only note asserted before the absences, a `writable: true` mutation
died at the note and the absences were never reached -- unproven. Reordered so
the absences come first: the same mutation now dies on 'New memory'. That also
settles the loading-transient question, since toHaveCount(0) would pass instantly
during loading, so it can only fail because the export assertion above it already
waited for the workspace to render.

managed.spec.ts 15/15, hosted-paths.spec.ts 4/4, oxlint 0 errors.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>


diff --git a/viewer/e2e/managed.spec.ts b/viewer/e2e/managed.spec.ts
index de36c84..71ce81d 100644
--- a/viewer/e2e/managed.spec.ts
+++ b/viewer/e2e/managed.spec.ts
@@ -94,44 +94,53 @@ test('choosing a paid plan uses Checkout; an existing paid plan changes through
   await page.getByRole('button', { name: 'Choose Pro', exact: true }).click()
   await expect(page).toHaveURL('https://checkout.stripe.com/test-fixture')
   expect(calls.find((call) => call.path === 'checkout')?.body).toEqual({ plan: 'pro' })
   await page.unroute('**/api/managed/**')
   calls = await managedFixture(page, { signedIn: true, billing: true, plan: 'pro' })
   await page.goto('/managed#billing')
   await page.getByRole('button', { name: 'Change through billing', exact: true }).click()
   await expect(page).toHaveURL('https://billing.stripe.com/test-fixture')
   expect(calls.filter((call) => call.path === 'checkout')).toHaveLength(0)
 })
 
 /* A read-only subscription keeps search and export and is refused writes. On the console the write
    control is not rendered rather than disabled (MemoriesPage.tsx), and the entitlement's own
    wording is on Billing (billing.ts READ_ONLY_WORKSPACE). */
 test('read-only subscriptions retain export and search without permitting writes', async ({ page }) => {
-  const calls = await managedFixture(page, { signedIn: true, plan: 'pro', writable: false, seed: 2 })
+  await managedFixture(page, { signedIn: true, plan: 'pro', writable: false, seed: 2 })
   await page.goto('/managed#memories')
   await expect(page.getByRole('button', { name: 'Export memories', exact: true })).toBeEnabled()
-  await expect(page.getByRole('note').filter({ hasText: 'Read only.' })).toBeVisible()
+  /* The absences come BEFORE the read-only note, per the lesson recorded in hosted-paths.spec.ts:
+     both read the same `workspace.canWrite`, so with the note asserted first a `writable: true`
+     mutation fails THERE and these two are never reached -- which is how an absence goes unproven.
+     Verified 2026-11-03: in the note-first order the mutation died at the note; in this order it
+     dies on 'New memory', so the absences are the assertions actually carrying the gate. */
   await expect(page.getByRole('button', { name: 'New memory', exact: true })).toHaveCount(0)
   await expect(page.getByRole('button', { name: 'Import a document', exact: true })).toHaveCount(0)
+  await expect(page.getByRole('note').filter({ hasText: 'Read only.' })).toBeVisible()
   // search still works: it filters the existing memories
   const list = page.getByRole('region', { name: 'Memory list' })
   await expect(list).toContainText('Seeded memory 0')
   await page.getByLabel('Search memory text', { exact: true }).fill('Seeded memory 1')
   await page.getByRole('button', { name: 'Search', exact: true }).click()
   await expect(list).toContainText('Seeded memory 1')
   await expect(list).not.toContainText('Seeded memory 0')
-  expect(calls.filter((call) => call.path === 'memories' && call.method === 'POST')).toHaveLength(0)
+  /* Deliberately NOT asserting "no POST memories": nothing here attempts a write -- the controls
+     are asserted absent above -- and hostedApi.ts:354 refuses a hosted write client-side before
+     the network, so that assertion holds with or without the gate. hosted-paths.spec.ts:158-160
+     records the same refusal. The gate on the CALL is proved in src/hostedApi.test.ts (mutation
+     M2), where a write IS attempted. */
   await page.goto('/managed#billing')
   await expect(page.getByText('This workspace is read-only.', { exact: false })).toBeVisible()
 })
 
 /* Review Focus items 4 and 5, on the one app: the hosted session declares seven destinations, and
    `operations` is not among them. A tab strip whose peers are partly undeclared must not render a
    tab that goes nowhere, and a hash route naming an undeclared destination must resolve to a
    defined surface rather than opening a page this deployment does not serve. Both read the SAME
    list the rail reads -- there is no second copy of it to keep in step. */
 test('a hosted tab strip drops the peers the server did not declare', async ({ page }) => {
   await managedFixture(page, { signedIn: true })
   await page.goto('/managed#settings')
   const tabs = page.locator('.xc-page-tabs')
   await expect(tabs).toBeVisible()
   await expect(tabs.getByRole('button', { name: 'Settings', exact: true })).toBeVisible()
```
