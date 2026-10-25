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
