/* Coincident marks must each stay clickable.
 *
 * The fixture's three memories are five minutes apart on an axis spanning nearly a month, so they
 * land within a pixel of each other. Before marks were stacked into rows, the topmost took every
 * click and Playwright reported `<button class="xc-mark"> intercepts pointer events` for the rest. */
import { test, expect, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

async function openTimeline(page: Page) {
  await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'))
  await stubConsoleApi(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.xc')).toBeVisible({ timeout: 20000 })
  await page.locator('.xc-ranges button', { hasText: /timeline/i }).first().click()
  await expect(page.locator('.xc-mark').first()).toBeVisible({ timeout: 20000 })
}

test('every mark on a lane can be selected, however close together they are', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await openTimeline(page)

  /* Selecting opens the detail dock, which narrows the lens by 380px and re-lays out every mark.
     One click up front settles that, so the loop below measures the steady state rather than
     racing a reflow it caused itself. */
  await page.locator('.xc-mark').last().click()
  await expect(page.locator('.xc-inspector')).toBeVisible({ timeout: 10000 })
  await page.waitForTimeout(600)

  const labels = await page.locator('.xc-mark').evaluateAll((els) =>
    els.map((e) => e.getAttribute('aria-label') ?? ''))
  expect(labels.length, 'no marks rendered -- this would pass vacuously').toBeGreaterThan(2)

  for (let i = 0; i < labels.length; i++) {
    // re-queried each time: a click re-renders the lane, so a held handle goes stale
    await page.locator('.xc-mark').nth(i).click({ timeout: 5000 })
    await page.waitForTimeout(250)
    const selected = page.locator('.xc-mark[data-selected="true"]')
    await expect(selected, `clicking mark ${i} (${labels[i]}) selected nothing`).toHaveCount(1)
    await expect(selected, `mark ${i} did not become the selection`).toHaveAttribute('aria-label', labels[i])
  }
})

test('marks that coincide are given different rows', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await openTimeline(page)
  const rows = await page.evaluate(() =>
    [...document.querySelectorAll('.xc-lane-track .xc-mark')].map((m) => ({
      x: Math.round(m.getBoundingClientRect().left),
      y: Math.round(m.getBoundingClientRect().top),
    })))
  // any two marks within a mark's width of each other horizontally must differ vertically
  for (let i = 0; i < rows.length; i++) {
    for (let j = i + 1; j < rows.length; j++) {
      if (Math.abs(rows[i].x - rows[j].x) < 10) {
        expect(Math.abs(rows[i].y - rows[j].y), `marks at x=${rows[i].x} share a row`).toBeGreaterThan(4)
      }
    }
  }
})

test('clicking empty timeline space inspects the nearest visible event', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await openTimeline(page)
  const axis = page.getByRole('slider', { name: 'Timeline time' })
  await axis.click({ position: { x: 50, y: 12 } })
  await expect(page.locator('.xc-mark[data-selected="true"]')).toHaveCount(1)
  await expect(page.locator('.xc-inspector')).toBeVisible()
  await expect(page.locator('.xc-tl-cursor')).toBeVisible()
})

test('dragging previews a stable time range, applies it on release, and resets', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await openTimeline(page)
  const axis = page.getByRole('slider', { name: 'Timeline time' })
  for (const [start, end] of [[0.2, 0.7], [0.8, 0.25]]) {
    const from = Number(await axis.getAttribute('aria-valuemin'))
    const to = Number(await axis.getAttribute('aria-valuemax'))
    const box = (await axis.boundingBox())!
    await page.mouse.move(box.x + box.width * start, box.y + 14)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width * end, box.y + 14, { steps: 8 })
    await expect(page.locator('.xc-tl-brush')).toBeVisible()
    expect(Number(await axis.getAttribute('aria-valuemin'))).toBe(from)
    await page.mouse.up()
    await expect(page.locator('.xc-tl-brush')).toHaveCount(0)
    const expectedFrom = from + Math.min(start, end) * (to - from)
    const expectedTo = from + Math.max(start, end) * (to - from)
    // Browser pointer positions round to device pixels.
    const tolerance = (to - from) / box.width * 2
    expect(Math.abs(Number(await axis.getAttribute('aria-valuemin')) - expectedFrom)).toBeLessThan(tolerance)
    expect(Math.abs(Number(await axis.getAttribute('aria-valuemax')) - expectedTo)).toBeLessThan(tolerance)
    await page.getByRole('button', { name: 'All time', exact: true }).click()
    await expect(axis).toHaveAttribute('aria-valuemin', String(from))
    await expect(axis).toHaveAttribute('aria-valuemax', String(to))
  }
})

test('timeline keyboard scrubbing and canceled gestures preserve event controls', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await openTimeline(page)
  const axis = page.getByRole('slider', { name: 'Timeline time' })
  await axis.focus()
  const before = Number(await axis.getAttribute('aria-valuenow'))
  await axis.press('ArrowRight')
  expect(Number(await axis.getAttribute('aria-valuenow'))).toBeGreaterThan(before)
  await expect(page.locator('.xc-mark[data-selected="true"]')).toHaveCount(1)
  await axis.press('End')
  expect(await axis.getAttribute('aria-valuenow')).toBe(await axis.getAttribute('aria-valuemax'))
  const box = (await axis.boundingBox())!
  await page.mouse.move(box.x + box.width * .3, box.y + 12)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * .7, box.y + 12, { steps: 6 })
  await expect(page.locator('.xc-tl-brush')).toBeVisible()
  await axis.dispatchEvent('pointercancel')
  await page.mouse.up()
  await expect(page.locator('.xc-tl-brush')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'All time', exact: true })).toHaveCount(0)
  await page.locator('.xc-mark').first().click()
  await expect(page.locator('.xc-mark').first()).toHaveAttribute('data-selected', 'true')
})
