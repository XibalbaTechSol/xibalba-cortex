# Task 5a report — re-home API-key issuance and bulk export into the console

Worktree: `/mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design`
Branch `docs/account-registration-design`, on top of `1238e8d`. `ManagedApp.tsx` untouched; no Python file touched.

## What was verified before building

Both claims in the brief hold:

- `ManagedApp.tsx:207-216` is the only API-key UI (`grep -n "keys" pages/AgentsPage.tsx pages/SettingsPage.tsx` → nothing).
- `ManagedApp.tsx:108-113` is the only bulk export (`download.ts` has only `saveBlob` + `attachmentFilename`).
- The backend already declares the capability: `src/xibalba_cortex/managed/api.py:39`
  `MANAGED_DESTINATIONS = ("graph","timeline","memories","recall","settings","agents","billing")`,
  returned by `GET /api/managed/me` (`api.py:248`), pinned by `tests/test_managed_service.py:468`.

## What was re-homed, and where

New plain module `viewer/src/console/hostedWorkspace.ts` (+ `hostedWorkspace.test.ts`), in the
style of `billing.ts`:

- `offersHostedWorkspace(list)` — the gate (below).
- `parseAgentDids(input)` — the DID parsing extracted from `ManagedApp.tsx:212`: splits on
  newlines and commas, trims, drops empties, de-duplicates, and returns
  `{ ok: false, error: AGENT_DID_REQUIRED }` (`Enter at least one agent DID`) for an empty result.
  Shaped `{ok,error}` like `buildNewMemory` in `actions.ts`.
- `keyRows(keys)` — the key-list rendering from `ManagedApp.tsx:214`: strips a leading
  `managed-api:` label prefix (only at the start), pluralises the bound agent count,
  `unbound` when there are none, and dates the expiry.
- `EXPORT_STARTED` / `EXPORT_FILENAME` / `EXPORT_DOWNLOAD_PATH` constants, plus one impure
  `hostedRequest<T>()` — byte-for-byte the same request shape as `BillingPage`'s private
  `managed<T>()` (same-origin cookies, `X-Cortex-CSRF-Token` on mutations only).

UI:

- `pages/AgentsPage.tsx` — new `HostedApiKeys` section ("Connect an agent with an API key"):
  Agent DIDs textarea, **Create API key**, **Show API keys**, per-key row
  (`label · N agents · expires …`) with **Revoke key**, and the one-shot token display.
  Request bodies are identical to `ManagedApp`: `POST keys {label:'agent', agent_ids}`,
  `POST keys/revoke {id}`, `GET keys` with no CSRF header.
- `pages/MemoriesPage.tsx` — **Export memories** in the page's `actions`, which calls
  `me` first and then triggers an anchor download of `/api/managed/export-download` as
  `cortex-memories.json`, and sets the console notice `Your memory export download has started.`
  The `me` call is deliberate and carried over: without it an expired cookie session would be
  saved to disk as a 401 body named `cortex-memories.json`. It is **outside** the
  `workspace.canWrite` ternary, because `managed.spec.ts:79` pins that a read-only subscription
  keeps export, and `canWrite` is about agent scope, not subscription state.
- `state.tsx` — one seam: `ConsoleProvider` takes an optional `destinations` prop defaulting to
  `DESTINATIONS`, and exposes it on `ConsoleValue`. Nothing else changed.

Deliberately **not** carried across from `ManagedApp`: the plan cards/usage panel (Task 3's
`BillingPage` owns those), the store/search memory forms (the console's Memories page already has
richer ones), `ManagedAgent0Directory` (`AgentsPage`'s `ERC8004Directory` is the surviving copy per
the Task 5 brief), the `xc-managed-key` class, and sign-in/signup/recovery (`SignIn.tsx` owns it).

## How it is gated, and why

`offersHostedWorkspace(list) === list.some(d => d.id === 'billing')`, read from the console
context's `destinations`, which is the **server-declared** destination list resolved by
`destinationsFrom`.

