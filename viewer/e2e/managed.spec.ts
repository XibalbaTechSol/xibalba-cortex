import { expect, test, type Page } from '@playwright/test'

const plans = [
  { id: 'free', name: 'Free', monthly_cents: 0, max_memories: 1000, writes_per_month: 250, retrievals_per_month: 1000 },
  { id: 'pro', name: 'Pro', monthly_cents: 2900, max_memories: 25000, writes_per_month: 5000, retrievals_per_month: 25000 },
  { id: 'team', name: 'Team', monthly_cents: 14900, max_memories: 250000, writes_per_month: 50000, retrievals_per_month: 250000 },
]

async function fixture(page: Page, { billing = false, signedIn = false, plan = 'free', writable = true } = {}) {
  let session = signedIn
  const memories: Array<{ id: string; content: string; status: string }> = []
  let keys: Array<{ id: string; label: string; expires_at: string }> = []
  const calls: Array<{ path: string; method: string; body: Record<string, unknown> }> = []
  await page.route('**/api/managed/**', async (route) => {
    const req = route.request(), path = new URL(req.url()).pathname.split('/api/managed/')[1]
    const body = req.postDataJSON() ?? {}
    calls.push({ path, method: req.method(), body })
    const send = (json: unknown, status = 200) => route.fulfill({ status, json })
    if (path === 'plans') return send({ plans, billing_configured: billing, signup_enabled: true, hosted_inference_enabled: false })
    if (path === 'signup' || path.startsWith('recovery/')) return send({ message: 'Check your email.' }, 202)
    if (path === 'login') { session = true; return send({ account: {}, csrf_token: 'fixture-csrf' }) }
    if (path === 'logout') { session = false; return send({ ok: true }) }
    if (!session) return send({ error: 'Sign in' }, 401)
    if (path === 'me') return send({ account: { display_name: 'Operator', email: 'operator@example.com' }, entitlement: { plan: plans.find((p) => p.id === plan), status: writable ? 'free' : 'canceled', writable, period_end: null, cancel_at_period_end: false }, usage: { month: '2026-10', used: { writes: memories.length } }, counts: { memories: memories.length }, csrf_token: 'fixture-csrf' })
    if (path === 'memories' && req.method() === 'POST') { memories.push({ id: 'm-' + memories.length, content: String(body.content), status: 'active' }); return send(memories.at(-1), 201) }
    if (path === 'memories') return send({ memories })
    if (path === 'keys' && req.method() === 'POST') { keys.push({ id: 'key-1', label: 'managed-api:agent', expires_at: '2026-11-25T00:00:00Z' }); return send({ token: 'fixture-only-managed-key', expires_in_days: 30 }, 201) }
    if (path === 'keys') return send({ keys })
    if (path === 'keys/revoke') { keys = []; return send({ revoked: true }) }
    if (path === 'checkout') return send({ url: 'https://checkout.stripe.com/test-fixture' })
    if (path === 'portal') return send({ url: 'https://billing.stripe.com/test-fixture' })
    return send({ error: 'Unknown fixture route' }, 404)
  })
  await page.route('https://checkout.stripe.com/**', (route) => route.fulfill({ body: 'Stripe checkout fixture' }))
  await page.route('https://billing.stripe.com/**', (route) => route.fulfill({ body: 'Stripe portal fixture' }))
  return calls
}

for (const width of [320, 390, 1280, 1600]) {
  test(`managed plans show the approved catalog without overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 })
    await fixture(page)
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
  const calls = await fixture(page)
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
  const calls = await fixture(page, { signedIn: true })
  await page.goto('/managed')
  await page.getByLabel('Memory', { exact: true }).fill('Remember this test-only fact')
  await page.getByRole('button', { name: 'Save memory', exact: true }).click()
  await expect(page.getByText('Memory saved with a verifiable event history.')).toBeVisible()
  await page.getByLabel('Search memories', { exact: true }).fill('test-only')
  await page.getByRole('button', { name: 'Search / list', exact: true }).click()
  await expect(page.locator('.xc-managed-results')).toContainText('Remember this test-only fact')
  const write = calls.find((call) => call.path === 'memories' && call.method === 'POST')!
  expect(write.body).toEqual({ content: 'Remember this test-only fact' })
  await page.getByRole('button', { name: 'Create API key', exact: true }).click()
  await expect(page.locator('.xc-managed-key')).toHaveText('fixture-only-managed-key')
  expect(await page.evaluate(() => Object.values(localStorage).join(' '))).not.toContain('fixture-only-managed-key')
  await page.getByRole('button', { name: 'Show API keys', exact: true }).click()
  await page.getByRole('button', { name: 'Revoke key', exact: true }).click()
  await expect(page.locator('.xc-managed-key')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Revoke key', exact: true })).toHaveCount(0)
})

test('choosing a paid plan uses Checkout; an existing paid plan changes through the portal', async ({ page }) => {
  let calls = await fixture(page, { signedIn: true, billing: true })
  await page.goto('/managed')
  await page.getByRole('button', { name: 'Choose Pro', exact: true }).click()
  await expect(page).toHaveURL('https://checkout.stripe.com/test-fixture')
  expect(calls.find((call) => call.path === 'checkout')?.body).toEqual({ plan: 'pro' })
  await page.unroute('**/api/managed/**')
  calls = await fixture(page, { signedIn: true, billing: true, plan: 'pro' })
  await page.goto('/managed')
  await page.getByRole('button', { name: 'Change through billing', exact: true }).click()
  await expect(page).toHaveURL('https://billing.stripe.com/test-fixture')
  expect(calls.filter((call) => call.path === 'checkout')).toHaveLength(0)
})

test('read-only subscriptions retain export and search without permitting writes', async ({ page }) => {
  await fixture(page, { signedIn: true, plan: 'pro', writable: false })
  await page.goto('/managed')
  await expect(page.getByRole('button', { name: 'Save memory', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Search / list', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Export memories', exact: true })).toBeEnabled()
  await expect(page.getByText('This workspace is read-only.', { exact: false })).toBeVisible()
})
