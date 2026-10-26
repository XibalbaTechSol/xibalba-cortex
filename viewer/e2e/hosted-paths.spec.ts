// The one check that discriminates production from dev: WHICH PATHS the hosted console requests.
//
// Every other hosted e2e in this directory runs behind the Vite dev proxy, which supplies a real
// local API at `/cortex-api/api/*`. So a console whose data layer speaks the self-hosted routes
// RENDERS perfectly here and 404s in production, where the managed backend serves 23 routes, all
// under `/api/managed/`, and answers anything else with 404. Asserting the rendering cannot see
// that. Asserting the request paths can.
//
// Two rules keep these tests from going vacuous:
//   1. the recorder matches `/api/` ANYWHERE in the path, plus `/readyz` and `/metrics`. In this
//      build an escaped call is `/cortex-api/api/graph`, so a `pathname.startsWith('/api/')`
//      filter would miss every escape and pass with the fix removed;
//   2. every absence assertion sits behind positive waits for surfaces that only exist once the
//      hosted data actually arrived, and behind an assertion that the managed routes WERE called.
//      Playwright stops at the first failing assertion, so an absence placed first proves nothing.

import { expect, test, type Page } from '@playwright/test'
import { managedFixture } from './managed-fixture'

const SEEDED = 'Seeded memory 0'

/** Every API request the page made, in order, as `METHOD /path`. */
function recordApiRequests(page: Page): string[] {
  const seen: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path.includes('/api/') || path === '/readyz' || path === '/metrics') seen.push(`${request.method()} ${path}`)
  })
  return seen
}

/** Answer every API request that is NOT a managed route with 404, which is what the hosted
 *  backend's SPA handler does. Registered before `managedFixture`, and it hands the managed
 *  paths on, so the fixture serves those whichever order Playwright tests the handlers in. */
async function behaveLikeProduction(page: Page): Promise<void> {
  await page.route(/\/api\/|\/(readyz|metrics)$/, async (route) => {
    if (new URL(route.request().url()).pathname.startsWith('/api/managed/')) return route.fallback()
    await route.fulfill({ status: 404, json: { error: 'Not Found' } })
  })
}

/** The signed-in hosted workspace, with the graph loaded and its one hard requirement met. */
async function openHosted(page: Page) {
  const requests = recordApiRequests(page)
  await behaveLikeProduction(page)
  const calls = await managedFixture(page, { signedIn: true, billing: true, seed: 2 })
  await page.goto('/managed')
  await expect(page.locator('.xc-workspace')).toBeVisible()
  await expect(page.locator('.xc-conn')).toContainText(/connected/i)
  return { requests, calls }
}

test('a hosted console never asks for a route the managed backend does not serve', async ({ page }) => {
  const { requests, calls } = await openHosted(page)

  // --- positive anchors first: each surface the hosted server declares, actually carrying hosted
  //     data. With the mapping removed these fail before any absence check is reached.
  await expect(page.locator('.xc-status')).toContainText('writable')

  await page.goto('/managed#memories')
  await expect(page.getByRole('button', { name: SEEDED, exact: true })).toBeVisible()
  // the single-memory read is its own managed route with its own shape (`{memory}`)
  await page.getByRole('button', { name: SEEDED, exact: true }).click()
  await expect(page.locator('.xc-memories-detail')).toContainText(SEEDED)

  /* Recall is declared by the hosted server, and its LEXICAL mode is the one the managed backend
     can serve: `/api/search` maps to `memories?q=`. Hybrid and Context post to
     `/api/retrieval/hybrid` and `/api/context/assemble`, which have no managed route, so they
     refuse locally with a stated reason -- see the report's "left degrading" list. */
  await page.goto('/managed')
  await expect(page.locator('.xc-workspace')).toBeVisible()
  await page.keyboard.press('Control+k')
  const recall = page.getByRole('dialog', { name: 'Recall' })
  await expect(recall).toBeVisible()
  await recall.getByRole('button', { name: 'Lexical' }).click()
  await recall.getByLabel('Recall query').fill('Seeded')
  await page.keyboard.press('Enter')
  await expect(recall.locator('li.xc-result').first()).toContainText(SEEDED)
  await page.keyboard.press('Escape')

  await page.goto('/managed#agents')
  await expect(page.getByRole('heading', { name: 'Connect an agent with an API key' })).toBeVisible()

  await page.goto('/managed#billing')
  await expect(page.getByRole('button', { name: 'Choose Pro', exact: true })).toBeVisible()

  await page.goto('/managed#settings')
  await expect(page.locator('.xc-drawer--page')).toBeVisible()

  await page.goto('/managed#timeline')
  await expect(page.locator('.xc-workspace')).toBeVisible()

  // --- and the managed routes were really exercised, so the sweep below is not over an empty list
  for (const path of ['me', 'graph', 'timeline', 'memories', 'memories/seed-0', 'plans']) {
    expect(calls.map((c) => c.path), path).toContain(path)
  }
  expect(requests.length).toBeGreaterThan(6)

  // --- THE check: not one request escaped the prefix the hosted backend serves.
  expect(requests.filter((r) => !r.startsWith('GET /api/managed/') && !r.startsWith('POST /api/managed/'))).toEqual([])
})

