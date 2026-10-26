import { expect, test, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

/* Scope and Reload belong over the workspace, not in the navigation rail.
 *
 * The assertions below are about PLACEMENT, not mere existence -- an earlier draft of this file
 * only checked that the two controls were visible somewhere, which passed just as happily with
 * both still in the rail. Each test therefore names the ancestor it demands, and the collapse
 * test exists because the rail's old copies disappeared into icons at 68px, which was the whole
 * reason for moving them. */

const headerScope = '.xc-workspace-header .xc-scope'
const headerReload = '.xc-workspace-header button[aria-label="Reload data"]'
const headerLens = '.xc-workspace-header [role="group"][aria-label="Lens"]'

async function openConsole(page: Page) {
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'))
  await stubConsoleApi(page)
}

test('scope and reload sit in the workspace header, not the rail', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')

  const header = page.locator('.xc-workspace-header')
  await expect(header).toBeVisible()
  await expect(page.locator(headerScope)).toBeVisible()
  await expect(page.locator(headerReload)).toBeVisible()

  // and no longer anywhere inside the navigation rail
  await expect(page.locator('.xc-rail-shell .xc-scope')).toHaveCount(0)
  await expect(page.locator('.xc-rail-shell button[aria-label="Reload data"]')).toHaveCount(0)

  // exactly one of each in the document, so the move did not leave a duplicate behind
  await expect(page.locator('.xc-scope')).toHaveCount(1)
  await expect(page.locator('button[aria-label="Reload data"]')).toHaveCount(1)
})

test('both survive collapsing the rail, which used to hide them', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')
  await page.locator('.xc-rail-toggle').click()
  await expect(page.locator('.xc-shell[data-collapsed="true"]')).toBeVisible()

  await expect(page.locator(headerScope)).toBeVisible()
  await expect(page.locator(headerReload)).toBeVisible()
  // the select is still operable, not just painted
  await expect(page.locator(`${headerScope} select, ${headerScope} .xc-scope-static`)).toBeVisible()
})

test('the reload button in the header actually refetches', async ({ page }) => {
  await openConsole(page)
  // registered AFTER the stub, so this handler runs first and falls through to it
  let calls = 0
  await page.route('**/api/**', async (route) => {
    calls += 1
    await route.fallback()
  })
  await page.goto('/')
  await expect(page.locator('.xc-workspace-header')).toBeVisible()
  const before = calls
  await page.locator(headerReload).click()
  await expect.poll(() => calls, { timeout: 5000 }).toBeGreaterThan(before)
})

test('the header takes its height from its controls and leaves the rest to the lens', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')
  const header = page.locator('.xc-workspace-header')
  await expect(header).toBeVisible()

  const hb = (await header.boundingBox())!
  const wb = (await page.locator('.xc-workspace').boundingBox())!

  // A header allowed to grow would eat the lens. 96px is generous for one row of controls.
  expect(hb.height).toBeLessThan(96)
  // The lens keeps the bulk of the column -- this is what `flex: none` on the header buys.
  expect(wb.height).toBeGreaterThan(500)
  // and the header sits above the workspace, not over it
  expect(hb.y + hb.height).toBeLessThanOrEqual(wb.y + 1)
})

/* The lens switch belongs in the same header, at its left, with scope and reload at the right.
 * It used to sit in each lens's own `.xc-bar`, so these tests name the ancestor and compare x
 * positions: "visible somewhere" would pass with the control still inside the lens toolbar. */

test('the lens switch sits in the header, left of scope and reload', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')

  await expect(page.locator(headerLens)).toBeVisible()
  // one switch in the document, and none left behind in either lens toolbar
  await expect(page.locator('[role="group"][aria-label="Lens"]')).toHaveCount(1)
  await expect(page.locator('.xc-bar [role="group"][aria-label="Lens"]')).toHaveCount(0)

  const header = (await page.locator('.xc-workspace-header').boundingBox())!
  const lens = (await page.locator(headerLens).boundingBox())!
  const scope = (await page.locator(headerScope).boundingBox())!
  const reload = (await page.locator(headerReload).boundingBox())!
  // left-hand group, right-hand group: the switch ends before scope begins
  expect(lens.x + lens.width).toBeLessThanOrEqual(scope.x)
  expect(scope.x + scope.width).toBeLessThanOrEqual(reload.x + 1)
  // all three on one row of the header
  expect(Math.abs(lens.y - scope.y)).toBeLessThan(40)
  // The switch starts at the header's left and reload ends at its right -- the spacer between them
  // is doing its job. Without a `flex` on `.xc-spacer` (this sheet has no base rule for it) the
  // three sat bunched together at the left, which the ordering checks above would not have caught.
  expect(lens.x - header.x).toBeLessThan(40)
  expect(header.x + header.width - (reload.x + reload.width)).toBeLessThan(40)
  expect(scope.x - (lens.x + lens.width)).toBeGreaterThan(200)
})

