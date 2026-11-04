# Task 4 report: sweep of /managed

STATUS: DONE_WITH_CONCERNS. The test is GREEN, not red. I did not weaken anything.

## Extraction
- New viewer/e2e/managed-fixture.ts exports `managedFixture` (the `plans` array moved with it; imports only the Page type).
- viewer/e2e/managed.spec.ts imports it and calls it in place of the old local `fixture` (6 call sites, same arguments); unused `Page` import dropped.
- viewer/e2e/design-system.spec.ts imports it for the new test.

## Result
`npx playwright test e2e/design-system.spec.ts -g "hosted workspace" --project=desktop`
Running 3 tests; 3 passed (390, 1280, 1600). Violation list: empty at every width.

## Proof the tests ran (not skipped)
Port 28431 was held by a leaked anchor-stub (pid 2213517, cwd ~/Projects/xibalba-cortex/viewer, 1h54m old), plus a stack on 28420 and 25190. I did not kill them (not mine). I used the config's own env overrides: E2E_ANCHOR_PORT=38431 E2E_API_PORT=38420 E2E_UI_PORT=35190 E2E_CORTEX_HOME=<scratchpad>. The worktree's uv cannot resolve ../integrity-core (editable path missing), so I set E2E_PYTHON to the worktree .venv python and put a test-only shim named uv on PATH (in the scratchpad, outside the repo) that execs the .venv console script for the vite config's token-issuing call. Output listed "Running 3 tests using 1 worker" with a per-test line each.

## Why green is believable, not vacuous
- Probe at 1280px: signed-in workspace rendered (buttons Sign out, Manage billing, Export memories, Create API key...), 119 elements under .xc, 7 .xc-win, 0 .xc-shell, 1 .xc-managed-inner.
- The sweep has its own vacuity guards (>=20 elements, >=1 .xc-win); they held.
- Mutation: temporarily injected `.xc-btn{border-radius:6px !important}` (and a 19px price). The test failed with repeated "button rounded button.xc-btn: 6px". Mutation reverted; not committed.
So the current ManagedApp genuinely satisfies the sweep. Task 5 will not be "turned green by deleting the second UI"; it starts green and the test is a regression guard that the consolidated UI must keep passing. Not covered: the signed-out view (landing) and the 320px width.

## managed.spec.ts
8 passed (was 8 tests; unchanged apart from the fixture import).

## Concerns
1. The plan's premise (red gate) is false; commit message says so instead of the requested "Red on purpose" text.
2. Env workaround above is needed to run e2e in this worktree; leaked stack on 28431/28420/25190 should be cleaned by its owner.
3. I accidentally typed a git stash in one command; the harness denied it and nothing was stashed (tree verified).

## Fix round 1
- Added `await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()` before the sweep; reworded the in-file comment (regression guard, next task must keep it green).
- Discrimination: fixture flipped to `signedIn: false` -> 3 run, 3 FAILED at design-system.spec.ts:702 ("getByRole('button', { name: 'Sign out' })... element(s) not found"). Restored byte-exact (cmp) -> 3 run, 3 passed.
- `-g "hosted workspace" --project=desktop`: 3 ran, 3 passed. `managed.spec.ts`: 8 ran, 8 passed.
- Same env workarounds as before (alt ports 38431/38420/35190, scratchpad home, worktree .venv python, uv shim).
- Note: the page has no SVG, so the icon-stroke assertions are inert here.
