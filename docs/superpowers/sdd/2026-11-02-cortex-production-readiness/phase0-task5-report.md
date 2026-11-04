# Phase 0 Task 5 report

Status: DONE_WITH_CONCERNS. Commit: 8a38002 (test). The deletion of ManagedApp.tsx, ManagedLenses.tsx and
managed.css is in 7f96180, not mine: my staged `git rm` was swept into a concurrent docs commit on this
shared worktree. Net effect on the branch is the same; the history attribution is wrong.

## Concern 1: Landing `managed` prop NOT removed (needs your decision)
The brief says remove `Landing.tsx`'s `managed` prop and its ~10 branches. That prop is LIVE:
`HostedLanding.tsx:122` renders `<Landing managed ...>`, and it selects the hosted hero/lead/primitives/facts
copy and `ProductSections showPricing={!managed}` (hides the self-hosted pricing section so the hosted `#pricing`
plan cards are the only ones). Removing it would silently change the hosted landing and break the plans tests
at managed.spec.ts:6. The brief assumed ManagedApp was the only caller. I left it alone. If the intent is to
rename it (e.g. `edition="hosted"`) or move the copy into HostedLanding, say so; it is independent of the rest.
It contains no `xc-managed-*` class, so step 6 is unaffected.

## Concern 2: the hosted grammar sweep cannot detect the two-app regression
With the edition fork restored the sweep stayed GREEN (see mutation below). It pins "Sign out OR profile button",
which ManagedApp also renders, and ManagedApp used the console's own CSS classes. I added
`the hosted workspace is the console shell, not a second app` to managed.spec.ts (`.xc-shell` visible, Billing in
`.xc-page-tabs`, `.xc-managed-inner` absent), which does go red.
Note: Billing is NOT a rail button on the default rail layout (the brief's `getByRole('button',{name:/^Billing\b/})`
at `/managed` finds nothing); it is a Settings peer tab, so the test goes to `#settings`.

## Re-homed tests (un-fixme'd)
1. stores/searches memory, creates/revokes key: Memories -> New memory -> "Text" -> "Add memory"; search via
   "Search memory text" + "Search"; keys on `#agents`. Fixture `seed: 2` so search is a real filter (a seeded
   memory must disappear), which the old test never proved.
   Kept: POST memories body `{content}`; Create API key disabled until DIDs filled (now asserted explicitly,
   disabled then enabled); `agent_ids` body de-duplicated/split; key not in localStorage; Revoke clears key and row;
   added: exactly one `keys/revoke` POST.
2. read-only: Kept: Export enabled; search enabled and works; read-only copy visible (now on `#billing`, where
   READ_ONLY_WORKSPACE lives); writes refused, strengthened to "no POST memories reached the server".

## Assertions dropped, and why they tested markup not behaviour
- `Memory saved with a verifiable event history.` text: ManagedApp's own success string. Behaviour is the POST
  body plus the row appearing in the list; replaced by the console's `Memory <id>… added to` notice.
- `.xc-managed-results` toContainText: a CSS class on ManagedApp's list. Behaviour (memory is returned by search)
  is kept against the console's "Memory list" region.
- `.xc-managed-key` toHaveText / toHaveCount(0): class of the key block. Same behaviour now read from
  `[aria-label="New API key"] code` and its absence after revoke.
- `Save memory` disabled: the console does not render a disabled write button; it removes `New memory` and
  `Import a document` and shows a "Read only." note. Asserted as count 0 + the note + no POST. Not a weaker claim.
- `Search / list` button enabled: ManagedApp's button label; replaced by actually running a search.
- `getByLabel('Memory')` / `'Search memories'` field labels: ManagedApp-only labels; replaced by the console's.

## Mutation evidence (step 3)
Restored from git: `main.tsx` = `git show 1d07f89^:viewer/src/main.tsx` (the `managed` path/edition fork) and
ManagedApp.tsx, ManagedLenses.tsx, managed.css from `7f96180~1`. Command:
`CI=true npx playwright test e2e/managed.spec.ts e2e/design-system.spec.ts --project=desktop --retries=0 -g "stores and searches|read-only subscriptions|hosted workspace"`
Result: 3 passed, 2 failed.
- PASSED (sweep did not notice): `the hosted workspace keeps its grammar at 390/1280/1600px`.
- RED: `a workspace stores and searches memory...` (waiting for button "New memory"),
  `read-only subscriptions retain export and search...` (note "Read only." not found).
- Then ran the new shell test alone under the same mutation: RED, `waiting for locator('.xc-shell')`.
Restored with `git checkout -- src/main.tsx` and removed the three files; shell test green afterwards.

## grep -rn "xc-managed-" viewer/src | grep -v BillingPage
(no output)

## CI commands (cwd viewer/)
- `npm run build`: success (vite built, ConsoleApp chunk 369.82 kB).
- `npx oxlint src e2e`: 0 errors, warnings only (pre-existing react-hooks / only-export-components).
- `npx vitest run --maxWorkers=1`: 34 files, 368/368 passed.
- `CI=true npx playwright test` (full, all projects): 198 passed, 0 failed, 0 skipped, 30.4m. (197 + the new shell test; the two fixmes now run.)

## Other notes
- Stale ManagedApp mentions remain only in comments (HostedLanding.tsx, Recall.tsx, managed.spec.ts) and in
  docs/plans; left as history.
- Not pushed, not merged, no PR.
