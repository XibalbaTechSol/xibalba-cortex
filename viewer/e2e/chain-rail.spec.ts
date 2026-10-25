/* The chain rail folds to a handle on the workspace's bottom-right margin, uncovering the strip
 * of lens it floats over. The fold persists, because it is a setting rather than component
 * state -- which is also why the reload case is worth asserting. */
import { test, expect, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

async function openWorkspace(page: Page) {
  await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'))
  await stubConsoleApi(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.xc')).toBeVisible({ timeout: 20000 })
  await expect(page.locator('.xc-chain, .xc-chain-handle').first()).toBeVisible({ timeout: 20000 })
}

test('the chain rail folds to the bottom-right margin and comes back', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await openWorkspace(page)

  const rail = page.locator('.xc-chain')
  const handle = page.locator('.xc-chain-handle')
  await expect(rail).toBeVisible()
  await expect(handle).toHaveCount(0)
  const railBox = (await rail.boundingBox())!

  await page.locator('.xc-chain-fold').click()
  await expect(rail).toHaveCount(0)
  await expect(handle).toBeVisible()

  // it is a handle, not the rail in disguise: far smaller, and against the bottom-right margin
  const h = (await handle.boundingBox())!
  expect(h.height, 'the handle is no smaller than the rail it replaced').toBeLessThan(railBox.height / 2)
  const win = (await page.locator('.xc-workspace').boundingBox())!
  expect(Math.round(win.x + win.width - (h.x + h.width)), 'handle is not on the right margin').toBeLessThan(40)
  expect(Math.round(win.y + win.height - (h.y + h.height)), 'handle is not on the bottom margin').toBeLessThan(40)

  await handle.click()
  await expect(rail).toBeVisible()
  await expect(handle).toHaveCount(0)
})

test('the fold survives a reload', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await openWorkspace(page)
  await page.locator('.xc-chain-fold').click()
  await expect(page.locator('.xc-chain-handle')).toBeVisible()

  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.locator('.xc-chain-handle')).toBeVisible({ timeout: 20000 })
  await expect(page.locator('.xc-chain')).toHaveCount(0)
})
