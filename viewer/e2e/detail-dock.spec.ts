import { expect, test, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

/* The detail dock: a memory's eight tabs of evidence, on the right, with two different exits.
 *
 * Collapse keeps the selection and narrows the dock to its strip; close drops the selection and
 * gives the lens the width back. The tests below check which of those two happened, not merely
 * that a button was clickable -- the two used to be one control, and a build that wired Close to
 * the collapse flag would still look right in a screenshot. */

const dock = '.xc-workspace > .xc-inspector'

/** Wait for the slide-in, and the transitions it starts elsewhere, to come to rest.
 *
 *  Every geometry assertion below goes through this. Without it the dock measures ~5px short of
 *  the right edge and the chain rail a few px narrow -- not a layout fault, just the 180ms still
 *  running -- which failed two of these tests about one run in three.
 *
 *  It compares two consecutive reads rather than awaiting `getAnimations()`: that set includes
 *  the console's own indefinite animations, whose `finished` never resolves, so awaiting it hung
 *  every test to the 30s timeout. */
async function settled(page: Page) {
  await page.waitForFunction(
    () => {
      const read = () =>
        Array.from(document.querySelectorAll('.xc-workspace > .xc-inspector, .xc-workspace > .xc-chain'))
          .map((e) => { const r = e.getBoundingClientRect(); return `${Math.round(r.x)}:${Math.round(r.width)}` })
          .join('|')
      const now = read()
      const same = (window as unknown as { __xcRest?: string }).__xcRest === now
      ;(window as unknown as { __xcRest?: string }).__xcRest = now
      return same
    },
    null,
    { polling: 60, timeout: 5000 },
  )
}

async function openWithSelection(page: Page, width = 1600, motion: 'reduce' | 'no-preference' = 'reduce') {
  // The geometry tests measure where the dock comes to rest, not how it gets there, and the
  // console honours prefers-reduced-motion by dropping the slide-in and the transitions it
  // starts elsewhere. Asking for it removes the race at the source; `settled()` below still
  // guards the reads. The animation test opts back in with 'no-preference'.
  await page.emulateMedia({ reducedMotion: motion })
  await page.setViewportSize({ width, height: 950 })
  await page.addInitScript(() => sessionStorage.setItem('xibalba-cortex.signed-in', '1'))
  await stubConsoleApi(page)
  await page.goto('/#timeline')
  await page.locator('.xc-mark').first().click()
  await expect(page.locator(dock)).toBeVisible()
}

test('selecting opens a dock that is considerably larger than it was', async ({ page }) => {
  await openWithSelection(page)
  await settled(page)

  const d = (await page.locator(dock).boundingBox())!
  const ws = (await page.locator('.xc-workspace').boundingBox())!

  // it was 380px flat, then 34vw (544px here, which still wrapped the tab row). At 1600px
  // it is now 42vw.
  expect(d.width).toBeGreaterThan(640)
  // but never more than the lens: the graph keeps the larger share
  expect(d.width).toBeLessThan(ws.width / 2)
  // flush to the right edge, full height -- a dock, not a card dropped on the canvas
  expect(Math.abs(ws.x + ws.width - (d.x + d.width))).toBeLessThan(2)
  expect(Math.abs(d.height - ws.height)).toBeLessThan(2)
})

test('it slides in rather than appearing', async ({ page }) => {
  // the one test that wants the motion on
  await openWithSelection(page, 1600, 'no-preference')
  // An animation, not a transition: the element mounts with the selection, so there is no
  // previous computed value for a transition to run from.
  const anim = await page.locator(dock).evaluate((el) => {
    const c = getComputedStyle(el)
    return { name: c.animationName, ms: c.animationDuration }
  })
  expect(anim.name).toBe('xc-dock-in')
  expect(anim.ms).not.toBe('0s')
})

test('close drops the selection and gives the width back', async ({ page }) => {
  await openWithSelection(page)
  await settled(page)
  const railBefore = (await page.locator('.xc-workspace > .xc-chain').boundingBox())!

  await page.locator(`${dock} button[aria-label="Close selected memory"]`).click()

  await expect(page.locator(dock)).toHaveCount(0)
  await expect(page.locator('.xc-workspace[data-detail="closed"]')).toBeVisible()
  // and everything that spans between the docks reclaims the room
  await settled(page)
  const railAfter = (await page.locator('.xc-workspace > .xc-chain').boundingBox())!
  expect(railAfter.width).toBeGreaterThan(railBefore.width + 300)
})

test('collapse keeps the selection and both exits stay reachable', async ({ page }) => {
  await openWithSelection(page)
  await settled(page)
  const open = (await page.locator(dock).boundingBox())!

  await page.locator(`${dock} button[aria-label="Collapse selected memory"]`).click()
  const strip = page.locator(`${dock}[data-collapsed="true"]`)
  await expect(strip).toBeVisible()
  await settled(page)

  // still mounted, so the selection survived -- this is what separates it from Close
  await expect(page.locator('.xc-workspace[data-detail="open"]')).toBeVisible()
  const narrow = (await strip.boundingBox())!
  expect(narrow.width).toBeLessThan(60)
  expect(narrow.width).toBeLessThan(open.width)

  // the collapsed strip keeps only its head, so both buttons have to be in it
  await expect(strip.locator('button[aria-label="Expand selected memory"]')).toBeVisible()
  await expect(strip.locator('button[aria-label="Close selected memory"]')).toBeVisible()

  await strip.locator('button[aria-label="Expand selected memory"]').click()
  await settled(page)
  const reopened = (await page.locator(dock).boundingBox())!
  expect(Math.abs(reopened.width - open.width)).toBeLessThan(2)
})

/* This one is a guard, not a discriminator: it passes against the 380px dock too. It is here
 * because widening a panel is exactly the change that lets its content find a new way to spill,
 * and the 380px rules that stop hashes and JSON setting their own width are width-agnostic only
 * if something keeps checking. */
test('the memory fits the dock at every width it is given', async ({ page }) => {
  for (const width of [1600, 1280]) {
    await openWithSelection(page, width)
    await settled(page)

    const over = await page.locator(`${dock} .xc-inspector-body`).evaluate((el) => el.scrollWidth - el.clientWidth)
    expect(over, `the detail body scrolls sideways at ${width}px`).toBeLessThanOrEqual(1)

    // nothing inside reaches past the dock's own box
    const spill = await page.locator(dock).evaluate((el) => {
      const box = el.getBoundingClientRect()
      let worst = 0
      el.querySelectorAll('*').forEach((n) => {
        const r = (n as HTMLElement).getBoundingClientRect()
        if (r.width === 0) return
        worst = Math.max(worst, r.right - box.right, box.left - r.left)
      })
      return Math.round(worst)
    })
    expect(spill, `content spills ${spill}px out of the dock at ${width}px`).toBeLessThanOrEqual(1)
  }
})
