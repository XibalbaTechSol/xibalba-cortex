import { test, expect, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

/* Conformance audit against the Industry design system (src/console/tokens.css).
 * The Cortex console is dark-only by decision, which is why there is no light
 * theme here to check -- "dark by default" is structural, not a preference.
 *
 * These read *computed* styles, so a rule anywhere in the cascade that overrides
 * a token fails the test. The palette is shared verbatim with Shield's console. */

const CANON = {
  ground: 'rgb(20, 23, 26)',        // #14171a -- same as Shield's --bg
  panel: 'rgb(27, 31, 35)',         // #1b1f23
  elevated: 'rgb(38, 43, 48)',      // #262b30
  ink: 'rgb(238, 240, 241)',        // #eef0f1
  inkMuted: 'rgb(183, 188, 193)',   // #b7bcc1
  inkDim: 'rgb(154, 161, 168)',     // #9aa1a8
  accent: 'rgb(148, 188, 227)',     // #94bce3 -- Industry accent-400, steel
  accentHover: 'rgb(181, 217, 253)',// #b5d9fd -- accent-300, lighter on a dark ground
}

/** The lavender accent Cortex used to carry, retired for the shared steel. */
const RETIRED_LAVENDER = ['rgb(195, 182, 221)', 'rgb(227, 220, 242)']

async function openConsole(page: Page) {
  await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'))
  await stubConsoleApi(page)
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  // the console is a dynamic import, so give the chunk time on a cold preview server
  await expect(page.locator('.xc')).toBeVisible({ timeout: 20000 })
  // guard against a vacuous pass: the sweeps below assert over a set of elements,
  // and an empty set would satisfy every one of them.
  const count = await page.locator('.xc *').count()
  expect(count, 'console rendered no elements to audit').toBeGreaterThan(20)
}

function tokens(page: Page, names: string[]) {
  return page.evaluate((ns) => {
    const host = document.querySelector('.xc') ?? document.documentElement
    const cs = getComputedStyle(host)
    const out: Record<string, string> = {}
    for (const n of ns) {
      const probe = document.createElement('span')
      probe.style.color = cs.getPropertyValue(n).trim()
      host.appendChild(probe)
      out[n] = getComputedStyle(probe).color
      probe.remove()
    }
    return out
  }, names)
}

test.describe('Industry design system conformance (Cortex console)', () => {
  test('the graphite ground and ink match Shield exactly', async ({ page }) => {
    await openConsole(page)
    const t = await tokens(page, ['--ground', '--panel', '--elevated', '--ink', '--ink-muted', '--ink-dim'])
    expect(t['--ground']).toBe(CANON.ground)
    expect(t['--panel']).toBe(CANON.panel)
    expect(t['--elevated']).toBe(CANON.elevated)
    expect(t['--ink']).toBe(CANON.ink)
    expect(t['--ink-muted']).toBe(CANON.inkMuted)
    expect(t['--ink-dim']).toBe(CANON.inkDim)
    await expect(page.locator('.xc')).toHaveCSS('background-color', CANON.ground)
  })

  test('the accent is Industry steel, not the retired lavender', async ({ page }) => {
    await openConsole(page)
    const t = await tokens(page, ['--cortex-accent', '--cortex-accent-hover', '--accent', '--status-anchored'])
    expect(t['--cortex-accent']).toBe(CANON.accent)
    expect(t['--cortex-accent-hover']).toBe(CANON.accentHover)
    // the .xc scope aliases --accent to the Cortex accent
    expect(t['--accent']).toBe(CANON.accent)
    // 'anchored' is the accent role in the shared status vocabulary
    expect(t['--status-anchored']).toBe(CANON.accent)
    for (const v of Object.values(t)) expect(RETIRED_LAVENDER).not.toContain(v)
  })

  test('no lavender survives anywhere in the rendered console', async ({ page }) => {
    await openConsole(page)
    const found = await page.evaluate((lav) => {
      const bad: string[] = []
      for (const el of document.querySelectorAll('.xc, .xc *')) {
        const cs = getComputedStyle(el)
        for (const v of [cs.color, cs.backgroundColor, cs.borderTopColor, cs.fill, cs.stroke]) {
          if (lav.some((l) => v && v.includes(l.replace('rgb(', '').replace(')', '')))) {
            bad.push(`${el.tagName.toLowerCase()}.${(el as HTMLElement).className}: ${v}`)
            break
          }
        }
      }
      return [...new Set(bad)]
    }, RETIRED_LAVENDER)
    expect(found, `lavender remains: ${found.slice(0, 10).join('; ')}`).toEqual([])
  })

  test('palette.ts resolves the tokens for canvas drawing', async ({ page }) => {
    // tokens.css defines --cortex-accent as var(--accent-400); custom properties are
    // substituted at computed-value time, so getPropertyValue must return the hex and
    // not the literal string "var(--accent-400)" -- the graph canvas depends on this.
    await openConsole(page)
    const raw = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue('--cortex-accent').trim())
    expect(raw).not.toContain('var(')
    expect(raw.toLowerCase()).toBe('#94bce3')
  })

  test('type is Barlow Condensed over Barlow, with no drifted faces', async ({ page }) => {
    await openConsole(page)
    const fonts = await page.evaluate(() => {
      const seen = new Set<string>()
      for (const el of document.querySelectorAll('.xc, .xc *')) seen.add(getComputedStyle(el).fontFamily)
      return [...seen].join(' | ')
    })
    expect(fonts.length, 'no elements sampled').toBeGreaterThan(0)
    for (const bad of ['Manrope', 'DM Sans', 'Inter', 'Avenir']) {
      expect(fonts, `no ${bad} in the console`).not.toContain(bad)
    }
    expect(fonts).toContain('Barlow')
    await expect(page.locator('.xc')).toHaveCSS('font-family', /Barlow/)
  })

  test('everything is square', async ({ page }) => {
    await openConsole(page)
    const rounded = await page.evaluate(() => {
      const bad: string[] = []
      for (const el of document.querySelectorAll('.xc, .xc *')) {
        const cs = getComputedStyle(el)
        for (const r of [cs.borderTopLeftRadius, cs.borderTopRightRadius,
                         cs.borderBottomLeftRadius, cs.borderBottomRightRadius]) {
          if (r !== '0px' && !r.endsWith('%')) {
            bad.push(`${el.tagName.toLowerCase()}.${(el as HTMLElement).className}: ${r}`)
            break
          }
        }
      }
      return [...new Set(bad)]
    })
    expect(rounded, `rounded: ${rounded.slice(0, 10).join('; ')}`).toEqual([])
  })

  test('no neutral surface renders a light fill', async ({ page }) => {
    await openConsole(page)
    const pale = await page.evaluate(() => {
      const bad: string[] = []
      for (const el of document.querySelectorAll('.xc, .xc *')) {
        const m = /^rgba?\((\d+), (\d+), (\d+)(?:, ([0-9.]+))?\)$/.exec(getComputedStyle(el).backgroundColor)
        if (!m) continue
        const [r, g, b] = [+m[1], +m[2], +m[3]]
        const a = m[4] === undefined ? 1 : +m[4]
        const chroma = Math.max(r, g, b) - Math.min(r, g, b)
        if (a >= 0.5 && (r + g + b) / 3 > 140 && chroma < 26) {
          bad.push(`${el.tagName.toLowerCase()}.${(el as HTMLElement).className}`)
        }
      }
      return [...new Set(bad)]
    })
    expect(pale, `neutral light fills: ${pale.slice(0, 10).join('; ')}`).toEqual([])
  })

  for (const [name, width] of [['desktop', 1440], ['mobile', 390]] as const) {
    test(`no horizontal overflow at ${name} width`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await openConsole(page)
      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow).toBeLessThanOrEqual(1)
    })
  }

  test('all text clears WCAG AA against the surface it sits on', async ({ page }) => {
    await openConsole(page)
    const report = await page.evaluate(() => {
      const parse = (v: string) => {
        const m = /^rgba?\((\d+), (\d+), (\d+)(?:, ([0-9.]+))?\)$/.exec(v)
        return m ? { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] } : null
      }
      const lum = (c: { r: number; g: number; b: number }) => {
        const f = [c.r, c.g, c.b].map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4 })
        return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]
      }
      const backdrop = (el: Element) => {
        let n: Element | null = el
        while (n) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a >= 0.85) return c; n = n.parentElement }
        return parse(getComputedStyle(document.body).backgroundColor)
      }
      const hueOf = (c: { r: number; g: number; b: number }) => {
        const [r, g, b] = [c.r / 255, c.g / 255, c.b / 255]
        const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min
        if (d === 0) return -1
        let h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4
        h *= 60; return h < 0 ? h + 360 : h
      }
      const onPalette = (h: number) => h < 0 || (h >= 185 && h <= 235) || (h >= 20 && h <= 55) || h <= 15 || h >= 345
      const low: string[] = [], off: string[] = []
      for (const el of document.querySelectorAll('.xc *')) {
        const cs = getComputedStyle(el)
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue
        const name = `${el.tagName.toLowerCase()}.${(el as HTMLElement).className}`.slice(0, 60)
        const bg = parse(cs.backgroundColor)
        if (bg && bg.a >= 0.5) {
          const chroma = Math.max(bg.r, bg.g, bg.b) - Math.min(bg.r, bg.g, bg.b)
          if (chroma > 24 && !onPalette(hueOf(bg))) off.push(`${name} bg ${cs.backgroundColor}`)
        }
        const fg = parse(cs.color)
        if (!fg) continue
        const chroma = Math.max(fg.r, fg.g, fg.b) - Math.min(fg.r, fg.g, fg.b)
        if (chroma > 24 && !onPalette(hueOf(fg))) off.push(`${name} fg ${cs.color}`)
        const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && (n.textContent || '').trim().length > 1)
        if (!hasText || fg.a < 0.9) continue
        const under = backdrop(el)
        if (!under) continue
        const size = parseFloat(cs.fontSize)
        const need = size >= 24 || (size >= 18.66 && (parseInt(cs.fontWeight, 10) || 400) >= 700) ? 3 : 4.5
        const [la, lb] = [lum(fg), lum(under)]
        const got = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
        if (got < need) low.push(`${name}: ${got.toFixed(2)}:1 (needs ${need}) ${cs.color} on rgb(${under.r}, ${under.g}, ${under.b})`)
      }
      return { low: [...new Set(low)], off: [...new Set(off)] }
    })
    expect(report.off, `colour outside steel/amber/red: ${report.off.slice(0, 8).join('; ')}`).toEqual([])
    expect(report.low, `text below AA: ${report.low.slice(0, 8).join('; ')}`).toEqual([])
  })
})
