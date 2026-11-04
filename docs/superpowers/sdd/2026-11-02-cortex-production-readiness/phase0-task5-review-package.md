# Review package — Phase 0, Task 5

Range: d946fc1..HEAD

## Commits
```
b115f2f refactor(viewer): name Landing's edition prop for the surface, not the retired edition
ef9da85 docs: record credentialed Stripe validation against Phase 3
8a38002 test(viewer): re-home the two disabled managed e2e tests onto the console; pin the one-app shell
7f96180 docs(plan): run Phase 5 Tasks 1-2 right after Phase 0 for an earlier test deploy
```

## Stat
```
 .../2026-11-02-cortex-production-readiness.md      |  93 +++++++-
 viewer/e2e/managed.spec.ts                         |  89 ++++---
 viewer/src/console/HostedLanding.tsx               |   4 +-
 viewer/src/console/Landing.tsx                     |  20 +-
 viewer/src/console/ManagedApp.tsx                  | 265 ---------------------
 viewer/src/console/ManagedLenses.tsx               |  61 -----
 viewer/src/console/managed.css                     |  45 ----
 7 files changed, 155 insertions(+), 422 deletions(-)
```

## Diff
```diff
diff --git a/docs/superpowers/plans/2026-11-02-cortex-production-readiness.md b/docs/superpowers/plans/2026-11-02-cortex-production-readiness.md
index 0d868ec..f0b8a38 100644
--- a/docs/superpowers/plans/2026-11-02-cortex-production-readiness.md
+++ b/docs/superpowers/plans/2026-11-02-cortex-production-readiness.md
@@ -159,20 +159,66 @@ a real user first. Each has its test pinned to the task that owns the code.
    by changing one transport alone.
 4. **A webhook replayed.** Stripe retries. An entitlement that advances twice on one event
    over-grants or double-charges. Phase 3 Task 2 replays the same event and asserts the
    second is a no-op.
 5. **An enrollment code used twice, late, or from the wrong workspace.** It is a bearer
    secret. Phase 2 Task 2 covers expired, already-redeemed, wrong-workspace and
    bad-signature redemptions as four distinct non-enumerating refusals.
 
 ---
 
+## Execution order — amended 2026-11-03
+
+**Phase 5 Tasks 1 and 2 run immediately after Phase 0**, ahead of Phases 1, 2 and 3.
+Operator decision: reach a deployable test build sooner. Those two tasks are what make the
+hosted product able to do the thing it currently cannot — record provenance-bearing turns —
+and Phases 1-3 harden auth and billing without unblocking testing.
+
+Running order: **Phase 0 → Phase 5 T1, T2 → Phase 1 → Phase 2 → Phase 3 → Phase 5 T3-T6.**
+
+**The reorder breaks no dependency.** Phase 5 Task 1 Step 6 was written as "call the
+enforcement Phase 3 Task 3 built". Verified 2026-11-03: **that enforcement already exists
+on `main`** and needs nothing from Phase 3 —
+
+- `ManagedControl.consume(tenant, meter, *, request_key=None, fingerprint="")`
+  (`control.py:183`) enforces `writes_per_month` and `retrievals_per_month` atomically
+  (`UPDATE usage SET amount=amount+1 WHERE ... AND amount<?`, raising `LimitExceeded` when
+  the row does not change), refuses writes on a read-only entitlement, and carries
+  idempotency through `request_key` + `fingerprint`.
+- `max_memories` is enforced by `GraphStore`'s own quotas, passed in `control.store()`
+  (`control.py:229`).
+- Routes already call it: `api.py:161, 369, 378, 405, 426`, inside
+  `service.write_guard(tenant)` and `service.store(tenant)`. `LimitExceeded` is mapped to a
+  response by the handler at `api.py:491` and registered at `api.py:534`.
+
+So Phase 5 Task 1 **calls the existing `service.consume(tenant, "writes", ...)`** rather
+than building anything, copying the shape of `api.py:368-370`. This also means **Phase 3
+Task 3 is mostly already implemented**; its remaining value is the three
+proved-able-to-fail tests, which is why it stays in the plan.
+
+**`control.store()` is also the workspace scoping Phase 5 Task 2 needs**, already hardened:
+it validates the tenant id's shape, rejects a symlinked tenant root, and rejects a resolved
+path whose parent is not the storage root (`control.py:216-224`). Task 2's job is therefore
+to prove the route derives its tenant from the **token** and never from the payload — not to
+build path isolation.
+
+**Fixture ownership moves with the order.** Phase 1 Task 4 was to create `managed_app` and
+`api_key` in `tests/conftest.py`; Phase 5 Task 1 now runs first, so **Phase 5 Task 1 creates
+them**. Phase 1 Task 4 reuses them.
+
+**Phase 1 Task 4's `xfail` inverts.** It was marked
+`@pytest.mark.xfail(strict=True)` because the ingest route did not exist yet. Under the new
+order it **does** exist, so Phase 1 Task 4 writes that test as an ordinary passing test with
+no marker, and Phase 5 Task 1 has no marker to remove.
+
+---
+
 ## Phase 0 — One app, and it is the console
 
 **Task detail lives in `docs/superpowers/plans/2026-10-26-p0-one-app-console.md`.** Do not
 re-plan it. Tasks 1–4 and Task 5 Step 3 have landed; that plan's "Execution status" section
 records what shipped against which commit.
 
 **Remaining work is Task 5, starting at Step 1**, in this order, because the order is the
 whole point: `managed.spec.ts` currently asserts against `ManagedApp.tsx:177` and `:209`, so
 deleting the file first would leave tests pointing at nothing.
 
@@ -565,20 +611,38 @@ screen, and a binding cannot be created without a signature from the agent's key
 ---
 
 ## Phase 3 — Stripe
 
 The spec's P3, split as recorded. Build against a dummy key:
 `ManagedConfig.billing_ready` already rejects any secret key containing `dummy`, `replace`
 or `placeholder`, so the service stays healthy, `billing_configured` stays `false`,
 `/readyz` keeps reporting `stripe_sandbox` **not ready**, and no customer can be charged
 against a fake gateway.
 
+**Credentialed validation already happened, and it does not replace these tasks.**
+On 2026-11-03 the whole billing chain was driven by hand against the operator's real
+`sk_test_` key on a locally-run managed service: the `/readyz` billing gate, a genuine
+`cs_test_` Checkout Session through `POST /api/managed/checkout` with cookie auth and
+CSRF, a tampered webhook signature (rejected 400), a real active Pro subscription
+applied through `customer.subscription.created` (tenant `free` to `pro/active`), the
+same event id replayed (`duplicate: true`, one `stripe_events` row), an event for a
+customer owned by no tenant (`ignored`), a `livemode: true` event against a test
+deployment (rejected 400), a real Stripe cancellation applied through
+`customer.subscription.deleted` (tenant `canceled`, `writable: false`), and a write
+refused 403 while reads and export stayed 200. The ledger records the run and its three
+findings.
+
+That was one operator driving one happy path plus seven negatives once. It is evidence
+the code works; it is not a regression gate, and nobody can re-run it in CI without the
+live key. Every task below still owes its assertions **in the test suite, each proved able
+to fail** — the manual run tells you the expected values, not that the work is done.
+
 ### Task 1: Checkout and portal against a fake gateway
 
 **Files:**
 - Modify: `src/xibalba_cortex/managed/stripe_gateway.py`
 - Create: `tests/test_stripe_gateway.py`
 
 **Interfaces:**
 - Produces: a `FakeGateway` test double satisfying the same protocol as the real gateway.
 
 - [ ] **Step 1: Write the failing tests** — checkout returns a session for a known price id
@@ -676,23 +740,28 @@ ingestion logic in a transport.
 ### Task 1: REST ingestion, scoped to the caller's workspace
 
 **Files:**
 - Create: `src/xibalba_cortex/managed/ingest.py`, `tests/test_managed_ingest.py`
 - Modify: `src/xibalba_cortex/managed/api.py`
 
 **Interfaces:**
 - Consumes: `GraphStore.ingest_agent_turn(external_session_id, *, runtime, prompt, response,
   tool_calls=(), agent_id=None, prompt_id=None, prompt_time=None, response_time=None,
   metadata=None, idempotency_key=None) -> dict`; `verify_token_record` from
-  `ingest_tokens`; `account["profile_id"]` as the workspace key.
-- Produces: `ingest_turn(token: str, payload: dict) -> dict` and the route
-  `POST /api/managed/ingest`.
+  `ingest_tokens`; and the three managed primitives this route must reuse rather than
+  reinvent — `service.write_guard(tenant)`, `service.store(tenant)` (per-tenant `GraphStore`
+  with path-escape validation and `max_memories` quota) and
+  `service.consume(tenant, "writes", request_key=..., fingerprint=...)`. Copy the shape of
+  `api.py:368-370`.
+- Produces: `ingest_turn(token: str, payload: dict) -> dict`, the route
+  `POST /api/managed/ingest`, and the `managed_app` and `api_key` fixtures in
+  `tests/conftest.py` (which does not exist yet — create it).
 
 - [ ] **Step 1: Write the failing test**
 
 ```python
 def test_a_full_turn_lands_with_its_tool_calls(managed_app, api_key):
     r = managed_app.post("/api/managed/ingest", headers=bearer(api_key), json={
         "external_session_id": "s-1", "runtime": "grok",
         "prompt": "hello", "response": "hi",
         "tool_calls": [{"name": "web_search"}],
     })
