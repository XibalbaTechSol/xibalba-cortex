# Task 5d report — the console's data layer learns the hosted edition

Branch `docs/account-registration-design`, worktree
`/mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design`.
Base at task start: `fa9d801`.

Commits, in order:

| SHA | What |
|---|---|
| `a23b01e` | `test(viewer)`: the self-hosted wire contract, written and committed GREEN against the unmodified `api.ts` |
| `89f3c37` | `feat(viewer)`: the hosted mapping, the entitlement write gate, the idempotency key, one transport |
| `7eb9726` | `test(e2e)`: the request-path spec, plus the fixture routes it needs |
| `15faa17` | `test(viewer)`: close the gaps the first evidence round left open (four unfailable checks, one over-wide claim, the fingerprint digest) |
| (this file) | the report |

Verification at the end state, all from `viewer/`:

- `npx vitest run` — **368 passed across 34 files** (baseline 347/32; +4 self-hosted contract, +17 hosted mapping)
- `npx tsc -b` — **exit 0** (run unpiped)
- `npm run lint` — **exit 0** (run unpiped), 13 pre-existing warnings, none in any file this task
  touched, no new ones
- `npx playwright test hosted-paths.spec.ts` — **Running 4 tests → 4 passed**
- `npx playwright test managed.spec.ts` — **Running 14 tests → 12 passed + 2 skipped** (baseline)
- `npx playwright test console.spec.ts` — **Running 49 tests → 49 passed**
- `npx playwright test phone.spec.ts` — **Running 6 tests → 6 passed**
- `npx playwright test design-system.spec.ts -g hosted` — **Running 5 tests → 5 passed**

### How the e2e suite had to be run (read this before re-running)

Three deviations from the documented command, all environmental, none a change to the suite:

1. **Leaked servers hold the default ports.** A previous session left the e2e anchor stub
   (`:28431`), API (`:28420`) and Vite (`:25190`) running for ~11 hours out of
   `~/Projects/xibalba-cortex/viewer`. `playwright.config.ts` sets `reuseExistingServer: false`
   on all three, so the suite refused to start. I killed the anchor stub; the permission system
   **denied** killing the API and Vite processes ("Interfere With Workloads"), so I ran on
   alternate ports instead via the config's own env hooks.
2. **`uv run` cannot resolve this worktree.** `pyproject.toml` has an editable path dependency
   `integrity-sdk @ editable+../integrity-core/integrity-sdk`, which does not exist beside the
   worktree, so the default `E2E_PYTHON="uv run python"` fails before the seed runs. I pinned
   `E2E_PYTHON` to the base checkout's interpreter; `playwright.config.ts` already prepends the
   worktree's `src` to `PYTHONPATH`, so the code under test is the worktree's. Nothing was written
   to the base checkout, and the profile lives in this session's scratchpad.
3. **`vite.config.ts` mints the dev operator token with `uv run`**, which fails for the same
   reason. It honours `CORTEX_DEV_TOKEN_FILE`, so I pre-minted a token into the scratchpad. The
   token lives in `ingest_tokens.sqlite3`, which `dev_seed_console.py --reset` does not delete
   (it only removes `graph-memory.sqlite3*`), so it survives every run.

The runner I used is `/tmp/claude-1000/-home-xibalba/91ce41c7-3892-4645-8963-ca13ae974417/scratchpad/e2e.sh`.
It is a scratchpad convenience, not part of the repo. Its body:

```
export E2E_PYTHON=/home/xibalba/Projects/xibalba-cortex/.venv/bin/python
export E2E_API_PORT=28520 E2E_UI_PORT=25290 E2E_ANCHOR_PORT=28531
export E2E_CORTEX_HOME=$SCRATCH/cortex-e2e-5d
export CORTEX_DEV_TOKEN_FILE=$SCRATCH/dev.token
exec npx playwright test "$@"
```

**Every count below was read off Playwright's own `Running N tests` line**, never inferred from
an exit code.

---

## 1. The mapping, and where it lives

`viewer/src/hostedApi.ts` — new, 309 lines. One table, one transport, read by one branch.

Supporting change: `ApiError` moved to `viewer/src/apiError.ts` (`api.ts` re-exports it, so every
`import { ApiError } from '../api'` keeps working). This exists only to break the cycle: the hosted
transport must reject with the SAME type, because `state.tsx:178` ends a session on
`e instanceof ApiError && e.status === 401` and a plain `Error` would have left an expired hosted
cookie rendering an error panel forever.

### The table

`ROUTES` in `hostedApi.ts`. Console path (method + path) → managed path, with the query narrowed
to what that route actually reads and the response reshaped to what the console's reader expects.
Every shape was read out of `src/xibalba_cortex/managed/api.py`, not assumed.