Why this and not an edition flag: `nav.ts:73-79` already states that `billing` is held out of
`BUILT` precisely because a self-hosted server must never list it, while it stays in
`ALL_DESTINATIONS` so a server *can* declare it. So "the resolved list contains `billing`" is the
existing model's own statement that this session is a hosted workspace — no new flag, no new
concept, and no probe request. An absent or empty declaration resolves to `DESTINATIONS`, which
has no `billing`, so **self-hosted is false with zero network calls** — that is why self-hosted
behaviour cannot change. (I did not probe `/api/managed/me` from the pages: that would add a
request on self-hosted, which *is* a behaviour change.)

**Important for the reviewer:** nothing passes `destinations` yet — Task 5b Step 3 is what reads
`destinations` off the session payload and hands it to the provider. Until then the context value
is the default `DESTINATIONS`, so both new controls are present in code and inert at runtime, on
both editions. That is intentional (5a must not change self-hosted, and `/managed` still runs
`ManagedApp`), but it means 5a has **no end-to-end hosted proof**; the positive path is proved
only by unit tests and by the mutation run below, where flipping the gate made both controls
render and reach the DOM. 5b should flip the gate on by passing the list and should re-run
`managed.spec.ts`'s key and export assertions against the console shell.

## Token handling (freshly issued credential)

The token lives in `HostedApiKeys`' `useState` and nowhere else. It is never logged, never put in
the hash/`pageArg`/a URL, never passed to `setNotice` (that notice is console-level and outlives
the page), and never written to `localStorage`/`sessionStorage`/IndexedDB. It is cleared when the
user presses **Hide key**, when any key is revoked (as `ManagedApp` did via `setNewKey('')`), and
on any request failure including a 401. Navigating away unmounts the component, which drops it —
so, as the copy says, it is gone when you hide it or leave the page. It is rendered as plain text
in a `<code className="xc-mono">`, exactly as `ManagedApp` did, and never into an attribute or a link.

## Grammar constraints

- No `xc-managed-*` class anywhere in the new code:
  `grep -rn "xc-managed-" src/console/hostedWorkspace.ts src/console/pages/AgentsPage.tsx src/console/pages/MemoriesPage.tsx src/console/state.tsx` → no output.
- Every class used is defined outside `managed.css` (checked: `xc-win`, `xc-btn`, `xc-field`,
  `xc-input`, `xc-input--mono` (console.css:287), `xc-title`, `xc-copy`, `xc-note`, `xc-eyebrow`,
  `xc-kv`, `xc-actions-row` (console.css:1455), `xc-mono` (console.css:177), `xc-callout`), so
  nothing loses its styling when 5b deletes `managed.css`. `xc-managed-key` (managed.css:26, the
  only definition) was **not** reused — hence `xc-mono` for the token.
- No inline `font-size` and no new CSS: zero stylesheet changes in this task.

## Red first — verbatim

### 1. Unit tests, red (stub module committed first: `offersHostedWorkspace` returned `true`,
`parseAgentDids` returned `{ok:true,agentIds:[]}`, `keyRows` returned `[]`, so the failures are
assertion failures, not import errors)

```
 RUN  v5.0.3 /mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design/viewer

 ❯ src/console/hostedWorkspace.test.ts (10 tests | 9 failed) 20ms
   ❯ offersHostedWorkspace (3)
     × is false when the server declared nothing, which is what self-hosted does 8ms
     × turns on the hosted-only destination, not on a page both editions serve 1ms
   ❯ parseAgentDids (3)
     × splits on newlines and commas, trims, and drops empties 3ms
     × de-duplicates, keeping the first occurrence 2ms
     × refuses an empty result rather than asking for a key bound to nothing 1ms
   ❯ keyRows (4)
     × strips the managed-api label prefix, but only at the start 1ms
     × pluralises the bound agent count and says unbound when there are none 1ms
     × dates the expiry in UTC, so the row does not read differently per machine 1ms
     × keeps the id, so a row can be revoked 1ms

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 9 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/console/hostedWorkspace.test.ts > offersHostedWorkspace > is false when the server declared nothing, which is what self-hosted does
AssertionError: expected true to be false // Object.is equality

- Expected
+ Received

- false
+ true

 ❯ src/console/hostedWorkspace.test.ts:10:64
      8| describe('offersHostedWorkspace', () => {
      9|   it('is false when the server declared nothing, which is what self-ho…
     10|     expect(offersHostedWorkspace(destinationsFrom(undefined))).toBe(fa…
       |                                                                ^
     11|     expect(offersHostedWorkspace(destinationsFrom([]))).toBe(false)
     12|   })

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/9]⎯
...
 Test Files  1 failed (1)
      Tests  9 failed | 1 passed (10)
```

