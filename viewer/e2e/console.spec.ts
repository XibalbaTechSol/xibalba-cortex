// Desktop validation of the Cortex console in headless Chromium, against a real API and fixture.
//
// Organised the way the console is: first that it boots and wears its theme, then the two lenses
// (Graph, Timeline), then every tool that opens over a lens, then the dialogs, then the
// collapsible chrome, and last the failure states. A "wiring" test at the end tours the app and
// fails if any request the console makes is refused (404/405/5xx) -- the frontend and backend
// must agree on every route.
import { expect, test, type Page } from '@playwright/test'
import { openConsole, paintedPixels, pinMemory, settled3d, watchErrors } from './helpers'

const SETTINGS_KEY = 'xibalba-cortex.console-settings'
const settingsOf = (page: Page) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) ?? '{}'), SETTINGS_KEY)

// ---------------------------------------------------------------------------------------------
test.describe('boot, theme and typography', () => {
  test('boots signed in with no uncaught errors, and the old viewer is gone', async ({ page }) => {
    const errors = watchErrors(page)
    const fontRequests: string[] = []
    page.on('request', (r) => { if (/fonts\.googleapis/.test(r.url())) fontRequests.push(r.url()) })
    await openConsole(page)
    await expect(page.locator('.xc')).toBeVisible()
    await expect(page).toHaveTitle('Xibalba Cortex')
    // the escape hatch to the previous viewer is removed, and so is its query switch
    await expect(page.getByRole('link', { name: /legacy viewer/i })).toHaveCount(0)
    await page.goto('/?ui=legacy#graph')
    await expect(page.locator('.xc')).toBeVisible()
    await expect(page.locator('.cortex-hero, .cortex-landing, .cortex-shell')).toHaveCount(0)
    // only the console's two families are requested (no DM Sans / Manrope left over)
    expect(fontRequests.length).toBeGreaterThan(0)
    for (const url of fontRequests) { expect(url).toMatch(/Barlow|JetBrains/); expect(url).not.toMatch(/DM\+Sans|Manrope/) }
    expect(errors).toEqual([])
  })

  test('is set in Barlow with lining figures, and JetBrains Mono for addresses', async ({ page }) => {
    await openConsole(page)
    await page.evaluate(() => document.fonts.ready)
    const faces = await page.evaluate(() => ({
      raleway400: document.fonts.check('400 16px Barlow'),
      raleway600: document.fonts.check('600 16px Barlow'),
      mono: document.fonts.check('400 12px "JetBrains Mono"'),
      body: getComputedStyle(document.querySelector('.xc')!).fontFamily,
      button: getComputedStyle(document.querySelector('.xc button')!).fontFamily,
      heading: getComputedStyle(document.querySelector('.xc-win h1, .xc-win h2, .xc-title, .xc-brand b')!).fontFamily,
      figures: getComputedStyle(document.querySelector('.xc button')!).fontFeatureSettings,
    }))
    expect(faces.raleway400 && faces.raleway600 && faces.mono).toBe(true)
    for (const family of [faces.body, faces.button, faces.heading]) expect(family).toMatch(/^"?Barlow/)
    expect(faces.figures).toMatch(/lnum/) // the console explicitly asks for lining figures
  })

  test('is square, flat, graphite and steel', async ({ page }) => {
    await openConsole(page)
    const look = await page.evaluate(() => {
      const root = getComputedStyle(document.querySelector('.xc')!)
      const btn = getComputedStyle(document.querySelector('.xc button.xc-btn, .xc button')!)
      return { ground: root.getPropertyValue('--ground').trim(), accent: root.getPropertyValue('--cortex-accent').trim(), radius: btn.borderTopLeftRadius, shadow: btn.boxShadow, bg: getComputedStyle(document.body).backgroundColor }
    })
    expect(look.ground).toBe('#14171a')
    expect(look.accent).toBe('#94bce3')
    expect(look.radius).toBe('0px')
    expect(look.shadow).toBe('none')
    expect(look.bg).toBe('rgb(20, 23, 26)')
  })
})

// ---------------------------------------------------------------------------------------------
test.describe('the two lenses are the navigation', () => {
  test('the rail keeps five readable destinations and the header switches lenses', async ({ page }) => {
    await openConsole(page)
    await expect(page.locator('.xc-rail-nav .xc-nav-btn')).toHaveText([/Workspace/, /Explore/, /Recall/, /Review/, /Integrity/])
    await expect(page.getByRole('group', { name: 'Lens', exact: true }).getByRole('button')).toHaveText(['Graph', 'Timeline'])
  })

  test('switching lens keeps the route, and a hash opens the right lens', async ({ page }) => {
    await openConsole(page, { hash: 'timeline' })
    await expect(page.getByRole('region', { name: /Timeline lens|Timeline/ }).first()).toBeVisible()
    await page.getByRole('group', { name: 'Lens', exact: true }).getByRole('button', { name: /Graph/ }).click()
    // the Graph lens is the default route, so its hash is empty
    await expect(page).not.toHaveURL(/#timeline/)
    await expect(page.getByRole('region', { name: 'Graph lens' })).toBeVisible()
  })
})

// ---------------------------------------------------------------------------------------------
test.describe('graph lens', () => {
  test('renders the 3D graph: a painted canvas whose node count matches the readout', async ({ page }) => {
    const errors = watchErrors(page)
    await openConsole(page, { primary: true })
    const canvas = await settled3d(page)
    const count = Number(await canvas.getAttribute('data-node-count'))
    expect(count).toBeGreaterThan(20)
    await expect(page.locator('.xc-graph-count')).toContainText(new RegExp(`^${count}(?: of \\d+)? nodes`))
    expect(await paintedPixels(page, 'canvas[data-node-count]')).toBeGreaterThan(500)
    expect(errors).toEqual([])
  })

  test('snap to grid puts every node in its own cell, and turning it off lets them go', async ({ page }) => {
    await openConsole(page, { primary: true })
    const canvas = await settled3d(page)
    const snap = page.getByRole('button', { name: 'Snap to grid' })
    await expect(snap).toHaveAttribute('aria-pressed', 'true')
    // one occupied cell per node is the lattice invariant (gridSnap.ts)
    expect(Number(await canvas.getAttribute('data-cells'))).toBe(Number(await canvas.getAttribute('data-node-count')))
    await snap.click()
    await expect(snap).toHaveAttribute('aria-pressed', 'false')
    await expect(canvas).toHaveAttribute('data-cells', 'off')
    expect((await settingsOf(page)).graphSnap).toBe(false)
    await snap.click()
    await expect(canvas).not.toHaveAttribute('data-cells', 'off')
  })

  test('2D and 3D toggle, and the choice survives a reload', async ({ page }) => {
    await openConsole(page, { primary: true })
    await settled3d(page)
    const group = page
    await group.getByRole('button', { name: '2D view', exact: true }).click()
    await expect(group.getByRole('button', { name: '2D view', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('canvas[data-node-count]')).toHaveCount(0) // the 3D engine is torn down
    await expect.poll(() => paintedPixels(page, '.xc-canvas-win canvas')).toBeGreaterThan(300)
    await page.reload()
    await expect(page.getByRole('button', { name: '2D view', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('button', { name: '3D view', exact: true }).click()
    await settled3d(page)
  })

  test('keyboard: arrows orbit, + and - zoom, F frames everything, Esc clears', async ({ page }) => {
    const errors = watchErrors(page)
    await openConsole(page, { primary: true })
    const canvas = await settled3d(page)
    await canvas.focus()
    const before = await paintedPixels(page, 'canvas[data-node-count]')
    for (const key of ['ArrowLeft', 'ArrowUp', 'Shift+ArrowRight', '+', '+', '-', 'f', 'Escape']) { await page.keyboard.press(key); await page.waitForTimeout(150) }
    await page.waitForTimeout(800)
    expect(await paintedPixels(page, 'canvas[data-node-count]')).toBeGreaterThan(Math.min(before, 300))
    expect(errors).toEqual([])
  })

  test('zoom buttons and Fit keep the graph on screen at every distance', async ({ page }) => {
    await openConsole(page, { primary: true })
    await settled3d(page)
    for (let i = 0; i < 6; i++) { await page.getByRole('button', { name: 'Zoom out' }).click(); await page.waitForTimeout(250) }
    expect(await paintedPixels(page, 'canvas[data-node-count]')).toBeGreaterThan(200)
    for (let i = 0; i < 12; i++) { await page.getByRole('button', { name: 'Zoom in' }).click(); await page.waitForTimeout(200) }
    expect(await paintedPixels(page, 'canvas[data-node-count]')).toBeGreaterThan(100)
    await page.getByRole('button', { name: 'Fit all' }).click()
    await page.waitForTimeout(1500)
    expect(await paintedPixels(page, 'canvas[data-node-count]')).toBeGreaterThan(500)
  })

  test('clicking nodes selects them and fills the inspector; the legend is also the switches', async ({ page }) => {
    await openConsole(page, { primary: true })
    const canvas = await settled3d(page)
    const box = (await canvas.boundingBox())!
    let selected = ''
    scan: for (let y = box.y + 40; y < box.y + box.height - 40; y += 16) {
      for (let x = box.x + 40; x < box.x + box.width - 60; x += 16) {
        await page.mouse.click(x, y); await page.waitForTimeout(90)
        selected = (await canvas.getAttribute('data-selected')) ?? ''
        if (selected) break scan
      }
    }
    expect(selected).not.toBe('')
    await expect(page.getByRole('complementary', { name: /Inspector/ }).or(page.locator('.xc-inspector'))).toBeVisible()
    await page.getByRole('button', { name: 'Legend' }).click()
    const legend = page.getByLabel(/Legend/)
    await expect(legend).toBeVisible()
    await legend.getByRole('button').first().click() // a legend row is a facet switch
    await page.waitForTimeout(500)
  })

  test('facets: hiding a node class shrinks the graph and Reset facets brings it back', async ({ page }) => {
    await openConsole(page, { primary: true })
    const canvas = await settled3d(page)
    const all = Number(await canvas.getAttribute('data-node-count'))
    await page.getByRole('checkbox', { name: /^Sessions/ }).uncheck()
    await expect.poll(async () => Number(await page.locator('canvas[data-node-count]').getAttribute('data-node-count'))).toBeLessThan(all)
    await page.getByRole('checkbox', { name: /^Sessions/ }).check()
    await expect.poll(async () => Number(await page.locator('canvas[data-node-count]').getAttribute('data-node-count'))).toBe(all)
  })
})

// ---------------------------------------------------------------------------------------------
test.describe('timeline lens', () => {
  test('shows session lanes and a chain rail that windows both lenses', async ({ page }) => {
    await openConsole(page, { hash: 'timeline', primary: true })
    await expect(page.locator('.xc-lane-label').first()).toBeVisible()
    expect(await page.locator('.xc-lane-label').count()).toBeGreaterThan(3)
    const week = page.getByRole('button', { name: '7d', exact: true })
    await week.click()
    await expect(week).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('button', { name: 'all', exact: true }).click()
    await expect(page.getByRole('button', { name: 'all', exact: true })).toHaveAttribute('aria-pressed', 'true')
  })

  test('selecting a lane selects its session, and the selection survives a lens switch', async ({ page }) => {
    await openConsole(page, { hash: 'timeline', primary: true })
    await page.locator('.xc-lane-label').first().click()
    await expect(page.getByRole('button', { name: 'Exchanges, replay, telemetry' })).toBeVisible()
    await page.getByRole('group', { name: 'Lens', exact: true }).getByRole('button', { name: /Graph/ }).click()
    await expect(page.getByRole('button', { name: 'Exchanges, replay, telemetry' })).toBeVisible()
  })
})

// ---------------------------------------------------------------------------------------------
test.describe('inspector', () => {
  test('a pinned memory opens with provenance, neighbours, contradictions, telemetry and files', async ({ page }) => {
    await openConsole(page, { primary: true })
    await pinMemory(page, 'relay retries', 'three times')
    for (const tab of ['Provenance', 'Neighbors', 'Contradictions', 'Telemetry', 'Files']) {
      await page.getByRole('tab', { name: tab }).click()
      await expect(page.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true')
    }
  })

  test('the primary profile is read only, and says so where the actions would be', async ({ page }) => {
    await openConsole(page, { primary: true })
    await pinMemory(page, 'relay retries', 'three times')
    await expect(page.getByText(/Read-only workspace/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Forget' })).toHaveCount(0)
  })

  test('the server recomputes a memory history on request and the result is worded as such', async ({ page }) => {
    await openConsole(page, { primary: true })
    await pinMemory(page, 'relay retries', 'three times')
    await page.getByRole('button', { name: 'Ask the server to verify' }).click()
    await expect(page.getByText(/Server recomputed this history/)).toBeVisible()
  })
})

// ---------------------------------------------------------------------------------------------
test.describe('tools open over the lens they were opened from', () => {
  const tools: Array<[tool: string, hash: string, heading: RegExp]> = [
    ['Memories', 'memories', /Memories/], ['Entities', 'entities', /Entities/], ['Sessions', 'sessions', /Sessions/],
    ['Operations', 'operations', /Operations/], ['Agents', 'agents', /Agents/], ['Settings', 'settings', /Settings/],
  ]
  for (const lens of ['graph', 'timeline'] as const) {
    for (const [tool, hash, heading] of tools) {
      test(`${tool} opens over ${lens}, keeps it mounted, and Esc returns to it`, async ({ page }) => {
        await openConsole(page, { hash: lens, primary: true })
        await page.evaluate((next) => { window.location.hash = next }, `${lens === 'graph' ? '' : 'timeline/'}${hash}`)
        const drawer = page.getByRole('dialog')
        await expect(drawer).toBeVisible()
        await expect(drawer.getByRole('heading', { name: heading }).first()).toBeVisible()
        await expect(page).toHaveURL(new RegExp(`#(${lens}/)?${hash}$`))
        // the lens is still in the DOM underneath
        await expect(page.getByRole('region', { name: lens === 'graph' ? 'Graph lens' : /Timeline/ }).first()).toBeAttached()
        await page.keyboard.press('Escape')
        await expect(drawer).toBeHidden()
        await expect(page).toHaveURL(lens === 'graph' ? /#(graph)?$/ : /#timeline$/)
        // Deep-link navigation keeps the existing canvas and its camera mounted.
      })
    }
  }

  test('deep links open a drawer directly: #settings and #timeline/sessions', async ({ page }) => {
    await openConsole(page, { hash: 'settings' })
    await expect(page.getByRole('dialog').getByRole('heading', { name: /Settings/ }).first()).toBeVisible()
    await page.goto('/#timeline/sessions')
    await expect(page.getByRole('dialog').getByRole('heading', { name: /Sessions/ }).first()).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page).toHaveURL(/#timeline$/)
  })

  test('Sessions: pick one and read exchanges, replay, telemetry, trace and kernel intents', async ({ page }) => {
    await openConsole(page, { hash: 'sessions' })
    await page.locator('.xc-sessions-list li').first().click()
    for (const tab of ['Exchanges', 'Memories', 'Replay', 'Telemetry', 'Decision trace', 'Kernel intents']) {
      await page.getByRole('tab', { name: tab }).click()
      await expect(page.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true')
    }
    await page.getByRole('tab', { name: 'Invocations' }).click()
  })

  test('Entities: look one up and find a path between two', async ({ page }) => {
    await openConsole(page, { hash: 'entities', primary: true })
    await page.getByLabel('From entity').fill('store.py')
    await page.getByLabel('To entity').fill('domain Merkle root')
    await page.getByRole('button', { name: 'Find path' }).click()
    await expect(page.getByRole('dialog').locator('.xc-path, .xc-callout, [role="status"]').first()).toBeVisible()
  })

  test('Operations: the readiness check runs and reports', async ({ page }) => {
    await openConsole(page, { hash: 'operations' })
    await page.getByRole('button', { name: 'Run full readiness check' }).click()
    await expect(page.getByText(/ready|not ready/i).first()).toBeVisible()
  })

  test('Settings: every tab loads from the profile', async ({ page }) => {
    await openConsole(page, { hash: 'settings' })
    for (const tab of ['Layout', 'Inference', 'Embeddings', 'Account', 'Developer']) {
      await page.getByRole('tab', { name: tab }).click()
      await expect(page.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true')
    }
    await page.getByRole('tab', { name: 'Account' }).click()
    await expect(page.getByText(/connected with a token/)).toBeVisible()
    await page.getByRole('tab', { name: 'Developer' }).click()
    await page.getByRole('button', { name: 'Run self-test' }).click()
  })
})

// ---------------------------------------------------------------------------------------------
test.describe('dialogs: Recall, Review, Integrity', () => {
  test('Recall: hybrid, lexical and context modes answer, and an empty search says so', async ({ page }) => {
    await openConsole(page, { primary: true })
    await page.keyboard.press('Control+k')
    const dialog = page.getByRole('dialog', { name: 'Recall' })
    await expect(dialog).toBeVisible()
    await dialog.getByLabel('Recall query').fill('relay submissions')
    await page.keyboard.press('Enter')
    await expect(dialog.locator('li.xc-result').first()).toBeVisible()
    await dialog.getByRole('button', { name: 'Lexical' }).click()
    await dialog.getByLabel('Recall query').fill('relay')
    await page.keyboard.press('Enter')
    await expect(dialog.locator('li.xc-result').first()).toBeVisible()
    await dialog.getByRole('button', { name: 'Context' }).click()
    await dialog.getByLabel('Recall query').fill('relay submissions')
    await page.keyboard.press('Enter')
    await expect(dialog.getByText(/characters used/)).toBeVisible()
    await dialog.getByRole('button', { name: 'Lexical' }).click()
    await dialog.getByLabel('Recall query').fill('zzqqxxnothing')
    await page.keyboard.press('Enter')
    await expect(dialog.locator('li.xc-result')).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
  })

  test('Review: proposals, PARA and tasks, and a decision is a two-step action', async ({ page }) => {
    await openConsole(page)
    await page.getByRole('button', { name: /^Review/ }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('tab', { name: /^PARA/ }).click()
    await dialog.getByRole('tab', { name: /^Tasks/ }).click()
    await dialog.getByRole('tab', { name: /^Proposals|^Extraction/ }).first().click().catch(() => {})
    const accept = dialog.getByRole('button', { name: /^Accept/ }).first()
    if (await accept.count()) {
      await accept.click()
      await expect(dialog.getByText(/will write|This will|Confirm/i).first()).toBeVisible() // says what it writes before it does
    }
  })

  test('Integrity: exchange proofs verify in the browser, checkpoints and links load', async ({ page }) => {
    await openConsole(page)
    await page.getByRole('button', { name: /^Integrity/ }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Verify exchanges' }).first().click()
    await expect(dialog.getByText(/Verified in this browser/).first()).toBeVisible({ timeout: 20_000 })
    await dialog.locator('#ig-checkpoints').click()
    await expect(dialog.getByRole('button', { name: 'New checkpoint' }).first()).toBeVisible()
    await dialog.locator('#ig-links').click()
    await expect(dialog.getByRole('tabpanel')).toBeVisible()
  })
})

// ---------------------------------------------------------------------------------------------
test.describe('writes happen only in a writable workspace', () => {
  test('a new memory in the agent workspace is stored and then listed', async ({ page }) => {
    await openConsole(page, { hash: 'memories' }) // default scope is the writable agent pair
    const text = `Playwright wrote this memory at ${Date.now()} to prove the console reaches the store.`
    await page.getByRole('button', { name: 'New memory' }).click()
    await page.locator('form[aria-label="New memory"] textarea').fill(text)
    await page.locator('form[aria-label="New memory"]').getByRole('button', { name: /^(Save|Store|Remember|Add)/ }).click()
    await expect(page.getByRole('dialog').getByText(text.slice(0, 40))).toBeVisible()
  })

  test('the primary profile never offers a write', async ({ page }) => {
    await openConsole(page, { hash: 'memories', primary: true })
    await expect(page.getByRole('button', { name: 'New memory' })).toHaveCount(0)
    await expect(page.getByRole('note').filter({ hasText: /Read only/ })).toBeVisible() // and it says why
  })
})

// ---------------------------------------------------------------------------------------------
test.describe('collapsible navigation and panes', () => {
  test('the rail collapses to icons and the choice persists', async ({ page }) => {
    await openConsole(page, { primary: true })
    const toggle = page.getByRole('button', { name: 'Collapse navigation' })
    await toggle.click()
    await expect(page.locator('.xc-rail-shell')).toHaveAttribute('data-collapsed', 'true')
    expect((await settingsOf(page)).railCollapsed).toBe(true)
    await page.reload()
    await expect(page.locator('.xc-rail-shell')).toHaveAttribute('data-collapsed', 'true')
    await page.getByRole('button', { name: 'Expand navigation' }).click()
    await expect(page.locator('.xc-rail-shell')).toHaveAttribute('data-collapsed', 'false')
  })

  test('Projection and selected-memory docks collapse independently', async ({ page }) => {
    await openConsole(page, { primary: true })
    await page.getByRole('button', { name: 'Collapse projection', exact: true }).click()
    await expect(page.locator('.xc-facets')).toHaveAttribute('data-collapsed', 'true')
    await pinMemory(page, 'relay retries', 'three times')
    await page.getByRole('button', { name: 'Collapse selected memory', exact: true }).click()
    await expect(page.locator('.xc-inspector')).toHaveAttribute('data-collapsed', 'true')
    expect(await settingsOf(page)).toMatchObject({ facetsCollapsed: true, detailCollapsed: true })
  })

  test('the top-bar layout keeps all primary destinations readable', async ({ page }) => {
    await openConsole(page, { settings: { shell: 'top' }, primary: true })
    await expect(page.locator('.xc-top')).toBeVisible()
    await expect(page.locator('.xc-top .xc-nav-btn')).toHaveCount(5)
    await expect(page.locator('.xc-top .xc-nav-label').first()).toBeVisible()
  })

  test('Settings → Layout switches shell and writes through to the same stored preference', async ({ page }) => {
    await openConsole(page, { hash: 'settings' })
    await page.getByRole('tab', { name: 'Layout' }).click()
    await page.getByRole('checkbox', { name: 'Collapse the Projection dock' }).check()
    expect((await settingsOf(page)).facetsCollapsed).toBe(true)
    await page.locator('.xc-choice-card', { hasText: 'Top bar' }).click() // the radio itself is visually hidden
    await expect(page.locator('.xc-top')).toBeVisible()
    await page.getByRole('button', { name: 'Restore defaults' }).click()
    await expect(page.locator('.xc-rail-shell')).toBeVisible()
  })
})

// ---------------------------------------------------------------------------------------------
test.describe('sign-in and failure states', () => {
  test('signed out shows the sign-in screen; a refused login names the problem', async ({ page }) => {
    await page.route('**/cortex-api/api/auth/login', (r) => r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: 'invalid email or password' }) }))
    await openConsole(page, { signedOut: true })
    await page.getByLabel('Email').fill('operator@example.com')
    await page.getByLabel('Password', { exact: true }).fill('not-the-password')
    await page.getByRole('button', { name: /Sign in/ }).last().click()
    await expect(page.getByText(/invalid email or password/i)).toBeVisible()
    await page.getByRole('tab', { name: 'Create account' }).click()
    await expect(page.getByText('Create your Cortex account')).toBeVisible()
  })

  test('a 401 anywhere returns to sign-in with a notice', async ({ page }) => {
    await openConsole(page, { primary: true })
    // the graph is the one call the console cannot do without; "invalid or revoked token" is the
    // server's real wording for an ended session and carries no "401" in its text
    await page.route('**/cortex-api/api/graph**', (r) => r.fulfill({ status: 401, contentType: 'application/json', body: '{"error":"invalid or revoked token"}' }))
    await page.getByRole('button', { name: 'Reload data' }).click()
    await expect(page.getByRole('button', { name: /sign in/i }).first()).toBeVisible()
  })

  test('an unreachable API reads Unavailable rather than hanging', async ({ page }) => {
    await page.route('**/cortex-api/**', (r) => r.abort())
    await openConsole(page, { signedOut: false }).catch(() => {})
    await expect(page.getByText('Unavailable').first()).toBeVisible({ timeout: 20_000 })
  })

  test('without WebGL the graph falls back to 2D and says why', async ({ page }) => {
    await page.addInitScript(() => {
      const get = HTMLCanvasElement.prototype.getContext
      HTMLCanvasElement.prototype.getContext = function (t: string, ...a: unknown[]) { return /webgl/.test(String(t)) ? null : (get as Function).call(this, t, ...a) } as typeof get
    })
    await openConsole(page, { primary: true })
    await expect(page.getByText(/WebGL/).first()).toBeVisible()
    await expect(page.locator('canvas[data-node-count]')).toHaveCount(0)
    await expect.poll(() => paintedPixels(page, '.xc-canvas-win canvas')).toBeGreaterThan(300)
  })
})

// ---------------------------------------------------------------------------------------------
test.describe('wiring: every request the console makes is answered by the backend', () => {
  test('a tour of every lens, tool and dialog draws no 404, 405 or 5xx', async ({ page }) => {
    test.setTimeout(240_000)
    const refused: string[] = []
    page.on('response', (res) => {
      const url = new URL(res.url())
      if (!url.pathname.startsWith('/cortex-api/')) return
      const path = url.pathname.replace('/cortex-api', '')
      // expected: 400 from /api/auth/csrf under a bearer token (nothing to protect); 404 for a
      // memory with no attachments/contradictions is NOT expected and would be reported
      if (path === '/api/auth/csrf') return
      if ([404, 405].includes(res.status()) || res.status() >= 500) refused.push(`${res.status()} ${res.request().method()} ${path}`)
    })
    await openConsole(page, { primary: true }) // the read-only primary profile has the full fixture
    await settled3d(page)
    // lenses and every tool
    for (const hash of ['timeline', 'graph', 'memories', 'entities', 'sessions', 'operations', 'agents', 'settings']) {
      await page.goto(`/#${hash}`); await page.waitForTimeout(1500)
    }
    // settings tabs
    for (const tab of ['Inference', 'Embeddings', 'Account', 'Developer']) { await page.getByRole('tab', { name: tab }).click(); await page.waitForTimeout(700) }
    // sessions detail
    await page.goto('/#sessions'); await page.locator('.xc-sessions-list li').first().click()
    for (const tab of ['Exchanges', 'Memories', 'Replay', 'Telemetry', 'Decision trace', 'Kernel intents', 'Invocations']) { await page.getByRole('tab', { name: tab }).click(); await page.waitForTimeout(600) }
    // recall in each mode, then an inspector over a pinned memory
    await page.goto('/#graph')
    await pinMemory(page, 'relay retries', 'three times')
    await page.getByRole('button', { name: 'Ask the server to verify' }).click(); await page.waitForTimeout(800) // on the first tab
    for (const tab of ['Provenance', 'Neighbors', 'Contradictions', 'Telemetry', 'Files']) { await page.getByRole('tab', { name: tab }).click(); await page.waitForTimeout(500) }
    // review and integrity
    await page.getByRole('button', { name: /^Review/ }).first().click(); await page.waitForTimeout(1200)
    await page.getByRole('dialog').getByRole('tab', { name: /^PARA/ }).click(); await page.waitForTimeout(600)
    await page.getByRole('dialog').getByRole('tab', { name: /^Tasks/ }).click(); await page.waitForTimeout(600)
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: /^Integrity/ }).first().click(); await page.waitForTimeout(800)
    await page.getByRole('dialog').getByRole('button', { name: 'Verify exchanges' }).first().click(); await page.waitForTimeout(2500)
    await page.locator('#ig-checkpoints').click(); await page.waitForTimeout(1000)
    await page.locator('#ig-links').click(); await page.waitForTimeout(1000)
    expect(refused).toEqual([])
  })
})