| Console call | Managed route | Query kept | Response reshaped |
|---|---|---|---|
| `GET /api/graph` | `graph` | `limit` | none — identical `{nodes, edges}` |
| `GET /api/sessions` | `timeline` | `limit` | `d.sessions` (managed returns `{sessions, nodes}`) |
| `GET /api/memories` | `memories` | `q` | `{memories, has_more: false, offset: 0, limit}` |
| `GET /api/search` | `memories` | `q` | `d.memories` |
| `GET /api/memory/{id}` | `memories/{id}` | — | `d.memory` (managed nests it) |
| `GET /api/memory/{id}/verify-chain` | `memories/{id}/verify` | — | none |
| `GET /api/agent0/search` | `agent0/search` | `q` | none |
| `GET /api/agent0/agent/{id}` | `agent0/agent/{id}` | `full` | none |
| `GET /api/agent0/reputation/{id}` | `agent0/reputation/{id}` | — | none |
| `GET /api/agents` | `me` | — | synthesized into the one hosted workspace |
| `POST /api/memory/propositions` | `memories` | — | body reduced to `{content}`; gated + keyed |

`similarity_threshold`, `agent_id`, `store_id`, `offset` and `status` are dropped rather than sent:
the managed routes ignore them, and sending a parameter a route ignores only misleads whoever reads
the request later.

**Anything not in that table is refused locally, before any fetch**, with `HostedUnsupported`
(status 501, message `The hosted edition does not serve GET /api/stats.`). That is the
"silently-by-design" half of deliverable 2: the hosted console issues **zero** requests for the
~60 console calls the managed backend has no route for, rather than one 404 per surface per load.
`loadConsoleData` already treats everything but the graph as degradable (`Promise.allSettled`), so
a local rejection lands exactly where a 404 used to, minus the round-trip.

### The one edition branch

`viewer/src/api.ts` gained a single function:

```ts
async function send(path: string, init: RequestInit = {}): Promise<Response> {
  if (hostedActive()) return hostedSend(path, init)
  return fetch(`${getApiBaseUrl()}${path}`, { credentials: 'include', ...init })
}
```

Every fetch in `api.ts` now goes through it (13 call sites converted; `getJson`, `postJson` via
`mutatingFetch`, `getBlob`, `uploadRaw` and the nine `account*` functions). **No call site anywhere
in the app asks which edition it is in.** `hostedActive()` is false unless `ConsoleApp` installed
the mapping, and it only does that when `edition() === 'managed'`.

`mutatingFetch` returns early on hosted. This was a real escape the brief did not name: every
hosted write went through `csrfHeader()` → `GET /api/auth/csrf`, a route the managed backend
answers 404, re-fired on every single write. Hosted takes its CSRF token from
`GET /api/managed/me` instead.

### One transport, not three

`hostedRequest` (Task 5a, `console/hostedWorkspace.ts`) and `BillingPage`'s `managed<T>()` were
byte-identical copies of the same fetch. Both are now `hostedFetch` in `hostedApi.ts`:
`hostedRequest` is literally `export const hostedRequest = hostedFetch`, and `BillingPage` imports
it as `managed`, so its call sites are unchanged. This was 5c's job; doing it here was preferred
and it is done. The CSRF token, the `Idempotency-Key`, the `ApiError` type and the session refresh
now have exactly one definition. `ManagedApp.tsx`'s own third copy is untouched — 5c deletes that
file.

### `/api/agents` → `me`: why the mapping reaches this far

This is the piece the brief could not know about, and without it findings 4 and 5 are unprovable.

`useWorkspace()` (`console/workspace.ts`) fetches `/api/agents` on every console mount and derives
`canWrite` from it (`selected?.writable === true`). The managed backend has no such route. So on a
**production** hosted console: one 404 per mount, an empty workspace list, and `canWrite === false`
forever — no write control at all, which is strictly worse than the finding-4 description.

On hosted there is exactly one workspace, and its writability IS the subscription entitlement. So
`me` is reshaped into that single `/api/agents` row (`workspaceFromMe`), and `workspace.ts` is
**unchanged**: no edition branch leaked into it. Every field the consumers read is present and
honest — `store_access` is the declared `'writable' | 'read_only'`, `memories` is the real count
with `memories_counted: true`, and `sessions`/`last_seen_at`/`on_chain`/`identity_verified` are
`0`/`null`/`false` with `sessions_counted: false`, because "not counted" is not zero and `me`
reports no session count. (I found this the hard way: the first version omitted `sessions`, and
`AgentsPage`'s `AgentCard` crashed on `undefined.toLocaleString()` — caught by the existing
`managed.spec.ts`, not by anything I wrote.)

