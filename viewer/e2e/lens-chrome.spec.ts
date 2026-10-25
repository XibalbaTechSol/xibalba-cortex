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

  // the frame was 44px around a 40px emblem: 2px of air, which read as a crop
  expect(mark.width).toBeLessThanOrEqual(38)
  expect(img.width).toBeLessThanOrEqual(26)
  expect((mark.width - img.width) / 2, 'the emblem has no room inside its frame').toBeGreaterThanOrEqual(4)

  // and the frame sits inside the rail with a gutter either side
  expect(mark.x - rail.x).toBeGreaterThanOrEqual(8)
  expect(rail.x + rail.width - (mark.x + mark.width)).toBeGreaterThanOrEqual(8)
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
