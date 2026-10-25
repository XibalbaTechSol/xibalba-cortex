import { expect, test } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

for (const width of [320, 390, 1280, 1600]) {
  test(`public page presents the hero and reachable sections at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 })
    await stubConsoleApi(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Your agents’ memory.Provably yours.')
    const mark = page.locator('.xc-landing-mark')
    await expect(mark).toBeVisible()
    await expect.poll(() => mark.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThanOrEqual(420)
    const box = (await mark.boundingBox())!
    expect(box.width).toBeGreaterThanOrEqual(width < 600 ? 220 : 380)
    await expect(page.locator('.xc-landing-top .xc-brand-mark')).toBeVisible()
    await page.getByRole('link', { name: 'How it runs', exact: true }).click()
    await expect(page.locator('#how')).toBeInViewport()
    await expect(page.locator('.xc-landing')).not.toContainText(/MIT|licen[cs]e/i)
    expect(await page.locator('.xc-landing').evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1)
    await page.getByRole('button', { name: 'Open the console' }).click()
    await expect(page).toHaveURL(/#signin$/)
    await expect(page.locator('.xc-auth-formwrap')).toBeVisible()
    await page.goBack()
    await expect(page.locator('.xc-landing')).toBeVisible()
  })
}

test('an expired session goes directly to sign-in with its notice', async ({ page }) => {
  await stubConsoleApi(page)
  await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.auth-notice', 'Session expired. Sign in again.'))
  await page.goto('/#memories')
  await expect(page.locator('.xc-auth-formwrap')).toBeVisible()
  await expect(page.getByText('Session expired. Sign in again.', { exact: true })).toBeVisible()
  await expect(page.locator('.xc-landing')).toHaveCount(0)
})
