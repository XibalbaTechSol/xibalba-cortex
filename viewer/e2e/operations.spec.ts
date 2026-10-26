// Operations (runtimes, workers, connectors), policy marks on the Timeline, and the trust vault
// lookup, against the real API and the seeded fixture. The fixture's runtime is "dev-seed"; it made
// one allowed and one denied tool call in session sess-w1 (a destructive action), and the store holds
// 105 queued inference tasks that no worker has touched.
import { expect, test } from '@playwright/test'
import { openConsole, settled3d } from './helpers'

test.describe('Operations → Agent runtimes', () => {
  test('lists the runtime, counts what its policy did, and leads to the Timeline', async ({ page }) => {
    await openConsole(page, { hash: 'operations' })
    const card = page.getByRole('region', { name: 'Agent runtimes' })
    const row = card.getByRole('listitem').filter({ hasText: 'dev-seed' })
    await expect(row).toBeVisible()
    await expect(row).toContainText('1 allowed, 1 denied, 0 asked')
    await expect(row).toContainText('Denied: write_file. destructive action')
    await expect(card).toContainText('the store cannot tell quiet from down')
    await row.getByRole('button', { name: 'Show on the Timeline' }).click()
    // the drawer is gone, the Timeline is the lens, and the session the denial happened in is selected
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect(page).toHaveURL(/#timeline$/)
    await expect(page.getByRole('heading', { name: 'sess-w1' })).toBeVisible()
  })
})

test.describe('Operations → Workers', () => {
  test('derives each worker from its queue and says there is no heartbeat', async ({ page }) => {
    await openConsole(page, { hash: 'operations' })
    const card = page.getByRole('region', { name: 'Workers' })
    await expect(card).toContainText('There is no heartbeat')
    for (const label of ['Entity and relation extraction', 'PARA classification', 'Contradiction detection', 'Session summaries', 'Embedding backfill']) {
      await expect(card.getByRole('listitem').filter({ hasText: label })).toBeVisible()
    }
    // the fixture queued tasks nobody serviced: waiting work with no recent activity is "backlog", not "idle"
    const para = card.getByRole('listitem').filter({ hasText: 'PARA classification' })
    await expect(para).toContainText(/waiting/)
    await expect(para.locator('.xc-tag')).toHaveText(/backlog|draining|working/)
    await expect(card.getByRole('listitem').filter({ hasText: 'Embedding backfill' })).toContainText(/memories embedded/)
  })
})

test.describe('Operations → Connectors and ingest', () => {
  test('reports ingest per connector, and never invents a count it cannot attribute', async ({ page }) => {
    await openConsole(page, { hash: 'operations' })
    const card = page.getByRole('region', { name: 'Connectors and ingest' })
    await expect(card).toContainText('does not start or drive it')
    await expect(card.getByRole('listitem').filter({ hasText: 'claude transcripts' })).toContainText('cannot attribute its memories to this connector, so no count is shown')
    // imported documents are attributable (the wiki connector), and the fixture has some
    const wiki = card.getByRole('listitem').filter({ hasText: 'integrity wiki' })
    await expect(wiki).toContainText(/\d+ memories, last/)
  })

  test('"Show these on the Graph" narrows the Graph to that connector’s memories', async ({ page }) => {
    await openConsole(page, { hash: 'graph', primary: true })
    const canvas = await settled3d(page)
    const all = Number(await canvas.getAttribute('data-node-count'))
    /* Operations lost its permanent nav link in 70935fb ("cut the navigation to five links") and
       now lives behind the account control, so there is no `Tools` group to click. The graph has
       to stay mounted for the node counts to be comparable, so this navigates in-page: the hash
       is the route (nav.ts keeps `#operations` resolving) and state.tsx re-parses it on
       `hashchange` without a reload. */
    await page.evaluate(() => { location.hash = 'operations' })
    await page.getByRole('region', { name: 'Connectors and ingest' }).getByRole('listitem').filter({ hasText: 'integrity wiki' }).getByRole('button', { name: 'Show these on the Graph' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect.poll(async () => Number(await page.locator('canvas[data-node-count]').getAttribute('data-node-count')), { timeout: 20_000 }).toBeLessThan(all)
  })
})

test.describe('Timeline policy marks', () => {
  test('a denied tool call is a mark on its session’s lane, with the reason', async ({ page }) => {
    await openConsole(page, { hash: 'timeline' })
    const lane = page.getByRole('row').filter({ hasText: 'sess-w1' })
    const stop = lane.locator('.xc-mark[data-cls="deny"]')
    await expect(stop).toHaveCount(1)
    await expect(stop).toHaveAttribute('title', /Denied: write_file\. destructive action/)
    await expect(page.getByText('▮ denied by policy')).toBeVisible()
    await stop.click()
    // the Inspector says what the policy did in this session, in words
    await expect(page.getByText('The policy stopped a tool call')).toBeVisible()
    await expect(page.getByText('1 allowed · 1 denied · 0 asked')).toBeVisible()
    await expect(page.getByText('dev-seed', { exact: true }).first()).toBeVisible()
  })

  test('only the session that made tool calls has policy marks or a policy row', async ({ page }) => {
    await openConsole(page, { hash: 'timeline', primary: true })
    // the primary profile holds every session; exactly one made policy-gated tool calls
    await expect(page.locator('.xc-mark[data-cls="deny"], .xc-mark[data-cls="ask"]')).toHaveCount(1)
    await page.getByRole('row').filter({ hasText: 'sess-7f3a1c' }).locator('.xc-lane-label').click()
    await expect(page.getByRole('heading', { name: 'sess-7f3a1c' })).toBeVisible()
    await expect(page.getByText('The policy stopped a tool call')).toHaveCount(0)
    await expect(page.getByText('Tool calls', { exact: true })).toHaveCount(0) // no calls recorded, so no row pretending there were
  })
})

test.describe('Settings → Developer → Trust vault lookup', () => {
  const open = async (page: import('@playwright/test').Page) => {
    await openConsole(page, { hash: 'settings' })
    await page.getByRole('tab', { name: 'Developer' }).click()
  }
  const HASH = `0x${'ab'.repeat(32)}`

  test('checks the hash shape before asking', async ({ page }) => {
    await open(page)
    await page.getByLabel('Leaf hash').fill('0x1234')
    await page.getByRole('button', { name: 'Look up' }).click()
    await expect(page.getByRole('alert')).toContainText('64 hexadecimal characters')
  })

  test('a server with no vault configured says so (real API)', async ({ page }) => {
    await open(page)
    await page.getByLabel('Leaf hash').fill(HASH)
    await page.getByRole('button', { name: 'Look up' }).click()
    await expect(page.getByRole('alert')).toContainText('No trust vault is configured on this server')
  })

  for (const [name, body, title, detail] of [
    ['found and anchored', { found: true, anchored: true, recomputed_hash_matches: true, leaf: { kind: 'commit', commit_sha: 'abc123' }, anchor: { leaves_through: 1 } }, 'Found and anchored', 'recomputed from the leaf’s own fields and matches'],
    ['found, not anchored', { found: true, anchored: false, recomputed_hash_matches: true, leaf: { kind: 'commit' }, anchor: null }, 'Found, not yet anchored', 'No anchor covers this leaf yet'],
    ['tampered', { found: true, anchored: true, recomputed_hash_matches: false, leaf: { kind: 'commit' }, anchor: null }, 'Found, but the entry does not match its hash', 'does NOT match'],
    ['not found', { found: false, anchored: false, leaf: null, anchor: null }, 'Not in the vault', 'says nothing about any memory'],
    ['unreadable', { found: false, anchored: false, error: 'the vault could not be read' }, 'The vault could not be read', 'not "not found"'],
  ] as const) {
    test(`reports "${name}" in words (stubbed: the fixture has no vault)`, async ({ page }) => {
      await page.route('**/cortex-api/api/vault/leaf**', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) }))
      await open(page)
      await page.getByLabel('Leaf hash').fill(HASH)
      await page.getByRole('button', { name: 'Look up' }).click()
      const result = page.getByRole('status').filter({ hasText: title })
      await expect(result).toBeVisible()
      await expect(result).toContainText(detail)
    })
  }
})