(The one passing test was `keyRows` on `[]` → `[]`, which the stub satisfied by accident.)

### 2. Unit tests, green

```
 RUN  v5.0.3 /mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design/viewer


 Test Files  1 passed (1)
      Tests  10 passed (10)
   Start at  03:43:38
   Duration  376ms (transform 52%, tests 35%, import 8%, worker 5%)
```

### 3. Playwright: the self-hosted negative check, proved by mutation

Added to `e2e/console.spec.ts` (describe "writes happen only in a writable workspace"):
`self-hosted offers neither hosted-only control` — no **Export memories** on `#memories`, and no
**Create API key** / **Show API keys** on `#agents` (with a positive heading assertion first, so
it cannot pass over a torn-down page).

This one could not be red first: on self-hosted it is green by construction. **Evidence route:
mutation.** `offersHostedWorkspace` was inverted to `return !list.some(...)` and the spec re-run:

```
      - waiting for getByRole('button', { name: 'Export memories' })
        33 × locator resolved to 1 element
           - unexpected value "1"


      380 |   test('self-hosted offers neither hosted-only control', async ({ page }) => {
      381 |     await openConsole(page, { hash: 'memories' })
    > 382 |     await expect(page.getByRole('button', { name: 'Export memories' })).toHaveCount(0)
          |                                                                         ^
      383 |     await page.goto('/#agents')
      384 |     await expect(page.getByRole('heading', { name: /Add your agents|Bring an agent into Cortex/ }).first()).toBeVisible()
      385 |     await expect(page.getByRole('button', { name: 'Create API key' })).toHaveCount(0)

  1 failed
    [desktop] › e2e/console.spec.ts:380:3 › writes happen only in a writable workspace › self-hosted offers neither hosted-only control
```

That run is double evidence: the check can fail, **and** the gate is really wired into the pages
(with the gate true, the control renders and is found in the DOM).

Mutation reverted, re-run green:

```
Running 1 test using 1 worker

  ✓  1 [desktop] › e2e/console.spec.ts:380:3 › writes happen only in a writable workspace › self-hosted offers neither hosted-only control (7.8s)

  1 passed (13.2s)
```

Playwright really ran (count confirmed from output, not the exit code). Ports were overridden to
avoid the leaked stub on 28431 and the stacks on 28420/25190; no process was killed:
`E2E_API_PORT=29420 E2E_UI_PORT=29190 E2E_ANCHOR_PORT=29431` (sic: 29431),
`E2E_CORTEX_HOME=<scratchpad>/cortex-e2e-5a`,
`E2E_PYTHON=<worktree>/.venv/bin/python`. `vite.config.ts` additionally shells out to `uv run
xibalba-cortex-ingest-tokens`, which fails here (`Distribution not found at
.../worktrees/xibalba-cortex/integrity-core/integrity-sdk`), so a `uv` shim mapping `uv run <cmd>`
to the worktree venv was placed **outside the repo** at
`/tmp/claude-1000/-home-xibalba/91ce41c7-3892-4645-8963-ca13ae974417/scratchpad/bin/uv` and put
first on `PATH` for the run only.

### 4. Full suite, typecheck, lint

```
 Test Files  31 passed (31)
      Tests  333 passed (333)
```

`npx tsc --noEmit -p tsconfig.app.json` → exit 0, no output.
`npm run lint` (oxlint) → exit 0; 13 warnings, all pre-existing (Graph3D, TimelineLens, GraphLens,
Shell, PageDrawer, settingsContext, VerifyPanel, capture.mjs, and `state.tsx:97` `useConsole`,
which is the pre-existing fast-refresh warning on that file and not from this change). No warning
names `hostedWorkspace.ts`, `AgentsPage.tsx` or `MemoriesPage.tsx`.
`npm run build` → `✓ built in 3.72s`.

## Concerns

