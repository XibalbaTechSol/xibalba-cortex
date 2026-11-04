# Task 2 report

## Changed
- viewer/src/console/nav.ts: PageId += billing; ALL_DESTINATIONS billing entry LAST (label Billing, group system, hint "Plan, usage and invoices"); BUILT += billing; PAGE_TABS billing appended to settings/operations/agents + new `billing` key; TAB_LABEL.billing; PAGE_IDS += billing (needed or `#billing` never parses); new `destinationsFrom`, `builtFrom`; `tabsFor(page, list = DESTINATIONS)` widened in place.
- viewer/src/console/nav.test.ts: new describe block (7 tests, includes the brief's 6 plus a null/undefined case and a single-arg tabsFor check).
- viewer/src/console/PageDrawer.tsx (WIDTH.billing) and Shell.tsx (DESTINATION_ICON.billing, reuses IconSettings): required, exhaustive Records over PageId/DestinationId stopped compiling once PageId gained billing.

## Step 2: failing output (before implementation; missing exports)
```
⎯⎯⎯⎯⎯⎯⎯ Failed Tests 7 ⎯⎯⎯⎯⎯⎯⎯
 FAIL  src/console/nav.test.ts > a server-declared destination set > an empty or absent declaration keeps every built destination
TypeError: destinationsFrom is not a function
 FAIL  src/console/nav.test.ts > a server-declared destination set > an unknown declared id is ignored rather than rendered
TypeError: destinationsFrom is not a function
 FAIL  src/console/nav.test.ts > a server-declared destination set > a declaration narrows to the intersection with BUILT, in canonical order
TypeError: destinationsFrom is not a function
 FAIL  src/console/nav.test.ts > a server-declared destination set > a tab strip drops peers the server did not declare
TypeError: destinationsFrom is not a function
 FAIL  src/console/nav.test.ts > a server-declared destination set > tabsFor with one argument is unchanged for self-hosted
AssertionError: expected [ 'settings', 'operations', 'agents' ] to deeply equal [ 'settings', 'operations', …(2) ]
 FAIL  src/console/nav.test.ts > a server-declared destination set > an undeclared hash route resolves against the narrowed set
TypeError: destinationsFrom is not a function
 FAIL  src/console/nav.test.ts > a server-declared destination set > billing is a system destination with a tab label
AssertionError: expected undefined to be 'system' // Object.is equality
 Test Files  1 failed (1)
      Tests  7 failed | 10 passed (17)
```

## Step 4: passing output
```
 Test Files  1 passed (1)
      Tests  17 passed (17)
```
Full viewer suite: 29 files, 314 tests passed.

## Typecheck / lint
`npx tsc --noEmit -p tsconfig.app.json` clean (it first FAILED on PageDrawer/Shell Records, fixed as above); `npm run build` succeeds; `npm run lint` only pre-existing warnings, no errors.
(Note: worktree had no node_modules; ran `npm ci` in viewer/.)

## Concerns
- Ruling 1 puts billing in BUILT, so with no declaration self-hosted now lists Billing in the phone "More" sheet and in the settings/operations/agents tab strip, but PageBody has no `billing` case (Task 5/later must add a surface). This violates "self-hosted behaviour must not change" until billing has a surface or self-hosted narrows it out. Left as ruled.
- Billing reuses IconSettings as a placeholder icon.

## Fix round 1: billing is not BUILT

Changes: removed billing from BUILT (comment now says BUILT is the self-hosted set and managed-only destinations are absent); destinationsFrom resolves a non-empty declaration against ALL_DESTINATIONS; DESTINATIONS unchanged so self-hosted tabsFor default has no billing. Added test 'self-hosted does not list billing, but a server that declares it does'; corrected the single-arg tabsFor test to expect ['settings','operations','agents']. Icon: no card/receipt/tag icon exists, kept IconSettings with a one-line comment.

### Red output (before the fix), command: npx vitest run src/console/nav.test.ts
```
⎯⎯⎯⎯⎯⎯⎯ Failed Tests 2 ⎯⎯⎯⎯⎯⎯⎯
 FAIL  src/console/nav.test.ts > a server-declared destination set > tabsFor with one argument is unchanged for self-hosted
- Expected
+ Received
+   "billing",
 FAIL  src/console/nav.test.ts > a server-declared destination set > self-hosted does not list billing, but a server that declares it does
- Expected
+ Received
- false
+ true
      Tests  2 failed | 16 passed (18)
```

### Green and checks
```
$ npx vitest run src/console/nav.test.ts
 Test Files  1 passed (1)
      Tests  18 passed (18)
$ npx vitest run
 Test Files  29 passed (29)
      Tests  315 passed (315)
$ npx tsc --noEmit -p tsconfig.app.json
exit 0
$ npm run lint
src/console/VerifyPanel.tsx:62:17: warning react(only-export-components): Fast refresh only works when a file only exports components. Use a new file to share constants or functions between components.
design-tools/capture.mjs:191:58: warning eslint(no-unused-expressions): Expected expression to be used help: Consider using this expression or removing it
```
