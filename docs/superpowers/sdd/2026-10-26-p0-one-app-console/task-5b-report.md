# Task 5b report — One app root, and the landing knows its edition

Branch `docs/account-registration-design`. Two commits on top of `7af9f08`: `1d07f89` (the four
deliverables and the three rulings) and `096a205` (review follow-up: the Ruling C consumer test,
the measured no-request claim, the hosted-landing sweep, the `?raw` declaration read). HEAD is
`096a205`. No Python file touched; no route added.
`ManagedApp.tsx`, `ManagedLenses.tsx` and `managed.css` are all still on disk, now referenced by nothing.

---

## 1. One app root

`viewer/src/main.tsx` — the `managed` constant and the conditional import are gone. `boot()` now
imports `./console/ConsoleApp.tsx` and renders it, unconditionally. There is no component branch
left in the file, and no reference to `VITE_CORTEX_EDITION`.

Evidence beyond reading it: the production bundle no longer contains the second UI at all.

```
dist/assets/console-nvaG3dRu.css             59.22 kB
dist/assets/ConsoleApp-CTVxnoPY.js          366.18 kB
dist/assets/vendor-0kOT9XM8.js            1,219.65 kB
```

One app chunk. `managed.css` and `ManagedApp` are not in the graph.

`VITE_CORTEX_EDITION` still selects CONFIGURATION, in a new module:

- `viewer/src/console/edition.ts` — `editionOf(flag, pathname)` (pure, both inputs passed in) and
  `edition()` (reads `import.meta.env.VITE_CORTEX_EDITION` and `location.pathname`).
  `managed` when the flag says so, or when the path is `/managed` (any number of trailing slashes).

The pathname is kept deliberately, and this is the one judgement call worth flagging: all three
hosted images (`deploy/{managed,render,railway}/Dockerfile`) set `VITE_CORTEX_EDITION=managed`, so
in production the flag alone decides. The path clause preserves exactly today's predicate, which is
what keeps `/managed` hosted-correct for a build without the flag (including the e2e dev server).
It selects configuration — landing copy, and whether to ask the hosted account API who this browser
is — never a component. If you want the path clause gone, it is two lines in one function and the
unit tests pin the behaviour either way.

## 2. Consuming the declaration

`viewer/src/console/ConsoleApp.tsx` is now the only root. On a hosted-edition boot it asks
`GET /api/managed/me` once, resolves the answer with `workspaceSession` (see Ruling C), and passes
`destinations` and `hosted` into `ConsoleProvider`. On a self-hosted boot it makes **no request at
all**: `me` starts at `null` and never moves.

The resolved list reaches every consumer the plan names, from the single source in console state:

| consumer | file | call |
| --- | --- | --- |
| `parseRoute` (initial + `hashchange` + re-resolve when the declaration lands) | `state.tsx` | `parseRoute(hash, builtFrom(destinations))` |
| `primaryDestinations` (rail and top bar) | `Shell.tsx` | `primaryDestinations(destinations)` |
| `destinationsIn` + the phone tab bar | `Phone.tsx` | `destinationsIn(group, destinations)`, `destinations.find(...)` |
| `tabsFor` | `pages/PageHost.tsx` | `tabsFor(page, destinations)` |

`Phone.tsx` no longer imports `DESTINATIONS` at all. No file keeps a second copy of the list.

`state.tsx` gained one `useEffect` that re-parses the hash when `built` changes — the declaration is
fetched, so it can narrow after the first render, and without this a hosted boot at `#operations`
would briefly resolve against the wrong set.

## 3. The narrowed list reaches the tab strip (Review Focus item 5)

`PageTabs` takes `destinations` out of `useConsole()` and calls `tabsFor(page, destinations)`.
Red-first proof is below; this is the check that was seen red and then made to pass.

## 4. The landing

`Landing.tsx` is **unmodified**. Its `managed` prop survives and is now passed by the console itself.

---

## Ruling A — `managed` survives as configuration

Implemented, and the ruling was right. `Landing` keeps the prop; the console passes `managed` when
`edition() === 'managed'`. Nothing forked: there is one `Landing` and one caller shape. A hosted
visitor still gets "Managed memory for agents", "An isolated workspace for recording agent
memories…", "Open your workspace", "Hosted memory, clear boundaries", the hosted primitives and the
hosted facts — all eight branch points, unchanged, because the file is untouched.

**Named before a reviewer finds it:** `ConsoleApp` chooses between `<HostedLanding>` and
`<SignIn>`/`<Landing>` by edition, so on the SIGNED-OUT path the edition does select a component.
The plan's "configuration only" clause is written about `main.tsx`, and that file now has no branch
at all — but the clause is not literally scoped to it. I did not restructure this, because
hosted-only content (prices, plan cards, an account form against `/api/managed/*`) has to be
conditional somewhere, and a single `edition()` read at the root is the smallest place to put it.
Everything below the root is one component tree for both editions.

## Ruling B — the hosted landing's children are re-homed

New file: `viewer/src/console/HostedLanding.tsx`. It renders `<Landing managed>` with the hosted
children, so 5c can delete `ManagedApp` without the hosted signed-out page losing anything:

- the pricing section (`id="pricing"`, eyebrow `Managed memory`, heading `Choose the capacity you need`);
- the plan cards, built from **Task 3's** `planRows` / `Plan` and Task 3's `BILLING_UNAVAILABLE`
  string from `console/billing.ts`. There is no second plan-formatting implementation: the prices,
  the limit labels and the "Paid subscriptions are not available yet." note all come from the same
  module the signed-in Billing page uses, so the two surfaces cannot word a plan differently;
- `New workspace registration is not available yet.`, the monthly-limits note, and the auth
  messages (error/notice, `aria-live="polite"`), including the `?verified` message and the
  "email is not verified yet" mapping;
- the account forms.