1. **The controls are inert until 5b.** Stated above. 5a's hosted path has unit + mutation
   evidence only. 5b must pass `destinations` into `ConsoleProvider`, and should re-point
   `managed.spec.ts`'s existing key/export assertions at the console controls — otherwise the
   hosted path loses its end-to-end coverage the moment `ManagedApp` is deleted.
2. **`hostedRequest` duplicates `BillingPage`'s private `managed<T>()`.** I left `BillingPage`
   untouched to keep this task's diff to its two capabilities; folding `BillingPage` onto
   `hostedRequest` would be a one-line cleanup for 5b or a follow-up.
3. **Expiry formatting changed slightly on purpose.** `ManagedApp` used
   `toLocaleDateString()` (host locale and time zone); `keyRows` pins `'en-US'` + `timeZone: 'UTC'`,
   like `billing.ts` pins `'en-US'`. Without it the assertion flakes by machine, and a local
   rendering of a UTC expiry can read a day early.
4. **CSRF is fetched per action.** Each key action calls `me` to get a fresh `csrf_token` (and to
   detect an expired session) instead of holding one from mount, which is one extra request per
   action but cannot act on a stale token. Export makes that same `me` call, which is the
   behaviour `ManagedApp` had.
5. **No section-level "hosted" wording audit.** The new key section's copy is lifted from
   `ManagedApp` nearly verbatim; if the product wants different wording in the consolidated UI,
   that is a copy decision, not a code one.

## Commit

`c1287a2` — `feat(viewer): re-home API keys and bulk export into the console`, on top of
`1238e8d`, local only (no push, no amend, no rebase, no stash). Six files:
`viewer/src/console/hostedWorkspace.ts` and `hostedWorkspace.test.ts` (new),
`viewer/src/console/pages/AgentsPage.tsx`, `viewer/src/console/pages/MemoriesPage.tsx`,
`viewer/src/console/state.tsx`, `viewer/e2e/console.spec.ts`.
`ManagedApp.tsx` has no diff; no Python file is in the commit
(`git status --short -- src/` → empty). `.superpowers/sdd/` is gitignored, so this report is
not part of the commit — which is also why the commit message cannot contain its own sha.

## Corrections and additional evidence (after review of this report's own claims)

Three statements above are wrong or overclaimed. They are corrected here rather than edited out,
and the checks they covered are now each proved able to fail.

### Correction 1 — "stub module committed first" is false

The red block above says the stub was "committed first". It was not: the stub was **written to
disk** and run, then replaced in the working tree. There is exactly one commit (`c1287a2`) and it
contains the finished module, so `git log` shows no stub. The red output is the evidence that the
stub existed and failed; it is not reproducible from history.

The verbatim head of that first red run is saved at
`/tmp/claude-1000/-home-xibalba/91ce41c7-3892-4645-8963-ca13ae974417/scratchpad/red-head.txt`.
The `...` in the quoted block above is an **elision** of failures 3–9, not output.

### Correction 2 — "The one passing test was `keyRows` on `[]`" is false

No such test exists. In the 9-failed/1-passed stub run the test that passed was
`offersHostedWorkspace > is true for the destination list the hosted edition declares`, because
the stub returned `true` unconditionally. So the gate's **positive** assertions had never been
seen red. Proved now by mutating `offersHostedWorkspace` to `return false`:

```
 RUN  v5.0.3 /mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design/viewer

 ❯ src/console/hostedWorkspace.test.ts (10 tests | 2 failed) 63ms
   ❯ offersHostedWorkspace (3)
     × is true for the destination list the hosted edition declares 7ms
     × turns on the hosted-only destination, not on a page both editions serve 1ms

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 2 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/console/hostedWorkspace.test.ts > offersHostedWorkspace > is true for the destination list the hosted edition declares
AssertionError: expected false to be true // Object.is equality

- Expected
+ Received

- true
+ false

 ❯ src/console/hostedWorkspace.test.ts:14:62
     12|   })
     13|   it('is true for the destination list the hosted edition declares', (…
     14|     expect(offersHostedWorkspace(destinationsFrom(MANAGED))).toBe(true)
       |                                                              ^
     15|     16|   it('turns on the hosted-only destination, not on a page both edition…

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/2]⎯

 FAIL  src/console/hostedWorkspace.test.ts > offersHostedWorkspace > turns on the hosted-only destination, not on a page both editions serve
AssertionError: expected false to be true // Object.is equality

- Expected
+ Received

- true
+ false

 ❯ src/console/hostedWorkspace.test.ts:18:75
     16|   it('turns on the hosted-only destination, not on a page both edition…
     17|     expect(offersHostedWorkspace(destinationsFrom(['graph', 'memories'…
     18|     expect(offersHostedWorkspace(destinationsFrom(['graph', 'billing']…
       |                                                                           ^
     19|   })
     20| })
```

