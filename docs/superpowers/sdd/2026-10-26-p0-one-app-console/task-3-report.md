# Task 3 report: billing as an ordinary console page

Commit d084ec2 on top of 35c31c0. Status: DONE.

## Draft decisions
- billing.ts: KEEP + extend. Matches brief shape (Plan, PlanRow, planRows, upgradeRefusal, verbatim copy). planAction and paymentDestination faithfully port ManagedApp.tsx lines 95-98 and 126-127 (checkout only from free, portal otherwise, https + checkout/billing.stripe.com only). Added usageRows (ManagedApp's usage panel) so that behaviour is not lost when the second UI is deleted.
- billing.test.ts: KEEP + extend (usageRows test).
- BillingPage.tsx: KEEP + fix. Uses Page (eyebrow System, title Billing), xc-win/xc-btn/xc-title/xc-note/xc-kv/xc-callout only; no xc-managed-* class; no font sizes or radii. Added usage block and me.usage/counts types. Existing routes only: GET plans, GET me, POST checkout, POST portal with X-Cortex-CSRF-Token.
- PageHost.tsx: KEEP (adds `case 'billing'`).

## Ported from ManagedApp.tsx
Plan cards (price, three limits), per-plan button labels/disabled logic, Manage billing, read-only workspace notice, subscription status + cancel-at-period-end, usage, unconfigured copy "Paid subscriptions are not available yet.", Stripe redirect allowlist.
Not ported: sign-in/signup, landing pricing section, memory write/export, API keys, logout, the long plan-coverage footnote (not billing behaviour; only "Limits reset monthly in UTC" kept in the page note).

## Evidence of failure (route: MUTATION; draft pre-existed)
Mutations: price format changed to `USD n/mo`, upgradeRefusal returns null. Red output (verbatim tail):
```
-   "$29 / month",
+   "USD 0/mo",
+   "USD 29/mo",
  ]
 ❯ src/console/billing.test.ts:12:38
     10|   it('carries a formatted price and marks the current plan', () => {
     11|     const rows = planRows(plans, 'free')
     12|     expect(rows.map((r) => r.price)).toEqual(['$0 / month', '$29 / mon…
       |                                      ^
     13|     expect(rows.map((r) => r.current)).toEqual([true, false])
     14|   })
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/2]⎯
 FAIL  src/console/billing.test.ts > upgradeRefusal > is refused with a reason when billing is unconfigured
AssertionError: expected null to be 'Paid subscriptions are not available …' // Object.is equality
- Expected:
"Paid subscriptions are not available yet."
+ Received:
null
 ❯ src/console/billing.test.ts:26:43
     24| describe('upgradeRefusal', () => {
     25|   it('is refused with a reason when billing is unconfigured', () => {
     26|     expect(upgradeRefusal(false, 'free')).toBe('Paid subscriptions are…
       |                                           ^
     27|     expect(upgradeRefusal(true, 'free')).toBeNull()
     28|   })
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[2/2]⎯
 Test Files  1 failed (1)
      Tests  2 failed | 4 passed (6)
   Start at  03:15:01
   Duration  252ms (transform 43%, tests 37%, import 15%, worker 5%)
```
Second mutation (removed https check, usage default 1) -> `FAIL billing.test.ts > paymentDestination ... Tests 1 failed | 5 passed (6)`. Note: the usageRows `?? 0` mutation on writes was NOT caught (test supplies writes); the retrievals-absent case covers the same default for retrievals only. All mutations restored byte-exact from a saved copy.

## Passing
```
 RUN  v5.0.3 /mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design/viewer


 Test Files  1 passed (1)
      Tests  6 passed (6)
   Start at  03:15:03
   Duration  232ms (transform 54%, tests 27%, import 14%, worker 5%)


 Test Files  30 passed (30)
      Tests  321 passed (321)
   Start at  03:15:04
   Duration  3.37s (transform 43%, tests 29%, import 20%, worker 7%)

    Isolate  30 workers spawned · ~186ms startup each (spawn + environment, per file)
             at least ~1.67s faster with isolate: false — reuses workers across files instead of one per file

```
`npx tsc --noEmit -p tsconfig.app.json`: clean (exit 0). `npm run lint`: exit 0, only pre-existing warnings in other files, none in billing files.

## Concerns
- Page not exercised in a browser/Playwright (no hosted server available); only types, lint and unit tests.
- Self-hosted: billing absent from BUILT, so unaffected.

## Fix round 1
1. usageRows: added a fresh-month case (`used: {}`). Mutation `used.writes ?? 7` now red ("FAIL ... usageRows > reads zero for every counter on a fresh month ... Tests 1 failed | 7 passed (8)").
2. paymentDestination: added refusals for `https://checkout.stripe.com.evil.example/x`, `https://evil.example/checkout.stripe.com`, `https://evil.example/?stripe.com`, `https://evilstripe.com/x`, `https://stripe.com/x`, and a normalisation test (`https://CHECKOUT.stripe.com` -> `https://checkout.stripe.com/`). Mutations: `href.includes('stripe.com')` red; returning raw `url` red ("returns the normalised href"). The reviewer's `hostname.endsWith('stripe.com')` mutation stayed green on the listed inputs, because `checkout.stripe.com.evil.example` does not end in `stripe.com`; the real hole is hosts like `evilstripe.com`, so I added that and `stripe.com`; the mutation is now red. All mutations restored byte-exact (cmp).
3. Copy. Before: "This workspace is read-only. Your existing memories remain available to read and export. Update billing to resume writes." After: "This workspace is read-only. Your existing memories remain available to read. Update billing to resume writes."
Results: billing tests 8/8, full suite 323 passed, tsc exit 0, lint exit 0.
