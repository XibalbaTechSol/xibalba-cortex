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
    expect(await mark.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThanOrEqual(420)
    const box = (await mark.boundingBox())!
    expect(box.width).toBeGreaterThanOrEqual(width < 600 ? 220 : 380)
    await expect(page.locator('.xc-landing-top .xc-brand-mark')).toBeVisible()
    const nav = page.getByRole('navigation', { name: 'Sections' })
    await nav.getByRole('link', { name: 'How it runs', exact: true }).click()
    await expect(page.locator('#how')).toBeInViewport()
    // The page deliberately says nothing about licensing. \b matters: unanchored, "MIT"
    // also matches the "mit" inside "submitted" in the contact form's status line.
    await expect(page.locator('.xc-landing')).not.toContainText(/\bMIT\b|licen[cs]e/i)
    expect(await page.locator('.xc-landing').evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1)
    // The commercial sections: each nav anchor has to actually land on its section.
    for (const [label, id] of [['Compare', '#compare'], ['Pricing', '#pricing'], ['Docs', '#docs'], ['Contact', '#contact']] as const) {
      await nav.getByRole('link', { name: label, exact: true }).click()
      await expect(page.locator(id)).toBeInViewport()
    }

    // Exactly three tiers, each with a price and a call to action.
    const tiers = page.locator('.xc-landing-tier')
    await expect(tiers).toHaveCount(3)
    for (const name of ['Local', 'Pilot', 'Enterprise']) {
      const tier = tiers.filter({ has: page.getByRole('heading', { name, exact: true }) })
      await expect(tier).toHaveCount(1)
      await expect(tier.locator('.xc-landing-tier-price b')).not.toBeEmpty()
      await expect(tier.locator('.xc-landing-tier-cta')).toBeVisible()
    }

    // The comparison names both products and scrolls inside its own frame rather than
    // widening the page. Guard against a vacuous pass: the rows have to exist.
    const table = page.locator('.xc-landing-table')
    await expect(table.locator('tbody tr').first()).toBeVisible()
    expect(await table.locator('tbody tr').count()).toBeGreaterThan(4)
    await expect(table.locator('thead')).toContainText('Supermemory')
    const wrapOverflow = await page.locator('.xc-landing-tablewrap')
      .evaluate((el) => el.scrollWidth - el.clientWidth)
    if (width < 760) expect(wrapOverflow).toBeGreaterThan(0)

    // Documentation links are real absolute URLs, not placeholders.
    const docs = page.locator('.xc-landing-doc')
    expect(await docs.count()).toBeGreaterThanOrEqual(6)
    for (const href of await docs.evaluateAll((els) => els.map((e) => e.getAttribute('href')))) {
      expect(href).toMatch(/^https:\/\/github\.com\/XibalbaTechSol\/xibalba-cortex\//)
    }

    // The footer carries its columns, and every link in it resolves somewhere.
    await expect(page.locator('.xc-landing-foot-col')).toHaveCount(4)
    for (const href of await page.locator('.xc-landing-foot a').evaluateAll((els) => els.map((e) => e.getAttribute('href')))) {
      expect(href).toMatch(/^(https:\/\/|mailto:|#)/)
    }

    // Still no horizontal overflow on the page itself, now that a table is on it.
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

test('the contact form is labelled and refuses an invalid address', async ({ page }) => {
  await stubConsoleApi(page)
  await page.goto('/')
  await page.getByRole('navigation', { name: 'Sections' })
    .getByRole('link', { name: 'Contact', exact: true }).click()

  const form = page.locator('.xc-landing-form')
  const name = form.locator('#xc-contact-name')
  const email = form.locator('#xc-contact-email')
  const message = form.locator('#xc-contact-message')

  for (const field of [name, email, message]) await expect(field).toHaveAttribute('required', '')
  await expect(email).toHaveAttribute('type', 'email')

  // Accessible names come from real <label>s, not placeholders.
  await expect(form.getByLabel('Name', { exact: true })).toBeVisible()
  await expect(form.getByLabel('Email', { exact: true })).toBeVisible()
  await expect(form.getByLabel(/^What are you trying to build/)).toBeVisible()
  await expect(form.getByLabel(/^Interest/)).toBeVisible()

  // Prove the validity check can fail before trusting that it passes.
  await name.fill('Dana Okonkwo')
  await message.fill('Auditing an agent that touches regulated records.')
  await email.fill('not-an-address')
  expect(await email.evaluate((el) => (el as HTMLInputElement).checkValidity())).toBe(false)
  expect(await form.evaluate((el) => (el as HTMLFormElement).checkValidity())).toBe(false)

  await email.fill('dana@example.org')
  expect(await email.evaluate((el) => (el as HTMLInputElement).checkValidity())).toBe(true)
  expect(await form.evaluate((el) => (el as HTMLFormElement).checkValidity())).toBe(true)

  // The status line is a live region, so the outcome is announced rather than only shown.
  await expect(form.getByRole('status')).toHaveAttribute('aria-live', 'polite')
  await expect(form.getByRole('status')).toContainText('nothing is submitted to a server')
})

// The composed draft itself is covered by src/console/contact.test.ts, which can assert the
// encoding directly rather than chasing an external-protocol navigation through the browser.
