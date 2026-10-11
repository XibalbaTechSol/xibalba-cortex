// Actions that write or reach outward, end to end against the real API: attach a file, import a
// document, export a window, end a session, verify a link, anchor a root, back up. Each is exercised
// for what it does AND for what the console says first and after. The API runs with a backup folder
// and an anchor service configured (playwright.config.ts); the browser is told neither location.
import { expect, test, type Page } from '@playwright/test'
import { openConsole, pinMemory, settled3d } from './helpers'

const ANCHOR = 'http://127.0.0.1:8431'
const unique = () => `${Date.now()}-${Math.floor(Math.random() * 1e6)}`

test.describe('Attach a file', () => {
  test('choose, read what will happen, attach, then download the same bytes back', async ({ page }) => {
    await openConsole(page)
    await pinMemory(page, 'relay retries', 'three times')
    await page.getByRole('tab', { name: 'Files' }).click()
    await expect(page.locator('.xc-row').filter({ hasText: 'Download' }).first()).toBeVisible() // the list has loaded
    const before = await page.locator('.xc-row').filter({ hasText: 'Download' }).count()

    const bytes = Buffer.from(`attachment ${unique()}\nsecond line\n`)
    await page.getByLabel('Attach a file').setInputFiles({ name: 'notes from e2e.txt', mimeType: 'text/plain', buffer: bytes })
    const confirm = page.getByRole('group', { name: 'Attach notes from e2e.txt' })
    await expect(confirm).toContainText('will be uploaded and attached to this memory')
    await expect(confirm).toContainText('cannot be removed from it')
    await confirm.getByRole('button', { name: 'Attach' }).click()

    await expect(page.getByRole('status').filter({ hasText: 'Attached notes from e2e.txt' })).toBeVisible()
    await expect(page.locator('.xc-row').filter({ hasText: 'Download' })).toHaveCount(before + 1)
    const newest = page.locator('.xc-row').filter({ hasText: 'Download' }).last()
    const [download] = await Promise.all([page.waitForEvent('download'), newest.getByRole('button', { name: 'Download' }).click()])
    const fs = await import('node:fs/promises')
    expect(await fs.readFile((await download.path())!)).toEqual(bytes)
  })

  test('an empty file is refused before anything is sent', async ({ page }) => {
    let sent = 0
    await page.route('**/cortex-api/api/memory/*/attachments**', (r) => { if (r.request().method() === 'POST') sent++; return r.continue() })
    await openConsole(page)
    await pinMemory(page, 'relay retries', 'three times')
    await page.getByRole('tab', { name: 'Files' }).click()
    await page.getByLabel('Attach a file').setInputFiles({ name: 'empty.txt', mimeType: 'text/plain', buffer: Buffer.alloc(0) })
    await expect(page.getByRole('alert')).toContainText('That file is empty.')
    expect(sent).toBe(0)
  })

  test('a read-only workspace says files cannot be attached', async ({ page }) => {
    await openConsole(page, { primary: true })
    await pinMemory(page, 'relay retries', 'three times')
    await page.getByRole('tab', { name: 'Files' }).click()
    await expect(page.getByText('Read-only workspace: files can be downloaded but not attached.')).toBeVisible()
    await expect(page.getByLabel('Attach a file')).toHaveCount(0)
  })
})

