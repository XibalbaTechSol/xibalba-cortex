// Phone layout (390 x 844). Below 760px the same components are arranged differently: the lens
// fills the screen, a tab bar switches Graph / Timeline / Recall / Review, "More" lists the tools,
// Filters and Time are bottom sheets, the inspector rises as a sheet, and a tool opens as a
// full-screen drawer. These tests check that arrangement, and that nothing scrolls sideways.
import { expect, test, type Page } from '@playwright/test'
import { openConsole, pinMemory, watchErrors } from './helpers'

/** True when the page is wider than the viewport: the one layout bug a phone cannot forgive. */
const overflowsSideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)

test.describe('phone', () => {
  test('boots with the tab bar and no sideways scroll on either lens', async ({ page }) => {
    const errors = watchErrors(page)
    await openConsole(page, { primary: true })
    const tabs = page.getByRole('navigation', { name: /tab|navigation/i }).last()
    await expect(page.getByRole('button', { name: 'Graph' }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Timeline' }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'More' })).toBeVisible()
    expect(await overflowsSideways(page)).toBe(false)
    await page.getByRole('button', { name: 'Timeline' }).first().click()
    await expect(page).toHaveURL(/#timeline/)
    expect(await overflowsSideways(page)).toBe(false)
    void tabs
    expect(errors).toEqual([])
  })

  test('Filters and Time are bottom sheets that show how many switches are off their defaults', async ({ page }) => {
    await openConsole(page, { primary: true })
    await page.getByRole('button', { name: /^Filters/ }).click()
    const sheet = page.getByRole('dialog')
    await expect(sheet).toBeVisible()
    await sheet.getByRole('checkbox', { name: /^Sessions/ }).uncheck()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: /^Filters/ })).toContainText(/1/)
    await page.goto('/#timeline')
    await page.getByRole('button', { name: /^Time\b(?!line)/ }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
  })

  test('Recall: the query field keeps its width and the modes sit beneath it', async ({ page }) => {
    await openConsole(page, { primary: true })
    await page.getByRole('button', { name: 'Recall' }).first().click()
    const dialog = page.getByRole('dialog')
    const query = dialog.getByLabel('Recall query')
    await expect(query).toBeVisible()
    expect((await query.boundingBox())!.width).toBeGreaterThan(150)
    await query.fill('relay submissions')
    await page.keyboard.press('Enter')
    await expect(dialog.locator('li.xc-result').first()).toBeVisible()
    expect(await overflowsSideways(page)).toBe(false)
  })

  test('every tool opens as a full-screen drawer without sideways scroll', async ({ page }) => {
    for (const hash of ['memories', 'entities', 'sessions', 'operations', 'agents', 'settings']) {
      await openConsole(page, { hash })
      const drawer = page.getByRole('dialog')
      await expect(drawer).toBeVisible()
      const box = (await drawer.boundingBox())!
      expect(box.width).toBeGreaterThanOrEqual(388) // full width
      expect(await overflowsSideways(page)).toBe(false)
      await page.keyboard.press('Escape')
      await expect(drawer).toBeHidden()
    }
  })

  test('More lists the tools, and the inspector rises as a sheet when something is selected', async ({ page }) => {
    await openConsole(page)
    await page.getByRole('button', { name: 'More' }).click()
    const more = page.getByRole('dialog')
    await expect(more).toBeVisible()
    for (const name of ['Memories', 'Entities', 'Sessions', 'Operations', 'Agents', 'Settings', 'Integrity']) {
      await expect(more.getByRole('button', { name: new RegExp(name) }).first()).toBeVisible()
    }
    await page.keyboard.press('Escape')
    await pinMemory(page, 'relay retries', 'three times')
    await expect(page.getByRole('tab', { name: 'Provenance' })).toBeVisible() // the inspector is a bottom sheet, not a dialog
    expect(await overflowsSideways(page)).toBe(false)
  })

  test('the sign-in screen fits a phone', async ({ page }) => {
    await openConsole(page, { signedOut: true })
    await expect(page.getByLabel('Email')).toBeVisible()
    expect(await overflowsSideways(page)).toBe(false)
  })
})
