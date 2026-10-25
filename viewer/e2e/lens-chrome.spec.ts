import { expect, test, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

/* The lenses carry no header of their own.
 *
 * Both used to open with a `.xc-bar` strip directly under the workspace header -- a second header
 * saying almost nothing, costing a row of the surface the user came for. The graph's bar held the
 * view controls, which now live in the canvas's own stack; the timeline's held a caption, which
 * now reads in the caption strip the lens already had at its foot.
 *
 * These assert STRUCTURE, not just that the controls exist somewhere: a build that left the bar
 * in place and merely added copies to the stack would pass a visibility check. */

async function openConsole(page: Page, width = 1600) {
  await page.setViewportSize({ width, height: 950 })
  await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'))
  await stubConsoleApi(page)
}

const stack = '.xc-zoom'

test('the graph lens opens with no header strip of its own', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')
  const lens = page.locator('section[aria-label="Graph lens"]')
  await expect(lens).toBeVisible()
  await expect(lens.locator('> .xc-bar')).toHaveCount(0)

  // the canvas starts directly under the workspace header, within a hairline of it
  const header = (await page.locator('.xc-workspace-header').boundingBox())!
  const host = (await page.locator('.xc-host').boundingBox())!
  expect(host.y - (header.y + header.height)).toBeLessThan(40)
})

test('2D, 3D and snap sit in the canvas stack, below the framing buttons', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')

  const fit = (await page.locator(`${stack} button[aria-label="Fit all"]`).boundingBox())!
  for (const label of ['2D view', '3D view', 'Snap to grid']) {
    const b = (await page.locator(`${stack} button[aria-label="${label}"]`).boundingBox())!
    expect(b.y, `${label} is not below the framing buttons`).toBeGreaterThan(fit.y + fit.height)
    // and inside the same stack box, not floating beside it
    expect(Math.abs(b.x - fit.x)).toBeLessThan(4)
  }
  // exactly one of each in the document -- the old toolbar copies are gone
  for (const label of ['2D view', '3D view', 'Snap to grid']) {
    await expect(page.locator(`button[aria-label="${label}"]`)).toHaveCount(1)
  }
})

test('the moved 2D/3D control still switches the renderer', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')
  const two = page.locator(`${stack} button[aria-label="2D view"]`)
  const three = page.locator(`${stack} button[aria-label="3D view"]`)

  await two.click()
  await expect(two).toHaveAttribute('aria-pressed', 'true')
  // the 2D renderer paints into a <canvas> inside the host; the 3D one mounts its own container
  await expect(page.locator('.xc-host canvas')).toBeVisible()
  await three.click()
  await expect(three).toHaveAttribute('aria-pressed', 'true')
  await expect(two).toHaveAttribute('aria-pressed', 'false')
})

test('the timeline keeps one caption strip, at its foot', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')
  await page.locator('.xc-workspace-header button', { hasText: 'Timeline' }).click()
  const lens = page.locator('section[aria-label="Timeline lens"]')
  await expect(lens).toBeVisible()

  const bars = lens.locator('> .xc-bar')
  await expect(bars).toHaveCount(1)

  // it is below the lane grid, not above it
  const bar = (await bars.boundingBox())!
  const scroll = (await lens.locator('> .xc-scroll').boundingBox())!
  expect(bar.y).toBeGreaterThan(scroll.y + scroll.height - 2)

  // and it still carries the session count and span that the old header strip did
  await expect(bars).toContainText(/\d+ session/)
  await expect(bars).toContainText('→')
})