@@ -709,28 +778,30 @@ Expected: FAIL — 404; the route does not exist.
 
 - [ ] **Step 3: Implement `ingest_turn` and the route.** Resolve the token to its
       `profile_id`, open that profile's store, and call `ingest_agent_turn` with the
       payload. Require the `memory:write` scope the managed key already carries. **Put no
       session, exchange or otel logic here** — the handler owns all of it.
 - [ ] **Step 4: Run it and confirm it passes.** Then remove the
       `xfail` marker from Phase 1 Task 3's
       `test_revoking_an_api_key_stops_ingestion_on_the_next_call` and confirm it passes.
 - [ ] **Step 5: Prove it can fail** — drop `tool_calls` from the handler call; confirm the
       committed-tool-calls assertion goes red.
-- [ ] **Step 6: Enforce the plan limits on this route.** Phase 3 Task 3 enforces
-      `writes_per_month`, `max_memories` and `retrievals_per_month` on the routes that
-      existed then. **This route is new and bypasses all three**, so a Free account could
-      ingest without limit. Write the test that a Free-tier ingest at the `writes_per_month`
-      boundary is refused and the same call succeeds on Pro, implement the check by calling
-      the same enforcement Phase 3 Task 3 built, and prove it can fail by removing the
-      check. Ingestion is the highest-volume write path in the product; unmetered is the
-      expensive failure.
+- [ ] **Step 6: Meter this route like every other write.** A new route bypasses the limits
+      by default, and ingestion is the highest-volume write path in the product — unmetered
+      is the expensive failure, and it is reachable by anyone who signs up free. The
+      mechanism already exists (see **Execution order**), so this is a call, not a build:
+      wrap the write in `service.write_guard(tenant)` and call
+      `service.consume(tenant, "writes", request_key=..., fingerprint=...)` exactly as
+      `api.py:368-370` does. Write the test that a Free-tier ingest at the
+      `writes_per_month` boundary is refused with `LimitExceeded` and the same call succeeds
+      on Pro; prove it can fail by removing the `consume` call. Take `request_key` from an
+      `Idempotency-Key` header so a retried ingest does not double-charge.
 - [ ] **Step 7: Commit**
 
 ### Task 2: A token reaches its own workspace and no other
 
 **Files:**
 - Modify: `src/xibalba_cortex/managed/ingest.py`, `tests/test_managed_ingest.py`
 
 - [ ] **Step 1: Write the failing test** — this is Review Focus item 2.
 
 ```python
diff --git a/viewer/e2e/managed.spec.ts b/viewer/e2e/managed.spec.ts
index 9450229..de36c84 100644
--- a/viewer/e2e/managed.spec.ts
+++ b/viewer/e2e/managed.spec.ts
@@ -36,78 +36,98 @@ test('signup requires verification and never grants an immediate signed-in works
   await form.getByRole('button', { name: 'Create workspace', exact: true }).click()
   await expect(page.getByText('Check your email for a verification link.', { exact: false })).toBeVisible()
   expect(calls.filter((call) => call.path === 'login')).toHaveLength(0)
   /* "no signed-in workspace" has to name a thing that still exists. It used to be the second UI's
      `Operator’s memory` heading (ManagedApp.tsx:177), which nothing renders now -- so that half of
      the test could no longer fail. The console's signed-in marker is the workspace itself. */
   await expect(page.locator('.xc-workspace')).toHaveCount(0)
   await expect(page.getByRole('button', { name: 'Open operator profile settings' })).toHaveCount(0)
 })
 
-/* Owed to Task 5c, not deleted. Every assertion below names the second UI's own DOM -- its single
-   write form, its `.xc-managed-results` list, its `.xc-managed-key` block. Task 5a re-homed the
-   same capabilities onto the console's Memories and Agents pages, and 5c owns re-pointing these
-   and adding the behavioural coverage; 5b was told not to re-point the key/export assertions, so
-   they are marked rather than weakened. */
-test.fixme('a workspace stores and searches memory, then creates and revokes an API key', async ({ page }) => {
-  const calls = await managedFixture(page, { signedIn: true })
-  await page.goto('/managed')
-  await page.getByLabel('Memory', { exact: true }).fill('Remember this test-only fact')
-  await page.getByRole('button', { name: 'Save memory', exact: true }).click()
-  await expect(page.getByText('Memory saved with a verifiable event history.')).toBeVisible()
-  await page.getByLabel('Search memories', { exact: true }).fill('test-only')
-  await page.getByRole('button', { name: 'Search / list', exact: true }).click()
-  await expect(page.locator('.xc-managed-results')).toContainText('Remember this test-only fact')
+/* Re-homed from the second UI's single screen onto the console's own surfaces: the write is
+   Memories -> New memory, the search is Memories' search box, and the key is Agents' hosted
+   API-keys section (AgentsPage.tsx, HostedApiKeys). Seeded memories make the search a real filter:
+   without them the new memory is the only row, and "search finds it" could not fail. */
+test('a workspace stores and searches memory, then creates and revokes an API key', async ({ page }) => {
+  const calls = await managedFixture(page, { signedIn: true, seed: 2 })
+  await page.goto('/managed#memories')
+  await page.getByRole('button', { name: 'New memory', exact: true }).click()
+  await page.getByLabel('Text', { exact: true }).fill('Remember this test-only fact')
+  await page.getByRole('button', { name: 'Add memory', exact: true }).click()
+  await expect(page.getByRole('main').getByText(/Memory \S+ added to/)).toBeVisible()
   const write = calls.find((call) => call.path === 'memories' && call.method === 'POST')!
   expect(write.body).toEqual({ content: 'Remember this test-only fact' })
+  await page.getByLabel('Search memory text', { exact: true }).fill('test-only')
+  await page.getByRole('button', { name: 'Search', exact: true }).click()
+  const list = page.getByRole('region', { name: 'Memory list' })
+  await expect(list).toContainText('Remember this test-only fact')
+  // the search filters: a seeded memory that does not match is gone, so the line above is not just "everything is listed"
+  await expect(list).not.toContainText('Seeded memory 0')
+
+  await page.goto('/managed#agents')
   /* A key is bound to the agent DIDs it is for, so the field is `required` and the button
-     stays disabled until it has one (ManagedApp.tsx:209, `!agentDids.trim()`). Before this,
-     the click waited out the full 90s timeout against a permanently disabled button. */
-  await page.getByLabel('Agent DIDs', { exact: true }).fill('did:integrity:test-agent-one\ndid:integrity:test-agent-two')
-  await page.getByRole('button', { name: 'Create API key', exact: true }).click()
-  await expect(page.locator('.xc-managed-key')).toHaveText('fixture-only-managed-key')
+     stays disabled until it has one (AgentsPage.tsx, `!dids.trim()`). Before this rule was
+     asserted, the click waited out the full 90s timeout against a permanently disabled button. */
+  const create = page.getByRole('button', { name: 'Create API key', exact: true })
+  await expect(create).toBeDisabled()
+  await page.getByRole('textbox', { name: /^Agent DIDs/ }).fill('did:integrity:test-agent-one\ndid:integrity:test-agent-two')
+  await expect(create).toBeEnabled()
+  await create.click()
+  const issuedKey = page.getByLabel('New API key', { exact: true })
+  await expect(issuedKey.locator('code')).toHaveText('fixture-only-managed-key')
   // the DIDs reach the API, de-duplicated and split on newlines or commas -- the point of the field
   const issued = calls.find((call) => call.path === 'keys' && call.method === 'POST')!
   expect(issued.body).toEqual({ label: 'agent', agent_ids: ['did:integrity:test-agent-one', 'did:integrity:test-agent-two'] })
   expect(await page.evaluate(() => Object.values(localStorage).join(' '))).not.toContain('fixture-only-managed-key')
   await page.getByRole('button', { name: 'Show API keys', exact: true }).click()
   await page.getByRole('button', { name: 'Revoke key', exact: true }).click()
-  await expect(page.locator('.xc-managed-key')).toHaveCount(0)
+  await expect(issuedKey).toHaveCount(0)
   await expect(page.getByRole('button', { name: 'Revoke key', exact: true })).toHaveCount(0)
+  expect(calls.filter((call) => call.path === 'keys/revoke' && call.method === 'POST')).toHaveLength(1)
 })
 
 /* Plans for a SIGNED-IN hosted workspace are the console's Billing page (Task 3), reached at
    `#billing` -- the second UI put them at the foot of its one screen. `planAction` gives the same
    two labels, so the assertions are unchanged. */
 test('choosing a paid plan uses Checkout; an existing paid plan changes through the portal', async ({ page }) => {
   let calls = await managedFixture(page, { signedIn: true, billing: true })
   await page.goto('/managed#billing')
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
 
-/* Owed to Task 5c for the same reason: "Save memory", "Search / list" and "Export memories" were
-   three controls on one managed screen. On the console the write lives on Memories, the export is
-   5a's control on Memories, and read-only comes from the workspace's own writability. */
-test.fixme('read-only subscriptions retain export and search without permitting writes', async ({ page }) => {
-  await managedFixture(page, { signedIn: true, plan: 'pro', writable: false })
-  await page.goto('/managed')
-  await expect(page.getByRole('button', { name: 'Save memory', exact: true })).toBeDisabled()
-  await expect(page.getByRole('button', { name: 'Search / list', exact: true })).toBeEnabled()
+/* A read-only subscription keeps search and export and is refused writes. On the console the write
+   control is not rendered rather than disabled (MemoriesPage.tsx), and the entitlement's own
+   wording is on Billing (billing.ts READ_ONLY_WORKSPACE). */
+test('read-only subscriptions retain export and search without permitting writes', async ({ page }) => {
+  const calls = await managedFixture(page, { signedIn: true, plan: 'pro', writable: false, seed: 2 })
+  await page.goto('/managed#memories')
   await expect(page.getByRole('button', { name: 'Export memories', exact: true })).toBeEnabled()
+  await expect(page.getByRole('note').filter({ hasText: 'Read only.' })).toBeVisible()
+  await expect(page.getByRole('button', { name: 'New memory', exact: true })).toHaveCount(0)
+  await expect(page.getByRole('button', { name: 'Import a document', exact: true })).toHaveCount(0)
+  // search still works: it filters the existing memories
+  const list = page.getByRole('region', { name: 'Memory list' })
+  await expect(list).toContainText('Seeded memory 0')
+  await page.getByLabel('Search memory text', { exact: true }).fill('Seeded memory 1')
+  await page.getByRole('button', { name: 'Search', exact: true }).click()
+  await expect(list).toContainText('Seeded memory 1')
+  await expect(list).not.toContainText('Seeded memory 0')
+  expect(calls.filter((call) => call.path === 'memories' && call.method === 'POST')).toHaveLength(0)
+  await page.goto('/managed#billing')
   await expect(page.getByText('This workspace is read-only.', { exact: false })).toBeVisible()
 })
 
 /* Review Focus items 4 and 5, on the one app: the hosted session declares seven destinations, and
    `operations` is not among them. A tab strip whose peers are partly undeclared must not render a
    tab that goes nowhere, and a hash route naming an undeclared destination must resolve to a
    defined surface rather than opening a page this deployment does not serve. Both read the SAME
    list the rail reads -- there is no second copy of it to keep in step. */
 test('a hosted tab strip drops the peers the server did not declare', async ({ page }) => {
   await managedFixture(page, { signedIn: true })
@@ -177,20 +197,33 @@ test('the hosted top-bar layout lists only the declared destinations', async ({
   })
   await managedFixture(page, { signedIn: true })
   await page.goto('/managed#settings')
   const nav = page.locator('.xc-nav')
   await expect(nav.getByRole('button', { name: 'Workspace', exact: true })).toBeVisible()
   await expect(nav.getByRole('button', { name: 'Explore', exact: true })).toBeVisible()
   await expect(nav.getByRole('button', { name: 'Review', exact: true })).toHaveCount(0)
   await expect(nav.getByRole('button', { name: 'Integrity', exact: true })).toHaveCount(0)
 })
 
+/* The one-app property itself. Every other test here would pass against a second UI that borrowed
+   the console's classes, and the grammar sweep did exactly that (it stayed green with the edition
+   fork restored). The console shell is the thing only the console renders, and Billing is reachable
+   from it only because the server declared it -- on the default rail layout it is a Settings peer
+   tab, not a rail entry. */
+test('the hosted workspace is the console shell, not a second app', async ({ page }) => {
+  await managedFixture(page, { signedIn: true })
+  await page.goto('/managed#settings')
+  await expect(page.locator('.xc-shell')).toBeVisible()
+  await expect(page.locator('.xc-page-tabs').getByRole('button', { name: /^Billing\b/ })).toBeVisible()
+  await expect(page.locator('.xc-managed-inner')).toHaveCount(0)
+})
+
 test('a hash route for an undeclared destination opens no page', async ({ page }) => {
   await managedFixture(page, { signedIn: true })
   await page.goto('/managed#operations')
   await expect(page.locator('.xc-workspace')).toBeVisible()
   await expect(page.locator('.xc-drawer--page')).toHaveCount(0)
   // the same route on a server that declares it does open the page, so the assertion above is not vacuous
   await page.goto('/managed#agents')
   await expect(page.locator('.xc-drawer--page')).toBeVisible()
 })
 
diff --git a/viewer/src/console/HostedLanding.tsx b/viewer/src/console/HostedLanding.tsx
index 256ab8e..0775bae 100644
--- a/viewer/src/console/HostedLanding.tsx
+++ b/viewer/src/console/HostedLanding.tsx
@@ -1,14 +1,14 @@
 // The hosted edition's signed-out page: the public landing, with the hosted pricing section, the
 // plan cards and the account forms as its children.
 //
-// This content used to live in ManagedApp, passed into the same `<Landing managed>` from the
+// This content used to live in ManagedApp, passed into the same `<Landing hosted>` from the
 // second UI. It is re-homed here, on the console's own signed-out path, so that deleting that UI
 // costs the hosted deployment nothing: without it a hosted visitor would arrive at a page with no
 // prices, no plan choice and no way to create an account.
 //
 // Plan wording is not reimplemented -- `planRows`, `Plan` and `BILLING_UNAVAILABLE` are the same
 // helpers and the same string the signed-in Billing page uses, so the two surfaces cannot word a
 // plan differently. `upgradeRefusal` is deliberately NOT used: it refuses every plan when billing
 // is unconfigured, and signed out the free plan must still offer "Start free".
 // The layout reuses the landing's own Industry primitives (`xc-landing-*`, `xc-win`, `xc-btn`,
 // `xc-field`, `xc-input`): none of the second UI's layout classes are carried over, and no new
@@ -112,21 +112,21 @@ export function HostedLanding({ onSignedIn }: { onSignedIn: () => void }) {
     <div aria-live="polite">
       {error && <p className="xc-callout xc-callout--conflict" role="alert">{error}</p>}
       {notice && <p className="xc-callout">{notice}</p>}
     </div>
   )
 
   // Signed out, no plan is current, so every card offers the way in rather than a plan change.
   const rows = catalog ? planRows(catalog.plans, '') : []
 
   return (
-    <Landing managed onSignIn={() => setMode('login')}>
+    <Landing hosted onSignIn={() => setMode('login')}>
       <section className="xc-landing-section" id="pricing" aria-labelledby="hosted-plans-title">
         <p className="xc-eyebrow">Managed memory</p>
         <h2 className="xc-landing-h2" id="hosted-plans-title">Choose the capacity you need</h2>
         {!mode && messages}
         <div className="xc-landing-grid">
           {rows.map((row) => (
             <article className="xc-win xc-landing-card" key={row.id} aria-label={`${row.name} plan`}>
               <p className="xc-eyebrow">{row.name}</p>
               <h3 className="xc-title">{row.price}</h3>
               <p className="xc-note">USD · monthly subscription</p>
diff --git a/viewer/src/console/Landing.tsx b/viewer/src/console/Landing.tsx
index 7ba4efe..644f896 100644
--- a/viewer/src/console/Landing.tsx
+++ b/viewer/src/console/Landing.tsx
@@ -28,27 +28,27 @@ const PRIMITIVES = [
   },
 ] as const
 
 /** How it runs, stated plainly enough that a reader can check it against the repo. */
 const FACTS = [
   ['Runs', 'On your machine. SQLite under ~/.hermes/xibalba-cortex.'],
   ['Speaks', 'MCP, over stdio or streamable-HTTP.'],
   ['Bridges', 'Claude Code, Codex and agy, through one shared contract.'],
 ] as const
 
-export function Landing({ onSignIn, children, managed = false }: { onSignIn: () => void; children?: ReactNode; managed?: boolean }) {
-  const primitives = managed ? [
+export function Landing({ onSignIn, children, hosted = false }: { onSignIn: () => void; children?: ReactNode; hosted?: boolean }) {
+  const primitives = hosted ? [
     PRIMITIVES[0],
     { icon: <IconSearch />, title: 'Search what your agents recorded', body: 'Find matching memories through bounded lexical search. Each request stays within the authenticated workspace and its monthly allowance.', tool: 'GET /api/managed/memories' },
     { icon: <IconLock />, title: 'An isolated workspace', body: 'Each customer has a separate memory store. Workspace-scoped API keys connect agents without granting access to billing or other customers’ memories.', tool: 'Workspace-scoped access' },
   ] : PRIMITIVES
-  const facts = managed ? [
+  const facts = hosted ? [
     ['Storage', 'A separate persistent memory store for each workspace.'],
     ['Access', 'An authenticated API and a managed web workspace.'],
     ['Billing', 'Monthly subscriptions, with payment details handled by Stripe.'],
   ] : FACTS
   return (
     <div className="xc-landing">
       <header className="xc-landing-top">
         <a className="xc-brand" href="#" aria-label="Xibalba Cortex" onClick={(e) => { e.preventDefault(); document.querySelector('.xc-landing')?.scrollTo({ top: 0, behavior: 'auto' }) }}>
           <span className="xc-brand-mark"><img src="/cortex-rail-mark.png" alt="" /></span>
           <b>Xibalba Cortex</b>
@@ -63,27 +63,27 @@ export function Landing({ onSignIn, children, managed = false }: { onSignIn: ()
         </nav>
         <button type="button" className="xc-btn xc-btn--primary" onClick={onSignIn}>Sign in</button>
       </header>
 
       <main>
       <section className="xc-landing-hero" aria-labelledby="xc-hero-title">
         {/* The mark leads. It carries its own hero derivative rather than the rail's, which is
             built for 124px -- see viewer/scripts/invert_logo_to_white.py. */}
         <img className="xc-landing-mark" src="/cortex-lockup-hero.png" width={420} height={390} alt="" />
         <div className="xc-landing-hero-body">
-          <p className="xc-eyebrow">{managed ? 'Managed memory for agents' : 'Graph memory for agents'}</p>
+          <p className="xc-eyebrow">{hosted ? 'Managed memory for agents' : 'Graph memory for agents'}</p>
           <h1 id="xc-hero-title">Your agents’ memory.<br />Provably yours.</h1>
           <p className="xc-landing-lead">
-            {managed ? 'An isolated workspace for recording agent memories, searching them through an authenticated API, and retaining a verifiable event history.' : <>A local-first memory server that records what your agents learned, where it came from, and whether it still holds — as a graph you can walk and a chain you can verify.</>}
+            {hosted ? 'An isolated workspace for recording agent memories, searching them through an authenticated API, and retaining a verifiable event history.' : <>A local-first memory server that records what your agents learned, where it came from, and whether it still holds — as a graph you can walk and a chain you can verify.</>}
           </p>
           <div className="xc-landing-cta">
-            <button type="button" className="xc-btn xc-btn--primary" onClick={onSignIn}>{managed ? 'Open your workspace' : 'Open the console'}</button>
+            <button type="button" className="xc-btn xc-btn--primary" onClick={onSignIn}>{hosted ? 'Open your workspace' : 'Open the console'}</button>
             <a className="xc-btn" href={REPO} target="_blank" rel="noreferrer noopener">Read the source</a>
           </div>
         </div>
       </section>
 
       <section className="xc-landing-section" id="what" aria-labelledby="xc-what-title">
         <p className="xc-eyebrow">What it is</p>
         <h2 className="xc-landing-h2" id="xc-what-title">Memory with a verifiable foundation</h2>
         <div className="xc-landing-grid">
           {primitives.map((p) => (
@@ -92,38 +92,38 @@ export function Landing({ onSignIn, children, managed = false }: { onSignIn: ()
               <h3 className="xc-title xc-title--sm">{p.title}</h3>
               <p className="xc-copy">{p.body}</p>
               <p className="xc-meta">{p.tool}</p>
             </article>
           ))}
         </div>
       </section>
 
       <section className="xc-landing-section" id="how" aria-labelledby="xc-how-title">
         <p className="xc-eyebrow">How it runs</p>
-        <h2 className="xc-landing-h2" id="xc-how-title">{managed ? 'Hosted memory, clear boundaries' : 'Local first, and legible'}</h2>
+        <h2 className="xc-landing-h2" id="xc-how-title">{hosted ? 'Hosted memory, clear boundaries' : 'Local first, and legible'}</h2>
         <div className="xc-landing-split">
           <dl className="xc-landing-facts">
             {facts.map(([term, detail]) => (
               <div key={term}>
                 <dt className="xc-meta">{term}</dt>
                 <dd className="xc-copy">{detail}</dd>
               </div>
             ))}
           </dl>
           <article className="xc-win xc-landing-card">
             <div className="xc-landing-card-icon" aria-hidden="true"><IconGraph /></div>
-            <h3 className="xc-title xc-title--sm">{managed ? 'A workspace for your agents' : 'Explore the memory graph'}</h3>
+            <h3 className="xc-title xc-title--sm">{hosted ? 'A workspace for your agents' : 'Explore the memory graph'}</h3>
             <p className="xc-copy">
-              {managed ? 'Record and retrieve memories, monitor your usage, connect agents with revocable API keys, and manage your subscription. Existing memories remain available to read and export if a subscription becomes read-only.' : <>The same store, read two ways: a force-directed graph of memories, entities, sessions and Merkle roots, and a timeline that places them on a real time axis. Select either and the detail dock shows the chain, the provenance and the inference behind it.</>}
+              {hosted ? 'Record and retrieve memories, monitor your usage, connect agents with revocable API keys, and manage your subscription. Existing memories remain available to read and export if a subscription becomes read-only.' : <>The same store, read two ways: a force-directed graph of memories, entities, sessions and Merkle roots, and a timeline that places them on a real time axis. Select either and the detail dock shows the chain, the provenance and the inference behind it.</>}
             </p>
             <p className="xc-landing-icons" aria-hidden="true"><IconGraph /><IconTimeline /><IconLock /></p>
           </article>
         </div>
       </section>
 
       {children}
-      <ProductSections showPricing={!managed} />
+      <ProductSections showPricing={!hosted} />
       </main>
       <ProductFooter />
     </div>
   )
 }
diff --git a/viewer/src/console/ManagedApp.tsx b/viewer/src/console/ManagedApp.tsx
deleted file mode 100644
index cf4f8b0..0000000
--- a/viewer/src/console/ManagedApp.tsx
+++ /dev/null
@@ -1,265 +0,0 @@
-import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
-import { Landing } from './Landing'
-import { ManagedGraphLens, ManagedTimelineLens } from './ManagedLenses'
-import { registerAgentWithMetaMask } from '../agent0_wallet'
-import './managed.css'
-
-type Plan = { id: string; name: string; monthly_cents: number; max_memories: number; writes_per_month: number; retrievals_per_month: number }
-type Catalog = { plans: Plan[]; billing_configured: boolean; signup_enabled: boolean; hosted_inference_enabled: boolean }
-type Account = { account: { display_name: string; email: string }; entitlement: { plan: Plan; status: string; writable: boolean; period_end: number | null; cancel_at_period_end: boolean }; usage: { month: string; used: Record<string, number> }; counts: Record<string, number>; csrf_token: string }
-type Memory = { id: string; content: string; status: string }
-type Agent0Record = { agentId?: string; agentURI?: string; name?: string; description?: string; owners?: string[]; walletAddress?: string; trustModels?: unknown[]; endpoints?: Array<Record<string, unknown>>; active?: boolean }
-type Agent0Search = { agents: Agent0Record[]; source: 'agent0'; query: string }
-
-class ManagedError extends Error {
-  status: number
-  constructor(status: number, message: string) { super(message); this.status = status }
-}
-
-async function request<T>(path: string, options: RequestInit = {}, csrf?: string): Promise<T> {
-  const response = await fetch('/api/managed/' + path, { ...options, credentials: 'same-origin',
-    headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-Cortex-CSRF-Token': csrf } : {}), ...options.headers } })
-  const data = await response.json().catch(() => ({}))
-  if (!response.ok) throw new ManagedError(response.status, data.error || `Request failed (${response.status})`)
-  return data as T
-}
-
-export function ManagedApp() {
-  const [catalog, setCatalog] = useState<Catalog | null>(null)
-  const [account, setAccount] = useState<Account | null>(null)
-  const [loading, setLoading] = useState(true)
-  const [error, setError] = useState('')
-  const [notice, setNotice] = useState(() => new URLSearchParams(location.search).has('verified') ? 'Email verified. Sign in to open your workspace.' : '')
-  const [authMode, setAuthMode] = useState<'login' | 'signup' | 'forgot-password' | 'resend-verification' | 'reset' | null>(() => new URLSearchParams(location.search).has('reset_token') ? 'reset' : null)
-  const resetToken = useRef(new URLSearchParams(location.search).get('reset_token') || '')
-  const [keys, setKeys] = useState<Array<{id: string; label: string; expires_at: string; agent_ids?: string[]}>>([])
-  const [agentDids, setAgentDids] = useState('')
-  const [busy, setBusy] = useState(false)
-  const [memories, setMemories] = useState<Memory[]>([])
-  const [query, setQuery] = useState('')
-  const [newKey, setNewKey] = useState('')
-  const [lens, setLens] = useState<'workspace' | 'graph' | 'timeline'>('workspace')
-  const retryWrite = useRef<{ content: string; key: string } | null>(null)
-
-  const refresh = useCallback(async () => {
-    const state = await request<Account>('me')
-    setAccount(state)
-    return state
-  }, [])
-
-  useEffect(() => {
-    let alive = true
-    if (resetToken.current) history.replaceState(null, '', '/managed')
-    Promise.all([
-      request<Catalog>('plans'),
-      request<Account>('me').catch((e: unknown) => { if (e instanceof ManagedError && e.status === 401) return null; throw e }),
-    ]).then(([plans, state]) => { if (alive) { setCatalog(plans); setAccount(state) } })
-      .catch((e: Error) => { if (alive) setError(e.message) })
-      .finally(() => { if (alive) setLoading(false) })
-    return () => { alive = false }
-  }, [])
-
-  useEffect(() => {
-    if (authMode) document.querySelector('.xc-managed-auth')?.scrollIntoView({ block: 'center' })
-  }, [authMode])
-
-  const act = async (work: () => Promise<void>) => {
-    setError(''); setNotice(''); setBusy(true)
-    try { await work() } catch (e) {
-      if (e instanceof ManagedError && e.status === 401) { setAccount(null); setNewKey(''); setKeys([]); setMemories([]); setAuthMode('login') }
-      const message = e instanceof Error ? e.message : 'Request failed'
-      setError(message === 'account requires email verification or administrator approval'
-        ? 'Your email is not verified yet. Open the newest “Verify your Cortex account” email, click its link, then sign in again.'
-        : message)
-    }
-    finally { setBusy(false) }
-  }
-
-  const signIn = (event: FormEvent<HTMLFormElement>) => {
-    event.preventDefault()
-    const fields = new FormData(event.currentTarget)
-    void act(async () => {
-      const recovery = authMode && !['signup', 'login'].includes(authMode)
-      const input = { ...Object.fromEntries(fields), ...(authMode === 'reset' ? { token: resetToken.current } : {}) }
-      await request(recovery ? 'recovery/' + authMode : authMode === 'signup' ? 'signup' : 'login', { method: 'POST', body: JSON.stringify(input) })
-      if (recovery) {
-        setNotice(authMode === 'reset' ? 'Password reset. Sign in with your new password.' : 'If this account needs this action, an email has been sent.')
-        if (authMode === 'reset') { resetToken.current = ''; history.replaceState(null, '', '/managed'); setAuthMode('login') }
-        return
-      }
-      if (authMode === 'signup') setNotice('Check your email for a verification link. Verify your address before signing in.')
-      else { await refresh(); setAuthMode(null) }
-    })
-  }
-
-  const billing = (plan?: string) => void act(async () => {
-    const result = await request<{ url: string }>(plan ? 'checkout' : 'portal', { method: 'POST', body: JSON.stringify(plan ? { plan } : {}) }, account?.csrf_token)
-    const destination = new URL(result.url)
-    if (destination.protocol !== 'https:' || !['checkout.stripe.com', 'billing.stripe.com'].includes(destination.hostname)) throw new Error('The payment service returned an invalid destination')
-    location.assign(destination.href)
-  })
-
-  const search = () => void act(async () => {
-    const result = await request<{ memories: Memory[] }>('memories' + (query.trim() ? '?q=' + encodeURIComponent(query.trim()) : ''))
-    setMemories(result.memories)
-    await refresh()
-  })
-
-  const exportMemories = () => void act(async () => {
-    await refresh()
-    const link = document.createElement('a')
-    link.href = '/api/managed/export-download'; link.download = 'cortex-memories.json'; link.click()
-    setNotice('Your memory export download has started.')
-  })
-
-  const cards = catalog && <div className="xc-managed-plans">
-    {catalog.plans.map((plan) => <article className="xc-win xc-managed-plan" key={plan.id} aria-label={plan.name + ' plan'}>
-      <p className="xc-eyebrow">{plan.name}</p>
-      <h3 className="xc-managed-price">${plan.monthly_cents / 100}<span> / month</span></h3>
-      <p className="xc-note">USD · monthly subscription</p>
-      <dl className="xc-managed-limits">
-        <div><dt>Stored memories</dt><dd>{plan.max_memories.toLocaleString()}</dd></div>
-        <div><dt>Write requests / month</dt><dd>{plan.writes_per_month.toLocaleString()}</dd></div>
-        <div><dt>Retrieval requests / month</dt><dd>{plan.retrievals_per_month.toLocaleString()}</dd></div>
-      </dl>
-      <p className="xc-copy">Isolated memory storage, a verifiable event history, lexical search, API keys, and data export.</p>
-      {account ? <button className="xc-btn xc-btn--primary" disabled={busy || plan.id === 'free' || plan.id === account.entitlement.plan.id || !catalog.billing_configured} onClick={() => account.entitlement.plan.id === 'free' ? billing(plan.id) : billing()}>
-        {plan.id === account.entitlement.plan.id ? 'Current plan' : plan.id === 'free' ? 'Manage through billing' : account.entitlement.plan.id === 'free' ? 'Choose ' + plan.name : 'Change through billing'}
-      </button> : <button className="xc-btn xc-btn--primary" disabled={busy || !catalog.signup_enabled || (plan.id !== 'free' && !catalog.billing_configured)} onClick={() => setAuthMode('signup')}>
-        {plan.id === 'free' ? 'Start free' : 'Choose ' + plan.name}
-      </button>}
-    </article>)}
-  </div>
-
-  const messages = <div aria-live="polite">
-    {error && <p className="xc-callout xc-callout--conflict" role="alert">{error}</p>}
-    {notice && <p className="xc-callout">{notice}</p>}
-  </div>
-
-  if (loading) return <div className="xc"><main className="xc-managed"><p className="xc-note">Loading managed memory services…</p></main></div>
-
-  if (!account) return <div className="xc"><Landing managed onSignIn={() => setAuthMode('login')}>
-    <section className="xc-landing-section" id="pricing" aria-labelledby="managed-plans-title">
-      <p className="xc-eyebrow">Managed memory</p>
-      <h2 className="xc-landing-h2" id="managed-plans-title">Choose the capacity you need</h2>
-      {!authMode && messages}
-      {cards}
-      {catalog && !catalog.billing_configured && <p className="xc-note xc-managed-note">Paid subscriptions are not available yet.</p>}
-      {catalog && !catalog.signup_enabled && <p className="xc-note">New workspace registration is not available yet.</p>}
-      <p className="xc-note xc-managed-note">Limits reset monthly in UTC. Each memory supports up to 16 KiB of text. These plans cover memory storage and lexical retrieval; hosted inference is not included yet. Team provides higher workspace capacity; shared user seats are not offered in this release.</p>
-    </section>
-    {authMode && <section className="xc-landing-section xc-managed-auth" aria-labelledby="managed-auth-title">
-      <h2 className="xc-landing-h2" id="managed-auth-title">{authMode === 'signup' ? 'Create your workspace' : authMode === 'forgot-password' ? 'Reset your password' : authMode === 'resend-verification' ? 'Resend verification email' : authMode === 'reset' ? 'Set a new password' : 'Sign in to managed Cortex'}</h2>
-      {messages}
-      <form className="xc-managed-form" onSubmit={signIn}>
-        {authMode === 'signup' && <label className="xc-field">Name<input className="xc-input" name="display_name" autoComplete="name" required maxLength={120} /></label>}
-        {authMode !== 'reset' && <label className="xc-field">Email<input className="xc-input" name="email" type="email" autoComplete="username" required /></label>}
-        {!['forgot-password', 'resend-verification'].includes(authMode) && <label className="xc-field">Password<input className="xc-input" name="password" type="password" autoComplete={authMode === 'login' ? 'current-password' : 'new-password'} minLength={10} required /></label>}
-        <button className="xc-btn xc-btn--primary" disabled={busy || (authMode === 'signup' && !catalog?.signup_enabled)}>{busy ? 'Working…' : authMode === 'signup' ? 'Create workspace' : authMode === 'login' ? 'Sign in' : authMode === 'reset' ? 'Set password' : 'Send email'}</button>
-        <button className="xc-btn" type="button" disabled={busy || (authMode === 'login' && !catalog?.signup_enabled)} onClick={() => setAuthMode(authMode === 'login' ? 'signup' : 'login')}>{authMode === 'login' ? 'Create an account' : 'I already have an account'}</button>
-        <button className="xc-btn" type="button" disabled={busy} onClick={() => setAuthMode('forgot-password')}>Forgot password</button>
-        <button className="xc-btn" type="button" disabled={busy} onClick={() => setAuthMode('resend-verification')}>Resend verification</button>
-      </form>
-    </section>}
-  </Landing></div>
-
-  if (lens === 'graph') return <div className="xc"><main className="xc-managed"><div className="xc-managed-inner"><ManagedGraphLens onBack={() => setLens('workspace')} /></div></main></div>
-  if (lens === 'timeline') return <div className="xc"><main className="xc-managed"><div className="xc-managed-inner"><ManagedTimelineLens onBack={() => setLens('workspace')} /></div></main></div>
-
-  return <div className="xc"><main className="xc-managed"><div className="xc-managed-inner">
-    <header className="xc-managed-head">
-      <a className="xc-brand" href="/managed" aria-label="Xibalba Cortex"><img className="xc-managed-logo" src="/cortex-rail-mark.png" alt="" /><b>Xibalba Cortex</b></a>
-      <span className="xc-tag">{account.entitlement.plan.name}</span>
-      <div className="xc-managed-nav" aria-label="Explore workspace"><button className="xc-btn" onClick={() => setLens('graph')}>Graph</button><button className="xc-btn" onClick={() => setLens('timeline')}>Timeline</button></div>
-      <button className="xc-btn" disabled={busy} onClick={() => void act(async () => { await request('logout', { method: 'POST' }, account.csrf_token); setAccount(null); setMemories([]); setNewKey(''); setKeys([]); setQuery('') })}>Sign out</button>
-    </header>
-    <p className="xc-eyebrow">Managed workspace</p>
-    <h1 className="xc-managed-title">{account.account.display_name}’s memory</h1>
-    {messages}
-    {!account.entitlement.writable && <p className="xc-callout">This workspace is read-only. Your existing memories remain available to read and export. Update billing to resume writes.</p>}
-    <section className="xc-win xc-managed-panel" aria-label="Usage and subscription">
-      <h2 className="xc-title">Usage · {account.usage.month} UTC</h2>
-      <div className="xc-managed-usage">
-        <p><b>{(account.counts.memories ?? 0).toLocaleString()}</b> / {account.entitlement.plan.max_memories.toLocaleString()} stored memories</p>
-        <p><b>{(account.usage.used.writes ?? 0).toLocaleString()}</b> / {account.entitlement.plan.writes_per_month.toLocaleString()} write requests</p>
-        <p><b>{(account.usage.used.retrievals ?? 0).toLocaleString()}</b> / {account.entitlement.plan.retrievals_per_month.toLocaleString()} retrieval requests</p>
-      </div>
-      <p className="xc-note">Subscription status: {account.entitlement.status}{account.entitlement.cancel_at_period_end ? ' · cancels at the end of the paid period' : ''}</p>
-      <div className="xc-managed-actions"><button className="xc-btn" disabled={busy || !catalog?.billing_configured} onClick={() => billing()}>Manage billing</button><button className="xc-btn" disabled={busy} onClick={exportMemories}>Export memories</button></div>
-    </section>
-    <section className="xc-win xc-managed-panel" aria-label="Memory workspace">
-      <h2 className="xc-title">Store and retrieve</h2>
-      <form className="xc-managed-form" onSubmit={(event) => {
-        event.preventDefault(); const form = event.currentTarget; const content = String(new FormData(form).get('content') || '')
-        if (retryWrite.current?.content !== content) retryWrite.current = { content, key: crypto.randomUUID() }
-        const write = retryWrite.current
-        void act(async () => { await request('memories', { method: 'POST', body: JSON.stringify({ content }), headers: { 'Idempotency-Key': write!.key } }, account.csrf_token); retryWrite.current = null; form.reset(); await refresh(); setNotice('Memory saved with a verifiable event history.') })
-      }}>
-        <label className="xc-field">Memory<textarea className="xc-input" name="content" required maxLength={16384} rows={4} disabled={!account.entitlement.writable} /></label>
-        <button className="xc-btn xc-btn--primary" disabled={busy || !account.entitlement.writable}>Save memory</button>
-      </form>
-      <form className="xc-managed-search" onSubmit={(event) => { event.preventDefault(); search() }}>
-        <label className="xc-field">Search memories<input className="xc-input" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={500} /></label>
-        <button className="xc-btn" disabled={busy}>Search / list</button>
-      </form>
-      <div className="xc-managed-results">{memories.map((memory) => <article key={memory.id}><p className="xc-copy">{memory.content}</p><p className="xc-meta">{memory.id}</p></article>)}</div>
-    </section>
-    <section className="xc-win xc-managed-panel" aria-label="Agent API keys">
-      <h2 className="xc-title">Connect an agent</h2>
-      <p className="xc-copy">Bind a key to the agent’s stable <code>did:integrity:…</code> identity. The same DID can use MCP or the SDK; keys expire after 30 days and are shown once.</p>
-      <label className="xc-field">Agent DIDs<textarea className="xc-input xc-input--mono" value={agentDids} onChange={(event) => setAgentDids(event.target.value)} placeholder="did:integrity:…" rows={3} required /></label>
-      <p className="xc-note">Enter one DID per line or separate them with commas. One key can serve multiple agents on the same device.</p>
-      <button className="xc-btn" disabled={busy || !agentDids.trim()} onClick={() => void act(async () => { const ids = [...new Set(agentDids.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean))]; if (ids.length === 0) throw new Error('Enter at least one agent DID'); const result = await request<{ token: string }>('keys', { method: 'POST', body: JSON.stringify({ label: 'agent', agent_ids: ids }) }, account.csrf_token); setNewKey(result.token) })}>Create API key</button>
-      <button className="xc-btn" disabled={busy} onClick={() => void act(async () => { setKeys((await request<{keys: typeof keys}>('keys')).keys) })}>Show API keys</button>
-      {keys.map((key) => <div className="xc-managed-actions" key={key.id}><span className="xc-note">{key.label.replace(/^managed-api:/, '')} · {key.agent_ids?.length ? `${key.agent_ids.length} agent${key.agent_ids.length === 1 ? '' : 's'}` : 'unbound'} · expires {new Date(key.expires_at).toLocaleDateString()}</span><button className="xc-btn" disabled={busy} onClick={() => void act(async () => { await request('keys/revoke', { method: 'POST', body: JSON.stringify({ id: key.id }) }, account.csrf_token); setKeys(keys.filter((item) => item.id !== key.id)); setNewKey('') })}>Revoke key</button></div>)}
-      {newKey && <div><p className="xc-note">Copy this key now; it will disappear when you leave this page.</p><code className="xc-managed-key">{newKey}</code><button className="xc-btn" onClick={() => setNewKey('')}>Hide key</button></div>}
-    </section>
-    <ManagedAgent0Directory />
-    <section aria-labelledby="workspace-plans-title"><h2 className="xc-landing-h2" id="workspace-plans-title">Workspace plans</h2>{cards}{!catalog?.billing_configured && <p className="xc-note xc-managed-note">Paid subscriptions are not available yet.</p>}</section>
-  </div></main></div>
-}
-
-function ManagedAgent0Directory() {
-  const [query, setQuery] = useState('')
-  const [agents, setAgents] = useState<Agent0Record[]>([])
-  const [selected, setSelected] = useState<Agent0Record | null>(null)
-  const [busy, setBusy] = useState(false)
-  const [message, setMessage] = useState('')
-  const [name, setName] = useState('Cortex Managed Test Agent')
-  const [description, setDescription] = useState('Test ERC-8004 identity registered from managed Cortex with MetaMask on Base Sepolia.')
-  const [txHash, setTxHash] = useState('')
-  const search = async (event: FormEvent) => {
-    event.preventDefault(); setBusy(true); setMessage('')
-    try { const result = await request<Agent0Search>('agent0/search?q=' + encodeURIComponent(query.trim())); setAgents(result.agents); setSelected(null) }
-    catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
-    finally { setBusy(false) }
-  }
-  const register = async (event: FormEvent) => {
-    event.preventDefault(); setBusy(true); setMessage(''); setTxHash('')
-    try { const result = await registerAgentWithMetaMask({ name, description }); setSelected(result.record as Agent0Record); setTxHash(result.txHash); setMessage(`Registered ${result.agentId} on Base Sepolia.`) }
-    catch (error) { setMessage(error instanceof Error ? error.message : String(error)) }
-    finally { setBusy(false) }
-  }
-  return <section className="xc-win xc-managed-panel xc-managed-agent0" aria-labelledby="managed-agent0-title">
-    <p className="xc-eyebrow">External directory · Agent0</p>
-    <h2 className="xc-title" id="managed-agent0-title">Search ERC-8004 agents</h2>
-    <p className="xc-copy">Managed and local Cortex use the same Agent0/ERC-8004 directory and MetaMask registration flow. Agent0 remains external chain evidence, not workspace authorization.</p>
-    <form className="xc-managed-search" onSubmit={search}>
-      <label className="xc-field">Search by name<input className="xc-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="agent name (optional)" /></label>
-      <button className="xc-btn xc-btn--primary" disabled={busy}>Search</button>
-    </form>
-    <details className="xc-managed-agent0-register">
-      <summary className="xc-btn">Register a test identity with MetaMask</summary>
-      <form className="xc-managed-form" onSubmit={register}>
-        <label className="xc-field">Name<input className="xc-input" value={name} onChange={(event) => setName(event.target.value)} required /></label>
-        <label className="xc-field">Description<textarea className="xc-input" value={description} onChange={(event) => setDescription(event.target.value)} rows={3} required /></label>
-        <p className="xc-note">MetaMask will switch to Base Sepolia and ask for approval. Gas is paid by the connected wallet.</p>
-        <button className="xc-btn xc-btn--primary" disabled={busy}>{busy ? 'Waiting…' : 'Connect & register'}</button>
-      </form>
-    </details>
-    {message && <p className="xc-callout xc-callout--review" role="status">{message}</p>}
-    {txHash && <p className="xc-note">Confirmed transaction: <a className="xc-mono" href={`https://sepolia.basescan.org/tx/${txHash}`} target="_blank" rel="noreferrer">{txHash}</a></p>}
-    {agents.map((agent) => <button className="xc-managed-agent0-result" type="button" key={String(agent.agentId)} onClick={() => setSelected(agent)}><b>{agent.name || 'Unnamed agent'}</b><span className="xc-mono">{agent.agentId}</span></button>)}
-    {selected && <div className="xc-managed-agent0-detail"><p className="xc-eyebrow">On-chain agent record</p><h3 className="xc-title">{selected.name || selected.agentId}</h3><p className="xc-mono">{selected.agentId}</p><dl className="xc-kv"><div><dt>Description</dt><dd>{selected.description || '—'}</dd></div><div><dt>Owner</dt><dd className="xc-mono">{selected.owners?.join(', ') || '—'}</dd></div><div><dt>Wallet</dt><dd className="xc-mono">{selected.walletAddress || '—'}</dd></div><div><dt>Agent URI</dt><dd className="xc-mono">{selected.agentURI || '—'}</dd></div><div><dt>Trust models</dt><dd>{selected.trustModels?.join(', ') || '—'}</dd></div></dl><p className="xc-note">Source: Agent0 / ERC-8004. This record does not grant workspace access.</p></div>}
-  </section>
-}
diff --git a/viewer/src/console/ManagedLenses.tsx b/viewer/src/console/ManagedLenses.tsx
deleted file mode 100644
index 4272d2b..0000000
--- a/viewer/src/console/ManagedLenses.tsx
+++ /dev/null
@@ -1,61 +0,0 @@
-import { useEffect, useMemo, useRef, useState } from 'react'
-import ForceGraph2D from 'react-force-graph-2d'
-
-type GraphNode = { id: string; type: string; label: string; status?: string; created_at?: string; observed_at?: string | null; session_id?: string | null }
-type GraphEdge = { source: string; target: string; type: string; predicate?: string }
-type GraphData = { nodes: GraphNode[]; edges: GraphEdge[] }
-type Session = { external_session_id: string; started_at: string; ended_at?: string | null; active?: boolean }
-type TimelineData = { sessions: Session[]; nodes: GraphNode[] }
-
-async function read<T>(path: string): Promise<T> {
-  const response = await fetch('/api/managed/' + path, { credentials: 'same-origin' })
-  const data = await response.json().catch(() => ({}))
-  if (!response.ok) throw new Error(data.error || 'Request failed (' + response.status + ')')
-  return data as T
-}
-
-export function ManagedGraphLens({ onBack }: { onBack: () => void }) {
-  const host = useRef<HTMLDivElement>(null)
-  const [width, setWidth] = useState(720)
-  const [data, setData] = useState<GraphData | null>(null)
-  const [error, setError] = useState('')
-  useEffect(() => {
-    const element = host.current
-    if (!element || typeof ResizeObserver === 'undefined') return
-    const observer = new ResizeObserver(() => setWidth(Math.max(320, Math.floor(element.clientWidth))))
-    observer.observe(element)
-    setWidth(Math.max(320, Math.floor(element.clientWidth)))
-    return () => observer.disconnect()
-  }, [])
-  useEffect(() => { read<GraphData>('graph?limit=700').then(setData).catch((e: Error) => setError(e.message)) }, [])
-  return <section className="xc-managed-lens" aria-label="Managed Graph">
-    <header className="xc-managed-lens-head"><div><p className="xc-eyebrow">Explore</p><h2 className="xc-title">Graph</h2><p className="xc-note">Memories, entities, sessions and their verified relationships.</p></div><button className="xc-btn" onClick={onBack}>Back to workspace</button></header>
-    {error && <p className="xc-callout xc-callout--conflict" role="alert">{error}</p>}
-    {!data && !error && <p className="xc-note">Loading graph…</p>}
-    {data && <div ref={host} className="xc-managed-graph" aria-label="Managed memory graph">
-      {data.nodes.length === 0 ? <div className="xc-empty"><h3 className="xc-title">No graph data yet</h3><p>Connect an agent and let it write a memory first.</p></div> : <ForceGraph2D width={width} height={620} graphData={{ nodes: data.nodes, links: data.edges }} nodeLabel={(node) => node.type + ': ' + node.label} nodeAutoColorBy="type" linkDirectionalArrowLength={3} linkDirectionalArrowRelPos={1} linkLabel={(link) => link.predicate || link.type} cooldownTicks={120} />}
-    </div>}
-  </section>
-}
-
-export function ManagedTimelineLens({ onBack }: { onBack: () => void }) {
-  const [data, setData] = useState<TimelineData | null>(null)
-  const [error, setError] = useState('')
-  useEffect(() => { read<TimelineData>('timeline?limit=700').then(setData).catch((e: Error) => setError(e.message)) }, [])
-  const timed = useMemo(() => (data?.nodes ?? []).filter((node) => node.type === 'memory' || node.type === 'exchange').map((node) => ({ node, time: Date.parse(node.observed_at || node.created_at || '') })).filter((item) => Number.isFinite(item.time)), [data])
-  const domain = useMemo(() => { const values = timed.map((item) => item.time); if (!values.length) return null; const from = Math.min(...values); const to = Math.max(Date.now(), ...values); return { from, to: Math.max(from + 3600000, to) } }, [timed])
-  const sessions = data?.sessions ?? []
-  return <section className="xc-managed-lens" aria-label="Managed Timeline">
-    <header className="xc-managed-lens-head"><div><p className="xc-eyebrow">Explore</p><h2 className="xc-title">Timeline</h2><p className="xc-note">Click a mark to inspect when an agent recorded it.</p></div><button className="xc-btn" onClick={onBack}>Back to workspace</button></header>
-    {error && <p className="xc-callout xc-callout--conflict" role="alert">{error}</p>}
-    {!data && !error && <p className="xc-note">Loading timeline…</p>}
-    {data && !domain && <div className="xc-empty"><h3 className="xc-title">No timed activity yet</h3><p>Sessions and memories will appear here after your agents connect.</p></div>}
-    {data && domain && <div className="xc-managed-timeline" role="table" aria-label="Managed activity timeline">
-      <div className="xc-managed-time-axis"><span>{new Date(domain.from).toLocaleString()}</span><span>{new Date(domain.to).toLocaleString()}</span></div>
-      {(sessions.length ? sessions : [{ external_session_id: 'unassigned', started_at: new Date(domain.from).toISOString(), ended_at: null }]).map((session) => {
-        const marks = timed.filter((item) => item.node.session_id === session.external_session_id || (session.external_session_id === 'unassigned' && !item.node.session_id))
-        return <div className="xc-managed-lane" key={session.external_session_id} role="row"><div className="xc-managed-lane-label"><b>{session.external_session_id.slice(0, 18)}</b><span>{marks.length} event{marks.length === 1 ? '' : 's'}</span></div><div className="xc-managed-lane-track">{marks.map((item) => <button key={item.node.id} className="xc-managed-mark" style={{ left: ((item.time - domain.from) / (domain.to - domain.from)) * 100 + '%' }} title={item.node.label} aria-label={item.node.label}>{item.node.type === 'memory' ? 'M' : 'E'}</button>)}</div></div>
-      })}
-    </div>}
-  </section>
-}
diff --git a/viewer/src/console/managed.css b/viewer/src/console/managed.css
deleted file mode 100644
index 6fccc50..0000000
--- a/viewer/src/console/managed.css
+++ /dev/null
@@ -1,45 +0,0 @@
-.xc-managed { flex: 1; min-height: 0; overflow: auto; padding: 32px var(--gutter) 64px; }
-.xc-managed-inner { max-width: 1280px; margin-inline: auto; }
-.xc-managed-head { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; padding-bottom: 24px; margin-bottom: 32px; border-bottom: 1px solid var(--hairline); }
-.xc-managed-logo { width: 48px; height: auto; }
-.xc-managed-title { font: 600 32px/1.12 var(--font-condensed); margin-block: 12px 32px; overflow-wrap: anywhere; }
-.xc-managed-plans { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; }
-.xc-managed-plan { min-width: 0; padding: 24px; display: flex; flex-direction: column; gap: 16px; }
-.xc-managed-price { font: 600 42px/1.1 var(--font-condensed); }
-.xc-managed-price span { font: 400 15px/1.4 var(--font-body); color: var(--ink-muted); }
-.xc-managed-limits { margin: 0; display: grid; gap: 12px; }
-.xc-managed-limits > div { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 6px; border-bottom: 1px solid var(--hairline-faint); padding-bottom: 8px; }
-.xc-managed-limits dt { color: var(--ink-muted); font-size: 13px; }
-.xc-managed-limits dd { margin: 0; font: 500 15px var(--font-mono); }
-.xc-managed-plan > .xc-btn { margin-top: auto; }
-.xc-managed-note { margin-block: 24px 16px; }
-.xc-managed-form { max-width: 560px; display: grid; gap: 16px; }
-.xc-managed-form textarea { height: auto; min-height: 100px; resize: vertical; }
-.xc-managed-panel { padding: 24px; display: grid; gap: 20px; margin-bottom: 32px; }
-.xc-managed-usage { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; color: var(--ink-muted); }
-.xc-managed-usage b { color: var(--ink); }
-.xc-managed-actions { display: flex; flex-wrap: wrap; gap: 12px; }
-.xc-managed-search { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; }
-.xc-managed-search .xc-field { flex: 1; min-width: 180px; }
-.xc-managed-results { display: grid; gap: 16px; }
-.xc-managed-results article { border-top: 1px solid var(--hairline); padding-top: 12px; overflow-wrap: anywhere; }
-.xc-managed-key { display: block; margin-block: 12px; overflow-wrap: anywhere; font-size: 13px; }
-.xc-managed-nav { display: flex; gap: 8px; margin-left: auto; }
-.xc-managed-lens { min-height: 700px; }
-.xc-managed-lens-head { display: flex; align-items: start; justify-content: space-between; gap: 20px; padding-bottom: 24px; margin-bottom: 24px; border-bottom: 1px solid var(--hairline); }
-.xc-managed-graph { min-height: 620px; border: 1px solid var(--hairline); overflow: hidden; background: var(--surface); }
-.xc-managed-timeline { display: grid; gap: 18px; overflow-x: auto; padding: 10px 0 30px; }
-.xc-managed-time-axis { display: flex; justify-content: space-between; gap: 16px; color: var(--ink-muted); font: 12px var(--font-mono); min-width: 620px; }
-.xc-managed-lane { display: grid; grid-template-columns: 180px minmax(440px, 1fr); gap: 18px; align-items: center; min-width: 620px; }
-.xc-managed-lane-label { display: grid; gap: 4px; overflow-wrap: anywhere; }
-.xc-managed-lane-label span { color: var(--ink-muted); font-size: 12px; }
-.xc-managed-lane-track { position: relative; height: 34px; border-top: 1px solid var(--hairline); border-bottom: 1px solid var(--hairline); background: repeating-linear-gradient(90deg, transparent 0, transparent calc(12.5% - 1px), var(--hairline-faint) 12.5%); }
-.xc-managed-mark { position: absolute; top: 7px; width: 20px; height: 20px; padding: 0; transform: translateX(-50%); border: 1px solid var(--accent); border-radius: 50%; background: var(--surface); color: var(--ink); font: 600 10px var(--font-mono); cursor: pointer; }
-.xc-managed-mark:hover, .xc-managed-mark:focus-visible { background: var(--accent); color: var(--ink-on-accent); }
-@media (max-width: 760px) {
-  .xc-managed-plans, .xc-managed-usage { grid-template-columns: minmax(0, 1fr); }
-  .xc-managed-plan, .xc-managed-panel { padding: 20px; }
-  .xc-managed { padding-top: 20px; }
-  .xc-managed-lens-head { flex-direction: column; }
-  .xc-managed-nav { width: 100%; margin-left: 0; }
-}
```