### Deliverable 3: the fatal case

`api.graph` resolves on hosted. Proved by `hosted-paths.spec.ts` test 1, which waits for
`.xc-workspace` visible and `.xc-conn` reading "connected" and asserts `graph` was among the
managed calls, under a fixture that 404s every non-managed API request exactly as production does.
With the mapping removed that test fails at `hosted-paths.spec.ts:49` (evidence below).

---

## 2. Mutation evidence — every check, proved able to fail

Procedure for each: apply the mutation, run the test, record where it went red, restore with
`git checkout <file>` (byte-exact; the implementation was committed first precisely so the revert
is a checkout and not a retype), confirm green.

**Two process notes, because `git checkout` as a restore mechanism cost me real work twice.**
First round: `hostedApi.ts` was still untracked, so `git checkout` failed outright and three
mutations accumulated silently; I restored them by hand and re-verified before continuing. Second
round: `git checkout src/hostedApi.ts` restored to the last COMMIT, which silently discarded an
uncommitted fix (the fingerprint digest) that was not part of the mutation. I re-applied and
re-verified it, and for the remainder I mutated in place and restored with the inverse edit
(M13 below), which cannot destroy uncommitted work. Nothing was ever `git stash`ed — the stack is
shared across worktrees and already holds an unrelated `stash@{0}`. Every result below was
re-confirmed at the final tree.

### Unit checks (`npx vitest run src/hostedApi.test.ts src/apiSelfHosted.test.ts`, 21 tests)

| # | Mutation (file:what) | Red at |
|---|---|---|
| M1 | `hostedApi.ts` — deleted the `['GET /api/graph', …]` table entry | 2 failed: `rewrites the calls the managed backend serves…` and `sends the graph to the one route that serves it` |
| M2 | `hostedApi.ts` `hostedSend` — `if (target.route.write && writable === false)` → `if (false)` | 1 failed: `refuses a write a read-only subscription forbids, locally, in Billing's own words` |
| M3 | `hostedApi.ts` `writeKeyFor` — never return the memoized key | 1 failed: `keeps the SAME key across retries of one logical write, and a different one per write` |
| M4 | `hostedApi.ts` `hostedFetch` — `if (method === 'POST') releaseWriteKey(…)` → `if (false)` | 1 failed: `starts a new key once a write succeeded, so writing the same text twice is two writes` |
| M5 | `api.ts` `mutatingFetch` — removed the `if (hostedActive()) return hostedSend(…)` early return | 6 failed, incl. `never asks /api/auth/csrf on a hosted write: the token comes from me` and all four idempotency/gate tests |
| M6 | `hostedApi.ts` `workspaceFromMe` — `writable: entitlement.writable === true` → `writable: true` | 1 failed: `makes the hosted workspace out of the subscription, so it is writable exactly when the plan is` |
| M7 | `console/hostedWorkspace.ts` — `hostedRequest = hostedFetch` → its own inline fetch again | 1 failed: `is the one fetch the console, Billing and the key surfaces all go through` |
| M8 | `hostedApi.ts` — `if (!target) throw new HostedUnsupported(…)` → `return fetch(path, init)` | 1 failed: `refuses a call the hosted backend has no route for without sending anything` |
| M9 | `hostedApi.ts` — memories adapter returns `{ memories }` without `has_more` | 1 failed: `unwraps the single memory, the session list and the search results the managed shapes nest` |
| M10 | `api.ts` `send` — `if (hostedActive())` → `if (true)`, i.e. self-hosted takes the hosted path | **all 3** `apiSelfHosted.test.ts` tests failed |
| M11 | `api.ts:1086` — `'/api/stats'` → `'/api/managed/stats'` (run at `a23b01e`, before the fix existed) | `apiSelfHosted.test.ts:103`, `GET /cortex-api/api/stats` vs `…/api/managed/stats` |
| M12 | `api.ts` `send` — dropped `credentials: 'include'` | `apiSelfHosted.test.ts:294`, `full.every((c) => c.credentials === 'include')` |
| M13 | `hostedApi.ts` — `digest(…)` reduced back to the raw fingerprint | `keys on a digest, so a failed sign-in does not park a plaintext password in module state`, received `POST login {"email":…,"password":"correct-horse-battery"}` |

### e2e checks (`npx playwright test hosted-paths.spec.ts`, `Running 4 tests`)

