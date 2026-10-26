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
  await expect(page.getByRole('heading', { name: 'Operator’s memory' })).toHaveCount(0)
})

/* Owed to Task 5c, not deleted. Every assertion below names the second UI's own DOM -- its single
   write form, its `.xc-managed-results` list, its `.xc-managed-key` block. Task 5a re-homed the
   same capabilities onto the console's Memories and Agents pages, and 5c owns re-pointing these
   and adding the behavioural coverage; 5b was told not to re-point the key/export assertions, so
   they are marked rather than weakened. */
test.fixme('a workspace stores and searches memory, then creates and revokes an API key', async ({ page }) => {
  const calls = await managedFixture(page, { signedIn: true })
  await page.goto('/managed')
  await page.getByLabel('Memory', { exact: true }).fill('Remember this test-only fact')
  await page.getByRole('button', { name: 'Save memory', exact: true }).click()
  await expect(page.getByText('Memory saved with a verifiable event history.')).toBeVisible()
  await page.getByLabel('Search memories', { exact: true }).fill('test-only')
  await page.getByRole('button', { name: 'Search / list', exact: true }).click()
  await expect(page.locator('.xc-managed-results')).toContainText('Remember this test-only fact')
  const write = calls.find((call) => call.path === 'memories' && call.method === 'POST')!
  expect(write.body).toEqual({ content: 'Remember this test-only fact' })
  /* A key is bound to the agent DIDs it is for, so the field is `required` and the button
     stays disabled until it has one (ManagedApp.tsx:209, `!agentDids.trim()`). Before this,
     the click waited out the full 90s timeout against a permanently disabled button. */
  await page.getByLabel('Agent DIDs', { exact: true }).fill('did:integrity:test-agent-one\ndid:integrity:test-agent-two')
  await page.getByRole('button', { name: 'Create API key', exact: true }).click()
  await expect(page.locator('.xc-managed-key')).toHaveText('fixture-only-managed-key')
  // the DIDs reach the API, de-duplicated and split on newlines or commas -- the point of the field
  const issued = calls.find((call) => call.path === 'keys' && call.method === 'POST')!
  expect(issued.body).toEqual({ label: 'agent', agent_ids: ['did:integrity:test-agent-one', 'did:integrity:test-agent-two'] })
  expect(await page.evaluate(() => Object.values(localStorage).join(' '))).not.toContain('fixture-only-managed-key')
  await page.getByRole('button', { name: 'Show API keys', exact: true }).click()
  await page.getByRole('button', { name: 'Revoke key', exact: true }).click()
  await expect(page.locator('.xc-managed-key')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Revoke key', exact: true })).toHaveCount(0)
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

/* Owed to Task 5c for the same reason: "Save memory", "Search / list" and "Export memories" were
   three controls on one managed screen. On the console the write lives on Memories, the export is
   5a's control on Memories, and read-only comes from the workspace's own writability. */
test.fixme('read-only subscriptions retain export and search without permitting writes', async ({ page }) => {
  await managedFixture(page, { signedIn: true, plan: 'pro', writable: false })
  await page.goto('/managed')
  await expect(page.getByRole('button', { name: 'Save memory', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Search / list', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Export memories', exact: true })).toBeEnabled()
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