No `xc-managed-*` class, and no new CSS: the section reuses `xc-landing-section`, `xc-landing-grid`,
`xc-landing-h2`, `xc-win xc-landing-card`, `xc-eyebrow`, `xc-title`, `xc-kv`, `xc-copy`, `xc-note`,
`xc-callout`, `xc-field`, `xc-input`, `xc-btn`. `grep -rn "xc-managed-" viewer/src` matches only
`ManagedApp.tsx`, `ManagedLenses.tsx` and `managed.css` — the three files 5c deletes. (I had written
that literal into a comment; removed, because it would have survived 5c's grep.)

**Where Ruling B understated the work, and I went further.** The ruling lists "the auth messages".
The messages alone would have left the hosted signed-out page with no way in, because the console's
own `SignIn` speaks `/api/auth/{login,signup,…}` and **the managed backend does not serve those
routes** — `managed/api.py`'s route table has `/api/managed/{login,signup,logout,recovery/{action}}`
and no `/api/auth/*` at all. So `HostedLanding` carries the account form too: the same five modes
(sign in, create workspace, forgot password, resend verification, set a new password from a
`?reset_token` link), posting to the same `/api/managed/*` paths, with the same copy. Without it
5c would have shipped a hosted deployment nobody could sign in to. Saying so plainly as asked: the
ruling's enumeration of the children was incomplete, not wrong.

Consequently `ConsoleApp` never shows the console `SignIn` on a hosted boot, and `signOut` also
POSTs `/api/managed/logout` with the `csrf_token` from `me` when the session is hosted — otherwise
the hosted cookie would survive and the user would be signed straight back in.

## Ruling C — the capability gate is an explicit session signal

`hostedWorkspace.ts` now separates the two questions 5a had conflated:

```ts
export function workspaceSession(me: HostedMe | null): WorkspaceSession {
  if (!me) return { hosted: false, destinations: DESTINATIONS, fault: null }
  const destinations = destinationsFrom(me.destinations)
  return { hosted: true, destinations, fault: offersHostedWorkspace(destinations) ? null : BILLING_UNDECLARED }
}
```

- `hosted` is true because the hosted account API **answered**, never because of what it listed. It
  reaches `AgentsPage` (`{hosted && <HostedApiKeys />}`) and `MemoriesPage` (the export button)
  through `useConsole()`. A hosted deployment that stopped declaring `billing` keeps both.
- `offersHostedWorkspace` is unchanged and still exported; its call site is now the *declaration*
  check inside `workspaceSession`, which is precisely the check the ruling asked for. Its three
  existing unit tests still pass untouched.
- The fault is not silent: `ConsoleApp` logs it with `console.error`, and it is asserted by tests.
  No banner, no new gating framework — one boolean plus one string.
- **The defect Ruling C named was "no failing test", so there is now one at the consumers.** New
  e2e `hosted capabilities survive a declaration that dropped billing` drives a hosted fixture
  declaring `['graph','memories','agents','settings']` — a hosted deployment that stopped declaring
  `billing` — and asserts the API-key control is on `#agents`, the export control is on
  `#memories`, and Billing is absent from the tab strip. Proved red by temporarily restoring 5a's
  gate in both pages (verbatim below). Issuance and download behaviour stay 5c's.

The declaration check reads the **real** declaration rather than a copy of it:
`declaredDestinations(source)` pulls `MANAGED_DESTINATIONS` out of
`src/xibalba_cortex/managed/api.py` with a regex, and `edition.test.ts` asserts it still contains
`billing`, that every id resolves through `ALL_DESTINATIONS`, and — by mutating the *string*, never
the file — that a declaration which dropped `billing` raises the fault. Nothing in Python is
modified; the file is only read — through Vite's `?raw` import rather than `node:fs`, so no node
types are needed and `tsconfig.app.json` is unchanged.

**Correction (fix round 1).** This report previously claimed the `?raw` path is "checked at compile
time". That is false, and the reviewer proved it by mutation: a bogus path leaves
`tsc --noEmit -p tsconfig.app.json` at exit 0 — that config does not resolve it — while `vitest`
fails the suite with "no tests". The guard is sound; its mechanism is the test run, not the
typechecker.

---

## Self-hosted behaviour is unchanged — proved, not asserted

1. **No new code path runs, and this is now MEASURED rather than read.** `edition()` returns
   `self-hosted` for `/`, so `me` is initialised to `null` and `ConsoleApp` issues no
   `/api/managed/*` request of any kind. `workspaceSession(null)` returns `DESTINATIONS` —
   object-identical to the constant the defaults used before. The self-hosted e2e now installs
   `managedFixture(page)` purely as a recorder before `openConsole` and asserts
   `expect(calls).toEqual([])`. The same recorder sees `me` in every hosted test in the file, so an
   empty list is a measurement, not a dead route.
2. **Every default argument still resolves to the same list.** `nav.test.ts` is unmodified and
   green, including `tabsFor('settings')` → `['settings','operations','agents']` and
   `DESTINATIONS.some(billing) === false`.
3. **A behavioural check, written to be able to fail.** New e2e
   `a server that declares nothing keeps every built destination`: the self-hosted console at
   `#settings` must still show an **Operations** tab and still show **no Billing** tab. It was red
   in its first run (see below) for a reason of its own, and is green now.
4. **The full self-hosted regression suites are green and unchanged**: `console.spec.ts` 49/49,
   `landing.spec.ts` 10/10, `auth.spec.ts` 14/14, `phone.spec.ts` 6/6 — not one of those files was
   edited.

---

## Red-first evidence

### Route 1 — the unit modules did not exist (verbatim)

```
 RUN  v5.0.3 /mnt/storage/.../viewer

 ❯ src/console/edition.test.ts (0 test)

⎯⎯⎯⎯⎯⎯ Failed Suites 1 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/console/edition.test.ts [ src/console/edition.test.ts ]
Error: Cannot find module './edition' imported from /mnt/storage/.../viewer/src/console/edition.test.ts
 ❯ src/console/edition.test.ts:5:1
      3| import { describe, expect, it } from 'vitest'
      4| import { ALL_DESTINATIONS, DESTINATIONS, destinationsFrom } from './na…
      5| import { editionOf, HOSTED_PATH } from './edition'
       | ^
      6| import { BILLING_UNDECLARED, declaredDestinations, workspaceSession } …

 Test Files  1 failed (1)
      Tests  no tests
```

### Route 2 — Review Focus item 5, red against the real `PageHost` (verbatim)

The boot change was in place and `PageTabs` still called `tabsFor(page)` with the default list:

```
Running 2 tests using 1 worker
  ✘  1 [desktop] › e2e/managed.spec.ts:94:1 › a hosted tab strip drops the peers the server did not declare (18.3s)
  ✓  2 [desktop] › e2e/managed.spec.ts:117:1 › a server that declares nothing keeps every built destination (4.4s)

  1) [desktop] › e2e/managed.spec.ts:94:1 › a hosted tab strip drops the peers the server did not declare

    Error: expect(locator).toBeVisible() failed

    Locator: locator('.xc-page-tabs').getByRole('button', { name: 'Billing', exact: true })
    Expected: visible
    Timeout: 15000ms
    Error: element(s) not found

       99 |   await expect(tabs.getByRole('button', { name: 'Settings', exact: true })).toBeVisible()
      100 |   await expect(tabs.getByRole('button', { name: 'Agents', exact: true })).toBeVisible()
    > 101 |   await expect(tabs.getByRole('button', { name: 'Billing', exact: true })).toBeVisible()
          |                                                                            ^
```

The default list produced a strip with **Operations** (undeclared, a tab to nowhere) and **no
Billing** (declared, unreachable) — both halves of item 5, on the real server-declared list.
Threading `destinations` into `PageTabs` turned it green.

An earlier run of the same pair also caught my own test being wrong — the self-hosted case had been
written as a bare `page.goto('/#settings')`, which lands signed out:

```
  2) [desktop] › e2e/managed.spec.ts:116:1 › a server that declares nothing keeps every built destination
    Error: expect(locator).toBeVisible() failed
    Locator: locator('.xc-page-tabs').getByRole('button', { name: 'Operations', exact: true })
    Expected: visible
    Error: element(s) not found
```

Fixed by using `openConsole(page, { hash: 'settings' })`, the helper the rest of the suite uses.
That is a genuinely-failing-then-passing check, not a mutation.

### Route 2b — Ruling C at the consumers, red under 5a's gate (verbatim)

`AgentsPage` and `MemoriesPage` temporarily reverted to `offersHostedWorkspace(destinations)`:

```
Running 1 test using 1 worker
  ✘  1 [desktop] › e2e/managed.spec.ts:147:1 › hosted capabilities survive a declaration that dropped billing (16.0s)

    Error: expect(locator).toBeVisible() failed

    Locator: getByRole('heading', { name: 'Connect an agent with an API key' })
    Expected: visible
    Timeout: 15000ms
    Error: element(s) not found

      148 |   await managedFixture(page, { signedIn: true, destinations: ['graph', 'memories', 'agents', 'settings'] })
      149 |   await page.goto('/managed#agents')
    > 150 |   await expect(page.getByRole('heading', { name: 'Connect an agent with an API key' })).toBeVisible()
```

Both files were restored from a copy taken before the mutation and the test is green; the committed
tree contains no trace of it.

### Route 2c — the sweep's rewritten signed-in pin, proved able to fail (verbatim)

The guard's pin was changed (see the `managed.spec.ts` section), so it had to be shown it can still
fail. Run once with a SIGNED-OUT fixture, at 1280px:

```
  ✘  1 [desktop] › e2e/design-system.spec.ts:727:3 › the hosted workspace keeps its grammar at 1280px (17.8s)

    Error: expect(locator).toBeVisible() failed

    Locator: getByRole('button', { name: 'Sign out' }).or(getByRole('button', { name: 'Open operator profile settings' })).first()
    Expected: visible
    Timeout: 15000ms
    Error: element(s) not found

      732 |     const account = page.getByRole('button', { name: 'Sign out' })
      733 |       .or(page.getByRole('button', { name: 'Open operator profile settings' }))
    > 734 |     await expect(account.first()).toBeVisible()
```

The landing is swept instead of the workspace exactly when the session breaks, which is what the
pin exists to prevent. Reverted immediately.

### Route 3 — mutation, for the declaration guard

`billing` cannot be removed from `api.py` to prove the guard (no Python may be touched), so the
guard is proved against a mutated **copy of the source string** inside the test:
`MANAGED_SOURCE.replace('"billing")', ')')` → `declaredDestinations` no longer reports `billing` →
`workspaceSession(...).fault === BILLING_UNDECLARED`. The test also asserts the mutation actually
changed something, and that a source with no declaration throws rather than reading as empty (which
would have passed vacuously).

---

## Verbatim passing output, with counts

**Unit (vitest), whole suite:**
```
 Test Files  32 passed (32)
      Tests  347 passed (347)
```
(14 of those are the new `src/console/edition.test.ts`; the 32 files include `nav.test.ts` and
`hostedWorkspace.test.ts`, both unmodified.)

**`e2e/managed.spec.ts`** — 11 tests, 9 passed, 2 deliberately `fixme` (see below):
```
Running 11 tests using 1 worker
  ✓   1 managed plans show the approved catalog without overflow at 320px (5.2s)
  ✓   2 managed plans show the approved catalog without overflow at 390px (2.4s)
  ✓   3 managed plans show the approved catalog without overflow at 1280px (2.4s)
  ✓   4 managed plans show the approved catalog without overflow at 1600px (2.5s)
  ✓   5 signup requires verification and never grants an immediate signed-in workspace (2.8s)
  -   6 a workspace stores and searches memory, then creates and revokes an API key
  ✓   7 choosing a paid plan uses Checkout; an existing paid plan changes through the portal (9.9s)
  -   8 read-only subscriptions retain export and search without permitting writes
  ✓   9 a hosted tab strip drops the peers the server did not declare (7.7s)
  ✓  10 a hash route for an undeclared destination opens no page (11.7s)
  ✓  11 a server that declares nothing keeps every built destination (4.0s)

  2 skipped
  9 passed (56.6s)
```

**`console.spec.ts` + `landing.spec.ts` + `auth.spec.ts`** (one invocation, 73 tests):
```
  Slow test file: [desktop] › e2e/console.spec.ts (5.3m)
  73 passed (6.5m)
```
Per file, from the same output: `console.spec.ts` **49 passed**, `landing.spec.ts` **10 passed**,
`auth.spec.ts` **14 passed**. The 49 is the self-hosted regression proof asked for, intact.

**`design-system.spec.ts -g "hosted workspace"`** — 3 tests, green (one line changed, below):
```
Running 3 tests using 1 worker
  ✓  1 the hosted workspace keeps its grammar at 390px (3.7s)
  ✓  2 the hosted workspace keeps its grammar at 1280px (2.6s)
  ✓  3 the hosted workspace keeps its grammar at 1600px (2.4s)

  3 passed (12.0s)
```

**`design-system.spec.ts -g "hosted landing"`** — new, 2 tests × 2 sweeps each (form closed, then
opened), green with no UI fix needed. `HostedLanding` is new UI that no sweep had seen: the existing
hosted sweep runs signed in, and `landing.spec.ts` sweeps `/`, which is the self-hosted copy.
```
  ✓  1 the hosted landing keeps its grammar at 390px (4.3s)
  ✓  2 the hosted landing keeps its grammar at 1280px (3.6s)
  ✓  3 the hosted workspace keeps its grammar at 390px (3.3s)
  ✓  4 the hosted workspace keeps its grammar at 1280px (2.7s)
  ✓  5 the hosted workspace keeps its grammar at 1600px (2.7s)

  5 passed (22.7s)
```

**`phone.spec.ts`** (phone project, 6 tests):
```
  6 passed (26.2s)
```

**The whole suite, one fresh run with no edits in flight** (`--project=desktop`, then
`--project=phone`). This is also 5c's final check, so anything red here would have been 5b's:
```
  2 skipped
  183 passed (15.1m)
```
```
  6 passed (30.3s)
```
183 desktop passed, 0 failed, 2 skipped — the two `test.fixme` below and nothing else. Every spec
in `e2e/` ran: console, landing, auth, managed, design-system, actions, workspace-header,
lens-chrome, operations, chain-rail, detail-dock, graph-settings, timeline-marks, collapsed-logo.

**Typecheck:** `npx tsc --noEmit -p tsconfig.app.json` — clean, no output.
**Lint:** `npm run lint` — 13 warnings, exit 0; the same 13 as before this change (PageDrawer,
state.tsx, settingsContext, Graph3D ×4, GraphLens, capture.mjs, Shell ×2, VerifyPanel, TimelineLens).
No new file produces a warning.
**Build:** `npm run build` (`tsc -b && vite build`) — `✓ built in 2.81s`, four chunks, no
second-UI chunk.

Playwright was run with `E2E_ANCHOR_PORT=28451 E2E_API_PORT=28440 E2E_UI_PORT=25200`, a scratch
`E2E_CORTEX_HOME`, `E2E_PYTHON` pointed at the worktree `.venv`, and a `uv` shim on `PATH` kept
outside the repo (vite.config.ts shells out to `uv run xibalba-cortex-ingest-tokens`, which cannot
resolve `../integrity-core` from a worktree). No process was killed. Every count above is from real
`Running N tests` / `N passed` lines, not from an exit code.

---

## `managed.spec.ts`: what failed for a real reason, and what I did

`/managed` now renders the console, so four of its five original tests failed honestly. First run,
after the boot change (11 tests): `4 failed, 7 passed`.

1. **`managed plans … at 320/390/1280/1600px` (4 tests) — still green, unchanged.** The re-homed
   hosted pricing section satisfies them as written: `article` named `"Free plan"` / `"Pro plan"` /
   `"Team plan"` containing `$0` / `$29` / `$149`, `#pricing`, a disabled `Choose Pro`, the
   `Paid subscriptions are not available yet.` note, and `.xc-landing` with no horizontal overflow
   at 320px. This is the strongest single piece of evidence that Ruling B landed correctly.
2. **`signup requires verification …` — failed at `page.locator('.xc-managed-auth form')`** (timeout
   on `locator.fill`). That class was the second UI's, so the locator became
   `page.locator('#hosted-auth form')`.

   **Correction (fix round 1): the claim "every assertion is the one that was there" was wrong on
   one point, and the reviewer was right to call it.** The last assertion,
   `expect(getByRole('heading', { name: 'Operator’s memory' })).toHaveCount(0)`, targeted
   `ManagedApp.tsx:177` — rendered by nothing after this change — so it could no longer fail. The
   test was half-vacuous, not dead: `calls.filter(path === 'login')` still bit. See the fix-round
   section at the end of this report for the re-pointing and its red proof.
3. **`choosing a paid plan uses Checkout; …` — failed at `Choose Pro`** (timeout on `locator.click`).
   Plans for a signed-in hosted workspace are Task 3's Billing page now. **Two lines changed**:
   `goto('/managed')` → `goto('/managed#billing')`, twice. `planAction` produces the same two
   labels, so both halves (`checkout` with `{plan:'pro'}`, then `portal` with no `checkout` call)
   assert unchanged and pass.
4. **`a workspace stores and searches memory, then creates and revokes an API key` — `test.fixme`.**
   Every locator names the second UI's own DOM: its single write form, `.xc-managed-results`,
   `.xc-managed-key`. These are the key/export assertions 5b was told not to re-point. Nothing was
   deleted or weakened; the test body is intact behind `fixme`, with a comment naming 5c and saying
   where 5a re-homed each capability.
5. **`read-only subscriptions retain export and search …` — `test.fixme`,** same reason:
   `Save memory`, `Search / list` and `Export memories` were three controls on one managed screen;
   on the console the write and the export live on Memories and read-only comes from the workspace's
   own writability. Re-pointing is 5c's, with its behavioural coverage.

**One further honest fix, in `e2e/design-system.spec.ts`.** The "hosted workspace" guard went red at
1280px and 1600px — `getByRole('button', { name: 'Sign out' })` **not found** — and green at 390px.
That is not a grammar failure and not the consolidation: the spec's own comment assumed "the console
shell" renders a `Sign out` button, and only two of its three layouts do (`Actions`, in the phone
layout and the top-bar layout). The console's **default** desktop layout is the rail, which puts the
session in the rail foot as `ProfileButton` with **Log out** in its menu. The assertion's purpose is
to pin the signed-in screen, so it now accepts the account control in either grammar
(`Sign out` **or** `Open operator profile settings`) and is still non-vacuous: the landing has a
`Sign in` button and neither control, so it still fails there. The `grammarSweep` itself passed at
all three widths with nothing changed in the UI.