| # | Mutation | Result |
|---|---|---|
| E1 | deleted the `GET /api/graph` table entry | 3 of 4 failed, each at `.xc-conn` not reading "connected". Test 4 passed, correctly: it loads the console (so `api.graph` IS called and refused) but has no anchor on the graph, and its absence assertion is honestly empty because the refused call sends nothing |
| E2 | removed the hosted branch from `api.ts`'s `send` — **the original regression, restored** | **4 of 4 failed**. Tests 1–3 red at `hosted-paths.spec.ts:49` (`.xc-conn` / "connected"); test 4 red at `:143`, the seeded memory never appearing. I.e. under production 404 behaviour the hosted console does not load at all |
| E3 | `if (!target) return fetch(path, init)` — leak the unsupported paths, render unaffected | 3 failed. Test 1 red at **the escape assertion itself**, listing `GET /api/stats`, `/api/status`, `/api/invocations`, `/api/memory/seed-0/events`, `/api/session/fixture-session/merkle-root`, `/api/agent-devices`. Test 2 red on `/api/stats`. Test 4 red on the same escape assertion with the same `/api/stats`, `/api/status`, `/api/invocations` (its failure line was truncated by `head -40` in the first write-up of this report; captured on the rerun) |
| E4 | `if (!target) return fetch(\`/cortex-api${path}\`, init)` — leak **wearing the dev-proxy prefix** | Test 1 red at the escape assertion listing `GET /cortex-api/api/stats`, `/cortex-api/api/status`, `/cortex-api/api/invocations`, `/cortex-api/api/memory/seed-0/events`, … |
| E5 | `workspaceFromMe` — `store_access`/`writable` forced to `'writable'`/`true`, i.e. the entitlement stops reaching `canWrite` | Test 4 red at **`hosted-paths.spec.ts:156`, the "New memory" absence itself** — which is only reachable because that absence was moved AHEAD of the status-bar check that reads the same signal |
| E6 | `hostedFetch` — dropped the `...idempotency` header spread | Test 3 red at `:138`, the `/^[\w-]{8,128}$/` key assertion |
| E7 | the propositions route — dropped its `body:` transform | Test 3 red at `:137`, `write.body` no longer `{ content: 'A hosted write' }` |
| E8 | `accountLogout` — restored its original raw `fetch(getApiBaseUrl() + "/api/auth/logout", …)` | Test 1 red at `:106`, the escape assertion, listing exactly `POST /cortex-api/api/auth/logout` |

**E4 is the one that matters most.** It is the exact shape the brief warned about: an escape in
this build is `/cortex-api/api/graph`, not `/api/graph`, so a recorder filtering on
`pathname.startsWith('/api/')` would have seen nothing and passed with the fix removed. The spec
filters on `path.includes('/api/')` plus `/readyz` and `/metrics`, and E4 proves that choice is
load-bearing rather than decorative.

**On assertion order.** Playwright stops at the first failing assertion, so in each test every
absence assertion sits last, behind: (a) positive waits for surfaces that exist only once hosted
data arrived (the seeded memory in the Memories table, the same text in the Inspector detail pane,
a lexical Recall result, the Agents key panel, the Billing plan button, the Settings drawer), and
(b) a positive assertion that `me`, `graph`, `timeline`, `memories`, `memories/seed-0` and `plans`
were really requested, plus `requests.length > 6`. An empty `requests` array cannot pass.

---

## 3. How self-hosted was proved unchanged

Not asserted — measured, with the measurement committed before the change.

`viewer/src/apiSelfHosted.test.ts` (commit `a23b01e`, **before** `hostedApi.ts` existed) records,
as three explicit tables, the request method and exact URL of **every** `api` method, every
`account*` function, the blob path, the server-rendered HTML URL, and the `GET /api/auth/csrf` the
first cookie-authenticated write fetches its token from — 56 reads, 34 writes, 12 account/blob
calls, in call order. It was green against the unmodified `api.ts`, proved failable there (M11),
and is **still green** at the end state after every change in `89f3c37`.

A table written after the change would have been a snapshot of the change and would have proved
nothing. That is the whole reason for the separate first commit.

**The extended leg (added in `15faa17`).** Method and URL are not the whole wire contract: the
change rewrote how `credentials`, the headers and the body are composed at thirteen call sites, and
none of that is visible in the tables. `console.spec.ts` cannot see it either, because the dev
proxy injects a bearer token and nothing there exercises the cookie credential. A fourth test now
records `credentials`, `Content-Type`, `X-Cortex-CSRF-Token` and the body, and asserts
`credentials === 'include'` on every call plus the exact header/body composition for a JSON write,
a raw upload, a sign-in and a logout.