Saved at `.../scratchpad/red-gate-false.txt`. Reverted with `git checkout --`, so all 10 pass
again (see the full-suite count below). With `return false` the two negative assertions still
pass, and with the stub's `return true` the negative ones failed: both directions of the gate are
now pinned by a run that was seen failing.

### Correction 3 — "the gate is really wired into the pages" was proved for Memories only

The first e2e mutation (inverted gate, whole module) failed at **line 382**, the Memories page's
`Export memories`, and Playwright stops a test at the first failed expect — so lines 385 and 386,
the Agents page's two buttons, never ran. The Agents wiring was unproven. Two further runs fix
that, each mutating only `AgentsPage.tsx` to `{!offersHostedWorkspace(destinations) && <HostedApiKeys />}`:

**(a)** with the button additionally renamed to `Issue key` (so line 385's substring match does
not hit), line 386 fails:

```
      - waiting for getByRole('button', { name: 'Show API keys' })
        33 × locator resolved to 1 element
           - unexpected value "1"


      384 |     await expect(page.getByRole('heading', { name: /Add your agents|Bring an agent into Cortex/ }).first()).toBeVisible()
      385 |     await expect(page.getByRole('button', { name: 'Create API key' })).toHaveCount(0)
    > 386 |     await expect(page.getByRole('button', { name: 'Show API keys' })).toHaveCount(0)
          |                                                                       ^
      387 |   })
```

**(b)** with the original button label restored and the gate still inverted, line 385 fails:

```
      - waiting for getByRole('button', { name: 'Create API key' })
        33 × locator resolved to 1 element
           - unexpected value "1"


      383 |     await page.goto('/#agents')
      384 |     await expect(page.getByRole('heading', { name: /Add your agents|Bring an agent into Cortex/ }).first()).toBeVisible()
    > 385 |     await expect(page.getByRole('button', { name: 'Create API key' })).toHaveCount(0)
          |                                                                        ^
      386 |     await expect(page.getByRole('button', { name: 'Show API keys' })).toHaveCount(0)
```

All three e2e assertions in the new test have now each been seen failing, and each failure shows
its control rendering when the gate is true — so both pages really consult the gate. Mutations
reverted with `git checkout -- viewer/src/console/pages/AgentsPage.tsx`; `git status --short` is
empty and HEAD is still `c1287a2` (the mutations were never committed).

### Full `console.spec.ts` run, not just the `-g` filter

```
  ✓  39 [desktop] › e2e/console.spec.ts:380:3 › writes happen only in a writable workspace › self-hosted offers neither hosted-only control (4.5s)
...
  49 passed (5.4m)
```

49 of 49 passed, count read from the output (`--project=desktop`, same port overrides, same
out-of-repo `uv` shim). No pre-existing failure to explain.

### Final check state at `c1287a2`

- `npx vitest run` → 31 files, 333 tests, all passing.
- `npx tsc --noEmit -p tsconfig.app.json` → exit 0, no output.
- `npm run lint` → exit 0, 13 pre-existing warnings, none naming the files in this change.
- `npx playwright test e2e/console.spec.ts --project=desktop` → 49 passed.
- `git status --short` → empty.

## Fix round 1 — the UTC expiry pin now has a check that catches its deletion

**The finding.** My expiry assertion did not defend the pin it was written for. The reviewer
replaced `'en-US', { timeZone: 'UTC' }` with nothing and the test still passed under `TZ=UTC`; it
only failed under `TZ=Asia/Tokyo`. The fixture was `2026-11-25T23:30:00Z`, which discriminates
only in zones east of UTC+00:30, and neither `vite.config.ts` nor `package.json` sets `TZ` — so a
UTC CI runner would have gone green with the pin deleted. Correct decision, undefended.

