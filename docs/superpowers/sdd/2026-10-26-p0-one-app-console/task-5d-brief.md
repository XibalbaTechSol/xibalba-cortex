# Task 5d — The console's data layer learns the hosted edition

NEW slice, not in the original plan. It exists because 5b made `/managed` render the
console, and the console's data layer calls bare `/api/*` paths the managed backend
does not serve. It MUST land before 5c deletes `ManagedApp`.

## The confirmed facts (verified by the controller, not inferred)

- `viewer/src/api.ts` calls bare `/api/*`: `/api/stats`, `/api/status`, `/api/operations`,
  `/api/sessions`, `/api/graph`, `/api/memories`, `/api/auth/tokens`, and ~20 more.
- The managed backend serves exactly 23 routes, all under `/api/managed/`:
  agent0/agent/{id}, agent0/reputation/{id}, agent0/search, checkout, export,
  export-download, graph, import, keys, keys/revoke, login, logout, me, memories,
  memories/{id}, memories/{id}/verify, plans, portal, recovery/{action}, signup,
  stripe/webhook, timeline, verify.
- There is NO managed `status`, `stats`, `sessions`, `entities`, `operations`,
  `auth/tokens`, `review` or `integrity` route. `managed/api.py`'s SPA handler answers
  any unmatched `/api/*` with 404.
- `deploy/*/Dockerfile` sets only `VITE_CORTEX_EDITION=managed`; no hosted image sets
  `VITE_LOCAL_API_URL`, so a production hosted build's API base is the page origin.
- **The scope-limiting fact:** `loadConsoleData` (`viewer/src/console/data.ts:43`) uses
  `Promise.allSettled` and only the graph is a hard requirement — "The graph is the one
  hard requirement; everything else degrades with a stated reason." `memories`,
  `sessions`, `stats`, `status` and `invocations` all already degrade.

## Deliverable

Make the console's data calls edition-aware, client-side only.

1. Route the calls that HAVE a managed equivalent to it: graph, timeline, memories
   (list, single, verify), import/export, the agent0 trio, keys and keys/revoke,
   plans/checkout/portal, me/login/logout/signup/verify/recovery.
2. Leave the calls that have no equivalent to degrade as they already do — but they must
   degrade SILENTLY-BY-DESIGN rather than by accident. Prefer not issuing a request the
   edition cannot serve at all, so the hosted console does not fire known-404s on every
   load. Task 1's declared destination list already models what hosted serves; use it.
3. The fatal case must go away: `api.graph` must resolve on hosted, so a hosted user
   reaches the knowledge graph rather than an error state.

## Constraints

- Backend untouched. No Python file, no new route. This is a client-side mapping.
- Self-hosted behaviour must not change: the bare `/api/*` paths stay exactly as they are
  when the edition is self-hosted. Prove it, do not assert it.
- One source of truth for the mapping. Do not scatter `edition === 'managed'` ternaries
  across call sites.
- Every check proved able to fail before being made to pass.

## The test that would have caught the regression

The reason this slipped through is that every "hosted" e2e runs under the Vite dev proxy,
which supplies a real local API, so the hybrid under test does not exist in production.
A test for this slice must therefore assert the REQUEST PATHS the console issues on
hosted — e.g. route-intercept every `/api/**`, drive the hosted workspace, and assert
that no request escapes the `/api/managed/` prefix (and that none of the known-404 paths
is requested at all). Assert the paths, not the rendering: rendering passes under the
dev proxy either way. That is the one check that discriminates production from dev.

## Two findings reassigned to this slice (from the 5a and 5b reviews)

These are capability losses that only the data layer can fix, so they land here.

4. **The missing managed-entitlement write gate.** `ManagedApp` disabled its write
   affordances when the workspace was read-only (an unpaid or lapsed hosted plan). The
   console has no such gate: on hosted it renders an enabled Save/Store control that the
   server then refuses, and the explanation lives on a different page from the banner.
   Carry the entitlement into the data layer and make a hosted write that the entitlement
   forbids fail fast, locally, with the reason — do not rely on the 402/403 round-trip.
   `BillingPage`'s `BILLING_UNAVAILABLE` / `upgradeRefusal` copy is the existing wording;
   reuse it rather than inventing a second phrasing.
5. **Hosted writes lost their `Idempotency-Key`.** `ManagedApp` sent one on its write
   requests; the console does not, so a retried hosted write can double-store a memory.
   Restore it on hosted writes, generated per logical write (not per retry).

Both need a test that can fail: for (4), that the control is disabled / the call is not
issued under a read-only entitlement and IS issued under an active one; for (5), that the
header is present and that two retries of the same logical write carry the SAME key while
two distinct writes carry different ones.