test('the collapsed rail gives its brand mark room', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')
  await page.locator('.xc-rail-toggle').click()
  await expect(page.locator('.xc-shell[data-collapsed="true"]')).toBeVisible()

  const rail = (await page.locator('.xc-rail-shell').boundingBox())!
  const mark = (await page.locator('.xc-brand-mark').boundingBox())!
  const img = (await page.locator('.xc-brand-mark img').boundingBox())!

  // It is the brand's own brain, cut from the same drawing as the lockup -- not
  // cortex-mark.png, which was a different, circuit-trace emblem.
  const src = await page.locator('.xc-brand-mark img').evaluate((el) => (el as HTMLImageElement).currentSrc)
  expect(src).toContain('cortex-rail-mark.png')

  // The crown is wider than it is tall, so it fills the rail's width rather than sitting in a
  // square box: 44px of the 48px the collapsed rail has, with the mark no taller than a nav row.
  expect(img.width).toBeGreaterThanOrEqual(40)
  expect(img.width).toBeLessThanOrEqual(48)
  expect(img.height, 'the crown must not tower over the nav icons').toBeLessThanOrEqual(24)
  expect(mark.width - img.width, 'the crown has no room inside its frame').toBeGreaterThanOrEqual(2)

  // and the frame sits inside the rail with a gutter either side
  expect(mark.x - rail.x).toBeGreaterThanOrEqual(6)
  expect(rail.x + rail.width - (mark.x + mark.width)).toBeGreaterThanOrEqual(6)

  // solid white at the size it is painted, measured the same way as the hero: the old emblem
  // shipped at 256px and painted at 24px averaged down to a grey blob (alpha p50 85).
  const ink = await page.locator('.xc-brand-mark img').evaluate(async (el) => {
    const im = el as HTMLImageElement
    const w = Math.round(im.getBoundingClientRect().width)
    const h = Math.round(im.getBoundingClientRect().height)
    const c = document.createElement('canvas')
    c.width = w; c.height = h
    const ctx = c.getContext('2d')!
    ctx.drawImage(im, 0, 0, w, h)
    const d = ctx.getImageData(0, 0, w, h).data
    const alphas: number[] = []
    let offWhite = 0
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] === 0) continue
      alphas.push(d[i + 3])
      if (d[i] < 250 || d[i + 1] < 250 || d[i + 2] < 250) offWhite++
    }
    alphas.sort((a, b) => a - b)
    return { n: alphas.length, median: alphas[Math.floor(alphas.length / 2)] ?? 0, offWhite }
  })
  expect(ink.n, 'the mark drew nothing').toBeGreaterThan(150)
  expect(ink.offWhite, 'the mark is not white').toBe(0)
  expect(ink.median, 'the mark is washed out at the size it is painted').toBeGreaterThan(120)
})

test('the sign-in hero states the mark at hero size, from its own derivative', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 950 })
  await stubConsoleApi(page)          // no signed-in hint -> the sign-in screen
  await page.goto('/')

  const logo = page.locator('.xc-auth-story .xc-brand-lockup')
  await expect(logo).toBeVisible()

  const m = await logo.evaluate((el) => {
    const img = el as HTMLImageElement
    const r = img.getBoundingClientRect()
    const c = document.createElement('canvas')
    c.width = Math.round(r.width)
    c.height = Math.round(r.height)
    const ctx = c.getContext('2d')!
    ctx.drawImage(img, 0, 0, c.width, c.height)
    const d = ctx.getImageData(0, 0, c.width, c.height).data
    const alphas: number[] = []
    let offWhite = 0
    for (let i = 0; i < d.length; i += 4) {
      if (d[i + 3] <= 8) continue
      alphas.push(d[i + 3])
      if (d[i] !== 255 || d[i + 1] !== 255 || d[i + 2] !== 255) offWhite += 1
    }
    alphas.sort((a, b) => a - b)
    return { src: img.currentSrc, natural: img.naturalWidth, rendered: Math.round(r.width), offWhite, median: alphas[Math.floor(alphas.length / 2)], ink: alphas.length }
  })

  // its own asset, not the rail's -- which is built for 124px and would thin if enlarged here
  expect(m.src).toContain('cortex-lockup-hero.png')
  expect(m.rendered, 'the hero mark is no longer hero-sized').toBeGreaterThanOrEqual(260)
  expect(m.natural, 'the hero asset is being upscaled').toBeGreaterThanOrEqual(m.rendered)
  // solid white at the size it is painted
  expect(m.ink).toBeGreaterThan(5000)
  expect(m.offWhite).toBe(0)
  expect(m.median).toBeGreaterThan(200)
})

test('the rail names its destinations at the size of the buttons they sit in', async ({ page }) => {
  await openConsole(page)
  await page.goto('/')
  await expect(page.locator('.xc-rail-shell')).toBeVisible()

  const rows = await page.locator('.xc-rail-nav .xc-nav-btn').evaluateAll((els) =>
    els.map((el) => ({
      text: (el.querySelector('.xc-nav-label') as HTMLElement | null)?.textContent ?? '',
      label: parseFloat(getComputedStyle(el.querySelector('.xc-nav-label') as Element).fontSize),
      button: parseFloat(getComputedStyle(el).fontSize),
      height: el.getBoundingClientRect().height,
    })),
  )
  expect(rows.length).toBeGreaterThanOrEqual(5)

  const SCALE = [10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 25, 32, 42]
  for (const r of rows) {
    // The rail's buttons were made 19px and its words stayed at 14px, because `.xc-nav-label`
    // carries its own size. 19 is not on the Industry scale either, so nothing was reading at
    // a legal size OR at the size the button was built for.
    expect(SCALE, `"${r.text}" renders at ${r.label}px, which is off the Industry scale`).toContain(r.label)
    expect(SCALE, `the button behind "${r.text}" is set to ${r.button}px, off the scale`).toContain(r.button)
    expect(r.label, `"${r.text}" is small for the row it sits in`).toBeGreaterThanOrEqual(16)
    expect(r.button, 'the button and its label disagree about size').toBe(r.label)
    // and the row is still a row, not a box with a word lost in it
    expect(r.height / r.label).toBeLessThan(3.2)
  }
})