Because the old `api.ts` is self-contained, that test can be run against BOTH versions, which is
the actual proof rather than a snapshot:

```
git checkout a23b01e -- viewer/src/api.ts && npx vitest run src/apiSelfHosted.test.ts   # 4 passed
git checkout HEAD     -- viewer/src/api.ts && npx vitest run src/apiSelfHosted.test.ts   # 4 passed
```

Failable: M12, dropping `credentials: 'include'` from `send`, turns it red at
`apiSelfHosted.test.ts:294`.

Two further legs:

- M10 above: forcing self-hosted down the hosted path turns all three tables red, so the test is
  specifically sensitive to the leak it exists to catch.
- `managed.spec.ts`'s `a server that declares nothing keeps every built destination` still passes,
  and it asserts `expect(calls).toEqual([])` — a self-hosted console asks the hosted account API
  nothing at all. The mapping did not change that.

---

## 4. Finding 4 — the managed-entitlement write gate

Two layers, both failable.

**The control.** Hosted `workspace.canWrite` now follows `entitlement.writable`, through the
`/api/agents` → `me` reshaping. A read-only hosted workspace therefore renders no "New memory" and
no "Import a document" (`MemoriesPage` already hides them on `canWrite`), and the status bar says
`read only`, which is ManagedApp's behaviour (it `disabled` the same affordances) reached through
the console's existing mechanism rather than a second one. Proved by `hosted-paths.spec.ts` test 4:
under `writable: false` the seeded memory is still listed and "Export memories" is still offered
(a read-only subscription keeps every read — that is the point of a per-write entitlement), then
"New memory" has count 0, and only then does the status bar read `read only`. The absence comes
BEFORE the status check deliberately: both read `workspace.canWrite`, so with the status check
first a mutation fails there and the absence is never reached. Failable via M6 (unit) and **E5
(e2e, red at the absence line itself)**.

The first version of this test also asserted "no `POST memories` was issued" under read-only.
That assertion **could not fail** — nothing in that test attempts a write, so it held with or
without the gate — and it has been removed. The gate on the CALL is proved in
`src/hostedApi.test.ts` (M2) only, where a write IS attempted.

**The call.** `hostedSend` refuses a `write: true` route when `writable === false`, throwing
`HostedReadOnly` **before any fetch** — no 402/403 round-trip, and the reason travels with the
refusal instead of living on a different page from the control. Failable via M2.

**The copy.** The brief pointed at `BILLING_UNAVAILABLE` / `upgradeRefusal`. I did not use them,
deliberately: `BILLING_UNAVAILABLE` is *"Paid subscriptions are not available yet."*, which is
about whether checkout is configured at all — a different refusal that would be wrong here. The
existing wording for *this* refusal was `BillingPage`'s inline callout. I extracted it verbatim
into `console/billing.ts` as `READ_ONLY_WORKSPACE` —
*"This workspace is read-only. Your existing memories remain available to read. Update billing to
resume writes."* — and `BillingPage` now renders that constant, so there is still exactly one
sentence and it is the one that already shipped. No second phrasing was invented.
`upgradeRefusal` / `BILLING_UNAVAILABLE` are untouched.

**`writable === false`, not `writable !== true`.** An unknown entitlement does not refuse. By
construction `ConsoleApp` renders nothing under the console until `me` resolves, so a write cannot
precede the entitlement; refusing on `undefined` would only have risked false refusals in paths I
cannot enumerate, and the server still enforces. This is a judgement call and I flag it as one.

## 5. Finding 5 — the hosted `Idempotency-Key`

`hostedFetch` attaches one to **every** hosted POST, keyed on
`` `${method} ${path} ${body}` `` through `writeKeyFor`, and releases it on success. So:

- a retry of one logical write (same route, same body) carries the **same** key — a write that
  failed after the server stored it cannot double-store, which was the regression;
- a different write carries a **different** key;
- after a success the next identical write gets a **new** key, so writing the same text twice on
  purpose is two writes rather than a silently swallowed duplicate.

This mirrors `ManagedApp`'s `retryWrite` ref, and it has to be bound to the payload rather than to
the attempt because the hosted backend fingerprints the body under the key
(`managed/api.py:366-369`) and refuses a reused key carrying different content.

Failable via M3 (key per attempt), M4 (never released) and M5 (hosted writes bypass the
transport). The header is also asserted end to end: `hosted-paths.spec.ts` test 3 reads it off the
recorded fixture call and matches `/^[\w-]{8,128}$/` — the 8–128 window the server enforces — and
that end-to-end pair is itself proved failable by **E6** (header spread dropped → red at the regex)
and **E7** (body transform dropped → red at the `{content}` check).

