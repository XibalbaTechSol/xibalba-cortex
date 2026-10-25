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
