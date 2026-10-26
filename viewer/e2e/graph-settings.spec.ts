/* The graph's shape and backdrop are settings, so the thing worth testing is not that the
 * controls exist but that changing one changes what is drawn. The engine publishes its active
 * choices on the canvas element; these assert the published value tracks the stored setting.
 *
 * There is deliberately no assertion on how large a node is drawn. Two were tried and both were
 * vacuous: one screenshotted `.xc-canvas-win` and was really measuring the accent fill of the
 * `Snap to grid` button, reporting the same 110px for a seven-node graph and a one-node graph;
 * the second measured the canvas correctly but still could not fail, because `half()` caps at
 * `MAX_HALF` and the camera refits afterwards, so apparent node size is self-normalising. A
 * check that cannot fail is worse than no check, so it is not here.
 */
import { test, expect, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

async function openGraph(page: Page, settings?: Record<string, unknown>) {
  await page.addInitScript((s) => {
    sessionStorage.setItem('xibalba-cortex.signed-in', '1')
    if (s) localStorage.setItem('xibalba-cortex.console-settings', JSON.stringify(s))
  }, settings ?? null)
  await stubConsoleApi(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.xc')).toBeVisible({ timeout: 20000 })
  const canvas = page.locator('.xc-canvas-win canvas')
  await expect(canvas).toBeVisible({ timeout: 20000 })
  // the engine fits the camera once the layout settles; the published dataset is written at startup
  await expect(canvas).toHaveAttribute('data-node-count', /[1-9]/, { timeout: 20000 })
  return canvas
}

test('the node shape setting reaches the lens', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const canvas = await openGraph(page)
  await expect(canvas).toHaveAttribute('data-shape', 'box')

  await page.goto('about:blank')
  const other = await openGraph(page, { nodeShape: 'diamond' })
  await expect(other).toHaveAttribute('data-shape', 'diamond')
})

test('the canvas setting reaches the lens', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const canvas = await openGraph(page)
  await expect(canvas).toHaveAttribute('data-canvas', 'lattice')

  await page.goto('about:blank')
  const other = await openGraph(page, { graphCanvas: 'plain' })
  await expect(other).toHaveAttribute('data-canvas', 'plain')
})

test('an unknown stored shape falls back rather than rendering nothing', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const canvas = await openGraph(page, { nodeShape: 'sphere', graphCanvas: 'hexes' })
  await expect(canvas).toHaveAttribute('data-shape', 'box')
  await expect(canvas).toHaveAttribute('data-canvas', 'lattice')
})


test('metadata face key is available for 3D cubes and clears when switching to 2D', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 950 })
  const crashes: string[] = []
  page.on('pageerror', (error) => crashes.push(error.message))
  await openGraph(page)
  await page.getByRole('button', { name: 'Legend', exact: true }).click()
  await expect(page.locator('.xc-face-legend')).toContainText('observed time')
  await expect(page.locator('.xc-face-legend')).toContainText('contradiction (red)')
  await page.getByRole('button', { name: '2D view', exact: true }).click()
  await expect(page.locator('.xc-face-legend')).toHaveCount(0)
  await page.getByRole('button', { name: '3D view', exact: true }).click()
  await expect(page.locator('.xc-face-legend')).toBeVisible()
  // Changing the lens and unmounting it exercise disposal of every face material.
  await page.locator('.xc-workspace-header button', { hasText: 'Timeline' }).click()
  await expect(page.locator('section[aria-label="Timeline lens"]')).toBeVisible()
  expect(crashes).toEqual([])
})
