import { expect, test } from '@playwright/test'
import { managedFixture } from './managed-fixture'
import { openConsole } from './helpers'

for (const width of [320, 390, 1280, 1600]) {
  test(`managed plans show the approved catalog without overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 })
    await managedFixture(page)
    await page.goto('/managed')
    for (const [name, price] of [['Free', '$0'], ['Pro', '$29'], ['Team', '$149']]) {
      const card = page.getByRole('article', { name: name + ' plan' })
      await expect(card).toBeAttached()
      await expect(card).toContainText(price)
    }
    /* `#plans` until dbc58b6 renamed the anchor to `#pricing` so the landing nav could link
       to it; the test was not updated and has been red since. */
    await page.locator('#pricing').scrollIntoViewIfNeeded()
    await expect(page.getByRole('button', { name: 'Choose Pro', exact: true })).toBeDisabled()
    await expect(page.getByText('Paid subscriptions are not available yet.', { exact: true })).toBeVisible()
    const overflow = await page.locator('.xc-landing').evaluate((el) => el.scrollWidth - el.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
  })
}

test('signup requires verification and never grants an immediate signed-in workspace', async ({ page }) => {
  const calls = await managedFixture(page)
  await page.goto('/managed')
  await page.getByRole('button', { name: 'Start free', exact: true }).click()
  /* The hosted account form is the console's own now (`#hosted-auth`, HostedLanding.tsx); the
     `.xc-managed-auth` section it used to live in belonged to the second UI. Only the selector
     moved -- every assertion below is the one that was here. */
  const form = page.locator('#hosted-auth form')
  await form.getByLabel('Name', { exact: true }).fill('Operator')
  await form.getByLabel('Email', { exact: true }).fill('operator@example.com')
  await form.getByLabel('Password', { exact: true }).fill('test-only-password')
  await form.getByRole('button', { name: 'Create workspace', exact: true }).click()
  await expect(page.getByText('Check your email for a verification link.', { exact: false })).toBeVisible()
  expect(calls.filter((call) => call.path === 'login')).toHaveLength(0)
  /* "no signed-in workspace" has to name a thing that still exists. It used to be the second UI's
     `Operator’s memory` heading (ManagedApp.tsx:177), which nothing renders now -- so that half of
     the test could no longer fail. The console's signed-in marker is the workspace itself. */
  await expect(page.locator('.xc-workspace')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Open operator profile settings' })).toHaveCount(0)
})

/* Re-homed from the second UI's single screen onto the console's own surfaces: the write is
   Memories -> New memory, the search is Memories' search box, and the key is Agents' hosted
   API-keys section (AgentsPage.tsx, HostedApiKeys). Seeded memories make the search a real filter:
   without them the new memory is the only row, and "search finds it" could not fail. */
test('a workspace stores and searches memory, then creates and revokes an API key', async ({ page }) => {
  const calls = await managedFixture(page, { signedIn: true, seed: 2 })
  await page.goto('/managed#memories')
  await page.getByRole('button', { name: 'New memory', exact: true }).click()
  await page.getByLabel('Text', { exact: true }).fill('Remember this test-only fact')
  await page.getByRole('button', { name: 'Add memory', exact: true }).click()
  await expect(page.getByRole('main').getByText(/Memory \S+ added to/)).toBeVisible()
  const write = calls.find((call) => call.path === 'memories' && call.method === 'POST')!
  expect(write.body).toEqual({ content: 'Remember this test-only fact' })
  await page.getByLabel('Search memory text', { exact: true }).fill('test-only')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  const list = page.getByRole('region', { name: 'Memory list' })
  await expect(list).toContainText('Remember this test-only fact')
  // the search filters: a seeded memory that does not match is gone, so the line above is not just "everything is listed"
  await expect(list).not.toContainText('Seeded memory 0')

  await page.goto('/managed#agents')
  /* A key is bound to the agent DIDs it is for, so the field is `required` and the button
     stays disabled until it has one (AgentsPage.tsx, `!dids.trim()`). Before this rule was
     asserted, the click waited out the full 90s timeout against a permanently disabled button. */
  const create = page.getByRole('button', { name: 'Create API key', exact: true })
  await expect(create).toBeDisabled()
  await page.getByRole('textbox', { name: /^Agent DIDs/ }).fill('did:integrity:test-agent-one\ndid:integrity:test-agent-two')
  await expect(create).toBeEnabled()
  await create.click()
  const issuedKey = page.getByLabel('New API key', { exact: true })
  await expect(issuedKey.locator('code')).toHaveText('fixture-only-managed-key')
  // the DIDs reach the API, de-duplicated and split on newlines or commas -- the point of the field
  const issued = calls.find((call) => call.path === 'keys' && call.method === 'POST')!
  expect(issued.body).toEqual({ label: 'agent', agent_ids: ['did:integrity:test-agent-one', 'did:integrity:test-agent-two'] })
  expect(await page.evaluate(() => Object.values(localStorage).join(' '))).not.toContain('fixture-only-managed-key')
  await page.getByRole('button', { name: 'Show API keys', exact: true }).click()
  await page.getByRole('button', { name: 'Revoke key', exact: true }).click()
  await expect(issuedKey).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Revoke key', exact: true })).toHaveCount(0)
  expect(calls.filter((call) => call.path === 'keys/revoke' && call.method === 'POST')).toHaveLength(1)
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

/* A read-only subscription keeps search and export and is refused writes. On the console the write
   control is not rendered rather than disabled (MemoriesPage.tsx), and the entitlement's own
   wording is on Billing (billing.ts READ_ONLY_WORKSPACE). */
test('read-only subscriptions retain export and search without permitting writes', async ({ page }) => {
  await managedFixture(page, { signedIn: true, plan: 'pro', writable: false, seed: 2 })
  await page.goto('/managed#memories')
  await expect(page.getByRole('button', { name: 'Export memories', exact: true })).toBeEnabled()
  /* The absences come BEFORE the read-only note, per the lesson recorded in hosted-paths.spec.ts:
     both read the same `workspace.canWrite`, so with the note asserted first a `writable: true`
     mutation fails THERE and these two are never reached -- which is how an absence goes unproven.
     Verified 2026-11-03: in the note-first order the mutation died at the note; in this order it
     dies on 'New memory', so the absences are the assertions actually carrying the gate. */
  await expect(page.getByRole('button', { name: 'New memory', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Import a document', exact: true })).toHaveCount(0)
  await expect(page.getByRole('note').filter({ hasText: 'Read only.' })).toBeVisible()
  // search still works: it filters the existing memories
  const list = page.getByRole('region', { name: 'Memory list' })
  await expect(list).toContainText('Seeded memory 0')
  await page.getByLabel('Search memory text', { exact: true }).fill('Seeded memory 1')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(list).toContainText('Seeded memory 1')
  await expect(list).not.toContainText('Seeded memory 0')
  /* Deliberately NOT asserting "no POST memories": nothing here attempts a write -- the controls
     are asserted absent above -- and hostedApi.ts:354 refuses a hosted write client-side before
     the network, so that assertion holds with or without the gate. hosted-paths.spec.ts declines
     the same vacuous assertion for the same reason. The gate on the CALL is proved in
     src/hostedApi.test.ts, `describe('the hosted write gate (finding 4)')`, where a write IS
     attempted: it asserts READ_ONLY_WORKSPACE, status 402 and an empty call list, with the
     converse case issuing POST /api/managed/memories once the subscription is active. */
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
  await expect(tabs.getByRole('button', { name: 'Agents', exact: true })).toBeVisible()
  await expect(tabs.getByRole('button', { name: 'Billing', exact: true })).toBeVisible()
  await expect(tabs.getByRole('button', { name: 'Operations', exact: true })).toHaveCount(0)

  /* The same rule, one level up. `PRIMARY_NAV` is graph/memories/recall/review/integrity, and a
     hosted server declares neither `review` nor `integrity` -- their surfaces call bare `/api/*`,
     which the managed backend answers 404. So the rail must offer three of the five, not five.
     Without this, reverting `primaryDestinations(destinations)` to the default list puts Review
     and Integrity back on the hosted rail and nothing fails. */
  const rail = page.locator('.xc-rail-nav')
  await expect(rail.getByRole('button', { name: 'Workspace', exact: true })).toBeVisible()
  await expect(rail.getByRole('button', { name: 'Explore', exact: true })).toBeVisible()
  await expect(rail.getByRole('button', { name: 'Recall', exact: true })).toBeVisible()
  await expect(rail.getByRole('button', { name: 'Review', exact: true })).toHaveCount(0)
  await expect(rail.getByRole('button', { name: 'Integrity', exact: true })).toHaveCount(0)
})

/* The third layout. `Phone.tsx` reads the same list three times -- the tab bar's four, the "is a
   secondary destination current" check, and the More sheet's groups -- and none of it had
   executable coverage. `review` is in the phone's PRIMARY four and is NOT declared by a hosted
   server, so the tab bar is the sharpest place to see the difference; More is where `billing`
   becomes reachable at all on a phone. */
test('the hosted phone layout lists only the declared destinations', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await managedFixture(page, { signedIn: true })
  await page.goto('/managed')
  const tabbar = page.locator('.xc-tabbar')
  await expect(tabbar.getByRole('button', { name: 'Graph', exact: true })).toBeVisible()
  await expect(tabbar.getByRole('button', { name: 'Timeline', exact: true })).toBeVisible()
  await expect(tabbar.getByRole('button', { name: 'Recall', exact: true })).toBeVisible()
  await expect(tabbar.getByRole('button', { name: 'Review', exact: true })).toHaveCount(0)
  await tabbar.getByRole('button', { name: 'More', exact: true }).click()
  const more = page.locator('.xc-more')
  /* `MoreList` filters out the phone's own PRIMARY four, so `review` can never appear here
     whatever the declared list says -- an assertion about its absence would be unfailable, which
     is the thing we keep finding. Review's exclusion is covered by the tab-bar check above, where
     it IS reachable. What this sheet can get wrong is the rest: `integrity` and `operations` are
     undeclared and must not be listed, and `billing` is declared and is only reachable here. */
  // `Memories` first: it is listed either way, so it is the positive wait that makes the two
  // absences below meaningful. The absences come before the `Billing` check on purpose -- with
  // `Billing` first, a mutation of this very site fails there and the absences are never reached,
  // which is how they went unproven in round 1.
  await expect(more.getByRole('button', { name: /^Memories/ })).toBeVisible()
  await expect(more.getByRole('button', { name: /^Integrity/ })).toHaveCount(0)
  await expect(more.getByRole('button', { name: /^Operations/ })).toHaveCount(0)
  await expect(more.getByRole('button', { name: /^Billing/ })).toBeVisible()
})

/* FIX 1: the OTHER `primaryDestinations(destinations)` site. `.xc-rail-nav` above exists only when
   `settings.shell === 'rail'` -- the default -- at non-phone widths, so reverting `Shell.tsx`'s
   TopBar line alone passed every check in this file. `.xc-nav` is that layout's navigation.

   The layout is seeded into localStorage rather than driven through Settings -> Layout: clicking
   through the settings page would make this test depend on that page as well as on the nav, and
   the key seeded is the very preference that page writes (`console.spec.ts:431` and its
   "writes through to the same stored preference" sibling cover the clicking). */
test('the hosted top-bar layout lists only the declared destinations', async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('xibalba-cortex.console-settings', JSON.stringify({ shell: 'top', railCollapsed: false })) } catch { /* no storage: the console keeps its default rail and this test is about the other one */ }
  })
  await managedFixture(page, { signedIn: true })
  await page.goto('/managed#settings')
  const nav = page.locator('.xc-nav')
  await expect(nav.getByRole('button', { name: 'Workspace', exact: true })).toBeVisible()
  await expect(nav.getByRole('button', { name: 'Explore', exact: true })).toBeVisible()
  await expect(nav.getByRole('button', { name: 'Review', exact: true })).toHaveCount(0)
  await expect(nav.getByRole('button', { name: 'Integrity', exact: true })).toHaveCount(0)
})

/* The one-app property itself. Every other test here would pass against a second UI that borrowed
   the console's classes, and the grammar sweep did exactly that (it stayed green with the edition
   fork restored). The console shell is the thing only the console renders, and Billing is reachable
   from it only because the server declared it -- on the default rail layout it is a Settings peer
   tab, not a rail entry. */
test('the hosted workspace is the console shell, not a second app', async ({ page }) => {
  await managedFixture(page, { signedIn: true })
  await page.goto('/managed#settings')
  await expect(page.locator('.xc-shell')).toBeVisible()
  await expect(page.locator('.xc-page-tabs').getByRole('button', { name: /^Billing\b/ })).toBeVisible()
  await expect(page.locator('.xc-managed-inner')).toHaveCount(0)
})

test('a hash route for an undeclared destination opens no page', async ({ page }) => {
  await managedFixture(page, { signedIn: true })
  await page.goto('/managed#operations')
  await expect(page.locator('.xc-workspace')).toBeVisible()
  await expect(page.locator('.xc-drawer--page')).toHaveCount(0)
  // the same route on a server that declares it does open the page, so the assertion above is not vacuous
  await page.goto('/managed#agents')
  await expect(page.locator('.xc-drawer--page')).toBeVisible()
})

/* Self-hosted is the other half of the same proof: declaring nothing keeps every BUILT
   destination, so the Settings strip still carries Operations and still carries no Billing. */
test('a server that declares nothing keeps every built destination', async ({ page }) => {
  // The fixture is installed only to RECORD: a self-hosted console must ask the hosted account
  // API nothing at all. The same recorder sees `me` in every hosted test above, so an empty list
  // here is a measurement, not a dead route.
  const calls = await managedFixture(page)
  await openConsole(page, { hash: 'settings' })
  const tabs = page.locator('.xc-page-tabs')
  await expect(tabs.getByRole('button', { name: 'Operations', exact: true })).toBeVisible()
  await expect(tabs.getByRole('button', { name: 'Billing', exact: true })).toHaveCount(0)
  expect(calls).toEqual([])
})

/* Ruling C, at the consumers: the hosted-only capabilities are gated on the SESSION, not on the
   nav list. This fixture is a hosted deployment that stopped declaring `billing` -- the defect
   that gate change exists to prevent. API keys and bulk export must both survive it, and Billing
   must be absent from the navigation, which is the declaration fault the console also logs. */
test('hosted capabilities survive a declaration that dropped billing', async ({ page }) => {
  await managedFixture(page, { signedIn: true, destinations: ['graph', 'memories', 'agents', 'settings'] })
  await page.goto('/managed#agents')
  await expect(page.getByRole('heading', { name: 'Connect an agent with an API key' })).toBeVisible()
  await expect(page.getByLabel('Agent DIDs', { exact: false })).toBeVisible()
  await expect(page.locator('.xc-page-tabs').getByRole('button', { name: 'Billing', exact: true })).toHaveCount(0)
  await page.goto('/managed#memories')
  await expect(page.getByRole('button', { name: 'Export memories', exact: true })).toBeVisible()
})