test.describe('Import a document', () => {
  const open = async (page: Page) => {
    await openConsole(page, { hash: 'memories' })
    await page.getByRole('button', { name: 'Import a document' }).click()
  }

  test('stores candidate memories, queues proposals, and a repeat stores nothing new', async ({ page }) => {
    await open(page)
    const body = `# Retry policy ${unique()}\n\nThe retry policy is described in docs/plan.md and implemented in src/relay.py.\n\n# Spool\n\nSpooled items replay in order on reconnect.\n`
    const file = { name: 'retry-policy.md', mimeType: 'text/markdown', buffer: Buffer.from(body) }
    await page.getByLabel('Text or Markdown file').setInputFiles(file)
    const confirm = page.getByRole('group', { name: 'Import retry-policy.md' })
    await expect(confirm).toContainText('stored as candidate memories (source: imported document)')
    await expect(confirm).toContainText('Nothing is added to the graph')
    await confirm.getByRole('button', { name: 'Import' }).click()
    const done = page.getByRole('status').filter({ hasText: 'stored as candidate memories' })
    await expect(done).toContainText('2 of 2 sections of retry-policy.md')
    await expect(done).toContainText('proposals waiting in Review')

    // the same bytes again: nothing new
    await page.getByLabel('Text or Markdown file').setInputFiles(file)
    await page.getByRole('group', { name: 'Import retry-policy.md' }).getByRole('button', { name: 'Import' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Nothing new' })).toContainText('all 2 sections of retry-policy.md were already in this workspace')

    // the memories are listed as candidates once the filter shows them
    await page.getByRole('button', { name: 'candidate', exact: true }).click()
    await expect(page.getByRole('dialog').getByText('Spooled items replay in order on reconnect.').first()).toBeVisible()
  })

  test('a file that is not text or Markdown is turned away and pointed somewhere better', async ({ page }) => {
    await open(page)
    await page.getByLabel('Text or Markdown file').setInputFiles({ name: 'paper.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 fake') })
    await expect(page.getByRole('alert')).toContainText('attach it to a memory instead')
  })

  test('a read-only workspace offers no import and says why', async ({ page }) => {
    await openConsole(page, { hash: 'memories', primary: true })
    await expect(page.getByRole('button', { name: 'Import a document' })).toHaveCount(0)
    await expect(page.getByRole('note').filter({ hasText: 'Read only.' })).toBeVisible()
  })
})

test.describe('Export this window', () => {
  test('says what is in the bundle, then downloads exactly that', async ({ page }) => {
    await openConsole(page)
    await page.getByRole('button', { name: 'Export this window' }).click()
    const panel = page.getByRole('group', { name: 'Export this window' })
    await expect(panel).toContainText('will be exported as one provenance bundle (JSON) with a Merkle commitment')
    await expect(panel).toContainText('Forgotten memories are never included')
    await expect(panel).toContainText('does not show they are true')
    const button = panel.getByRole('button', { name: /^Download \d+ memor/ })
    const promised = Number((await button.innerText()).match(/\d+/)![0])
    const [download] = await Promise.all([page.waitForEvent('download'), button.click()])
    expect(download.suggestedFilename()).toMatch(/^cortex-provenance-.*\.json$/)
    const bundle = JSON.parse(await (await import('node:fs/promises')).readFile((await download.path())!, 'utf8'))
    expect(bundle.schema_version).toBe('xibalba.provenance_export.v1')
    expect(bundle.count).toBe(promised)
    expect(bundle.memory_ids).toHaveLength(promised)
    expect(bundle.root_hash).toMatch(/^sha256:/)
    expect(bundle.include_forgotten).toBe(false)
    await expect(page.getByRole('status').filter({ hasText: 'Saved a bundle' })).toBeVisible()
  })

  test('hidden-by-filter memories are counted, not silently dropped', async ({ page }) => {
    await openConsole(page, { primary: true })
    await settled3d(page)
    await page.getByRole('checkbox', { name: /^confirmed/ }).uncheck() // a Filters switch hides every confirmed memory
    await page.getByRole('button', { name: 'Export this window' }).click()
    await expect(page.getByRole('group', { name: 'Export this window' })).toContainText(/\d+ more in the workspace are left out because Filters hide them/)
  })
})

test.describe('End session', () => {
  test('is confirmed, says it cannot be undone, and takes effect once', async ({ page }) => {
    await openConsole(page, { hash: 'sessions' })
    await page.locator('.xc-sessions-list li').filter({ hasText: 'sess-w2' }).click()
    await expect(page.getByRole('button', { name: 'End session' })).toBeVisible()
    await page.getByRole('button', { name: 'End session' }).click()
    const confirm = page.getByRole('group', { name: 'End session sess-w2' })
    await expect(confirm).toContainText('cannot be reopened')
    await expect(confirm).toContainText('a summary is queued')
    // Escape backs out without ending anything
    await page.keyboard.press('Escape')
    await expect(confirm).toHaveCount(0)
    await page.getByRole('button', { name: 'End session' }).click()
    await page.getByRole('group', { name: 'End session sess-w2' }).getByRole('button', { name: 'End this session' }).click()
    await expect(page.getByRole('status').filter({ hasText: 'Session sess-w2 ended' })).toBeVisible()
    // ended: the header no longer says open and the button is gone
    await expect(page.getByRole('button', { name: 'End session' })).toHaveCount(0)
    await expect(page.locator('.xc-inspector-head').filter({ hasText: 'sess-w2' })).not.toContainText('→ open')
  })

  test('a read-only workspace cannot end a session', async ({ page }) => {
    await openConsole(page, { hash: 'sessions', primary: true })
    await page.locator('.xc-sessions-list li').first().click()
    await expect(page.getByRole('button', { name: 'End session' })).toHaveCount(0)
  })
})

test.describe('Integrity: verify a link and anchor a root', () => {
  test('verifying a link records and words the result, and never claims more than byte lineage', async ({ page }) => {
    await openConsole(page)
    await page.getByRole('button', { name: /^Integrity/ }).first().click()
    await page.locator('#ig-links').click()
    const row = page.locator('.xc-card').filter({ has: page.getByRole('button', { name: 'Verify this link' }) }).first()
    await row.getByRole('button', { name: 'Verify this link' }).click()
    await expect(row.getByRole('status')).toContainText('This memory is not linked to a DAG node')
  })

  test('anchoring says it leaves the machine, sends the root to the configured service, and shows no address', async ({ page, request }) => {
    const before = ((await (await request.get(`${ANCHOR}/received`)).json()) as { received: unknown[] }).received.length
    await openConsole(page)
    await page.getByRole('button', { name: /^Integrity/ }).first().click()
    const card = page.locator('.xc-card').filter({ hasText: 'sess-w1' })
    await expect(card.getByRole('button', { name: 'Anchor this root' })).toBeEnabled()
    await card.getByRole('button', { name: 'Anchor this root' }).click()
    const confirm = page.getByRole('group', { name: /Anchor sess-w1/ })
    await expect(confirm).toContainText('leaves this machine and cannot be taken back')
    await expect(confirm).toContainText('the content itself is not sent')
    await confirm.getByRole('button', { name: 'Send the root' }).click()
    await expect(card.getByRole('status').filter({ hasText: 'The root was sent' })).toContainText('does not by itself show external finality')
    const after = ((await (await request.get(`${ANCHOR}/received`)).json()) as { received: unknown[] }).received
    expect(after.length).toBe(before + 1)
    expect(await page.content()).not.toContain('8431') // the service address stays on the server
  })

  test('a read-only workspace is not offered an anchor', async ({ page }) => {
    await openConsole(page, { primary: true })
    await page.getByRole('button', { name: /^Integrity/ }).first().click()
    await expect(page.getByRole('button', { name: 'Anchor this root' })).toHaveCount(0)
  })
})

test.describe('Operations → Backup', () => {
  test('writes a verified copy, lists it by name, and a check notices when the store moves on', async ({ page, request }) => {
    await openConsole(page, { hash: 'operations' })
    const card = page.getByRole('region', { name: 'Backup' })
    await expect(card).toContainText('A copy that is complete is not shown to restore')
    await card.getByRole('button', { name: 'Back up now' }).click()
    const confirm = page.getByRole('group', { name: 'Back up the store' })
    await expect(confirm).toContainText('you cannot choose where it goes')
    await confirm.getByRole('button', { name: 'Write the backup' }).click()
    const done = card.getByRole('status').filter({ hasText: 'The copy is complete' })
    await expect(done).toContainText('does not show it restores')
    await expect(done).toHaveCount(1)

    // the listing names the file and never a path
    const row = card.getByRole('listitem').first()
    const name = (await row.locator('b').innerText()).trim()
    expect(name).toMatch(/^cortex-backup-\d{8}T\d{6}Z-[0-9a-f]{6}\.sqlite3$/)
    expect(await card.innerText()).not.toMatch(/\/tmp\/|cortex-e2e/)

    await row.getByRole('button', { name: 'Check against the live store' }).click()
    await expect(row.getByRole('status')).toContainText('Matches the live store')

    // the live store moves on; the same copy no longer matches
    const wrote = await request.post('http://127.0.0.1:5190/cortex-api/api/memory/propositions', { data: { content: `Written after the backup ${unique()}.`, source: { kind: 'explicit_memory', locator: `e2e://after-${unique()}` }, status: 'active' } })
    expect(wrote.ok()).toBeTruthy()
    await row.getByRole('button', { name: 'Check against the live store' }).click()
    await expect(row.getByRole('status')).toContainText('Differs from the live store')
  })
})
