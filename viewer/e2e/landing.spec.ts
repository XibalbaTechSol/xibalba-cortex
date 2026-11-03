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
    /* One floor at every width: the mark is capped at 280px everywhere now, because that is
       the largest size its 560px raster is sharp at. The old desktop floor of 380 encoded the
       previous 420px cap. */
    expect(box.width).toBeGreaterThanOrEqual(220)
    /* The mark must carry at least 2 device pixels per CSS pixel, or it is visibly soft on any
       HiDPI screen -- the defect this cap was introduced to fix. Asserted as a ratio rather than
       a fixed size so it keeps holding if either the asset or the cap changes. */
    const density = await mark.evaluate((el) => {
      const img = el as HTMLImageElement
      return img.naturalWidth / img.getBoundingClientRect().width
    })
    expect(density).toBeGreaterThanOrEqual(2)
    await expect(page.locator('.xc-landing-top .xc-brand-mark')).toBeVisible()
    await page.getByRole('link', { name: 'How it runs', exact: true }).click()
    await expect(page.locator('#how')).toBeInViewport()
    await expect(page.locator('.xc-landing')).not.toContainText(/\bMIT\b|\blicen[cs]e\b/i)
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

for (const width of [320, 390, 1600]) {
  test(`plans, comparison, documentation and footer remain readable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 })
    await page.goto('/')
    await expect(page.getByRole('article', { name: 'Free subscription' })).toContainText('$0')
    await expect(page.getByRole('article', { name: 'Pro subscription' })).toContainText('$29')
    await expect(page.getByRole('article', { name: 'Team subscription' })).toContainText('$149')
    await expect(page.locator('#compare')).toContainText('Supermemory')
    await expect(page.locator('#compare a[href="https://supermemory.ai/product/"]')).toHaveCount(1)
    await expect(page.locator('#docs a')).toHaveCount(3)
    await page.getByRole('link', { name: 'Request Pro access' }).click()
    await expect(page.getByRole('form', { name: 'Contact Cortex' })).toBeInViewport()
    await expect(page.getByLabel('Interested in')).toHaveValue('Pro plan')
    await expect(page.getByRole('navigation', { name: 'Company links' })).toContainText('Contact')
    expect(await page.locator('.xc-landing').evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1)
  })
}

test('the contact form reports accepted delivery and clears the submitted fields', async ({ page }) => {
  let sent: Record<string, string> | null = null
  await page.route('**/api/contact', async route => {
    sent = route.request().postDataJSON()
    await route.fulfill({ status: 202, json: { message: 'Your inquiry has been sent.' } })
  })
  await page.goto('/#contact')
  await page.getByLabel('Name', { exact: true }).fill('Test founder')
  await page.getByLabel('Email', { exact: true }).fill('founder@example.com')
  await page.getByLabel('Message', { exact: true }).fill('Please help me connect a local agent to a managed workspace.')
  await page.getByRole('button', { name: 'Send inquiry' }).click()
  await expect(page.getByRole('status')).toContainText('Your inquiry has been sent.')
  expect(sent?.['email']).toBe('founder@example.com')
  await expect(page.getByLabel('Message', { exact: true })).toHaveValue('')
})

test('failed contact delivery preserves the message and offers direct email', async ({ page }) => {
  await page.route('**/api/contact', route => route.fulfill({ status: 503, json: { error: 'Your message could not be delivered. Please email us directly.' } }))
  await page.goto('/#contact')
  await page.getByLabel('Name', { exact: true }).fill('Test founder')
  await page.getByLabel('Email', { exact: true }).fill('founder@example.com')
  const message = 'Please help me connect a local agent to a managed workspace.'
  await page.getByLabel('Message', { exact: true }).fill(message)
  await page.getByRole('button', { name: 'Send inquiry' }).click()
  await expect(page.getByRole('alert')).toContainText('could not be delivered')
  await expect(page.getByLabel('Message', { exact: true })).toHaveValue(message)
  await expect(page.locator('#contact a[href^="mailto:"]')).toBeVisible()
})