**Fixture fidelity, not re-pointing:** `e2e/managed-fixture.ts`'s `me` had no `destinations`, so a
hosted session would have resolved to the self-hosted set — testing a deployment that does not
exist, and tripping the new fault. It now returns the seven ids `MANAGED_DESTINATIONS` declares,
overridable per test.

---

## Concerns

In the order they matter.

1. **VERIFIED, AND THE MOST SERIOUS: on a real hosted deployment the console's data calls will 404,
   and that regression lands in 5b, not 5c.** Primary evidence:
   - `grep -n VITE_ deploy/*/Dockerfile` returns only `VITE_CORTEX_EDITION=managed`, in all three
     images. No hosted image sets `VITE_LOCAL_API_URL`, and a production build's
     `DEFAULT_BASE_URL` is `''` — the page's own origin.
   - `managed/api.py`'s SPA handler: `if request.url.path.startswith("/api/"): return
     JSONResponse({"error": "Unknown managed API route"}, status_code=404)`. So `/api/status`,
     `/api/graph`, `/api/memories`, `/api/sessions` — everything `loadConsoleData` asks for — 404.

   Before this commit `/managed` rendered `ManagedApp`, which only ever called `/api/managed/*`,
   and worked. From this commit `/managed` renders the console: the shell comes up and Billing, the
   API keys and the export work (all `/api/managed/*`), but Graph, Timeline, Explore, Operations
   and the status bar have no backend. A 404 does not match the console's `EXPIRED` regex, so the
   user is not bounced to sign-in — they sit on an error state.

   **Every "hosted" e2e in this task is a hybrid that does not exist in production**: the Vite dev
   proxy supplies a real `local_api` at `/cortex-api`, so the console's data calls succeed under
   test and cannot see this. The plan forbids touching the managed backend, so closing it is either
   a backend task or pointing the hosted build at a local_api. Whoever owns the Render pilot should
   decide before `/managed` is deployed from this branch. If the answer is "not yet", 5c is still
   safe to run — nothing here depends on it — but the pilot deploy is not.

2. **I edited a guard the brief said must stay green** — `design-system.spec.ts`'s hosted-workspace
   sweep — and 5c's brief says "fix the UI, never the sweep". What failed was the spec's *pin*, not
   the grammar: it asserted a visible `Sign out`, which the console renders in two of its three
   layouts (phone, top bar) but not in its default desktop rail, where the session lives in
   `ProfileButton` with **Log out** in its menu. The alternative was adding a visible Sign out to
   the rail — changing self-hosted UI to satisfy a test. The pin now accepts either grammar, and
   was proved able to fail (Route 2c above): signed out, it is red. `grammarSweep` itself needed no
   UI change at any width. Flagging it because it is the one check someone else owns that I touched.

3. **5c's gate says "the rail lists Billing". It will not.** `primaryDestinations` resolves
   `PRIMARY_NAV` (`graph, memories, recall, review, integrity`) and `billing` is not in it — by
   design, since Task 2 capped the rail at five. On hosted the rail shows Workspace / Explore /
   Recall; Billing is reached by `#billing`, by the Settings tab strip (which this task made work),
   or on the phone under **More**. 5c needs to assert one of those, or `PRIMARY_NAV` needs a
   deliberate change — a navigation decision, not a test fix.

4. **A hosted `me` that fails with 500 rather than 401 is treated as "no session".**
   `hostedRequest` does not carry a status, so a transient server error sends a signed-in hosted
   user to the landing instead of showing an error; `ManagedApp` distinguished the two. Review
   Focus item 3's *list* half is handled (a hosted answer with no list falls back to every `BUILT`
   destination and reports the fault); the *request-failed* half degrades to the landing. Fixing it
   means giving `hostedRequest` a status, which is a 5a-interface change; flagging rather than doing.

5. **Two places where the edition still informs anything**, both named above: `editionOf`'s
   pathname clause (deliverable 1) and the signed-out component choice in `ConsoleApp` (Ruling A).
   `main.tsx` itself has no branch.

---

# Fix round 1 — closing two coverage holes

Commit `3a4babb`, on top of `096a205`. **Test-only.** No `src/` file is modified by this
round; `Shell.tsx` and `Phone.tsx` were mutated for the red proof and restored byte-exact
(`git diff` on both is empty). The two findings routed to 5d (the missing managed-entitlement write
gate, the lost `Idempotency-Key`) and the four Minors are untouched, and the
`read-only subscriptions…` `test.fixme` is left in place as the only artefact in the repo pointing
at the entitlement gap.

## Fix 1 — the rail and the phone had no executable coverage

The review's mutation was the right one and the hole was real: reverting both
`primaryDestinations(destinations)` sites in `Shell.tsx` and all four list reads in `Phone.tsx` to
the default list left every suite green. On a production hosted build that mutation puts **Review**
and **Integrity** on the rail — destinations `MANAGED_DESTINATIONS` does not declare, whose
surfaces call bare `/api/*` — so it is Review Focus item 5 one level above the tab strip, and
nothing would have caught its reintroduction.

Closed in `e2e/managed.spec.ts`, no new file:

- `a hosted tab strip drops the peers the server did not declare` now also asserts the **rail**:
  `Workspace`, `Explore` and `Recall` visible (three of `PRIMARY_NAV`'s five), `Review` and
  `Integrity` at count 0. `NavButton` carries `aria-label={dest.label}` unconditionally, so these
  are exact accessible names at any rail width.
- New `the hosted phone layout lists only the declared destinations` — same spec, viewport set to
  390×844 so `PhoneWorkspace` renders. `review` is in the phone's own `PRIMARY` four and is not
  declared by a hosted server, which makes the tab bar the sharpest probe; the **More** sheet then
  covers `destinationsIn(group, destinations)`, with `Billing` present and `Review`, `Integrity`
  and `Operations` absent.

### Red under the review's own mutation (verbatim)

Both `primaryDestinations(destinations)` sites reverted to `primaryDestinations()`, and `Phone.tsx`
back to `DESTINATIONS` / `destinationsIn(group)`:

```
Running 2 tests using 1 worker

  ✘  1 [desktop] › e2e/managed.spec.ts:112:1 › a hosted tab strip drops the peers the server did not declare (19.8s)
  ✘  2 [desktop] › e2e/managed.spec.ts:140:1 › the hosted phone layout lists only the declared destinations (18.5s)

  1) [desktop] › e2e/managed.spec.ts:112:1 › a hosted tab strip drops the peers the server did not declare

    Error: expect(locator).toHaveCount(expected) failed

    Locator:  locator('.xc-rail-nav').getByRole('button', { name: 'Review', exact: true })
    Expected: 0
    Received: 1
    Timeout:  15000ms

    Call log:
      - Expect "toHaveCount" locator('.xc-rail-nav').getByRole('button', { name: 'Review', exact: true }) with timeout 15000ms
      - waiting for locator('.xc-rail-nav').getByRole('button', { name: 'Review', exact: true })
        31 × locator resolved to 1 element
           - unexpected value "1"

      129 |   await expect(rail.getByRole('button', { name: 'Explore', exact: true })).toBeVisible()
      130 |   await expect(rail.getByRole('button', { name: 'Recall', exact: true })).toBeVisible()
    > 131 |   await expect(rail.getByRole('button', { name: 'Review', exact: true })).toHaveCount(0)
          |                                                                           ^

  2) [desktop] › e2e/managed.spec.ts:140:1 › the hosted phone layout lists only the declared destinations

    Error: expect(locator).toHaveCount(expected) failed

    Locator:  locator('.xc-tabbar').getByRole('button', { name: 'Review', exact: true })
    Expected: 0
    Received: 1
    Timeout:  15000ms
```

`Review` on the hosted rail, exactly as the review predicted. Both files were then restored from
copies taken before the mutation; `git diff src/console/Shell.tsx src/console/Phone.tsx` prints
nothing, and both tests are green in the run below.

## Fix 2 — the half-vacuous absence assertion

The review is right and my earlier claim was wrong. In `signup requires verification…`,
`expect(getByRole('heading', { name: 'Operator’s memory' })).toHaveCount(0)` named
`ManagedApp.tsx:177`, which nothing renders after `1d07f89`, so that half could no longer fail.
(`calls.filter(path === 'login')` still bit, so the test was half-vacuous, not dead.) The report's
"every assertion is the one that was there" sentence is corrected in place, above.

Re-pointed at the console's own signed-in markers:

```ts
await expect(page.locator('.xc-workspace')).toHaveCount(0)
await expect(page.getByRole('button', { name: 'Open operator profile settings' })).toHaveCount(0)
```

`Sign out` was deliberately **not** used: the console renders it only in the phone and top-bar
layouts, so at the desktop project's 1440px width it is absent from a signed-in console too, and
asserting its absence would have replaced one vacuous check with another. `.xc-workspace` and the
rail's account control are both present on a signed-in console at every non-phone width.

### Proving the new form can fail — and a trap found while doing it

First attempt: switch the test's fixture to `signedIn: true`. That went red, but at
`form.getByLabel('Name')` — it never reached the assertions under test, so it proved nothing about
them. Second attempt, a temporary probe running only the two assertions against a signed-in hosted
console, **passed** — because `toHaveCount(0)` is satisfied instantly by a DOM that has not booted
yet. `page.goto()` returns before the lazily-imported console chunk and the hosted `me` call have
rendered anything.

**So an absence assertion placed immediately after `goto` is vacuous by construction, whatever it
names.** With a positive wait first, the probe is red:

```
Running 1 test using 1 worker

  ✘  1 [desktop] › e2e/managed.spec.ts:198:1 › PROBE the signed-in markers (18.8s)

    Error: expect(locator).toHaveCount(expected) failed

    Locator:  locator('.xc-workspace')
    Expected: 0
    Received: 1
    Timeout:  15000ms

    Call log:
      - Expect "toHaveCount" locator('.xc-workspace') with timeout 15000ms
      - waiting for locator('.xc-workspace')
        34 × locator resolved to 1 element
           - unexpected value "1"

      200 |   await page.goto('/managed')
      201 |   await expect(page.locator('.xc-rail-nav')).toBeVisible()
    > 202 |   await expect(page.locator('.xc-workspace')).toHaveCount(0)
          |                                               ^
```

The probe was deleted (`grep -c PROBE e2e/managed.spec.ts` → 0). In its real position the
assertion is safe: it runs after `expect(getByText('Check your email for a verification link.'))
.toBeVisible()`, so the hosted landing has definitively rendered. Every absence assertion added in
this round sits behind a positive wait on the same layout, for the same reason — the rail
absences follow three `toBeVisible()` checks on rail buttons, the phone's follow three on tab-bar
buttons and one on a More entry.

## Verbatim results, with counts

`npx playwright test e2e/managed.spec.ts --project=desktop` — 13 declared, **11 passed, 2 skipped**
(the two 5c `test.fixme`), 0 failed:
```
  ✓   1 managed plans show the approved catalog without overflow at 320px (3.6s)
  ✓   2 managed plans show the approved catalog without overflow at 390px (2.2s)
  ✓   3 managed plans show the approved catalog without overflow at 1280px (2.4s)
  ✓   4 managed plans show the approved catalog without overflow at 1600px (2.8s)
  ✓   5 signup requires verification and never grants an immediate signed-in workspace (2.9s)
  ✓   7 choosing a paid plan uses Checkout; an existing paid plan changes through the portal (7.1s)
  ✓   9 a hosted tab strip drops the peers the server did not declare (4.5s)
  ✓  10 the hosted phone layout lists only the declared destinations (3.0s)
  ✓  11 a hash route for an undeclared destination opens no page (7.4s)
  ✓  12 a server that declares nothing keeps every built destination (3.6s)
  ✓  13 hosted capabilities survive a declaration that dropped billing (3.0s)

  2 skipped
  11 passed (47.4s)
```

`npx playwright test e2e/design-system.spec.ts -g "hosted" --project=desktop` — **5 passed**:
```
  ✓  1 the hosted landing keeps its grammar at 390px (4.1s)
  ✓  2 the hosted landing keeps its grammar at 1280px (3.5s)
  ✓  3 the hosted workspace keeps its grammar at 390px (3.1s)
  ✓  4 the hosted workspace keeps its grammar at 1280px (2.9s)
  ✓  5 the hosted workspace keeps its grammar at 1600px (3.1s)

  5 passed (22.7s)
```

`npx playwright test e2e/phone.spec.ts --project=phone` — **6 passed**:
```
  6 passed (26.5s)
```

`npx playwright test e2e/console.spec.ts --project=desktop` — **49 passed**, including the wiring
tour (`a tour of every lens, tool and dialog draws no 404, 405 or 5xx`):
```
  49 passed (5.8m)
```

`npx vitest run`:
```
 Test Files  32 passed (32)
      Tests  347 passed (347)
```

`npx tsc --noEmit -p tsconfig.app.json`, run **unpiped** so `$?` is the typechecker's:
```
TSC_EXIT=0
```
(no diagnostics printed)

`npm run lint`:
```
LINT_EXIT=0
```
13 warnings, the same 13 as before any of this work, none in a file this round touched.

Same environment as before: `E2E_ANCHOR_PORT=28451 E2E_API_PORT=28440 E2E_UI_PORT=25200`, scratch
`E2E_CORTEX_HOME`, `E2E_PYTHON` at the worktree `.venv`, and the `uv` shim kept in the session
scratchpad outside the repo. No process was killed.

## Concerns from this round

1. **New, and it generalises beyond this spec: `toHaveCount(0)` immediately after `page.goto` can
   never fail.** The console is a lazily-imported chunk, so the DOM is empty when `goto` resolves
   and any absence assertion passes on an empty document. Found while proving Fix 2 — my first
   probe passed for exactly this reason. Every absence assertion I added or re-pointed is now
   behind a positive wait, but nothing enforces that, and the pattern `goto` → `toHaveCount(0)`
   appears elsewhere in `e2e/` and is worth a sweep in its own right.
2. **The rail check is pinned to the rail layout.** `.xc-rail-nav` exists only when
   `settings.shell === 'rail'` (the default) at non-phone widths; the top-bar layout's `.xc-nav`
   is the other `primaryDestinations(destinations)` site and is still uncovered on hosted. The
   mutation proof covered both sites at once because reverting them both was one edit, but a
   mutation of the `TopBar` site alone would not be caught. Cheap to add if you want it —
   `Settings → Layout` switches the shell and `console.spec.ts:431` already drives that path.
3. Unchanged from the first report, and unaffected by this round: the hosted data-path 404
   regression (concern 1) remains the thing to decide before `/managed` is deployed from this
   branch.

---

# Fix round 2 — the last two mutations that still passed

**Test-only again.** The commit touches one file, `viewer/e2e/managed.spec.ts`. `Shell.tsx` and
`Phone.tsx` were each mutated at ONE call site for the isolated proofs and restored byte-exact;
`git diff` on both is empty and neither is in the commit. Nothing owed to 5c or 5d was touched, and
no Minor.

## Fix 1 — the TopBar site (my own concern b, confirmed)

Round 1's rail check pins `.xc-rail-nav`, which exists only when `settings.shell === 'rail'` — the
default — at non-phone widths. `Shell.tsx:267`'s `.xc-nav` is the other
`primaryDestinations(destinations)` site and was still uncovered on hosted.

New test `the hosted top-bar layout lists only the declared destinations`, in the same spec. It
seeds `xibalba-cortex.console-settings` to `{shell:'top',railCollapsed:false}` through
`addInitScript` and then asserts `.xc-nav` shows `Workspace` and `Explore` visible, with `Review`
and `Integrity` at count 0.

**I took the re-reviewer's shape, including seeding rather than clicking, and agree with it for a
reason worth stating:** driving `Settings → Layout` would make a navigation test depend on the
settings page too, so a regression in either would fail it and the message would not say which.
The key seeded is the very preference that page writes, and the clicking path is already covered by
`console.spec.ts:431` and its "writes through to the same stored preference" sibling. The seed is
wrapped in try/catch, so a browser with storage blocked keeps the default rail rather than throwing.

### Red under a TopBar-ONLY mutation (verbatim)

Only the `.xc-nav` line reverted — `grep -c` confirms one `primaryDestinations()` and one
`primaryDestinations(destinations)` left in the file, so the rail site is untouched:

```
Running 2 tests using 1 worker

  ✓  1 [desktop] › e2e/managed.spec.ts:112:1 › a hosted tab strip drops the peers the server did not declare (6.4s)
  ✘  2 [desktop] › e2e/managed.spec.ts:170:1 › the hosted top-bar layout lists only the declared destinations (18.2s)

  1) [desktop] › e2e/managed.spec.ts:170:1 › the hosted top-bar layout lists only the declared destinations

    Error: expect(locator).toHaveCount(expected) failed

    Locator:  locator('.xc-nav').getByRole('button', { name: 'Review', exact: true })
    Expected: 0
    Received: 1
    Timeout:  15000ms

    Call log:
      - Expect "toHaveCount" locator('.xc-nav').getByRole('button', { name: 'Review', exact: true }) with timeout 15000ms
      - waiting for locator('.xc-nav').getByRole('button', { name: 'Review', exact: true })
        34 × locator resolved to 1 element
           - unexpected value "1"

      177 |   await expect(nav.getByRole('button', { name: 'Workspace', exact: true })).toBeVisible()
      178 |   await expect(nav.getByRole('button', { name: 'Explore', exact: true })).toBeVisible()
    > 179 |   await expect(nav.getByRole('button', { name: 'Review', exact: true })).toHaveCount(0)
          |                                                                          ^
```

Note the first line: the round-1 rail test stayed **green** under this mutation, which is exactly
the hole. Restored byte-exact, both green in the run below.

## Fix 2 — the More-sheet absences, each seen red on its own

Mutating only `MoreList`'s `destinationsIn(group, destinations)` (the tab bar's two reads left
threaded) exposed two problems, one of them in my own test.

**First, one assertion was unfailable and is now gone.** `MoreList` filters out the phone's own
`PRIMARY` four (`graph, timeline, recall, review`), so `review` can never appear in the More sheet
whatever the server declares. My round-1 `more.getByRole('button', { name: /^Review/ })
.toHaveCount(0)` could not fail under any mutation. Saying it plainly as asked: that assertion was
decoration, and I removed it rather than leave it standing. Review's exclusion from the phone IS
reachable in the tab bar, where it is still asserted and where it was seen red in round 1.

**Second, assertion order was hiding the rest.** With `Billing` checked before the absences, a
mutation of this very site failed at `Billing` and the absences were never reached — which is how
they went unproven in round 1:

```
    Error: expect(locator).toBeVisible() failed
    Locator: locator('.xc-more').getByRole('button', { name: /^Billing/ })
    Expected: visible
    Error: element(s) not found
    > 157 |   await expect(more.getByRole('button', { name: /^Billing/ })).toBeVisible()
```

Reordered to `Memories` (the positive wait, listed either way) → the two absences → `Billing`. Each
absence then observed red on its own under the same single-site mutation, `Integrity` first:

```
    Error: expect(locator).toHaveCount(expected) failed

    Locator:  locator('.xc-more').getByRole('button', { name: /^Integrity/ })
    Expected: 0
    Received: 1
    Timeout:  15000ms

      160 |   await expect(more.getByRole('button', { name: /^Memories/ })).toBeVisible()
    > 161 |   await expect(more.getByRole('button', { name: /^Integrity/ })).toHaveCount(0)
          |                                                                  ^
```

and then `Operations`, by temporarily putting it first so it is the one that reports (the only way
to observe the second of two consecutive absences, since Playwright stops at the first failure):

```
    Error: expect(locator).toHaveCount(expected) failed

    Locator:  locator('.xc-more').getByRole('button', { name: /^Operations/ })
    Expected: 0
    Received: 1
    Timeout:  15000ms
```

Order restored, `Phone.tsx` restored byte-exact. So of the four More-sheet assertions: `Memories`
and `Billing` positive and both reachable, `Integrity` and `Operations` absences each individually
observed failing, and the unfailable `Review` one deleted.

Every absence assertion in this round still sits behind a positive wait on the same layout, for the
`goto`-then-`toHaveCount(0)` reason from round 1.

## Verbatim results, with counts

`npx playwright test e2e/managed.spec.ts --project=desktop` — **`Running 14 tests`, 12 passed,
2 skipped** (the two 5c `test.fixme`), 0 failed:
```
Running 14 tests using 1 worker
  ✓   1 managed plans show the approved catalog without overflow at 320px (3.3s)
  ✓   2 managed plans show the approved catalog without overflow at 390px (2.3s)
  ✓   3 managed plans show the approved catalog without overflow at 1280px (2.7s)
  ✓   4 managed plans show the approved catalog without overflow at 1600px (2.2s)
  ✓   5 signup requires verification and never grants an immediate signed-in workspace (2.5s)
  -   6 a workspace stores and searches memory, then creates and revokes an API key
  ✓   7 choosing a paid plan uses Checkout; an existing paid plan changes through the portal (7.8s)
  -   8 read-only subscriptions retain export and search without permitting writes
  ✓   9 a hosted tab strip drops the peers the server did not declare (3.6s)
  ✓  10 the hosted phone layout lists only the declared destinations (2.6s)
  ✓  11 the hosted top-bar layout lists only the declared destinations (3.3s)
  ✓  12 a hash route for an undeclared destination opens no page (5.5s)
  ✓  13 a server that declares nothing keeps every built destination (3.8s)
  ✓  14 hosted capabilities survive a declaration that dropped billing (5.4s)

  2 skipped
  12 passed (49.7s)
```

`npx playwright test e2e/design-system.spec.ts -g "hosted" --project=desktop`:
```
Running 5 tests using 1 worker
  5 passed (23.6s)
```

`npx playwright test e2e/phone.spec.ts --project=phone`:
```
Running 6 tests using 1 worker
  6 passed (34.3s)
```

`npx playwright test e2e/console.spec.ts --project=desktop`:
```
Running 49 tests using 1 worker
  49 passed (5.4m)
```

`npx vitest run`:
```
 Test Files  32 passed (32)
      Tests  347 passed (347)
```

`npx tsc --noEmit -p tsconfig.app.json`, **unpiped**:
```
TSC_EXIT=0
```
(no diagnostics printed)

`npm run lint`:
```
LINT_EXIT=0
```
13 warnings, the unchanged baseline, none in a file this round touched.

Same environment as the previous rounds: `E2E_ANCHOR_PORT=28451 E2E_API_PORT=28440
E2E_UI_PORT=25200`, scratch `E2E_CORTEX_HOME`, `E2E_PYTHON` at the worktree `.venv`, `uv` shim in
the session scratchpad outside the repo. No process killed.

## Coverage of the four threaded consumers, after this round

| consumer | site | proved red by a mutation of that site alone |
| --- | --- | --- |
| `tabsFor` | `PageHost.tsx` | yes (round 1 of the task, Route 2) |
| `primaryDestinations` — rail | `Shell.tsx` `.xc-rail-nav` | yes (fix round 1) |
| `primaryDestinations` — top bar | `Shell.tsx` `.xc-nav` | yes (this round, TopBar-only) |
| `destinationsIn` — More sheet | `Phone.tsx` `MoreList` | yes (this round, MoreList-only) |
| `destinations.find` / `.some` — tab bar | `Phone.tsx` `TabBar` | yes (fix round 1, tab-bar assertion) |
| `builtFrom`→`parseRoute` | `state.tsx` | yes (`a hash route for an undeclared destination opens no page`, plus the vacuity guard in the same test) |

## Concerns from this round

1. **Nothing new, and nothing outstanding in my slice.** The two residual holes are closed, each
   with a single-site mutation, and the one unfailable assertion I had left behind is deleted rather
   than argued for.
2. `Phone.tsx`'s `destinations.some(...)` secondary-current check is exercised only incidentally
   (the tab-bar mutation covers the same variable but a different read). It decides whether **More**
   shows as the current tab, which is cosmetic; I did not add a check for it, and say so rather
   than imply the table above is exhaustive at statement level.
3. Still the thing to decide before `/managed` ships from this branch, and not mine: the hosted
   data-path 404 regression, now assigned to 5d.
