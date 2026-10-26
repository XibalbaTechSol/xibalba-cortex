import { expect, test } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

for (const width of [1600, 1280, 1100]) {
  test(`collapsed navigation preserves the complete logo at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'))
    await stubConsoleApi(page)
    await page.goto('/')
    if (width === 1600) await page.locator('.xc-rail-toggle').click()
    const mark = page.locator('.xc-rail-head .xc-brand-mark img')
    await expect(mark).toBeVisible()
    await expect.poll(() => mark.evaluate((el) => (el as HTMLImageElement).naturalHeight)).toBeGreaterThan(0)
    const shape = await mark.evaluate((el) => {
      const im = el as HTMLImageElement
      const box = im.getBoundingClientRect()
      const frame = im.parentElement!.getBoundingClientRect()
      const rail = im.closest('.xc-rail-shell')!.getBoundingClientRect()
      return {
        naturalRatio: im.naturalHeight / im.naturalWidth,
        renderedRatio: box.height / box.width,
        spill: Math.max(frame.left - box.left, box.right - frame.right, frame.top - box.top, box.bottom - frame.bottom,
          rail.left - box.left, box.right - rail.right, rail.top - box.top, box.bottom - rail.bottom),
      }
    })
    // The discarded crown was 88x33: it removed over half of the complete drawing.
    expect(shape.naturalRatio).toBeGreaterThan(0.8)
    expect(shape.naturalRatio).toBeLessThan(1.1)
    expect(shape.renderedRatio).toBeCloseTo(shape.naturalRatio, 2)
    expect(shape.spill).toBeLessThanOrEqual(1)
  })
}
