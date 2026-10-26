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
        /* A swatch is a colour sample, not a surface: its whole job is to show
           the colour it denotes, and the graph palette gives Entities a neutral
           grey, rgb(183, 188, 193). That tripped this check -- but only when the
           legend happened to have an Entities row, which is why the test looked
           intermittent rather than wrong. It was a false positive with a
           data-dependent trigger, not a flake. */
        if (el.classList.contains('xc-swatch')) continue
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

/* ────────────────────────────────────────────────────────────────────────────
 * The rendered console, measured route by route.
 *
 * The checks above assert the palette and the faces. These assert the GRAMMAR,
 * and they do it over every destination rather than the default lens, which is
 * what the earlier pass measured. That distinction is not academic: the Settings
 * page rendered 848px wide inside a 390px phone -- every line of guidance cut
 * off mid-sentence -- while "no horizontal overflow at mobile width" above sat
 * green, because it never opened Settings.
 *
 * Measurement notes, each of which produced a false finding before it was fixed:
 *  - A rect must be intersected with every clipping ancestor, or a collapsed
 *    <details> reads as a 391px spill across the Sign in button.
 *  - display/visibility/opacity do not describe a closed <details>: its rows
 *    keep their boxes and simply are not painted. checkVisibility knows.
 *  - A registration cross is identified by HOW it is drawn, not by a pseudo
 *    merely existing: eight gradient arms on one inset pseudo here, and the
 *    eyebrow's 7px tick is not a mark.
 *  - Two boxes in different stacking layers do not collide: an overlay drawer
 *    is MEANT to cover the lens beneath it, and paint order cannot tell that
 *    apart from a real overlap -- the layer can.
 *  - Scrolling is not clipping. A window below the fold is fine; a cross past
 *    the left or right edge is not, because nothing scrolls sideways to it.
 *  - Marks placed on an axis by DATA (two memories two minutes apart) are the
 *    density of the store, not a defect, and change with its contents.
 * ──────────────────────────────────────────────────────────────────────────── */

const SCALE = [10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 25, 32, 42]
const ROUTES = ['', 'timeline', 'memories', 'entities', 'sessions', 'operations', 'agents', 'settings']
/* The workflow surfaces open over whichever lens is current. They are where
   the stacking-layer rule and the legend toggle actually appear, so leaving
   them out left both untested. */
const OVERLAYS = ['recall', 'review', 'integrity']

