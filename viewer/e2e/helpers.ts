// Shared helpers for the console's browser tests.
//
// The dev proxy answers every API call with an operator bearer token, so the console boots signed
// in. Three pieces of browser state steer what it shows, and the helpers set them before the page
// loads (an init script runs before any app code):
//   sessionStorage 'xibalba-cortex.signed-in'         "1" skips the sign-in screen
//   sessionStorage 'xibalba-cortex.selected-primary'  "1" picks the read-only Primary profile scope
//                                                     (otherwise the first writable agent pair)
//   localStorage   'xibalba-cortex.console-settings'  layout preferences (settings.ts)
import { expect, type Locator, type Page } from '@playwright/test'

export interface OpenOptions {
  /** route fragment, e.g. 'graph', 'timeline', 'settings', 'timeline/sessions' */
  hash?: string
  /** read-only Primary profile instead of the writable agent workspace */
  primary?: boolean
  /** console-settings overrides, e.g. { shell: 'top', railCollapsed: true } */
  settings?: Record<string, unknown>
  /** show the sign-in screen instead of the workspace */
  signedOut?: boolean
}

export async function openConsole(page: Page, opts: OpenOptions = {}): Promise<void> {
  await page.addInitScript(({ signedOut, primary, settings }) => {
    try {
      if (signedOut) sessionStorage.removeItem('xibalba-cortex.signed-in')
      else sessionStorage.setItem('xibalba-cortex.signed-in', '1')
      if (primary) sessionStorage.setItem('xibalba-cortex.selected-primary', '1')
      if (settings) localStorage.setItem('xibalba-cortex.console-settings', JSON.stringify({ shell: 'rail', railCollapsed: false, ...settings }))
    } catch { /* storage can be unavailable; the console falls back to its defaults */ }
  }, { signedOut: !!opts.signedOut, primary: !!opts.primary, settings: opts.settings ?? null })
  await page.goto(`/#${opts.hash ?? 'graph'}`)
  if (opts.signedOut) {
    await expect(page.getByRole('button', { name: /sign in/i }).first()).toBeVisible()
  } else {
    // the shell is up once the connection chip says so; a phone has no chip (its chrome is a tab bar)
    const chip = page.locator('.xc-conn, .xc-conn--button').first()
    const more = page.getByRole('button', { name: 'More' })
    await expect(chip.or(more).first()).toBeVisible()
    if (await chip.count()) await expect(chip).toContainText(/connected/i)
    // wait for the first data load to finish so a test never races the loading state
    await expect(page.getByText('Connecting…')).toHaveCount(0)
  }
}

/** The 3D canvas, once its layout has settled and the camera has framed the cloud. */
export async function settled3d(page: Page): Promise<Locator> {
  const canvas = page.locator('canvas[data-node-count]')
  await expect(page.locator('canvas[data-settled="true"]')).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(1200) // the framing animation runs a moment after the layout stops
  return canvas
}

/** How many pixels of a canvas differ from its most common colour: a blank canvas has none. */
export async function paintedPixels(page: Page, selector: string): Promise<number> {
  return page.evaluate(async (sel) => {
    const canvas = document.querySelector<HTMLCanvasElement>(sel)
    if (!canvas || canvas.width < 50 || canvas.height < 50) return 0
    // preserveDrawingBuffer is on, so a WebGL canvas can be drawn onto a 2D one and read back
    const bitmap = await createImageBitmap(canvas)
    const sampler = new OffscreenCanvas(bitmap.width, bitmap.height)
    const ctx = sampler.getContext('2d')
    if (!ctx) return 0
    ctx.drawImage(bitmap, 0, 0)
    const { data } = ctx.getImageData(0, 0, sampler.width, sampler.height)
    const counts = new Map<number, number>()
    for (let i = 0; i < data.length; i += 16) {
      const key = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2]
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    let total = 0
    let top = 0
    for (const n of counts.values()) { total += n; if (n > top) top = n }
    return total - top
  }, selector)
}

/** Recall a memory by words and pin it to the graph, which selects it in the inspector. */
export async function pinMemory(page: Page, query: string, pick?: string | RegExp): Promise<void> {
  await page.keyboard.press('Control+k')
  const dialog = page.getByRole('dialog', { name: 'Recall' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Lexical' }).click()
  await dialog.getByLabel('Recall query').fill(query)
  await page.keyboard.press('Enter')
  const rows = pick ? dialog.locator('li.xc-result', { hasText: pick }) : dialog.locator('li.xc-result')
  await rows.first().getByRole('button', { name: 'Pin to graph' }).click()
  await expect(dialog).toBeHidden()
}

/** Console errors and uncaught exceptions, collected for the whole test. */
export function watchErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const text = m.text()
    // Expected and benign: a bearer-token session has no CSRF cookie to protect, so /api/auth/csrf
    // answers 400 (README, "Cookie sessions need a CSRF header"); and a refused request logs itself.
    if (/auth\/csrf/.test(text) || /Failed to load resource/.test(text)) return
    errors.push(`console.error: ${text}`)
  })
  return errors
}
