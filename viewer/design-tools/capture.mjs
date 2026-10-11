// Capture the implemented console, screen by screen, as markup for Claude Design boards.
import { createRequire } from 'node:module'
import { writeFileSync } from 'node:fs'
const require = createRequire(new URL('../package.json', import.meta.url))
let chromium
try { ({ chromium } = require('playwright')) } catch { ({ chromium } = require('@playwright/test')) }
const only = process.argv[2] ? new Set(process.argv[2].split(',')) : null
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium', args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] })
const BASE = process.env.VIEWER_URL || 'http://127.0.0.1:5190/'

const pinMemory = async (page, query, pick) => {
  await page.keyboard.press('Control+k'); await page.getByRole('dialog', { name: 'Recall' }).waitFor()
  await page.getByRole('button', { name: 'Lexical' }).click(); await page.getByLabel('Recall query').fill(query); await page.keyboard.press('Enter')
  const row = pick ? page.locator('li.xc-result', { hasText: pick }) : page.locator('li.xc-result')
  await row.first().getByRole('button', { name: 'Pin to graph' }).click()
  await page.waitForTimeout(600)
}


// wait until the 3D engine has settled and the camera has framed the cloud
const settle3d = async (p) => { await p.locator('canvas[data-settled="true"]').waitFor({ timeout: 20000 }); await p.waitForTimeout(2500) }
// click across the 3D canvas until something matching is selected; returns where
const scan3d = async (p, want) => {
  const box = await p.locator('canvas[data-node-count]').boundingBox()
  for (let y = box.y + 30; y < box.y + box.height - 30; y += 14) for (let x = box.x + 30; x < box.x + box.width - 60; x += 14) {
    await p.mouse.click(x, y); await p.waitForTimeout(110)
    const s = (await p.locator('canvas[data-node-count]').getAttribute('data-selected')) || ''
    if (s && want(s)) return { x, y, s }
  }
  throw new Error('nothing to select')
}
const isEdge = (s) => s.includes('>')