test('switching lens from the header swaps the lens and keeps the switch there', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')
  await expect(page.locator('section[aria-label="Graph lens"]')).toBeVisible()

  await page.locator(`${headerLens} button`, { hasText: 'Timeline' }).click()
  await expect(page.locator('section[aria-label="Timeline lens"]')).toBeVisible()
  await expect(page.locator('section[aria-label="Graph lens"]')).toHaveCount(0)
  // the control did not travel with the lens chrome, and is marked as current
  await expect(page.locator(headerLens)).toBeVisible()
  await expect(page.locator(`${headerLens} button[aria-pressed="true"]`)).toHaveText('Timeline')
  await expect(page.locator('.xc-bar [role="group"][aria-label="Lens"]')).toHaveCount(0)
})

test('a full page has no lens to switch, so the header shows no switch', async ({ page }) => {
  await openConsole(page)
  await page.goto('/#settings')
  await expect(page.locator('.xc-workspace-header')).toBeVisible()
  await expect(page.locator('[role="group"][aria-label="Lens"]')).toHaveCount(0)
  // scope and reload are not lens-specific, so they stay
  await expect(page.locator(headerScope)).toBeVisible()
  await expect(page.locator(headerReload)).toBeVisible()

  // Back on the workspace the switch returns -- the half of this test that actually discriminates,
  // since a build with the switch still in the lens toolbar also shows none of it on a page.
  /* The drawer is `aria-modal="true"` and its scrim covers the rail on purpose (PageDrawer.tsx:4,
     "Escape and the scrim close it"), so the rail button cannot be clicked through it -- the click
     spent the full timeout being intercepted by `.xc-scrim`. Escape is how the UI leaves a page,
     and it returns to the lens the page was opened from, which is the transition under test. */
  await page.keyboard.press('Escape')
  await expect(page.locator(headerLens)).toBeVisible()
})

/* Connection moved out of the rail foot and in beside Reload, and the account control grew. */

test('the connection indicator sits in the header beside reload, not in the rail', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')

  const conn = page.locator('.xc-workspace-header .xc-conn')
  await expect(conn).toBeVisible()
  await expect(page.locator('.xc-rail-shell .xc-conn')).toHaveCount(0)
  await expect(page.locator('.xc-conn')).toHaveCount(1)
  // its text, not just the dot -- the rail foot's copy lost the text whenever the rail collapsed
  await expect(conn.locator('span')).not.toBeEmpty()

  const cb = (await conn.boundingBox())!
  const rb = (await page.locator(headerReload).boundingBox())!
  // immediately to the left of Reload, on the same row
  expect(rb.x - (cb.x + cb.width)).toBeLessThan(40)
  expect(rb.x).toBeGreaterThan(cb.x)
  expect(Math.abs(cb.y - rb.y)).toBeLessThan(40)

  // and it survives collapsing the rail, which is what moving it bought
  await page.locator('.xc-rail-toggle').click()
  await expect(page.locator('.xc-shell[data-collapsed="true"]')).toBeVisible()
  await expect(conn).toBeVisible()
  await expect(conn.locator('span')).toBeVisible()
})

test('the account control is larger than the 28px it started at', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')

  const avatar = page.locator('.xc-profile-avatar')
  await expect(avatar).toBeVisible()
  const ab = (await avatar.boundingBox())!
  expect(ab.width).toBeGreaterThan(34)
  expect(ab.height).toBeGreaterThan(34)
  // still square, and still inside the collapsed rail's 48px of content
  expect(Math.abs(ab.width - ab.height)).toBeLessThan(2)
  expect(ab.width).toBeLessThanOrEqual(48)

  const btn = (await page.locator('.xc-profile-btn').boundingBox())!
  expect(btn.height).toBeGreaterThan(ab.height)

  // and the menu it opens is unchanged: Settings and Log out
  await page.locator('.xc-profile-btn').click()
  await expect(page.locator('.xc-profile-menu [role="menuitem"]')).toHaveText(['Settings', 'Log out'])
})

/* The header is one unwrapping row of four controls. Everything above runs at 1600px with the
 * rail layout; these two cover the widths and the shell that the rules above never exercise. */