test('a hosted console asks for none of the routes that would 404', async ({ page }) => {
  const { requests } = await openHosted(page)
  await expect(page.locator('.xc-status')).toContainText('writable')
  await page.goto('/managed#memories')
  await expect(page.getByRole('button', { name: SEEDED, exact: true })).toBeVisible()

  /* The console's own paths for the capabilities the hosted backend has no route for. These are
     not merely "under a different prefix": the point is that nothing is requested for them at
     all, so a hosted load does not spend a round-trip per surface learning it is a 404. */
  const paths = ['/api/stats', '/api/status', '/api/operations', '/api/invocations', '/api/agents',
    '/api/auth/csrf', '/api/auth/tokens', '/api/sessions', '/api/sessions/page', '/api/memory/',
    '/api/search', '/api/profile/config', '/readyz', '/metrics']
  for (const path of paths) {
    expect(requests.filter((r) => r.includes(path)), path).toEqual([])
  }
})

test('a hosted write carries an Idempotency-Key, and a read-only subscription has no write control', async ({ page }) => {
  const { calls } = await openHosted(page)
  await page.goto('/managed#memories')
  await expect(page.getByRole('button', { name: SEEDED, exact: true })).toBeVisible()

  // writable: the control is offered and the write reaches the managed route with a key
  await page.getByRole('button', { name: 'New memory', exact: true }).click()
  await page.getByLabel('Text', { exact: true }).fill('A hosted write')
  await page.getByRole('button', { name: 'Add memory', exact: true }).click()
  await expect(page.getByRole('button', { name: 'A hosted write', exact: true })).toBeVisible()
  const write = calls.find((c) => c.path === 'memories' && c.method === 'POST')!
  expect(write.body).toEqual({ content: 'A hosted write' })
  expect(write.key).toMatch(/^[\w-]{8,128}$/)
})

test('a read-only hosted subscription offers no write control and says why', async ({ page }) => {
  const requests = recordApiRequests(page)
  await behaveLikeProduction(page)
  const calls = await managedFixture(page, { signedIn: true, plan: 'pro', writable: false, seed: 1 })
  await page.goto('/managed#memories')

  // positive anchor: the workspace loaded and its memories are readable -- a read-only
  // subscription keeps every read, which is the whole point of the entitlement being per-write
  await expect(page.getByRole('button', { name: SEEDED, exact: true })).toBeVisible()
  await expect(page.locator('.xc-status')).toContainText('read only')
  // the export is outside the writable check on purpose, so it proves the page rendered its actions
  await expect(page.getByRole('button', { name: 'Export memories', exact: true })).toBeVisible()

  await expect(page.getByRole('button', { name: 'New memory', exact: true })).toHaveCount(0)
  expect(calls.filter((c) => c.path === 'memories' && c.method === 'POST')).toEqual([])
  expect(requests.filter((r) => !r.startsWith('GET /api/managed/') && !r.startsWith('POST /api/managed/'))).toEqual([])
})