**The fingerprint is hashed, not raw (`digest`, djb2).** Keying every hosted POST by
`method + path + body` means a failed `login` or `signup` leaves the plaintext password as a Map
key in module state until something else succeeds. `digest` makes the key non-reversible. This
needed its own check, because every key-stability test above passes either way: `hostedApi.ts`
exports `pendingWriteFingerprints()` purely so a test can assert that nothing retained IS the
payload. Failable via **M13** — reducing `digest(…)` back to the raw fingerprint turns it red with
`POST login {"email":…,"password":"correct-horse-battery"}` in the retained keys.

One widening this also forced me to look at: `login`, `signup` and `recovery/*` do not need an
idempotency key at all, and an alternative fix would have been to skip keying them. I hashed
instead, because one rule for every hosted POST cannot drift the way a per-route exclusion list
would, and the hash fixes the hygiene problem for every future route as well as these three.

One widening worth stating: `ManagedApp` sent the header only on its memory write. I send it on
every hosted POST. The managed routes that do not require it ignore it, the ones that do
(`memories`, `import`) get it, and one rule in one place cannot drift the way a per-route list
would.

---

## 6. What I deliberately left degrading, and why

Each of these is a console capability with no managed route. All now refuse **locally**, with a
stated reason naming the call, and issue no request.

- **Everything `loadConsoleData` already treated as optional**: `/api/stats`, `/api/status`,
  `/api/invocations`. The status bar reads `—` for profile/schema/identity/integrity and
  `memory total not counted`, which is what it already did on a hosted load — except now without
  three 404s per load.
- **`/api/import` — the one brief item I did not deliver.** The brief's deliverable 1 lists
  "import/export". Export is done (`EXPORT_DOWNLOAD_PATH` / `export`, already managed-native from
  5a). Import is **not mapped**, because the two routes are not the same operation:
  `api.importDocument` POSTs raw Markdown bytes with the filename in the query, and the console
  reads `r.document.name/sections/sha256` off the reply; managed `import` takes a JSON structured
  bundle (`import_structured_bundle`, `xibalba.managed_import.v1`) and answers
  `{schema_version, inserted}`. Mapping one onto the other would need a client-side document
  splitter and a fabricated `document` envelope — a new feature, not a mapping, and it would have
  put invented section counts in front of a user. It refuses locally with its reason. In practice
  the control is also not reachable on a read-only hosted workspace, and on a writable one it is
  offered and fails with the stated reason. **This is a deviation from the brief and I am flagging
  it rather than quietly dropping it.**
- **Recall's Hybrid and Context modes.** `recall` IS a declared hosted destination, but only its
  **lexical** mode can be served: `/api/search` maps to `memories?q=`, while Hybrid posts to
  `/api/retrieval/hybrid` and Context to `/api/context/assemble`, neither of which exists on
  hosted. Hybrid is the DEFAULT mode, so a hosted user pressing Enter in Recall gets a stated
  refusal until they pick Lexical. That is a real rough edge; it is not a 404 and not a silent
  failure, but it is not good. The e2e exercises Lexical and says so in a comment.
- **The Inspector's secondary panels.** `memory/{id}` and `verify-chain` map, so the detail pane
  works; `events`, `otel`, `attachments`, `similar`, `neighbors`, `contradictions` and
  `provenance` have no managed route and each renders its stated refusal. Before this task the
  whole Inspector 404'd on hosted, so this is a strict improvement, but a hosted Inspector shows
  several refusal callouts and that will look noisy.
- **`MemoryActions` (supersede / forget / link entities) and `SessionsPage`'s writes.** Turning
  `canWrite` true on hosted makes these controls *enabled*, and they have no managed equivalent, so
  clicking one produces a stated local refusal rather than a 404. I did not hide them: the only
  signal available for that is the declared destination list, and these controls live on surfaces
  hosted DOES declare. A per-capability declaration would be the right fix and it is a backend
  change, which this task is forbidden from making.
