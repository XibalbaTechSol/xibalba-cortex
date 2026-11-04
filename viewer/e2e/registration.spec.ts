import { expect, test, type Page } from '@playwright/test'
import { stubConsoleApi } from './consoleFixture'
import { managedFixture } from './managed-fixture'

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

/* Phase 2, Task 3 — a successful bind selects the agent and opens the Graph lens.
 *
 * The server half of this lives in `tests/test_enrollment_bind.py`: a redeemed enrollment
 * code pairs the DID's agent id with its device, which is what puts it in the listing below,
 * and returns the `agent_id`/`store_id` that `workspace.choose` needs. These tests cover the
 * console's half -- that it notices the agent arriving and opens its workspace.
 *
 * Why a transition and not a reload: the person is looking at the connect screen in a browser
 * while they run `cortex connect --code` in a terminal. Nothing in the browser knows the
 * redemption happened, so the console has to be the thing that looks. */

const ENROLLED_AGENT = 'did:integrity:00000000000000000000000000000000000000000000000000000000000000ff'
const ENROLLED_DEVICE = 'enrolled-device-01'
const ENROLLED_STORE = 'store-fixture'
/* A second agent that arrives in the same listing, and the reason it exists: `useWorkspace`
 * has a "nothing valid selected but namespaces exist, so take the default" effect. With a
 * single agent in the listing that effect selects the right one by accident, so a mutation
 * that bound no agent id at all (`choose('', storeId)`) still left the scope assertion
 * green. Two agents means the default is NOT the enrolled one, and the assertion has to be
 * carried by the bind. */
const OTHER_AGENT = 'did:integrity:00000000000000000000000000000000000000000000000000000000000000aa'

const listedAgent = (agentId: string, deviceId: string) => ({
  agent_id: agentId, device_id: deviceId, agent_name: deviceId,
  device_name: deviceId, pair_status: 'active', pair_updated_at: null,
  memories: 0, memories_counted: true, sessions: 0, sessions_counted: false,
  last_seen_at: null, store_id: ENROLLED_STORE, profile_id: 'default',
  store_access: 'writable', writable: true, did: agentId, on_chain: false,
  seen: true, handle: null, name: null, local_label: deviceId,
})

/** Zero agents until `redeem()` is called, one afterwards -- the 0 -> 1 transition a
 *  redemption produces, driven from the test rather than waited for. */
async function agentArrivesWhenRedeemed(page: Page, arrived = [listedAgent(ENROLLED_AGENT, ENROLLED_DEVICE)]) {
  let redeemed = false
  const body = (value: unknown) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(value) })
  await page.route('**/api/agents**', (route) => route.fulfill(body({
    agents: redeemed ? arrived : [],
    oracle_reachable: false,
    primary_profile_id: 'default',
  })))
  await page.route('**/api/agent-devices**', (route) => route.fulfill(body({
    pairs: redeemed
      ? arrived.map((a) => ({ device_id: a.device_id, agent_id: a.agent_id, display_name: a.device_name, status: 'active', created_at: null, updated_at: null, last_seen_at: null }))
      : [],
  })))
  return { redeem: () => { redeemed = true } }
}

/** The header scope selector. "The agent is selected" has to be asserted on something the
 *  person can see -- the URL alone says only which lens is open, and the canvas proves
 *  nothing either way because the lens stays mounted under the page drawer. */
const scopePicker = (page: Page) => page.locator('.xc-scope select')

test('an agent that arrives while the connect surface is open is selected, in the Graph lens', async ({ page }) => {
  await stubConsoleApi(page)
  await signedIn(page)
  const enrollment = await agentArrivesWhenRedeemed(page)

  await page.goto('/')
  // The Task 1 gate put us here: zero agents, so "connect an agent" is the first screen.
  await expect(connectSurface(page)).toBeVisible()

  // ...and now the operator runs `cortex connect --code` in their terminal.
  enrollment.redeem()

  /* "Opens the Graph lens" is asserted as the Agents page *closing*, not as a hash saying
   * "graph": `routeHash` (nav.ts) gives the default lens no token at all, so the graph lens
   * is the empty hash and `toHaveURL(/graph/)` could never pass however well the wiring
   * worked. The canvas is no use either -- it stays mounted and visible beneath the page
   * drawer, so it is visible whether or not the drawer closed. */
  await expect(connectSurface(page), 'the bind left the connect page open over the lens')
    .toHaveCount(0, { timeout: 20_000 })
  await expect(page, 'the bind left the route on the Agents page').not.toHaveURL(/agents/)
  await expect(scopePicker(page), 'the Graph lens opened on some other workspace than the agent that just enrolled')
    .toHaveValue(`${ENROLLED_STORE}\u0000${ENROLLED_AGENT}`)
})

test('an account that already has an agent is not thrown out of the Agents page', async ({ page }) => {
  /* The control, and the reason the transition is a transition. A rule of "if there is an
   * agent, go to Graph" would make the Agents page unreachable: every visit would bounce.
   * Only a 0 -> 1 change observed while waiting may navigate. */
  await stubConsoleApi(page)
  await signedIn(page)

  await page.goto('/#agents')
  await expect(page.getByRole('heading', { name: 'Bring an agent into Cortex' })).toBeVisible()
  await page.waitForTimeout(6_000) // longer than the poll interval

  await expect(page, 'visiting Agents with an agent already connected bounced to Graph').toHaveURL(/agents/)
})

