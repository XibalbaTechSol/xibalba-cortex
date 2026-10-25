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

test('the chain rail can be dragged off its dock and dropped back onto it', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await openWorkspace(page)

  const rail = page.locator('.xc-chain')
  await expect(rail).toHaveAttribute('data-floating', 'false')
  const docked = (await rail.boundingBox())!

  const grip = page.locator('.xc-chain-grip')
  const g = (await grip.boundingBox())!
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2)
  await page.mouse.down()
  await page.mouse.move(g.x + 40, g.y - 320, { steps: 12 })
  await page.mouse.up()

  await expect(rail, 'the rail did not come off its dock').toHaveAttribute('data-floating', 'true')
  const floated = (await rail.boundingBox())!
  expect(floated.y, 'the rail did not actually move up').toBeLessThan(docked.y - 200)

  // dropping it near the bottom edge docks it again -- the only way back, so it has to work
  const g2 = (await grip.boundingBox())!
  const ws = (await page.locator('.xc-workspace').boundingBox())!
  await page.mouse.move(g2.x + g2.width / 2, g2.y + g2.height / 2)
  await page.mouse.down()
  await page.mouse.move(g2.x, ws.y + ws.height - 20, { steps: 12 })
  await page.mouse.up()

  await expect(rail, 'dropping at the bottom edge did not re-dock the rail').toHaveAttribute('data-floating', 'false')
  const redocked = (await rail.boundingBox())!
  expect(Math.abs(redocked.y - docked.y), 'the re-docked rail is not back where it started').toBeLessThan(4)
})

test('a stored position that is off the workspace is pulled back on screen', async ({ page }) => {
  /* The drop clamp only sees the workspace as it was when the pointer was released, and the
     position persists -- so a smaller window later, or a hand-edited value, could strand the rail
     where it can never be grabbed again. Seeding the setting directly is the only way to reach
     that state: a real drag cannot, because the browser clamps the pointer to the viewport, which
     is what made an earlier version of this test pass against a deliberately broken clamp. */
  await page.addInitScript(() => {
    sessionStorage.setItem('xibalba-cortex.signed-in', '1')
    localStorage.setItem('xibalba-cortex.console-settings', JSON.stringify({ chainPos: { x: -4000, y: -3000 } }))
  })
  await stubConsoleApi(page)
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const rail = page.locator('.xc-chain')
  await expect(rail).toHaveAttribute('data-floating', 'true', { timeout: 20000 })

  const ws = (await page.locator('.xc-workspace').boundingBox())!
  const r = (await rail.boundingBox())!
  expect(r.x, 'the rail sits off the left edge, where it could never be grabbed').toBeGreaterThanOrEqual(ws.x - 1)
  expect(r.y, 'the rail sits above the workspace').toBeGreaterThanOrEqual(ws.y - 1)
  // and the grip is reachable, which is the thing that actually matters
  await expect(page.locator('.xc-chain-grip')).toBeVisible()
})

test('a floating position survives a reload and stays on screen', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await openWorkspace(page)
  const grip = page.locator('.xc-chain-grip')
  const g = (await grip.boundingBox())!
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2)
  await page.mouse.down()
  await page.mouse.move(g.x + 260, g.y - 300, { steps: 12 })
  await page.mouse.up()

  await page.reload({ waitUntil: 'domcontentloaded' })
  const rail = page.locator('.xc-chain')
  await expect(rail).toHaveAttribute('data-floating', 'true', { timeout: 20000 })
  const r = (await rail.boundingBox())!
  const ws = (await page.locator('.xc-workspace').boundingBox())!
  expect(r.y, 'the reloaded rail is back at its dock, so the position did not persist').toBeLessThan(ws.y + ws.height - 200)
})
