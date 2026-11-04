# Task 5c — Delete the second UI, and prove the gate

Final slice of the plan's Task 5. Everything the hosted edition needs must already
exist on the console by now (Task 3 billing, 5a keys + export, 5b app root + landing).

## Files
- Delete: `viewer/src/console/ManagedApp.tsx`, `viewer/src/console/ManagedLenses.tsx`, `viewer/src/console/managed.css`
- Modify: `viewer/e2e/managed.spec.ts` — replace assertions naming `xc-managed-*` layout.
- Modify: whatever still references the deleted files.

## The gate — must be SEEN red before the deletion and green after
At `/managed`, signed in:
- the console shell is present, asserted PER LAYOUT: `.xc-shell` at desktop widths, and whatever `PhoneWorkspace` renders at 390px. `.xc-shell` exists ONLY in the non-phone `settings.shell === 'rail'` branch (`ConsoleApp.tsx:78`), so an unconditional assertion goes red because of the viewport rather than the consolidation — that would be a vacuous gate.
- the rail lists Billing.
- `.xc-managed-inner` has count 0, at every width.

## Final checks
- `grep -rn "xc-managed-" viewer/src | grep -v BillingPage` -> no output.
- Task 4's sweep `-g "hosted workspace"` must STAY green (it is a regression guard, not a gate; it was green before the consolidation).
- `npm run build`, `npm run lint`, `npx vitest run`, `npx playwright test --project=desktop` all green.
- If the sweep goes red, the violations are real grammar bugs in the consolidated UI: fix the UI, never the sweep.

## Carried finding
`Landing.tsx:116` still claims memories "remain available to read and export if a subscription becomes read-only". Task 3 removed that unsupported claim from the billing page. By 5c, 5a has re-homed a real export control — so either the claim is now substantiated (say where the control is) or it is reworded. Do not leave it unexamined.

## Playwright trap
`npx playwright test` can exit 0 having run NOTHING, printing `127.0.0.1:28431/healthz is already used`. A leaked stub holds 28431; other stacks hold 28420/25190. Do not kill any process — use `E2E_ANCHOR_PORT`/`E2E_API_PORT`/`E2E_UI_PORT`/`E2E_CORTEX_HOME`, and `E2E_PYTHON` for the worktree `.venv`. Confirm the test COUNT from real output.