const boards = [
  // ---- graph, in every state the lens can be in
  { name: 'graph-3d-overview', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => { await settle3d(p) } },
  { name: 'graph-3d-edge', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => { await settle3d(p); await scan3d(p, isEdge); await p.waitForTimeout(600) } },
  { name: 'graph-3d-pinned', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => {
      await settle3d(p); const n = await scan3d(p, (s) => !isEdge(s))
      await p.mouse.move(n.x, n.y); await p.mouse.down(); await p.mouse.move(n.x + 50, n.y + 20, { steps: 6 }); await p.mouse.move(n.x + 90, n.y + 40, { steps: 6 }); await p.mouse.up(); await p.waitForTimeout(2500) } },
  { name: 'graph-3d-nosnap', w: 1440, h: 900, hash: '#graph', primary: true, init: { graphSnap: false }, run: async (p) => { await settle3d(p) } },
  { name: 'graph-3d-legend', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => { await settle3d(p); await p.getByRole('button', { name: 'Legend' }).click(); await p.waitForTimeout(400) } },
  { name: 'graph-3d-hidden', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => { await pinMemory(p, 'domain-separated'); await p.getByRole('checkbox', { name: /^Memories/ }).first().uncheck(); await p.waitForTimeout(2500) } },
  { name: 'graph-facets', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => { await settle3d(p); await p.evaluate(() => { const el = document.querySelector('.xc-rail .xc-scroll'); el.scrollTop = el.scrollHeight }); await p.waitForTimeout(500) } },
  { name: 'graph-3d-far', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => { await settle3d(p); await p.locator('canvas[data-node-count]').focus(); for (let i = 0; i < 12; i++) { await p.keyboard.press('-'); await p.waitForTimeout(500) } await p.waitForTimeout(1200) } },
  { name: 'graph-3d-near', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => { await settle3d(p); await p.locator('canvas[data-node-count]').focus(); for (let i = 0; i < 7; i++) { await p.keyboard.press('+'); await p.waitForTimeout(500) } await p.waitForTimeout(1200) } },
  { name: 'graph-2d', w: 1440, h: 900, hash: '#graph', primary: true, init: { graphMode: '2d' }, run: async (p) => { await pinMemory(p, 'domain-separated'); await p.waitForTimeout(3500) } },
  { name: 'graph-2d-nosnap', w: 1440, h: 900, hash: '#graph', primary: true, init: { graphMode: '2d', graphSnap: false }, run: async (p) => { await p.waitForTimeout(4000) } },
  { name: 'graph-nowebgl', w: 1440, h: 900, hash: '#graph', primary: true, noWebgl: true, run: async (p) => { await p.waitForTimeout(3500) } },
  { name: 'phone-graph-2d', w: 390, h: 844, hash: '#graph', primary: true, init: { graphMode: '2d' }, run: async (p) => { await p.waitForTimeout(3500) } },
  // ---- round 3: the remaining states, tablet widths and phone overlays
  { name: 'inspector-provenance', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('tab', { name: 'Provenance' }).click(); await p.waitForTimeout(900) } },
  { name: 'inspector-neighbors', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('tab', { name: 'Neighbors' }).click(); await p.waitForTimeout(900) } },
  { name: 'inspector-contradictions', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('tab', { name: 'Contradictions' }).click(); await p.waitForTimeout(900) } },
  { name: 'inspector-telemetry', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('tab', { name: 'Telemetry' }).click(); await p.waitForTimeout(900) } },
  { name: 'memories-new', w: 1440, h: 900, hash: '#memories', run: async (p) => { await p.getByRole('button', { name: 'New memory' }).click(); await p.locator('form[aria-label="New memory"] textarea').fill('The relay retries a failed submission three times before it is queued for review.'); await p.waitForTimeout(400) } },
  { name: 'entities-path', w: 1440, h: 900, hash: '#entities', primary: true, run: async (p) => { await p.getByLabel('From entity').fill('store.py'); await p.getByLabel('To entity').fill('domain Merkle root'); await p.getByRole('button', { name: 'Find path' }).click(); await p.waitForTimeout(1500) } },
  { name: 'sessions-replay', w: 1440, h: 900, hash: '#sessions', run: async (p) => { await p.locator('.xc-sessions-list li, .xc-sessions-list button').first().click(); await p.getByRole('tab', { name: 'Replay' }).click(); await p.waitForTimeout(1200) } },
  { name: 'sessions-telemetry', w: 1440, h: 900, hash: '#sessions', run: async (p) => { await p.locator('.xc-sessions-list li, .xc-sessions-list button').first().click(); await p.getByRole('tab', { name: 'Telemetry' }).click(); await p.waitForTimeout(1200) } },
  { name: 'sessions-invocations', w: 1440, h: 900, hash: '#sessions', run: async (p) => { await p.getByRole('tab', { name: 'Invocations' }).click(); await p.waitForTimeout(1200) } },
  { name: 'settings-layout-top', w: 1440, h: 900, hash: '#settings', init: { shell: 'top' } },
  { name: 'graph-empty', w: 1440, h: 900, hash: '#graph', primary: true, routes: [['**/cortex-api/api/graph*', { nodes: [], edges: [] }]], run: async (p) => { await p.waitForTimeout(1500) } },
  { name: 'timeline-empty', w: 1440, h: 900, hash: '#timeline', primary: true, routes: [['**/cortex-api/api/graph*', { nodes: [], edges: [] }]], run: async (p) => { await p.waitForTimeout(1500) } },
  { name: 'recall-empty', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.keyboard.press('Control+k'); await p.getByRole('dialog', { name: 'Recall' }).waitFor(); await p.getByRole('button', { name: 'Lexical' }).click(); await p.getByLabel('Recall query').fill('zzqqxxnothing'); await p.keyboard.press('Enter'); await p.waitForTimeout(1500) } },
  { name: 'tablet-graph', w: 1024, h: 768, hash: '#graph', primary: true },
  { name: 'tablet-timeline', w: 1024, h: 768, hash: '#timeline', primary: true },
  { name: 'tablet-memories', w: 1024, h: 768, hash: '#memories', primary: true },
  { name: 'tablet-settings', w: 820, h: 1000, hash: '#settings' },
  { name: 'phone-signin', w: 390, h: 844, signedOut: true },
  { name: 'phone-recall', w: 390, h: 844, hash: '#graph', primary: true, run: async (p) => { await p.getByRole('button', { name: 'Recall' }).first().click(); await p.getByRole('dialog').waitFor(); await p.waitForTimeout(600) } },
  { name: 'phone-review', w: 390, h: 844, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: 'Review' }).first().click(); await p.getByRole('dialog').waitFor(); await p.waitForTimeout(1200) } },
  { name: 'phone-graph-legend', w: 390, h: 844, hash: '#graph', primary: true, run: async (p) => { await p.getByRole('button', { name: 'Legend' }).click(); await p.waitForTimeout(500) } },
  // ---- round 4: tools open over the lens they were opened from
  { name: 'drawer-timeline-sessions', w: 1440, h: 900, hash: '#timeline/sessions', primary: true, run: async (p) => { await p.locator('.xc-sessions-list li, .xc-sessions-list button').first().click(); await p.waitForTimeout(1000) } },
  { name: 'drawer-session-from-lens', w: 1440, h: 900, hash: '#timeline', primary: true, run: async (p) => { await p.locator('.xc-lane-label').first().click(); await p.waitForTimeout(600); await p.getByRole('button', { name: 'Exchanges, replay, telemetry' }).click(); await p.waitForTimeout(1500) } },
  { name: 'drawer-entity-from-graph', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => { await settle3d(p); await scan3d(p, (s) => s.startsWith('entity:')); await p.getByRole('button', { name: 'Neighbours and paths' }).click(); await p.waitForTimeout(1800) } },
  // ---- round 5: built states that had no board
  { name: 'inspector-link', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('button', { name: 'Link entities' }).click(); await p.waitForTimeout(700) } },
  { name: 'inspector-contradict', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('button', { name: 'Contradiction', exact: true }).click(); await p.waitForTimeout(700) } },
  { name: 'review-para', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: /^Review/ }).first().click(); await p.getByRole('dialog').waitFor(); await p.getByRole('tab', { name: /^PARA/ }).click(); await p.waitForTimeout(1200) } },
  { name: 'review-tasks', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: /^Review/ }).first().click(); await p.getByRole('dialog').waitFor(); await p.getByRole('tab', { name: /^Tasks/ }).click(); await p.waitForTimeout(1200) } },
  { name: 'review-readonly', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => { await p.getByRole('button', { name: /^Review/ }).first().click(); await p.getByRole('dialog').waitFor(); await p.waitForTimeout(1200) } },
  { name: 'sessions-memories', w: 1440, h: 900, hash: '#sessions', run: async (p) => { await p.locator('.xc-sessions-list li, .xc-sessions-list button').first().click(); await p.getByRole('tab', { name: 'Memories' }).click(); await p.waitForTimeout(1200) } },
  { name: 'sessions-trace', w: 1440, h: 900, hash: '#sessions', run: async (p) => { await p.locator('.xc-sessions-list li, .xc-sessions-list button').first().click(); await p.getByRole('tab', { name: 'Decision trace' }).click(); await p.waitForTimeout(1200) } },
  { name: 'sessions-kernel', w: 1440, h: 900, hash: '#sessions', run: async (p) => { await p.locator('.xc-sessions-list li, .xc-sessions-list button').first().click(); await p.getByRole('tab', { name: 'Kernel intents' }).click(); await p.waitForTimeout(1200) } },
  { name: 'agents-pair', w: 1440, h: 900, hash: '#agents', run: async (p) => { await p.getByRole('button', { name: 'Pair a device' }).click(); await p.getByLabel('Device id').fill('laptop-4f2a91'); await p.getByLabel(/Display name/).fill('Racine laptop'); await p.waitForTimeout(500) } },
  { name: 'agents-paired', w: 1440, h: 900, hash: '#agents', run: async (p) => { await p.getByRole('button', { name: 'Pair a device' }).click(); await p.getByLabel('Device id').fill('laptop-4f2a91'); await p.getByLabel(/Display name/).fill('Racine laptop'); await p.getByRole('button', { name: 'Pair device' }).click(); await p.waitForTimeout(1800) } },
  { name: 'settings-account-signed-in', w: 1440, h: 1500, hash: '#settings', routes: [
      ['**/cortex-api/api/auth/me', { account: { id: 'acct-7d1c', email: 'operator@organization.com', display_name: 'Operator', profile_id: 'default', role: 'operator', status: 'active', email_verified: true, approval_status: 'approved', agent_ids: [], created_at: '2026-10-06T14:02:11Z' }, session_expires_at: '2026-10-18T14:02:11Z' }],
      ['**/cortex-api/api/auth/sessions', { sessions: [{ id: 's1', label: 'browser · Chromium', created_at: '2026-10-11T02:41:09Z', last_used_at: '2026-10-11T03:20:44Z', revoked_at: null }, { id: 's2', label: 'browser · Firefox', created_at: '2026-10-08T19:12:30Z', last_used_at: '2026-10-09T08:01:02Z', revoked_at: null }, { id: 's3', label: 'browser · Chromium', created_at: '2026-10-06T14:02:11Z', last_used_at: '2026-10-07T21:40:00Z', revoked_at: '2026-10-08T00:00:00Z' }] }],
      ['**/cortex-api/api/auth/events', { events: [{ event_type: 'login', detail: '', created_at: '2026-10-11T02:41:09Z' }, { event_type: 'login_failed', detail: 'invalid password', created_at: '2026-10-10T23:58:31Z' }, { event_type: 'password_changed', detail: '', created_at: '2026-10-09T08:00:12Z' }] }],
    ], run: async (p) => { await p.getByRole('tab', { name: 'Account' }).click(); await p.getByText('Signed in as').first().waitFor(); await p.waitForTimeout(800) } },
  { name: 'signin-error', w: 1440, h: 900, signedOut: true, status: 400, routes: [['**/cortex-api/api/auth/login', { error: 'invalid email or password' }]], run: async (p) => { await p.getByLabel('Email').fill('operator@organization.com'); await p.getByLabel('Password', { exact: true }).fill('not-the-password'); await p.getByRole('button', { name: /Sign in/ }).last().click(); await p.waitForTimeout(900) } },
  { name: 'signin-pending', w: 1440, h: 900, signedOut: true, status: 400, routes: [['**/cortex-api/api/auth/login', { error: 'account requires email verification or administrator approval' }]], run: async (p) => { await p.getByLabel('Email').fill('new.operator@organization.com'); await p.getByLabel('Password', { exact: true }).fill('a-long-enough-password'); await p.getByRole('button', { name: /Sign in/ }).last().click(); await p.waitForTimeout(900) } },
  { name: 'signin-expired', w: 1440, h: 900, signedOut: true, notice: 'Session expired. Sign in again to reconnect to this Cortex profile.' },
  { name: 'integrity-checkpoint-new', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: /^Integrity/ }).first().click(); await p.getByRole('dialog').waitFor(); await p.locator('#ig-checkpoints').click(); await p.waitForTimeout(1200); await p.getByRole('button', { name: 'New checkpoint' }).first().click(); await p.waitForTimeout(2500); await p.getByRole('button', { name: 'Reconcile' }).first().click(); await p.waitForTimeout(2500) } },
  { name: 'integrity-confirm-rebuild', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: /^Integrity/ }).first().click(); await p.getByRole('dialog').waitFor(); await p.locator('#ig-checkpoints').click(); await p.waitForTimeout(1200); await p.getByRole('button', { name: 'Rebuild…' }).first().click(); await p.waitForTimeout(700) } },
  { name: 'operations-readiness', w: 1440, h: 1500, hash: '#operations', run: async (p) => { await p.getByRole('button', { name: 'Run full readiness check' }).click(); await p.waitForTimeout(3500) } },
  { name: 'recall-lexical', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.keyboard.press('Control+k'); await p.getByRole('dialog', { name: 'Recall' }).waitFor(); await p.getByRole('button', { name: 'Lexical' }).click(); await p.getByLabel('Recall query').fill('relay'); await p.keyboard.press('Enter'); await p.locator('li.xc-result').first().waitFor(); await p.waitForTimeout(600) } },
  { name: 'recall-error', w: 1440, h: 900, hash: '#graph', routes: [['**/cortex-api/api/retrieval/hybrid', { error: 'lexical and vector retrieval are disabled by feature policy' }]], status: 500, run: async (p) => { await p.keyboard.press('Control+k'); await p.getByRole('dialog', { name: 'Recall' }).waitFor(); await p.getByLabel('Recall query').fill('relay submissions'); await p.keyboard.press('Enter'); await p.waitForTimeout(1200) } },
  { name: 'timeline-session-selected', w: 1440, h: 900, hash: '#timeline', primary: true, run: async (p) => { await p.locator('.xc-lane-label').first().click(); await p.waitForTimeout(900) } },
  // ---- round 6: collapsed navigation and panes
  { name: 'panes-hidden', w: 1440, h: 900, hash: '#graph', primary: true, init: { facetsCollapsed: true, inspectorCollapsed: true }, run: async (p) => { await settle3d(p) } },
  { name: 'inspector-hidden', w: 1440, h: 900, hash: '#timeline', primary: true, init: { inspectorCollapsed: true } },
  { name: 'topbar-collapsed', w: 1440, h: 900, hash: '#graph', primary: true, init: { shell: 'top', railCollapsed: true } },
  { name: 'rail-graph', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times') } },
  { name: 'rail-timeline', w: 1440, h: 900, hash: '#timeline', init: { railCollapsed: true }, run: async (p) => { await pinMemory(p, 'relay retries', 'three times') } },
  { name: 'signin', w: 1440, h: 900, signedOut: true },
  { name: 'settings-layout', w: 1440, h: 900, hash: '#settings' },
  { name: 'settings-inference', w: 1440, h: 1560, hash: '#settings', run: async (p) => { await p.getByRole('tab', { name: 'Inference' }).click(); await p.getByLabel('Batch size').waitFor(); await p.getByText('Worker contract').click() } },
  { name: 'settings-developer', w: 1440, h: 900, hash: '#settings', run: async (p) => { await p.getByRole('tab', { name: 'Developer' }).click(); await p.getByRole('button', { name: 'Run self-test' }).click(); await p.getByText('The test could not run.').waitFor() } },
  { name: 'memories', w: 1440, h: 900, hash: '#memories' },
  { name: 'entities', w: 1440, h: 900, hash: '#entities', run: async (p) => { await p.getByRole('dialog').getByText('relay', { exact: true }).first().click(); await p.waitForTimeout(1200) } },
  { name: 'sessions', w: 1440, h: 900, hash: '#sessions', run: async (p) => { await p.locator('.xc-sessions-list li, .xc-sessions-list button').first().click(); await p.waitForTimeout(800) } },
  { name: 'operations', w: 1440, h: 1500, hash: '#operations' },
  { name: 'agents', w: 1440, h: 900, hash: '#agents' },
  { name: 'inspector-verify', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('button', { name: 'Ask the server to verify' }).click(); await p.getByText(/Server recomputed this history/).waitFor() } },
  { name: 'inspector-extract', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('button', { name: 'Request extraction' }).click(); await p.getByLabel('Task').selectOption({ label: 'structural entities — rule-based, no model, runs now' }) } },
  { name: 'recall-context', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.keyboard.press('Control+k'); await p.getByRole('dialog', { name: 'Recall' }).waitFor(); await p.getByRole('button', { name: 'Context' }).click(); await p.getByLabel('Recall query').fill('relay submissions'); await p.keyboard.press('Enter'); await p.getByText(/characters used/).waitFor() } },
  { name: 'integrity', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: /^Integrity/ }).first().click(); await p.getByRole('dialog').waitFor(); await p.getByRole('button', { name: 'Verify exchanges' }).first().click(); await p.getByText(/Verified in this browser/).first().waitFor({ timeout: 12000 }) } },
  { name: 'settings-embeddings', w: 1440, h: 900, hash: '#settings', run: async (p) => { await p.getByRole('tab', { name: 'Embeddings' }).click(); await p.getByText('Coverage of the active model').waitFor() } },
  { name: 'settings-account', w: 1440, h: 900, hash: '#settings', run: async (p) => { await p.getByRole('tab', { name: 'Account' }).click(); await p.getByText(/connected with a token/).waitFor() } },
  { name: 'signin-create', w: 1440, h: 900, signedOut: true, run: async (p) => { await p.getByRole('tab', { name: 'Create account' }).click(); await p.getByText('Create your Cortex account').waitFor() } },
  { name: 'review', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: /^Review/ }).first().click(); await p.getByRole('dialog').waitFor(); await p.waitForTimeout(1200) } },
  { name: 'topbar-graph', w: 1440, h: 900, hash: '#graph', init: { shell: 'top' }, run: async (p) => { await pinMemory(p, 'relay retries', 'three times') } },
  { name: 'topbar-sessions', w: 1440, h: 900, hash: '#sessions', init: { shell: 'top' }, run: async (p) => { await p.locator('.xc-sessions-list li, .xc-sessions-list button').first().click(); await p.waitForTimeout(800) } },
  { name: 'memories-empty', w: 1440, h: 900, hash: '#memories', run: async (p) => { await p.getByPlaceholder(/Search memory/).fill('zzzzqq'); await p.keyboard.press('Enter'); await p.waitForTimeout(1200) } },
  { name: 'unavailable', w: 1440, h: 900, hash: '#graph', abortApi: true },
  { name: 'phone-memories', w: 390, h: 844, hash: '#memories' },
  { name: 'phone-entities', w: 390, h: 844, hash: '#entities', run: async (p) => { await p.getByRole('dialog').getByText('relay', { exact: true }).first().click(); await p.waitForTimeout(1000) } },
  { name: 'phone-sessions', w: 390, h: 844, hash: '#sessions', run: async (p) => { await p.locator('.xc-sessions-list li, .xc-sessions-list button').first().click(); await p.waitForTimeout(800) } },
  { name: 'phone-operations', w: 390, h: 844, hash: '#operations' },
  { name: 'phone-agents', w: 390, h: 844, hash: '#agents' },
  { name: 'phone-settings', w: 390, h: 844, hash: '#settings', run: async (p) => { await p.getByRole('tab', { name: 'Inference' }).click(); await p.getByLabel('Batch size').waitFor() } },
  { name: 'recall-hybrid', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.keyboard.press('Control+k'); await p.getByRole('dialog', { name: 'Recall' }).waitFor(); await p.getByLabel('Recall query').fill('relay submissions'); await p.keyboard.press('Enter'); await p.locator('li.xc-result').first().waitFor(); await p.waitForTimeout(800) } },
  { name: 'review-confirm', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: /^Review/ }).first().click(); await p.getByRole('dialog').waitFor(); await p.getByRole('button', { name: /^Accept/ }).first().click(); await p.waitForTimeout(800) } },
  { name: 'integrity-checkpoints', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: /^Integrity/ }).first().click(); await p.getByRole('dialog').waitFor(); await p.locator('#ig-checkpoints').click(); await p.waitForTimeout(1500) } },
  { name: 'integrity-links', w: 1440, h: 900, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: /^Integrity/ }).first().click(); await p.getByRole('dialog').waitFor(); await p.locator('#ig-links').click(); await p.waitForTimeout(1500) } },
  { name: 'inspector-files', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('tab', { name: 'Files' }).click(); await p.waitForTimeout(600) } },
  { name: 'inspector-supersede', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('button', { name: 'Supersede' }).click(); await p.waitForTimeout(500) } },
  { name: 'inspector-forget', w: 1440, h: 900, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times'); await p.getByRole('button', { name: 'Forget' }).click(); await p.waitForTimeout(500) } },
  { name: 'graph-primary', w: 1440, h: 900, hash: '#graph', primary: true, run: async (p) => { await pinMemory(p, 'domain-separated'); } },
  { name: 'timeline-primary', w: 1440, h: 900, hash: '#timeline', primary: true, run: async (p) => { await pinMemory(p, 'domain-separated'); } },
  { name: 'timeline-window', w: 1440, h: 900, hash: '#timeline', primary: true, run: async (p) => { await p.getByRole('button', { name: '7d', exact: true }).click(); await p.waitForTimeout(800) } },
  { name: 'topbar-timeline', w: 1440, h: 900, hash: '#timeline', primary: true, init: { shell: 'top' }, run: async (p) => { await pinMemory(p, 'domain-separated'); } },
  { name: 'phone-timeline', w: 390, h: 844, hash: '#timeline', primary: true },
  { name: 'phone-filters', w: 390, h: 844, hash: '#graph', primary: true, run: async (p) => { await p.getByRole('button', { name: /^Filters/ }).click(); await p.getByRole('dialog').waitFor() } },
  { name: 'phone-time', w: 390, h: 844, hash: '#timeline', primary: true, run: async (p) => { await p.getByRole('button', { name: /^Time\b(?!line)/ }).click(); await p.getByRole('dialog').waitFor() } },
  { name: 'phone-graph-primary', w: 390, h: 844, hash: '#graph', primary: true },
  { name: 'phone-graph', w: 390, h: 844, hash: '#graph' },
  { name: 'phone-more', w: 390, h: 844, hash: '#graph', run: async (p) => { await p.getByRole('button', { name: 'More' }).click(); await p.getByRole('dialog').waitFor() } },
  { name: 'phone-inspector', w: 390, h: 844, hash: '#graph', run: async (p) => { await pinMemory(p, 'relay retries', 'three times') } },
]