async function grammarSweep(page: Page, expectWindows = true): Promise<string[]> {
  return page.evaluate(({ scale, expectWindows }) => {
    const out: string[] = []
    const num = (v: string) => parseFloat(v) || 0
    const own = (e: Element) =>
      e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\s+/)[0] : '')
    /* An unclassed `span` is not something anyone can find in the stylesheet,
       so an element with no class of its own is reported under its nearest
       classed ancestor. */
    const name = (e: Element): string => {
      const self = own(e)
      if (self.includes('.')) return self
      for (let p = e.parentElement; p; p = p.parentElement) {
        if (own(p).includes('.')) return `${own(p)} > ${self}`
      }
      return self
    }
    const vis = (e: Element) => {
      const s = getComputedStyle(e), r = e.getBoundingClientRect()
      if (!(s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity > 0.01 && r.width > 0 && r.height > 0)) return false
      if (typeof e.checkVisibility === 'function'
        && !e.checkVisibility({ contentVisibilityAuto: true, opacityProperty: true, visibilityProperty: true })) return false
      for (let p = e.parentElement; p; p = p.parentElement) {
        if (p.tagName === 'DETAILS' && !(p as HTMLDetailsElement).open && !e.closest('summary')) return false
      }
      return true
    }
    /* Also records WHICH ancestor each bound came from. "cut off by a clipping
       ancestor" named no element, which left every such finding needing a
       separate hand-written probe before it could be fixed. */
    /* `scrollClips` picks which of two different questions this box answers.
       `false` -- can the user ever get to it? A scroll container is NOT a clip: whatever sits
       past its visible box is reachable by scrolling, so the walk stops there (used by the
       registration-mark cut-off check, which is about content being permanently lost).
       `true` -- which pixels does it actually paint right now? A scroll container clips
       absolutely, so the walk clamps to it (used by the overlap check: two things cannot be
       on top of each other if one of them is behind a scroll box's edge). Sharing one box
       between the two reported every row sitting below its scroller's bottom edge as
       overlapping the status bar -- 14 pairs on Memories/Operations/Agents -- for content the
       browser was clipping. */
    const clip = (e: Element, seedViewport: boolean, scrollClips = false) => {
      let r: { l: number; t: number; r: number; b: number; by: Record<string, string> } = seedViewport
        ? { l: 0, t: 0, r: innerWidth, b: innerHeight, by: {} }
        : { l: 0, t: -1e7, r: innerWidth, b: 1e7, by: {} }
      for (let p = e.parentElement; p; p = p.parentElement) {
        const s = getComputedStyle(p)
        if (s.overflowX === 'visible' && s.overflowY === 'visible') continue
        /* A scroll container is not a clip: whatever sits past its visible box is still
           reachable, and the user gets there the same way they reach any other content below
           the fold. Treating it as one reported every window on a scrolling page as "cut off"
           -- 267px on Operations -- for the ordinary fact that the page is longer than the
           screen. Only a container that genuinely cannot be scrolled to its content clips. */
        const scrollsX = !scrollClips && (s.overflowX === 'auto' || s.overflowX === 'scroll') && p.scrollWidth > p.clientWidth
        const scrollsY = !scrollClips && (s.overflowY === 'auto' || s.overflowY === 'scroll') && p.scrollHeight > p.clientHeight
        /* Past a scroll container, nothing further out clips either: scrolling moves this
           element inside every outer box in turn. Without stopping here, `.xc-main`'s own
           `overflow: hidden` -- which exists precisely so the page scrolls instead of the
           document -- reported every window below the fold as cut off. */
        if (scrollsX && scrollsY) break
        const pr = p.getBoundingClientRect(), who = name(p) + ` [${s.overflowX}/${s.overflowY}]`
        if (scrollsY) {
          if (pr.left > r.l) { r.l = pr.left; r.by.l = who }
          if (pr.right < r.r) { r.r = pr.right; r.by.r = who }
          break
        }
        if (scrollsX) {
          if (pr.top > r.t) { r.t = pr.top; r.by.t = who }
          if (pr.bottom < r.b) { r.b = pr.bottom; r.by.b = who }
          continue
        }
        if (pr.left > r.l) { r.l = pr.left; r.by.l = who }
        if (pr.top > r.t) { r.t = pr.top; r.by.t = who }
        if (pr.right < r.r) { r.r = pr.right; r.by.r = who }
        if (pr.bottom < r.b) { r.b = pr.bottom; r.by.b = who }
      }
      return r
    }
    const layer = (e: Element) => {
      for (let p: Element | null = e; p; p = p.parentElement) {
        const s = getComputedStyle(p)
        if (s.position !== 'static' && s.zIndex !== 'auto') {
          const z = parseInt(s.zIndex, 10)
          if (Number.isFinite(z)) return z
        }
      }
      return 0
    }
    const shown = [...document.querySelectorAll('.xc *')].filter(vis)
    if (shown.length < 20) out.push(`only ${shown.length} elements rendered -- the sweep would pass vacuously`)

    // (a) text stays inside its own box
    for (const e of shown) {
      const s = getComputedStyle(e)
      if (!(s.overflow + s.overflowX).includes('hidden')) continue
      if (![...e.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim())) continue
      const dx = Math.round(e.scrollWidth - e.clientWidth)
      if (dx > 1) out.push(`text clipped ${name(e)} by ${dx}px: ${(e.textContent || '').trim().slice(0, 48)}`)
    }

    // (b) nothing is permanently out of reach sideways
    for (const e of [document.documentElement, ...shown]) {
      if (!(e instanceof Element)) continue
      if (e !== document.documentElement && !/hidden|clip/.test(getComputedStyle(e).overflowX)) continue
      // a form control scrolls its own value natively; the caret still reaches it
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.tagName)) continue
      const over = e.scrollWidth - e.clientWidth
      if (over > 1) out.push(`${name(e)} overflows horizontally by ${over}px`)
    }

    // (c) every window carries a complete, unclipped registration cross
    const wins = [...document.querySelectorAll('.xc-win')].filter(vis)
    if (!wins.length && expectWindows) out.push('no .xc-win rendered -- the mark checks would pass vacuously')
    for (const w of wins) {
      const pb = getComputedStyle(w, '::before')
      const arms = (pb.backgroundImage.match(/gradient/g) || []).length
      if (pb.content === 'none' || arms < 8) { out.push(`${name(w)} is missing its registration cross (${arms} arms)`); continue }
      const bleed = -num(pb.top)
      if (bleed < 6) out.push(`${name(w)} cross bleeds only ${bleed}px; Industry offsets the corner -6px`)
      const r = w.getBoundingClientRect(), c = clip(w, false)
      const sides: string[] = []
      if (r.left - bleed < c.l - 1) sides.push(`left by ${Math.round(c.l - (r.left - bleed))}px (${c.by.l ?? 'viewport'})`)
      if (r.right + bleed > c.r + 1) sides.push(`right by ${Math.round(r.right + bleed - c.r)}px (${c.by.r ?? 'viewport'})`)
      if (r.top - bleed < c.t - 1) sides.push(`top by ${Math.round(c.t - (r.top - bleed))}px (${c.by.t ?? 'viewport'})`)
      if (r.bottom + bleed > c.b + 1) sides.push(`bottom by ${Math.round(r.bottom + bleed - c.b)}px (${c.by.b ?? 'viewport'})`)
      if (sides.length) out.push(`${name(w)} registration cross cut off -- ${sides.join('; ')}`)
      const s = getComputedStyle(w)
      const missing = ['Top', 'Right', 'Bottom', 'Left'].filter((d) =>
        num(s[('border' + d + 'Width') as never]) < 0.5)
      if (missing.length) out.push(`${name(w)} frame is missing its ${missing.join('/')} border`)
    }

    // (d) windows are line drawings on one ground, not stacked surfaces
    const root = document.querySelector('.xc')
    const ground = root ? getComputedStyle(root).backgroundColor : 'rgb(20, 23, 26)'
    const rgb = (c: string) => (c.match(/[\d.]+/g) || []).slice(0, 3).map(Number)
    for (const w of wins) {
      const r = w.getBoundingClientRect()
      if (r.width < 200 || r.height < 72) continue
      const bg = getComputedStyle(w).backgroundColor
      const a = (bg.match(/[\d.]+/g) || []).length === 4 ? +(bg.match(/[\d.]+/g) || [])[3] : 1
      if (a < 0.2) continue
      const [x, y, z] = rgb(bg), g = rgb(ground)
      if (Math.abs(x - g[0]) + Math.abs(y - g[1]) + Math.abs(z - g[2]) > 12)
        out.push(`${name(w)} carries a surface fill ${bg} over a ${ground} ground`)
    }

    // (e) two things in the same layer never sit on top of each other
    const leaves = shown.filter((e) => ['BUTTON', 'A', 'INPUT', 'SELECT'].includes(e.tagName)
      || [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim()))
    for (let i = 0; i < leaves.length; i++) {
      for (let j = i + 1; j < leaves.length; j++) {
        const a = leaves[i], b = leaves[j]
        if (a.contains(b) || b.contains(a)) continue
        /* Two exemptions, both for things whose position is not authored in CSS
           and so cannot be laid out away from anything:
            - `.xc-mark` is a timeline tick placed from a timestamp.
            - `.xc-3d-label` is a node label whose screen position is the node's
              3D point projected through the camera every frame (Graph3D.tsx),
              so it drifts with the simulation and the camera. The controls that
              float over the canvas are the ones that must stay legible, and
              they do: they paint above, on an opaque ground, while the label
              layer is `pointer-events: none` and cannot take a click. */
        if (a.matches('.xc-mark, .xc-3d-label') || b.matches('.xc-mark, .xc-3d-label')) continue
        if (layer(a) !== layer(b)) continue
        const ca = clip(a, true, true), cb = clip(b, true, true)
        const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect()
        const A = { l: Math.max(ra.left, ca.l), r: Math.min(ra.right, ca.r), t: Math.max(ra.top, ca.t), b: Math.min(ra.bottom, ca.b) }
        const B = { l: Math.max(rb.left, cb.l), r: Math.min(rb.right, cb.r), t: Math.max(rb.top, cb.t), b: Math.min(rb.bottom, cb.b) }
        const ox = Math.min(A.r, B.r) - Math.max(A.l, B.l), oy = Math.min(A.b, B.b) - Math.max(A.t, B.t)
        if (ox > 2 && oy > 2) out.push(`${name(a)} overlaps ${name(b)} by ${Math.round(ox)}x${Math.round(oy)}px`)
      }
    }

    /* (e2) button grounds. Industry allows a button exactly two grounds: the
       one solid accent fill ("the one solid object on the board") or a
       transparent object with a hairline border. A neutral panel fill is not a
       variant, and this is the check that answers "are the button colours in
       line with the theme".

       Exemptions, each deliberate and each named rather than left silent:
        - Nav and tab rows mark the current item with a fill; that is selection
          state, not a button ground.
        - `.xc-legend-toggle` floats over the graph canvas, where a transparent
          ground would leave its label sitting on top of edges and nodes. It is
          the same reasoning that exempts a drawer or dialog from the "windows
          are line drawings" rule: a thing that overlaps the canvas has to
          occlude it to stay legible. */
    const resolve = (expr: string) => {
      const probe = document.createElement('span')
      probe.style.cssText = `position:absolute;left:-9999px;color:${expr}`
      ;(document.querySelector('.xc') ?? document.body).appendChild(probe)
      const c = (getComputedStyle(probe).color.match(/[\d.]+/g) || []).slice(0, 3).map(Number)
      probe.remove()
      return c
    }
    const acc = resolve('var(--accent)')
    /* An undefined custom property makes `color` invalid at computed-value time,
       so the probe silently inherits the ink colour and every button then reads
       as off-palette -- or, if no accent button happens to be on screen, the
       whole check passes while measuring nothing. Resolving the same colour by
       its other name and requiring the two to agree is what rules that out. */
    const accAlt = resolve('var(--cortex-accent)')
    if (acc.length !== 3 || accAlt.length !== 3 || acc.some((v, i) => v !== accAlt[i]))
      out.push(`accent probe did not resolve: var(--accent)=${JSON.stringify(acc)} vs var(--cortex-accent)=${JSON.stringify(accAlt)}`)
    const nearAcc = (c: number[], tol: number) =>
      c.length === 3 && acc.length === 3 && c.every((v, i) => Math.abs(v - acc[i]) <= tol)
    const OVER_CANVAS = '.xc-legend-toggle'
    const navLike = (e: Element) =>
      /* `.xc-rail-shell`/`.xc-rail-nav`, not `.xc-rail`: the Integrity overlay has
         a content pane classed `xc-win xc-pane xc-rail`, and the broader selector
         exempted every button inside it -- a silent allowance over real content. */
      !!e.closest('nav, [role="tablist"], .xc-rail-shell, .xc-rail-nav, .xc-tabs, .xc-seg')
      || e.getAttribute('role') === 'tab'
      || /(^|[\s.-])(xc-nav-btn|xc-tab|xc-seg-opt|xc-session-row|xc-mark)/.test((e.className || '').toString())
    for (const b of shown) {
      if (!(b.tagName === 'BUTTON' || b.getAttribute('role') === 'button')) continue
      if (navLike(b) || b.matches(OVER_CANVAS)) continue
      const cs = getComputedStyle(b), bg = cs.backgroundColor
      const a = (bg.match(/[\d.]+/g) || []).length === 4 ? +(bg.match(/[\d.]+/g) || [])[3] : 1
      const c = (bg.match(/[\d.]+/g) || []).slice(0, 3).map(Number)
      const solid = a > 0.9 && nearAcc(c, 26)
      const tint = a <= 0.9 && nearAcc(c, 60)
      if (!solid && !(a < 0.12 || tint))
        out.push(`button ground ${name(b)}: ${bg} ${JSON.stringify((b.textContent || '').trim().slice(0, 20))}`)
      if (num(cs.borderTopLeftRadius) > 2 && cs.borderTopLeftRadius !== '50%')
        out.push(`button rounded ${name(b)}: ${cs.borderTopLeftRadius}`)
    }

    // (f) type sits on Industry's fixed scale
    for (const e of shown) {
      if (![...e.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim())) continue
      const px = Math.round(num(getComputedStyle(e).fontSize) * 10) / 10
      if (!scale.includes(px)) out.push(`${name(e)} is ${px}px, off the scale: ${(e.textContent || '').trim().slice(0, 32)}`)
    }

    // (g) icons are drawn at one weight
    for (const svg of document.querySelectorAll<SVGElement>('.xc svg')) {
      if (!vis(svg)) continue
      const sw = getComputedStyle(svg).strokeWidth
      if (sw && sw !== '1.5' && sw !== '1.5px' && sw !== '0px') out.push(`icon stroke ${sw} on ${name(svg.parentElement ?? svg)}`)
    }
    return out
  }, { scale: SCALE, expectWindows })
}

