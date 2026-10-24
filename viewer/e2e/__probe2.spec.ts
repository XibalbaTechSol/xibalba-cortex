import { test, expect, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'
test('probe overlay findings', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 })
  await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'))
  await stubConsoleApi(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.xc')).toBeVisible({ timeout: 20000 })
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: /^integrity\b/i }).first().click()
  await page.waitForTimeout(900)
  const out = await page.evaluate(() => {
    const r: any = { asides: [], pair: null }
    for (const el of document.querySelectorAll('aside.xc-win')) {
      const chain: any[] = []
      let p = el.parentElement
      while (p) {
        const cs = getComputedStyle(p)
        if (/hidden|clip|auto|scroll/.test(cs.overflow + cs.overflowX + cs.overflowY))
          chain.push({ sel: p.tagName + '.' + p.className, ox: cs.overflowX, oy: cs.overflowY,
                       rect: p.getBoundingClientRect().toJSON() })
        p = p.parentElement
      }
      r.asides.push({ sel: el.tagName + '.' + el.className, rect: el.getBoundingClientRect().toJSON(),
                      inset: getComputedStyle(el, '::before').inset, clippers: chain })
    }
    const lab = document.querySelector('.xc-3d-label') as HTMLElement
    const btn = document.querySelector('.xc-zoom > button') as HTMLElement
    if (lab && btn) {
      const z = (e: Element) => { const s = getComputedStyle(e); return s.zIndex + '/' + s.position }
      r.pair = { lab: { r: lab.getBoundingClientRect().toJSON(), z: z(lab), txt: lab.textContent },
                 btn: { r: btn.getBoundingClientRect().toJSON(), z: z(btn) } }
    }
    return r
  })
  console.log(JSON.stringify(out, null, 1))
})