**The fix** (`viewer/src/console/hostedWorkspace.test.ts`), two parts:

1. **The test sets its own zone**, instead of inheriting the runner's:
   `vi.stubEnv('TZ', 'America/Los_Angeles')` at module top level, before any `Date` is formatted.
   Stated explicitly here as the coordinator asked: *the test forces `TZ=America/Los_Angeles`*, so
   its verdict does not depend on where it runs. (`process.env.TZ = …` worked at runtime but fails
   `tsc -p tsconfig.app.json` with `TS2591: Cannot find name 'process'` — that config has no node
   types — so `vi.stubEnv` is used, which assigns the same variable through vitest.)
2. **Two instants, one either side of midnight UTC**, since no single instant can discriminate in
   both directions (one instant has exactly one local date per zone):
   - `2026-11-25T00:30:00Z` → reads `11/24` in every zone **west** of UTC,
   - `2026-11-25T23:30:00Z` → reads `11/26` in every zone **east** of UTC,
   - both must render `11/25/2026`.

   So whichever direction the forced zone is later changed to, the pair still catches a dropped pin.

### Red: `'en-US', { timeZone: 'UTC' }` deleted from `keyRows`

```
$ cd viewer
$ sed -i "s|new Date(key.expires_at).toLocaleDateString('en-US', { timeZone: 'UTC' })|new Date(key.expires_at).toLocaleDateString()|" src/console/hostedWorkspace.ts
```

```
=== TZ=UTC npx vitest run src/console/hostedWorkspace.test.ts ===
 ❯ src/console/hostedWorkspace.test.ts (10 tests | 1 failed) 32ms
   ❯ keyRows (4)
     × dates the expiry in UTC, so the row does not read differently per machine 7ms

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/console/hostedWorkspace.test.ts > keyRows > dates the expiry in UTC, so the row does not read differently per machine
AssertionError: expected '11/24/2026' to be '11/25/2026' // Object.is equality

Expected: "11/25/2026"
Received: "11/24/2026"

 ❯ src/console/hostedWorkspace.test.ts:68:79
     66|      the pin is red wherever this runs -- and, with TZ forced above, r…
     67|   it('dates the expiry in UTC, so the row does not read differently pe…
     68|     expect(keyRows([key({ expires_at: '2026-11-25T00:30:00Z' })])[0].e…
       |                                                                               ^
     69|     expect(keyRows([key({ expires_at: '2026-11-25T23:30:00Z' })])[0].e…
     70|   })

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯

=== TZ=America/Los_Angeles npx vitest run src/console/hostedWorkspace.test.ts ===
 ❯ src/console/hostedWorkspace.test.ts (10 tests | 1 failed) 35ms
   ❯ keyRows (4)
     × dates the expiry in UTC, so the row does not read differently per machine 7ms

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/console/hostedWorkspace.test.ts > keyRows > dates the expiry in UTC, so the row does not read differently per machine
AssertionError: expected '11/24/2026' to be '11/25/2026' // Object.is equality

Expected: "11/25/2026"
Received: "11/24/2026"

 ❯ src/console/hostedWorkspace.test.ts:68:79
     66|      the pin is red wherever this runs -- and, with TZ forced above, r…
     67|   it('dates the expiry in UTC, so the row does not read differently pe…
     68|     expect(keyRows([key({ expires_at: '2026-11-25T00:30:00Z' })])[0].e…
       |                                                                               ^
     69|     expect(keyRows([key({ expires_at: '2026-11-25T23:30:00Z' })])[0].e…
     70|   })

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯

=== TZ=Asia/Tokyo npx vitest run src/console/hostedWorkspace.test.ts ===
 ❯ src/console/hostedWorkspace.test.ts (10 tests | 1 failed) 32ms
   ❯ keyRows (4)
     × dates the expiry in UTC, so the row does not read differently per machine 7ms

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/console/hostedWorkspace.test.ts > keyRows > dates the expiry in UTC, so the row does not read differently per machine
AssertionError: expected '11/24/2026' to be '11/25/2026' // Object.is equality

Expected: "11/25/2026"
Received: "11/24/2026"

 ❯ src/console/hostedWorkspace.test.ts:68:79
     66|      the pin is red wherever this runs -- and, with TZ forced above, r…
     67|   it('dates the expiry in UTC, so the row does not read differently pe…
     68|     expect(keyRows([key({ expires_at: '2026-11-25T00:30:00Z' })])[0].e…
       |                                                                               ^
     69|     expect(keyRows([key({ expires_at: '2026-11-25T23:30:00Z' })])[0].e…
     70|   })

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯
```