/* The signed-out screen is the first thing anyone sees and it is not reachable
   from any route, because `openConsole` seeds the signed-in flag. Nothing else
   in this file covers it. */
for (const [w, h] of [[390, 844], [1280, 720], [1600, 1000]] as const) {
  test(`the sign-in screen keeps its grammar at ${w}px`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h })
    await stubConsoleApi(page)
    await page.goto('/#signin', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('.xc')).toBeVisible({ timeout: 20000 })
    // it must actually be the signed-out screen, not the console
    await expect(page.locator('.xc-auth-formwrap, .xc-auth-story').first()).toBeVisible({ timeout: 10000 })
    await page.waitForTimeout(600)
    /* expectWindows: false -- this screen is a two-column split drawn by a
       single rule plus one hairline callout, and neither is a window. The guard
       stays on for every other surface, where a missing window WOULD mean the
       mark checks measured nothing. */
    const problems = await grammarSweep(page, false)
    expect(problems, `Industry grammar violations on sign-in:\n  ${problems.join('\n  ')}`).toEqual([])
  })

  test(`every destination keeps its content, frames and grammar at ${w}px`, async ({ page }) => {
    // Eight routes and three overlays share this budget, including their intentional settling waits.
    test.setTimeout(60000)
    await page.setViewportSize({ width: w, height: h })
    const crashes: string[] = []
    page.on('pageerror', (e) => crashes.push(String(e.message || e).slice(0, 180)))
    await openConsole(page)
    const problems: string[] = []
    for (const route of ROUTES) {
      // drive the hash in-page: a goto() to a hash is still a document load, and
      // the console is a dynamic import that has to boot again each time.
      await page.evaluate((r) => { location.hash = r ? '#' + r : '' }, route)
      await page.waitForTimeout(900)
      if (!(await page.locator('.xc').count())) {
        problems.push(`[${route || 'graph'}] console unmounted: ${crashes[crashes.length - 1] ?? 'no page error'}`)
        continue
      }
      await page.waitForTimeout(700)
      problems.push(...(await grammarSweep(page)).map((p) => `[${route || 'graph'}] ${p}`))
    }
    for (const ov of OVERLAYS) {
      await page.evaluate(() => { location.hash = '' })
      await expect(page.locator('.xc')).toBeVisible({ timeout: 20000 })
      /* The rail carries all three at desktop width. The phone tabbar carries
         only the first two and files the rest behind "More", so the walk has to
         go through that sheet rather than declare the overlay missing. */
      const byName = (re: RegExp) => page.getByRole('button', { name: re }).first()
      /* word-anchored, not `$`-anchored: the More sheet puts each destination's
         hint inside the button, so its accessible name is "Integrity Verify
         chains and checkpoints". A leading anchor still keeps it off the
         overlays' own "Close Integrity" buttons. */
      const trigger = new RegExp('^' + ov + '\\b', 'i')
      let btn = byName(trigger)
      if (!(await btn.count())) {
        const more = byName(/^more$/i)
        expect(await more.count(), `overlay ${ov} unreachable at ${w}px: no "More"`).toBeGreaterThan(0)
        await more.click()
        await page.waitForTimeout(400)
        btn = byName(trigger)
      }
      expect(await btn.count(), `overlay ${ov} unreachable at ${w}px`).toBeGreaterThan(0)
      await btn.click()
      await page.waitForTimeout(700)
      /* Each overlay's close button carries its own name ("Close Integrity"), so
         this proves the overlay that opened is the one asked for. A bare
         `[role=dialog]` would also be satisfied by a previous overlay that
         failed to close, and the sweep would then measure it twice. */
      await expect(page.getByRole('button', { name: `Close ${ov}`, exact: false }).first())
        .toBeVisible({ timeout: 10000 })
      problems.push(...(await grammarSweep(page)).map((p) => `[${ov}] ${p}`))
      await page.keyboard.press('Escape').catch(() => {})
      await page.waitForTimeout(300)
    }
    expect(problems, `Industry grammar violations:\n  ${problems.join('\n  ')}`).toEqual([])
  })
}