for (const width of [1280, 1100, 900]) {
  test(`the header fits its column and keeps the connection dot at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'))
    await stubConsoleApi(page)
    await page.goto('/')

    const header = page.locator('.xc-workspace-header')
    await expect(header).toBeVisible()
    // the dot survives even where the text is dropped for room
    await expect(page.locator('.xc-workspace-header .xc-conn i')).toBeVisible()

    const hb = (await header.boundingBox())!
    for (const sel of [headerLens, headerScope, '.xc-workspace-header .xc-conn', headerReload]) {
      const b = (await page.locator(sel).boundingBox())!
      expect(b.x, `${sel} starts left of the header at ${width}px`).toBeGreaterThanOrEqual(hb.x - 1)
      expect(b.x + b.width, `${sel} runs past the header at ${width}px`).toBeLessThanOrEqual(hb.x + hb.width + 1)
    }

    // and nothing gave the page a horizontal scrollbar
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(over, `the page scrolls horizontally by ${over}px at ${width}px`).toBeLessThanOrEqual(1)
  })
}

test('the top-bar shell puts the lens switch left of the brand-side group too', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.addInitScript(() => {
    sessionStorage.setItem('xibalba-cortex.signed-in', '1')
    localStorage.setItem('xibalba-cortex.console-settings', JSON.stringify({ shell: 'top' }))
  })
  await stubConsoleApi(page)
  await page.goto('/')

  await expect(page.locator('header.xc-top')).toBeVisible()
  await expect(page.locator('.xc-workspace-header')).toHaveCount(0)

  const lens = page.locator('.xc-top [role="group"][aria-label="Lens"]')
  await expect(lens).toBeVisible()
  await expect(page.locator('[role="group"][aria-label="Lens"]')).toHaveCount(1)

  const lb = (await lens.boundingBox())!
  const brand = (await page.locator('.xc-top .xc-brand').boundingBox())!
  const scope = (await page.locator('.xc-top .xc-scope').boundingBox())!
  // just right of the brand, not flung to the far side by the brand's old `margin-right: auto`
  expect(lb.x).toBeGreaterThan(brand.x + brand.width - 1)
  expect(lb.x - (brand.x + brand.width)).toBeLessThan(60)
  expect(lb.x + lb.width).toBeLessThanOrEqual(scope.x)

  // and it still switches the lens
  await lens.locator('button', { hasText: 'Timeline' }).click()
  await expect(page.locator('section[aria-label="Timeline lens"]')).toBeVisible()
})

/* The rail's lockup is stated in solid white.
 *
 * It is measured through the browser's own decode and downscale, at the 124px the rail actually
 * paints, because that is where the previous asset failed: its RGB was already pure white, but
 * shipped at 549px and resampled down to 124 every hairline stroke averaged to about a third
 * coverage, so the mark rendered grey. Pixel values, not a screenshot diff. */
test('the brand lockup renders as solid white at the size the rail paints it', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')
  await expect(page.locator('.xc-brand-lockup')).toBeVisible()

  const m = await page.evaluate(async () => {
    const img = new Image()
    img.src = '/cortex-brain-compact-dark.png'
    await img.decode()
    const w = 124
    const h = Math.round((img.naturalHeight * w) / img.naturalWidth)
    const c = document.createElement('canvas')
    c.width = w
    c.height = h
    const ctx = c.getContext('2d')!
    ctx.drawImage(img, 0, 0, w, h)
    const d = ctx.getImageData(0, 0, w, h).data
    const alphas: number[] = []
    let offWhite = 0
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] <= 8) continue
      alphas.push(d[i + 3])
      if (d[i] !== 255 || d[i + 1] !== 255 || d[i + 2] !== 255) offWhite += 1
    }
    alphas.sort((a, b) => a - b)
    return {
      ink: alphas.length,
      median: alphas[Math.floor(alphas.length / 2)],
      strong: alphas.filter((a) => a >= 200).length / alphas.length,
      offWhite,
    }
  })

  expect(m.ink, 'the lockup decoded to no ink at all').toBeGreaterThan(1000)
  // the ink is white, not a grey that merely looks white on a dark ground
  expect(m.offWhite, 'the lockup has ink that is not pure white').toBe(0)
  // and it is stated, not ghosted: the 549px asset measured a median of 75 here, and 0% strong
  expect(m.median).toBeGreaterThan(140)
  expect(m.strong).toBeGreaterThan(0.25)
})