test('an enrolled agent with no memories is told how to write one, not shown an empty canvas', async ({ page }) => {
  /* The second half of the plan's Step 1. A workspace that is empty *because the agent has
   * not written yet* is the normal state one second after enrollment, and "no memories yet"
   * on its own does not tell anyone what to do about it. */
  await stubConsoleApi(page)
  await signedIn(page)
  await page.route('**/api/graph**', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ nodes: [], edges: [], truncated: false }),
  }))

  await page.goto('/#graph')

  const empty = page.getByRole('heading', { name: /no memories yet/i })
  await expect(empty).toBeVisible()
  await expect(
    page.getByText('cortex connect', { exact: false }).first(),
    'an empty workspace says it is empty but not how to fill it',
  ).toBeVisible()
})

test('two agents arriving at once is not guessed at', async ({ page }) => {
  /* What makes the single-agent case safe is that there is nothing to choose between. With
   * two namespaces appearing in the same listing the console has no way to know which one
   * redeemed the code, and `useWorkspace`'s "nothing selected, take the default" effect would
   * quietly pick `options[0]` -- landing the person in a workspace they did not enroll. So
   * the transition fires only for an unambiguous arrival; otherwise the listing is the answer
   * and the person picks. */
  await stubConsoleApi(page)
  await signedIn(page)
  const enrollment = await agentArrivesWhenRedeemed(page, [
    listedAgent(OTHER_AGENT, 'other-device-01'),
    listedAgent(ENROLLED_AGENT, ENROLLED_DEVICE),
  ])

  await page.goto('/')
  await expect(connectSurface(page)).toBeVisible()
  enrollment.redeem()

  /* Both are listed as cards -- addressed as cards, not by their names: the scope picker
   * carries the same names in hidden <option> elements, which a text locator matches first. */
  await expect(page.locator('.xc-opscard')).toHaveCount(2, { timeout: 20_000 })
  await expect(page, 'the console picked one of two simultaneous arrivals instead of letting the person choose').toHaveURL(/agents/)
  await expect(connectSurface(page), 'the connect surface vanished without anything being opened').toBeVisible()
})

/* Phase 2, Task 4 — the DID-bound API key path keeps working.
 *
 * The spec's second registration path, and the one that already existed: a key bound to the
 * agent DIDs it is for. The plan expected Phase 0's deletion of `ManagedApp` to take this
 * path's only test with it, so the assertion needed "re-homing onto the console's API-keys
 * surface rather than quietly losing coverage".
 *
 * Two things turned out to be true instead. The coverage was never lost: `main.tsx` boots
 * `ConsoleApp` unconditionally, so `managed.spec.ts` navigating to `/managed#agents` has been
 * driving the console's own `HostedApiKeys` all along. And `/managed` is not a leftover to be
 * re-homed away from -- `editionOf()` (edition.ts) reads that exact path, and the hosted
 * deployment serves the app there (`managed/api.py` redirects `/`). A self-hosted console has
 * no hosted API-keys surface, correctly, so there is nowhere else for this to live.
 *
 * So what this adds is the part that was actually missing: the rules asserted in Phase 2's
 * own file, the edition boundary asserted explicitly, and a mutation proving they can fail.
 * They pass on first run because the behaviour already exists -- this is characterisation.
 * The plan's Step 5 is what makes them worth having: allowing an empty DIDs field reds the
 * first one. */

test('a hosted API key cannot be created without the DIDs it binds to', async ({ page }) => {
  await managedFixture(page, { signedIn: true })

  await page.goto('/managed#agents')

  const create = page.getByRole('button', { name: 'Create API key', exact: true })
  /* This rule is real, not cosmetic: before it was asserted, a click against a permanently
   * disabled button waited out a 90-second CI timeout (PR #72). */
  await expect(create, 'a key with no DIDs is bound to no agent, so the control must refuse first').toBeDisabled()

  await page.getByRole('textbox', { name: /^Agent DIDs/ }).fill('did:integrity:agent-one\ndid:integrity:agent-two')
  await expect(create).toBeEnabled()
})

test('the issued hosted key carries exactly the agent DIDs that were entered', async ({ page }) => {
  const calls = await managedFixture(page, { signedIn: true })

  await page.goto('/managed#agents')
  await page.getByRole('textbox', { name: /^Agent DIDs/ }).fill('did:integrity:agent-one\ndid:integrity:agent-two')
  await page.getByRole('button', { name: 'Create API key', exact: true }).click()

  await expect(page.getByLabel('New API key', { exact: true })).toBeVisible()
  // The binding is the point of the field: the DIDs must reach the API, split and in order.
  const issued = calls.find((call) => call.path === 'keys' && call.method === 'POST')
  expect(issued?.body, 'the key was issued without the agent binding it exists to carry').toEqual({
    label: 'agent',
    agent_ids: ['did:integrity:agent-one', 'did:integrity:agent-two'],
  })
  // A freshly issued key is a credential; it must not be left in browser storage.
  expect(await page.evaluate(() => Object.values(localStorage).join(' '))).not.toContain('fixture-only-managed-key')
})

test('a self-hosted console offers no hosted API-key form at all', async ({ page }) => {
  /* The edition boundary, which is why the two tests above live at `/managed` and not at `/`.
   * `HostedApiKeys` issues a credential against the hosted account API; a self-hosted console
   * has no hosted account, so the form must be absent rather than present-and-failing. This
   * is also what makes "re-home it onto the console's own route" the wrong move: there is no
   * such surface there to re-home onto. */
  await stubConsoleApi(page)
  await signedIn(page)

  await page.goto('/#agents')

  // the page itself is there, so this is not asserting against a blank screen
  await expect(page.getByRole('heading', { name: 'Bring an agent into Cortex' })).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Create API key', exact: true }),
    'a self-hosted console is offering to issue a hosted credential it has no account for',
  ).toHaveCount(0)
})