test.describe('nothing is clipped and nothing scrolls the page', () => {
  // The console hides all scrollbar chrome, which makes a layout bug invisible rather than
  // ugly: content that overflows a box with `overflow: hidden` is simply gone, and there is no
  // bar left to hint at it. This is the check that keeps that honest.
  //
  // `MARK` is the reach of Industry's registration marks, which are drawn on a pseudo-element
  // inset outside the frame and so legitimately report a few pixels of overflow on every
  // `.xc-win`. Anything past that is content with nowhere to go.
  const MARK = 7

  const SURFACES = [
    ['workspace', async () => {}],
    ['explore', async (page: Page) => { await page.getByRole('button', { name: 'Explore' }).first().click() }],
    ['settings', async (page: Page) => {
      await page.locator('.xc-profile-btn').click()
      await page.getByRole('menuitem', { name: 'Settings' }).click()
    }],
  ] as const

  for (const [name, open] of SURFACES) {
    for (const width of [1600, 1280]) {
      test(`${name} fits the viewport at ${width}px`, async ({ page, baseURL }) => {
        await page.setViewportSize({ width, height: 900 })
        await page.goto(baseURL!)
        await page.evaluate(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'))
        await page.goto(baseURL!)
        await page.waitForTimeout(1500)
        await open(page)
        await page.waitForTimeout(1200)
        await page.evaluate(() => document.fonts.ready)

        const seen = await page.evaluate((MARK) => {
          const clipped: string[] = []
          document.querySelectorAll('*').forEach((el) => {
            const e = el as HTMLElement
            const s = getComputedStyle(e)
            const box = e.getBoundingClientRect()
            if (box.width < 2 || box.height < 2) return
            const overX = e.scrollWidth - e.clientWidth
            const overY = e.scrollHeight - e.clientHeight
            if (overX <= MARK && overY <= MARK) return
            const scrollsX = s.overflowX === 'auto' || s.overflowX === 'scroll'
            const scrollsY = s.overflowY === 'auto' || s.overflowY === 'scroll'
            if ((overX > MARK && !scrollsX) || (overY > MARK && !scrollsY)) {
              const named = e.tagName.toLowerCase() + '.' + (e.className || '').toString().trim().split(/\s+/)[0]
              clipped.push(`${named} overflows by ${overX}x${overY} with overflow ${s.overflowX}/${s.overflowY}`)
            }
          })
          return { document: document.documentElement.scrollHeight - window.innerHeight, clipped }
        }, MARK)

        expect(seen.document, 'the page itself scrolls; the shell should be exactly one viewport tall').toBe(0)
        expect(seen.clipped, `content with nowhere to go:\n  ${seen.clipped.join('\n  ')}`).toEqual([])
      })
    }
  }
})

for (const width of [390, 1280, 1600]) {
  test(`the public landing keeps its grammar at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 })
    await stubConsoleApi(page)
    await page.goto('/')
    await expect(page.locator('.xc-landing')).toBeVisible()
    await page.evaluate(() => document.fonts.ready)
    const problems = await grammarSweep(page)
    expect(problems, problems.join('\n')).toEqual([])
  })
}