Red under all three prefixes — including `TZ=UTC`, which is the case that used to go green —
because the file forces its own zone. Saved verbatim at
`/tmp/claude-1000/-home-xibalba/91ce41c7-3892-4645-8963-ca13ae974417/scratchpad/red-tz.txt`.
Note the failure is always the **first** assertion (`00:30Z`, line 68), since Playwright-style
early exit applies to vitest too.

**The second (eastern) assertion was proved separately**, by dropping the pin *and* setting the
file's forced zone to `Asia/Tokyo`, where line 68 passes and line 69 fails:

```
 FAIL  src/console/hostedWorkspace.test.ts > keyRows > dates the expiry in UTC, so the row does not read differently per machine
AssertionError: expected '11/26/2026' to be '11/25/2026' // Object.is equality

Expected: "11/25/2026"
Received: "11/26/2026"

 ❯ src/console/hostedWorkspace.test.ts:69:79
     67|   it('dates the expiry in UTC, so the row does not read differently pe…
     68|     expect(keyRows([key({ expires_at: '2026-11-25T00:30:00Z' })])[0].e…
     69|     expect(keyRows([key({ expires_at: '2026-11-25T23:30:00Z' })])[0].e…
       |                                                                               ^
     70|   })
```

Both assertions in the pair have therefore each been seen failing.

### Green: pin restored (`git checkout -- viewer/src/console/hostedWorkspace.ts`)

```
=== TZ=UTC npx vitest run src/console/hostedWorkspace.test.ts ===
 RUN  v5.0.3 /mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design/viewer


 Test Files  1 passed (1)
      Tests  10 passed (10)
   Start at  11:27:59
   Duration  276ms (transform 62%, tests 21%, import 13%, worker 4%)

=== TZ=America/Los_Angeles npx vitest run src/console/hostedWorkspace.test.ts ===
 RUN  v5.0.3 /mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design/viewer


 Test Files  1 passed (1)
      Tests  10 passed (10)
   Start at  04:28:00
   Duration  257ms (transform 59%, tests 24%, import 14%, worker 4%)

=== TZ=Asia/Tokyo npx vitest run src/console/hostedWorkspace.test.ts ===
 RUN  v5.0.3 /mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design/viewer


 Test Files  1 passed (1)
      Tests  10 passed (10)
   Start at  20:28:01
   Duration  251ms (transform 61%, tests 21%, import 14%, worker 4%)
```

### Full checks after the fix

```
$ npx vitest run
 Test Files  31 passed (31)
      Tests  333 passed (333)

$ npx tsc --noEmit -p tsconfig.app.json
(exit 0, no output)

$ npm run lint
(exit 0; 13 pre-existing warnings, none naming hostedWorkspace / AgentsPage / MemoriesPage)
```

Playwright not re-run: this change touches one unit test's fixture and zone only, and no DOM.

### Not touched, as instructed

- No behavioural tests for `HostedApiKeys`, `hostedRequest` or the export click. The reviewer's
  demonstration stands: removing every `setToken('')` leaves all 333 tests green, so the
  credential-hygiene claims in this report are reasoned, not test-guarded. Ruled into the slice
  that deletes `ManagedApp`, where the hosted path actually runs and a Playwright positive path is
  possible (this repo has no jsdom/testing-library).
- The gate keying off `billing`. The wiring slice will pass an explicit hosted-session signal.
- All five Minors (the `aria-label` on a plain `div`, the inert `required` on a textarea outside a
  form, the label wrapping its note, `xc-actions-row` around the token `<p>`, the missing 401
  recovery) — deferred to the final review.