for (const b of boards) {
  if (only && !only.has(b.name)) continue
  const ctx = await browser.newContext({ viewport: { width: b.w, height: b.h } })
  await ctx.addInitScript(({ signedOut, init, primary, notice }) => {
    if (primary) sessionStorage.setItem('xibalba-cortex.selected-primary', '1')
    if (signedOut) { sessionStorage.removeItem('xibalba-cortex.signed-in'); sessionStorage.removeItem('xibalba-cortex.auth-notice'); if (notice) sessionStorage.setItem('xibalba-cortex.auth-notice', notice) }
    else sessionStorage.setItem('xibalba-cortex.signed-in', '1')
    if (init) localStorage.setItem('xibalba-cortex.console-settings', JSON.stringify({ shell: 'rail', railCollapsed: false, ...init }))
  }, { signedOut: !!b.signedOut, init: b.init ?? null, primary: !!b.primary, notice: b.notice ?? null })
  if (b.noWebgl) await ctx.addInitScript(() => { const get = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (t, ...a) { return /webgl/.test(String(t)) ? null : get.call(this, t, ...a) } })
  for (const [pat, body] of b.routes ?? []) await ctx.route(pat, (r) => r.fulfill({ status: b.status ?? 200, contentType: 'application/json', body: JSON.stringify(body) }))
  if (b.abortApi) await ctx.route('**/cortex-api/**', (r) => r.abort())
  const page = await ctx.newPage(); page.setDefaultTimeout(10000)
  try {
    await page.goto(BASE + (b.hash ?? '')); await page.waitForTimeout(4500)
    if (b.run) await b.run(page)
    // a 3D graph keeps animating until its layout settles; wait so the snapshot is the settled state
    if (await page.locator('canvas[data-node-count]').count()) { await page.locator('canvas[data-settled="true"]').waitFor({ timeout: 20000 }).catch(() => {}); await page.waitForTimeout(2200) }
    await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(500)
    // size the board to the content: grow the viewport until the page stops being taller than it
    let h = b.h
    for (let i = 0; i < (b.w < 500 ? 0 : 4); i++) {
      const sh = await page.evaluate(() => document.documentElement.scrollHeight)
      if (sh <= h + 1) break
      h = sh; await page.setViewportSize({ width: b.w, height: h }); await page.waitForTimeout(500)
    }
    b.h = h
    await page.screenshot({ path: `boards-png/${b.name}.png` })
    // a <canvas> does not survive serialization, so rasterize each one and mark where it goes
    const canvases = await page.evaluate(() => [...document.querySelectorAll('.xc canvas')].map((c, i) => {
      c.setAttribute('data-capture-canvas', String(i))
      return { i, w: c.clientWidth, h: c.clientHeight, url: c.toDataURL('image/png') }
    }))
    for (const c of canvases) writeFileSync(`boards-src/${b.name}-canvas-${c.i}.png`, Buffer.from(c.url.split(',')[1], 'base64'))
    const html = await page.evaluate(() => {
      document.querySelectorAll('input').forEach((i) => {
        if (i.type === 'checkbox' || i.type === 'radio') i.checked ? i.setAttribute('checked', '') : i.removeAttribute('checked')
        else i.setAttribute('value', i.value)
        i.removeAttribute('autofocus')
      })
      document.querySelectorAll('select').forEach((s) => [...s.options].forEach((o) => (o.selected ? o.setAttribute('selected', '') : o.removeAttribute('selected'))))
      document.querySelectorAll('textarea').forEach((t) => { t.textContent = t.value })
      return document.querySelector('.xc').outerHTML
    })
    writeFileSync(`boards-src/${b.name}.json`, JSON.stringify({ name: b.name, w: b.w, h: b.h, html, canvases: canvases.map(({ i, w, h }) => ({ i, w, h })) }))
    console.log('ok  ', b.name, html.length)
  } catch (e) { console.log('FAIL', b.name, String(e).split('\n')[0]); await page.screenshot({ path: `boards-png/${b.name}-FAIL.png` }) }
  await ctx.close()
}
await browser.close()
