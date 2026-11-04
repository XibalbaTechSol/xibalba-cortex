import { expect, test, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'

/* Phase 2, Task 1 — zero agents means "connect an agent" is the first screen.
 *
 * `parseRoute('')` returns `{ lens: 'graph', page: null }` regardless of how many agents
 * exist, so a fresh account with nothing connected lands on an empty workspace: a canvas of
 * memory boxes with no memories, and no indication that connecting an agent is the next step.
 *
 * The count is derived from the agent listing the console already fetches. No new endpoint. */

/** Sign the browser in without forcing a hash. `openConsole` always navigates to a route, and
 *  the whole question here is what a *hash-less* first load opens. */
async function signedIn(page: Page) {
  await page.addInitScript(() => {
    try { sessionStorage.setItem('xibalba-cortex.signed-in', '1') } catch { /* storage may be unavailable */ }
  })
}

/** Shadow the fixture's populated agent listing with an empty one. A route added after
 *  `stubConsoleApi` is matched first, so this wins without editing the shared fixture. */
async function withNoAgents(page: Page) {
  const empty = (body: unknown) => async (route: import('@playwright/test').Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  await page.route('**/api/agents**', empty({ agents: [], oracle_reachable: false, primary_profile_id: 'default' }))
  await page.route('**/api/agent-devices**', empty({ pairs: [] }))
}

/* `.xc-agent-onboarding` is worn by two sections on this page (connect, and the ERC-8004
 * directory search), so address the connect one by its own region name. */
/** The first-run probe the console issues on load (`api.agents(1)`). A test that asserts the
 *  gate did NOT fire must wait for this, because `.not.toHaveURL(...)` and `toHaveCount(0)`
 *  both pass instantly against a URL that has not changed *yet* -- the gate fires a second or
 *  two later, when the load resolves. A mutation that removed the guard left the negative test
 *  green for exactly this reason. */
function firstRunProbe(page: Page) {
  return page.waitForResponse((r) => /\/api\/agents\?limit=1(&|$)/.test(r.url()))
}

const connectSurface = (page: Page) => page.getByRole('region', { name: 'Bring an agent into Cortex' })
const workspaceCanvas = (page: Page) => page.locator('.xc-canvas-win')

test('an account with no agents lands on the connect-an-agent surface', async ({ page }) => {
  await stubConsoleApi(page)
  await signedIn(page)
  await withNoAgents(page)

  // No hash: this is what a fresh sign-in actually opens.
  await page.goto('/')

  await expect(connectSurface(page), 'a fresh account was dropped on a workspace instead of being told to connect an agent').toBeVisible()
  await expect(page.getByRole('heading', { name: 'Bring an agent into Cortex' })).toBeVisible()
  /* The gate moves the address, it does not merely draw over the lens. A page renders in a
   * drawer above a still-mounted lens (`ConsoleApp.tsx`), so the canvas staying in the DOM is
   * by design and asserting its absence would be asserting against the architecture. What must
   * be true is that the destination changed -- which is also what survives the reload below. */
  await expect(page).toHaveURL(/agents/)
})

test('an account with an agent still lands on its workspace', async ({ page }) => {
  // The control. Step 5 seeds an agent and this test must stay green while the gate test reds.
  await stubConsoleApi(page)
  await signedIn(page)

  await page.goto('/')

  await expect(workspaceCanvas(page), 'an account with an agent was diverted to onboarding').toBeVisible()
  await expect(connectSurface(page)).toHaveCount(0)
})

test('the gate is the agent count, not a first-visit flag', async ({ page }) => {
  /* A gate implemented as "have I shown this before?" would send a returning user with zero
   * agents to the workspace. Reloading must still land on the connect surface. */
  await stubConsoleApi(page)
  await signedIn(page)
  await withNoAgents(page)

  await page.goto('/')
  await expect(connectSurface(page)).toBeVisible()
  await page.reload()

  await expect(connectSurface(page), 'the gate did not survive a reload, so it is not reading the count').toBeVisible()
})

test('an explicit destination in the hash is still honoured with zero agents', async ({ page }) => {
  /* The gate replaces the *default* landing, not navigation. A user who asks for the
   * workspace gets the workspace, empty or not -- otherwise the console becomes unnavigable
   * until an agent exists. */
  await stubConsoleApi(page)
  await signedIn(page)
  await withNoAgents(page)

  const probe = firstRunProbe(page)
  await page.goto('/#graph')
  await probe
  // and give the effect that reads it a chance to run
  await page.waitForTimeout(1500)

  /* Asserting the canvas is *visible* here cannot fail: the lens stays mounted and visible
   * under the page drawer, so it is visible whether or not the gate hijacked the destination.
   * (Proved by a mutation that removed the guard and left this test green.) The destination is
   * the thing being claimed, so assert that instead. */
  await expect(page, 'an explicit #graph was overridden by the onboarding gate').not.toHaveURL(/agents/)
  await expect(connectSurface(page)).toHaveCount(0)
  await expect(workspaceCanvas(page)).toBeVisible()
})
