import { expect, test } from '@playwright/test'
import { managedFixture } from './managed-fixture'

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
  const form = page.locator('.xc-managed-auth form')
  await form.getByLabel('Name', { exact: true }).fill('Operator')
  await form.getByLabel('Email', { exact: true }).fill('operator@example.com')
  await form.getByLabel('Password', { exact: true }).fill('test-only-password')
  await form.getByRole('button', { name: 'Create workspace', exact: true }).click()
  await expect(page.getByText('Check your email for a verification link.', { exact: false })).toBeVisible()
  expect(calls.filter((call) => call.path === 'login')).toHaveLength(0)
  await expect(page.getByRole('heading', { name: 'Operator’s memory' })).toHaveCount(0)
})

test('a workspace stores and searches memory, then creates and revokes an API key', async ({ page }) => {
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

test('choosing a paid plan uses Checkout; an existing paid plan changes through the portal', async ({ page }) => {
  let calls = await managedFixture(page, { signedIn: true, billing: true })
  await page.goto('/managed')
  await page.getByRole('button', { name: 'Choose Pro', exact: true }).click()
  await expect(page).toHaveURL('https://checkout.stripe.com/test-fixture')
  expect(calls.find((call) => call.path === 'checkout')?.body).toEqual({ plan: 'pro' })
  await page.unroute('**/api/managed/**')
  calls = await managedFixture(page, { signedIn: true, billing: true, plan: 'pro' })
  await page.goto('/managed')
  await page.getByRole('button', { name: 'Change through billing', exact: true }).click()
  await expect(page).toHaveURL('https://billing.stripe.com/test-fixture')
  expect(calls.filter((call) => call.path === 'checkout')).toHaveLength(0)
})

test('read-only subscriptions retain export and search without permitting writes', async ({ page }) => {
  await managedFixture(page, { signedIn: true, plan: 'pro', writable: false })
  await page.goto('/managed')
  await expect(page.getByRole('button', { name: 'Save memory', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Search / list', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Export memories', exact: true })).toBeEnabled()
  await expect(page.getByText('This workspace is read-only.', { exact: false })).toBeVisible()
})