- **`/api/agent-devices`.** No managed route, so the hosted Agents page lists the workspace with
  "No device is paired to this agent" and a refusal note. The API-key panel (5a's work) is
  unaffected — it was already managed-native.
- **Settings is a declared hosted destination whose sections mostly refuse.** `AccessSection`'s
  `/api/auth/tokens` and `/api/auth/tokens/revoke`, `DeveloperSection`'s `/api/vault/leaf` and
  `/api/kernel-bridge/self-test`, and `/api/settings/inference` and `/api/profile/config` all have
  no managed route. Layout/appearance (purely local) works. **Why `/api/auth/tokens` is not mapped
  to managed `keys`, even though the brief's deliverable 1 names "keys":** the two are different
  contracts, not two spellings of one. `/api/auth/tokens` is the operator token admin surface —
  it returns `{tokens, grantable_roles}`, takes `{label, role, ttl_hours}`, and issues credentials
  with operator roles; managed `keys` returns `{keys}`, takes `{label, agent_ids}` of
  `did:integrity:…`, and issues a tenant-scoped `writer` key that explicitly cannot mint other
  keys or administer accounts. Mapping one onto the other would mean fabricating roles the hosted
  backend refuses. Hosted key management already exists and is already managed-native: Task 5a's
  `AgentsPage` panel, which calls `keys` / `keys/revoke` through `hostedRequest`. So the
  capability is served; the operator-token page is the thing that refuses, correctly.
- **`MemoriesPage`'s status chips are ignored on hosted — degrading by ACCIDENT, not by design.**
  Managed `memories` has no `status` parameter, so the mapping drops it. The chips still render and
  still look like they filter, and toggling one re-fetches the same unfiltered page. This is the
  one place in the slice where the console makes a claim the edition does not honour, and I am
  listing it as a defect rather than a decision. Fixing it needs either a managed `status`
  parameter (backend, out of scope here) or an edition-aware control (which is what "no
  `edition === 'managed'` at call sites" forbids).
- **`accountMe` / `accountAuth` / `accountSessions` / `accountEvents` / `accountLogout` and the
  password-reset pair are refused rather than mapped**, deliberately: `HostedLanding` and
  `ConsoleApp` own the hosted account flow and already speak `/api/managed/{login,signup,logout,
  recovery/*,verify}` directly. Mapping `/api/auth/*` onto them would create a second path to the
  same thing. `accountLogout`'s refusal is swallowed by `ConsoleApp`'s existing `.catch(() => {})`,
  and hosted sign-out is now driven end to end in `hosted-paths.spec.ts` test 1.
- **Retrieval-quota cost.** Managed `graph` and `memories` each call `consume(tenant,
  "retrievals")`, and `/api/sessions` → `timeline` is a third. A hosted console load therefore
  spends ~3 of the plan's monthly retrievals where `ManagedApp` spent fewer. Not a blocker, but it
  is a real metering change and the product owner should know.

## 7. NOT VERIFIED

- **Nothing was run against a real managed backend.** Every hosted assertion is against
  `managed-fixture.ts`, which I extended with the mapped routes using shapes read out of
  `managed/api.py`. If a managed handler's reply differs from what I read, the fixture agrees with
  me and the test passes anyway. The specific shapes I transcribed rather than observed:
  `timeline`'s `{sessions, nodes}`, `memories/{id}`'s `{memory}`, `memories/{id}/verify`'s
  `verify_chain` dict, and the agent0 envelopes. `NOT VERIFIED` against a live service.
- **`memories/{id}/verify` ↔ `/api/memory/{id}/verify-chain` equivalence** is inferred from both
  calling `store.verify_chain(id)`. I did not run `VerifyPanel` against a managed backend.
  `NOT VERIFIED`.
- **`has_more: false` on the hosted memories listing.** The managed route serves one page of at
  most 50 and ignores `offset`, so the adapter reports "there is no more" — meaning "no more that
  this edition will serve", which is true, but a hosted workspace with more than 50 memories shows
  50 with no indication that more exist. `loadMemoryIndex` likewise reports `complete: true` on a
  partial index. I chose this over paging the same 50 rows ten times. **A hosted workspace with
  >50 memories is NOT VERIFIED** — the fixture seeds 1–2.
- **A production hosted build was not built or served.** I did not run `vite build` with
  `VITE_CORTEX_EDITION=managed` and serve the result behind `managed/api.py`. The claim that the
  production base URL is the page origin comes from the brief's reading of `deploy/*/Dockerfile`.
  The e2e emulates production by 404ing every non-managed API request, which is the behaviour that
  matters, but it is an emulation. `NOT VERIFIED` end to end.
- **The extended self-hosted leg (credentials/headers/body) covers a representative five calls**,
  not all 102. It asserts `credentials === 'include'` across every call it makes, and the exact
  type/CSRF/body for a JSON write, a raw upload, a sign-in and a logout. The method+URL tables
  cover all 102. A self-hosted call whose *headers* changed but that is not among those five would
  not be caught. Narrowing the claim accordingly: **all 102 calls are measured for method and URL;
  five are measured for credentials, headers and body.**
- **Hosted sign-out now reaches the landing** (`hosted-paths.spec.ts` test 1 clicks through the
  profile menu and asserts `.xc-workspace` count 0), and the `logout` call is in the sweep. What is
  still `NOT VERIFIED` is sign-out against a real managed backend, i.e. that the cookie is actually
  cleared — the fixture just answers `{ok: true}`.
- **`ManagedApp.tsx` still holds a third copy of the transport.** I left it alone; 5c deletes the
  file. If 5c slips, that copy is live code with no idempotency key and its own error type.

## 8. Baselines

| Suite | Baseline | Observed |
|---|---|---|
| `npx vitest run` | 347 passing / 32 files | **368 passing / 34 files** (+4 self-hosted contract, +17 hosted mapping) |
| `npx tsc -b` | exit 0 | **exit 0** |
| `npm run lint` | pre-existing warnings only | **unchanged** — same `Graph3D.tsx` / `state.tsx` warnings, no new ones |
| `managed.spec.ts` | 14 run → 12 passed + 2 skipped | **14 run → 12 passed + 2 skipped** |
| `hosted-paths.spec.ts` | new | **4 run → 4 passed** |
| `console.spec.ts` | 49/49 | **Running 49 tests → 49 passed** (confirmed twice) |
| `phone.spec.ts` | 6/6 | **Running 6 tests → 6 passed** |
| `design-system.spec.ts -g hosted` | 5/5 | **Running 5 tests → 5 passed** |

Every e2e number above was read off Playwright's own `Running N tests` line, never from an exit
code — the leaked-stub hazard (a held port 28431 makes Playwright exit 0 having run ZERO tests) is
exactly what this session hit on its first attempt, so the counts are the only trustworthy signal.
`design-system.spec.ts -g hosted` was watched most closely of the four: its hosted sweeps now take
the graph from the extended fixture rather than from the dev proxy, so its rendered DOM could have
shifted. It did not — 5/5.

`console.spec.ts` was run twice: once at `7eb9726` plus the (then uncommitted) test edits that
became `15faa17`, and once again in full at the final tree `15faa17`. Both reported
`Running 49 tests → 49 passed` (6.3m). Everything in this table was
measured at `15faa17`.

---

## 9. What task 5c inherits

- **`ManagedApp.tsx` still holds a third copy of the hosted transport** — its own `request()`, with
  its own `ManagedError` type and no idempotency key on anything but the memory write. I left the
  file untouched because 5c deletes it. If 5c slips, that is live code with none of this slice's
  guarantees.
- **The two `test.fixme` tests in `managed.spec.ts`** are still fixme and still owned by 5c. Their
  assertions name the second UI's own DOM (`.xc-managed-results`, `.xc-managed-key`, its single
  write form). The capabilities they describe now all work on the console, and
  `hosted-paths.spec.ts` covers the write and the key header behaviourally, but re-pointing those
  two tests is 5c's job and I did not do it.
- **The `destinations` declaration is per-SURFACE, not per-capability.** Several controls on
  surfaces hosted DOES declare have no managed route (`MemoryActions`, the Settings sections,
  Recall's two non-lexical modes, the status chips). Each refuses with a stated reason, which is
  correct behaviour and poor UX. A per-capability declaration from the backend is the real fix and
  is out of scope for a client-side-only slice.

## 10. Files

New:

- `viewer/src/hostedApi.ts` — the table and the transport
- `viewer/src/apiError.ts` — `ApiError`, extracted so the transport can throw the same type
- `viewer/src/hostedApi.test.ts` — 17 tests, the hosted contract
- `viewer/src/apiSelfHosted.test.ts` — 4 tests, the self-hosted contract
- `viewer/e2e/hosted-paths.spec.ts` — 4 tests, the request-path discriminator

Changed:

- `viewer/src/api.ts` — one `send()` branch; 13 fetch sites routed through it; `mutatingFetch`
  returns early on hosted; `ApiError` re-exported
- `viewer/src/console/ConsoleApp.tsx` — installs the mapping on a hosted boot, feeds it the
  entitlement and the CSRF token from the `me` it already fetches
- `viewer/src/console/hostedWorkspace.ts` — `hostedRequest` is now `hostedFetch`
- `viewer/src/console/pages/BillingPage.tsx` — its private `managed()` deleted; imports the shared
  transport and renders `READ_ONLY_WORKSPACE`
- `viewer/src/console/billing.ts` — `READ_ONLY_WORKSPACE` extracted from BillingPage's callout
- `viewer/e2e/managed-fixture.ts` — the mapped routes, a `seed` option, the recorded
  `Idempotency-Key`

Backend: **untouched.** No Python file in the diff, no new route. `git diff fa9d801..HEAD --stat`
is 11 files, all under `viewer/`.
