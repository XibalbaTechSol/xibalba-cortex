# Task 5d review — the console's data layer learns the hosted edition

Reviewer: independent task reviewer. Worktree
`/mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design`,
branch `docs/account-registration-design`, HEAD `15faa17`, BASE `fa9d801`.
Tree was clean at start and is clean at end (`git status --porcelain` empty, HEAD unmoved).
All mutations below were applied in place and restored with the inverse edit; no `git checkout`,
no `git stash`.

## Verdicts

- **Spec compliance: ✅**, with two deviations, both named and both accepted:
  (a) **`/api/import` is not mapped** — managed `import` is a different operation (structured
      bundle vs raw Markdown), so it falls under deliverable 2 and refuses locally with a reason;
  (b) **the finding-4 copy is `READ_ONLY_WORKSPACE`, not the `BILLING_UNAVAILABLE` /
      `upgradeRefusal` the brief named** — `upgradeRefusal` is literally
      `billingConfigured ? null : BILLING_UNAVAILABLE` (`billing.ts:45-47`), i.e. about whether
      checkout is configured at all, not about a read-only entitlement. Reusing it would have put
      the wrong sentence in front of the user. The implementer instead extracted BillingPage's own
      existing inline callout verbatim into `READ_ONLY_WORKSPACE` and made BillingPage render the
      constant, so one shipped sentence now has one definition. **The deviation is correct and the
      brief's instruction was the thing that was wrong.**
  Plus one partial miss of deliverable 2's "silently-by-design rather than by accident" (four
  accidental claims, Important #2 / #4 and Minor #5). None of this is a reason to hold the slice,
  which fixes a live production break.
- **Quality: APPROVED** (no Critical findings; 6 Important, 5 Minor)

---

## 1. Baselines — confirmed by my own runs, not accepted

Every count below I measured myself. e2e counts are read off Playwright's `Running N tests` line.
The leaked default-port servers (`:28420` pid 2213564, `:25190` pid 2213661) are still live; I did
not kill them and ran on my own ports (`28620/25390/28631`) with `E2E_PYTHON` pinned to the base
checkout's interpreter, as the implementer did.

| Check | Claimed | Measured | Verdict |
|---|---|---|---|
| `npx vitest run` | 368 / 34 files | **368 passed, 34 files** | ✅ |
| `npx tsc -b` **unpiped** | exit 0 | **TSC_EXIT=0** | ✅ |
| `npx oxlint` | exit 0 | **LINT_EXIT=0**, 13 pre-existing warnings, none in a touched file | ✅ |
| `hosted-paths.spec.ts` | 4 → 4 | **Running 4 tests → 4 passed** | ✅ |
| `managed.spec.ts` | 14 → 12 + 2 skipped | **Running 14 tests → 12 passed, 2 skipped** | ✅ |
| `console.spec.ts` | 49 → 49 | **Running 49 tests → 49 passed (6.1m)** | ✅ |
| `phone.spec.ts` | 6 → 6 | **Running 6 tests → 6 passed** | ✅ |
| `design-system.spec.ts -g hosted` | 5 → 5 | **Running 5 tests → 5 passed** | ✅ |

No suite exited 0 having run zero tests.

## 2. Mutation spot-checks — 11 of 21 re-run, all reproduce

### Unit

| # | Mutation applied | Result |
|---|---|---|
| M13 | `digest(…)` → raw `METHOD path body` fingerprint | RED: `keys on a digest, so a failed sign-in does not park a plaintext password in module state` |
| M2 | `if (target.route.write && writable === false)` → `if (false)` | RED: `refuses a write a read-only subscription forbids, locally, in Billing’s own words` |
| M3 | `writeKeyFor` never returns the memoized key | RED: `keeps the SAME key across retries of one logical write…` |
| M4 | `releaseWriteKey` never called on success | RED: `starts a new key once a write succeeded…` |
| M5 | `mutatingFetch`'s hosted early return removed | RED ×6, incl. `never asks /api/auth/csrf on a hosted write` and all four gate/idempotency tests |
| M6 | `store_access` forced `'writable'` | RED: `makes the hosted workspace out of the subscription…` |
| M6b | `writable: true` forced | RED: same test |
| M8 | `if (!target) return fetch(path, init)` | RED: `refuses a call the hosted backend has no route for without sending anything` |
| M10 | `send`'s `if (hostedActive())` → `if (true)` | RED: **all 4** `apiSelfHosted.test.ts` tests (report said 3 — there were 3 at the time of writing; now 4) |

**The `digest()` check is load-bearing exactly as described.** Reducing the fingerprint back to the
raw `METHOD path body` turns `pendingWriteFingerprints()` red with the plaintext password present.
Confirmed.

**The `Idempotency-Key` is per-logical-write, not per-retry.** Confirmed by code and by M3/M4:
the key is memoized on the payload digest and released on success, so a retry of a failed write
reuses it and a deliberate repeat gets a new one.

### e2e (`hosted-paths.spec.ts`)

| # | Mutation | Result |
|---|---|---|
| E2 | hosted branch removed from `api.ts`'s `send` — **the original production regression, restored** | **4 of 4 RED.** Tests 1–3 at `:49` (`.xc-conn` never reads "connected"); test 4 at `:149` (the seeded memory never appears). Under production 404 behaviour the hosted console does not load at all. |
| E4 | `if (!target) return fetch(\`/cortex-api${path}\`, init)` — the leak **wearing the dev-proxy prefix** | **3 of 4 RED** (report said test 1; it is in fact 1, 2 and 4). Test 1 red at `:106`, the escape assertion itself, listing `GET /cortex-api/api/stats`, `/cortex-api/api/status`, `/cortex-api/api/invocations`, `/cortex-api/api/memory/seed-0/events`, `/cortex-api/api/session/fixture-session/merkle-root`, `/cortex-api/api/agent-devices`, `POST /cortex-api/api/auth/logout`. |
| E5 | `workspaceFromMe` entitlement ignored | **Test 4 RED at `:156`, the "New memory" absence assertion itself**, not at the status-bar check behind it. |

**E4 settles the central question of this slice.** The recorder's `path.includes('/api/')` filter is
load-bearing: a `pathname.startsWith('/api/')` filter would have recorded nothing and passed with
the fix removed. The e2e genuinely discriminates production from dev.

**E5 settles the vacuity question for the absence assertion.** The assertion reorder in `15faa17`
is real work, not cosmetics: the absence itself is sensitive, not shadowed by the status check.

Report line-number drift noted: E2's test-4 failure is at `:149`, not `:143`. Substance identical
(the seeded memory); the lines moved in `15faa17`. Not a defect.

## 3. Self-hosted unchanged — proved, and the ordering claim holds

I verified the `a23b01e` ordering claim structurally and empirically:

- `a23b01e` changes **one file**, `viewer/src/apiSelfHosted.test.ts`. Confirmed with `--name-only`.
- `git rev-parse fa9d801:viewer/src/api.ts` == `git rev-parse a23b01e:viewer/src/api.ts` →
  the contract was recorded against the **byte-identical unmodified** `api.ts`.
- Running `a23b01e`'s test against `a23b01e`'s `api.ts`: **3 passed**. Green before the fix existed.
- Failability at that commit (M11 analogue): rewriting `'/api/stats'` → `'/api/managed/stats'` in the
  pre-change `api.ts` turns it **RED** (2 failed, diff shows `GET /cortex-api/api/managed/stats`).
  So the pre-fix measurement was a real measurement, not a snapshot.
- **The strongest leg, which I ran myself:** the *current* 4-test contract, run against the
  **pre-change `api.ts`**, is **4 passed**. The same table holds for both versions of the module.
  That is cross-version proof, not a post-hoc snapshot.
- M10 shows the table is specifically sensitive to the leak it exists to catch.

Self-hosted behaviour is genuinely unchanged and genuinely proved.

## 4. One source of truth — confirmed

`grep` across `viewer/src` finds the edition only in `console/edition.ts`, and in `ConsoleApp.tsx`
(lines 119/123/140/143/144/170 — the install site and the hosted-landing choice). `api.ts` has one
`send()` and one `mutatingFetch` early return, both transport-level. `ROUTES` in `hostedApi.ts` is
the only mapping. `console/workspace.ts` is **absent from the diff**, confirming no edition branch
leaked into it. No `edition === 'managed'` ternary exists at any call site. ✅

Backend untouched: the diff is 11 files, all under `viewer/`. ✅

### Deliverable 1's coverage, checked caller by caller

Deliverable 1 names destinations that are **not** in `ROUTES`. I verified each is already
managed-native rather than taking the report's word:

| Deliverable-1 item | Where it actually goes | Verdict |
|---|---|---|
| graph, timeline, memories (list / single / verify), agent0 trio | `ROUTES` in `hostedApi.ts` | ✅ mapped |
| keys, keys/revoke | `hostedRequest<{keys}>('keys')`, `hostedRequest('keys','POST')`, `hostedRequest('keys/revoke')` (AgentsPage) | ✅ native |
| plans | `hostedRequest<Catalog>('plans')` (HostedLanding, BillingPage) | ✅ native |
| checkout, portal | `managed<{url}>(kind, {method:'POST'}, csrf)`, `kind: 'checkout'\|'portal'` — `BillingPage.tsx:32` | ✅ native |
| me, logout | `hostedRequest('me')` / `hostedRequest('logout')` (ConsoleApp) | ✅ native |
| login, signup, recovery/* | `hostedRequest(path, {method:'POST'})`, `path` = `login` / `signup` / `recovery/${mode}` — `HostedLanding.tsx:88-90` | ✅ native |
| verify | not a client call: `managed/api.py:222` is a GET from the emailed link that redirects to `?verified` | ✅ nothing to map |
| export | `EXPORT_DOWNLOAD_PATH = '/api/managed/export-download'` (5a) | ✅ native |
| **import** | **not mapped** — refuses locally | ⚠️ the one deviation |

So deliverable 1 is met for everything except import, and all of it now goes through the one
shared transport. Nothing rests on the implementer's word.

## 5. Concern 5 — the self-confirming fixture, cross-checked at source

This was the concern most worth my time, and I did the cheap cross-check the implementer did not:
I read every transcribed shape out of `src/xibalba_cortex/managed/api.py`, `store.py` and
`managed/control.py` directly.

| Shape the implementer transcribed | Source of truth | Verdict |
|---|---|---|
| `graph` reads only `limit`, threshold fixed 0.75 | `api.py:422-435` `graph_operation` | ✅ exact |
| `timeline` → `{sessions, nodes}` | `api.py:434` | ✅ exact |
| `memories` GET → `{memories}`, cap 50, ignores `offset`/`status`/scope | `api.py:388` | ✅ exact |
| `memories/{id}` → `{memory}` | `api.py:384` | ✅ exact |
| `memories/{id}/verify` → raw `verify_chain` dict | `api.py:382-386` | ✅ exact |
| agent0 trio envelopes `{agents,source,query}` / `{agent,source}` / `{agent_id,reputation,source}` | `api.py:166-170` | ✅ exact |
| `me` → `{account, entitlement, usage, counts, csrf_token, destinations}` | `api.py:239-249` | ✅ exact |
| `entitlement.writable` boolean | `control.py:171-174` | ✅ exists |
| `counts.memories` | `store.py:2190-2200` | ✅ exists |
| `account.profile_id` / `account.display_name` | `control.py:87-97` | ✅ exist |
| `POST memories` requires `Idempotency-Key` 8–128, fingerprints the body, forces `status="active"` | `api.py:354-381` | ✅ exact |
| `import` takes a structured bundle, answers `{schema_version, inserted}` | `api.py:396-415` | ✅ exact |
| `keys` GET `{keys}` / POST `{label, agent_ids}` of `did:integrity:`, role `writer` | `api.py:314-352` | ✅ exact |
| `POST memories` reply → `store_memory` → `get_memory(id)` (full row, has `id`) | `store.py:1969`, `store.py:162` | ✅ and `MemoriesPage.tsx:250` reads only `created.id` |

**`verify-chain` ↔ `memories/{id}/verify` equivalence is now PROVED at source, not inferred.**
`local_api.py:1210` sends `memory_store.verify_chain(parts[2])` unwrapped; `managed/api.py:386`
returns `store.verify_chain(...)` unwrapped. Identical call, identical unwrapping. The
implementer's `NOT VERIFIED` on this item is over-conservative and can be retired.

**But the cross-check did find one real divergence, and it is in the fixture, not the mapping.**
`managed-fixture.ts` answers `memories/{id}/verify` with
`{memory_id, valid, events, chain_head}`. The real `GraphStore.verify_chain` returns
`{valid, length, broken_at_event_id, head_node_id}` (`store.py:1939-1944`). The fixture omits
`head_node_id` — which `VerifyPanel.tsx:53` reads — and invents `events` and `chain_head`.
Nothing currently asserts on it (no e2e opens VerifyPanel on hosted, and `memories/{id}/verify`
is not in test 1's positive-anchor list), so **no green test is false today**; but it is the
demonstrated instance of exactly the hazard the implementer named, and it is a landmine for the
next test written against this fixture. See Important #1.

Second, smaller divergence: the fixture's `me.account` has **no `profile_id`**, so every e2e so far
has exercised only `workspaceFromMe`'s `?? 'managed'` fallback id. The real backend always supplies
one. See Minor #1.

**Net ruling on concern 5:** the concern was honestly stated and is now substantially discharged.
The transcription is accurate in every field any reader consumes, verified against the Python
source. The fixture is upgraded from self-confirming to cross-checked, with two corrections owed.
What remains genuinely `NOT VERIFIED` is a live round-trip and the production `vite build` behind
`managed/api.py`; I did not attempt either and agree they are not cheap.

## 6. Rulings on the seven concerns

1. **Both out-of-brief fixes were real, necessary and soundly done.** I read
   `console/workspace.ts` myself: `hasVerifiedStoreScope` (line 17) requires `store_id`,
   `profile_id`, `store_access` and a boolean `writable`, and `canWrite = selected?.writable === true`
   (line 190). With no managed `/api/agents` route the list is empty, so hosted `canWrite` is
   false forever — strictly worse than the brief's finding 4, exactly as claimed. Finding 4's
   "control is disabled" half and finding 5's write path are both *unreachable* without this, so it
   is not scope creep: it is the precondition for two assigned findings. Reshaping `me` into the one
   hosted workspace and leaving `workspace.ts` untouched is the right shape — the edition stays in
   the one table. The `mutatingFetch` early return is likewise not optional: under the new transport
   `csrfHeader()` → `send('/api/auth/csrf')` now *throws* `HostedUnsupported`, so without it every
   hosted write would fail outright, not merely fire a 404. My M5 run (6 red) demonstrates this.
   **Not scope creep. Correctly kept in this slice.**

2. **"Different operation, refuse with reason" is the right call.** `import_operation`
   (`api.py:396-415`) requires a structured `xibalba.managed_import.v1` bundle and answers
   `{schema_version, inserted}`; `api.importDocument` POSTs raw Markdown bytes and the console reads
   `r.document.name/sections/sha256`. A client-side adapter would have to split the document and
   fabricate a `document` envelope with invented section counts shown to the user. That is a feature,
   not a mapping. Import therefore falls under deliverable 2, not deliverable 1, and the deviation
   is correctly flagged rather than quietly dropped. **Accepted deviation.**

3. **Acceptable to ship, but the implementer's framing is wrong: a client-side fix IS available
   inside the one table.** Narrower than stated, and broader than stated, both:
   *narrower* because the console's `DEFAULT_STATUSES` is `['active','confirmed']`
   (`MemoriesPage.tsx:22`) and managed `list_memories` defaults to exactly those two
   (`store.py:2472`), so the default view is accidentally honest — the lie appears only when a chip
   is deselected; *broader* because the implementer says the only fixes are a backend parameter or
   a call-site ternary, and that is not so. The rows carry `status` (rendered at
   `MemoriesPage.tsx:202`), so the memories adapter can filter client-side, or `ROUTES` can export
   a `supports(method, path, param)` capability query. Either lives entirely inside `hostedApi.ts`
   and is a query against the single table, not an `edition === 'managed'` ternary, so neither
   violates the brief. **Ships, but Important #2 — the implementer's "no option exists" claim does
   not hold.**

4. **Same class as 3, worse UX, but here the refusal is the defensible answer.** Hybrid is the
   default mode and pressing Enter on hosted yields a stated refusal. I checked the parity claim
   rather than assuming it: `ManagedApp.tsx:102-104` has exactly one search, `request('memories?q=')`
   — lexical only, no hybrid or context mode at all — so a hosted user's search **did** work on the
   first press before this slice and now does not. That is a genuine UX regression even though no
   hybrid capability was lost. Unlike 3, there is no honest client-side mapping:
   routing `/api/retrieval/hybrid` to `memories?q=` would *claim* hybrid retrieval and deliver
   lexical, which is a worse lie than a refusal. A `supports()`-driven default (fall back to Lexical
   when no hybrid route exists) is the clean fix and is the same mechanism as 3's. **Acceptable to
   ship with a stated refusal; Important #3 to fix with the same `supports()` export.**

5. **Substantially discharged by my own source-level cross-check** — see section 5. Every
   transcribed shape is correct; `verify-chain` equivalence is now proved rather than inferred;
   the fixture's `verify` body is wrong but load-bearing on nothing. The other NOT VERIFIED items:
   the `>50` hosted workspace is a real product-facing defect, not merely unverified (Important #4);
   the production `vite build` behind `managed/api.py` remains genuinely NOT VERIFIED and I agree
   it is out of reach here. **Concern was honest; evidence now stands on cross-checked ground.**

6. **Nothing was lost.** The discarded fingerprint `digest` is present in the committed tree
   (`hostedApi.ts:217-221`, used at `:273`, added in `15faa17`) and is guarded by a test I ran red
   myself (M13). A residue scan for `if (false)`, `if (true)`, `const existing = undefined` and
   `cortex-api${path}` across `viewer/src` and `viewer/e2e` finds **nothing**. 368/368 green,
   tsc 0, lint 0. `15faa17` also *removed* a genuinely vacuous assertion
   (`expect(calls.filter(POST memories)).toEqual([])` under read-only) — self-correction, in the
   right direction. **Closed.**

7. **Noted, nothing touched.** The leaked e2e servers are still live: `:28420` pid 2213564
   (python3) and `:25190` pid 2213661 (node). I did not kill them and ran on `28620/25390/28631`.
   I confirmed what they are from `/proc/<pid>/cmdline`, read-only: pid 2213564 is
   `xibalba_cortex.local_api --home /tmp/cortex-e2e --port 28420` and pid 2213661 is
   `vite --host 127.0.0.1 --port 25190 --strictPort`, both cwd `~/Projects/xibalba-cortex`. They
   serve a throwaway `/tmp/cortex-e2e` profile and are definitively e2e leftovers, **distinct** from
   the live-service `local_api` processes on 8420/8422/8423/8424/8427/8428 (which serve
   `~/.hermes/*` and `~/.claude/*` homes) and from the vite on 5190. `pyproject.toml` has the editable path dep on a
   sibling `integrity-core` checkout that is not beside this worktree, so `uv run` cannot resolve
   it; I did not modify `pyproject.toml` and pinned `E2E_PYTHON` to the base checkout's
   interpreter instead, with `PYTHONPATH` already pointing at the worktree's `src` via
   `playwright.config.ts`. **Both hazards real; both to be cleared outside this slice.**

## 7. Findings

### Critical
None.

### Important

1. **`managed-fixture.ts`'s `memories/{id}/verify` body does not match reality.** It answers
   `{memory_id, valid, events, chain_head}`; `GraphStore.verify_chain` returns
   `{valid, length, broken_at_event_id, head_node_id}`. `VerifyPanel.tsx:53` reads `head_node_id`,
   which the fixture never sends. Nothing asserts on it today, so no test is false — but this is
   the concrete instance of the self-confirming-fixture hazard and the next test written against it
   will be wrong. Correct the fixture to the real shape.

2. **`MemoriesPage`'s status chips: fix it in the table, don't defer it to the backend.** The
   mapping drops `status`; the chips still look like they filter. The rows carry `status`, so a
   filter in the memories adapter (or a `supports(method, path, param)` export derived from
   `ROUTES`) fixes it without any call-site edition branch. The implementer's stated reason for not
   fixing it ("backend, or a ternary the brief forbids") is not accurate.

3. **Recall's default mode on hosted.** A hosted user's first Enter fails. Derive the default from
   the same `supports()` export as #2 so hosted defaults to Lexical, rather than leaving the
   primary action of a declared destination broken.

4. **The New-memory form's `status` and `evidence_class` selects are silently discarded on
   hosted.** `body: (d) => ({ content: d.content ?? '' })` drops them and `api.py:376` forces
   `status="active"`. The user picks "candidate", the memory is stored "active", and nothing says
   so. This is a *write* whose metadata differs from what the user chose — arguably worse than the
   read-side chips in #2. The implementer notes it in a code comment and in the shape table but
   does **not** list it among its concerns. Either hide the two selects on hosted via the same
   `supports()` mechanism, or state the substitution in the form.

5. **Refusal copy is developer-facing and reaches users verbatim.** `HostedUnsupported`'s message
   is `The hosted edition does not serve GET /api/memory/seed-0/events.`, and
   `useAsync` (`useAsync.ts:31`) plus `MemoriesPage.tsx:59` render `e.message` straight into
   user-visible callouts. Hosted users will see HTTP methods and internal route names across eight
   Inspector panels, four Settings sections, Recall's two modes, import and the memory actions.
   Give `HostedUnsupported` a human sentence and keep `METHOD path` in a separate non-rendered
   field for diagnostics.

### Minor

1. The fixture's `me.account` omits `profile_id`, so every e2e has exercised only
   `workspaceFromMe`'s `?? 'managed'` fallback. The real backend always supplies it. Add it, so the
   fixture tests the real branch.

2. **`installHostedTransport()` is called in `ConsoleApp`'s render body (line 140) while
   `clearHostedTransport()` is an effect cleanup (line 144).** Asymmetric, and a side effect during
   render. Under `StrictMode` (which `main.tsx:19` does use) the double-invoked cleanup disarms the
   transport until `me` lands and triggers a re-render. Empirically safe today because the console
   renders nothing before `me` resolves — and the e2e, which runs under StrictMode, shows no
   escape — but the safety is incidental. Pair install and clear in the same effect, or make the
   install idempotent from inside the effect.

3. `send`'s doc comment calls itself "the ONLY edition branch in the data layer" while
   `mutatingFetch` carries a second `hostedActive()` branch nine lines above. Both are
   transport-level so the brief's constraint is honoured; the comment overstates. Reword.

4. `digest` is 32-bit djb2 plus a length suffix. A collision between two different hosted POST
   bodies would make them share a key, which the server rejects (reused key, different fingerprint)
   rather than mis-storing. Acceptable; worth a comment naming the failure mode. Separately, two
   *concurrent* identical writes share one key by construction, so the second is server-deduped.

5. **`has_more: false` / `complete: true` claims completeness on a capped page.** Managed serves
   one unpaged page of 50; the adapter reports `has_more: false`, so `MemoriesPage.tsx:222-225`
   disables "Next" and omits "· more available", and `data.ts:26` marks the memory index
   `complete: true`. **Ranked Minor rather than Important because the data cap is parity:**
   `ManagedApp.tsx:103-205` rendered exactly one page of `memories?q=` with no pager, limit, offset
   or "more" handling at all, so no capability is lost. What *is* new is the claim — the console has
   a pager and now asserts completeness where ManagedApp asserted nothing. `complete: true` on a
   partial index is a false claim and should be replaced by a stated notice when the page returns
   at the cap.

6. **`console/ManagedLenses.tsx:11` is a FOURTH copy of the hosted fetch**, not the third the
   report counts. It is dead on hosted (imported only by `ManagedApp.tsx`, which `main.tsx` no
   longer boots), so there is no live bypass — but 5c must delete **both** files, and the report's
   handoff names only `ManagedApp.tsx`.

## 8. NOT VERIFIED

- **A live managed backend round-trip.** Every hosted assertion still runs against
  `managed-fixture.ts`. I cross-checked every shape against `managed/api.py`, `store.py` and
  `control.py` at source (section 5), which removes the self-confirmation for the *shapes*, but no
  real handler was invoked. I did not stand up a `TestClient` run.
- **A production `vite build` with `VITE_CORTEX_EDITION=managed` served behind `managed/api.py`.**
  Not attempted. The e2e's 404-everything-non-managed emulation is the behaviour that matters, and
  it is an emulation.
- **A hosted workspace with more than 50 memories.** The fixture seeds 1–2. See Minor #5 for what
  the code does in that case, which I established by reading rather than running.
- **Hosted sign-out against a real backend** (that the cookie is actually cleared). The fixture
  answers `{ok: true}`.
- **Headers/body for the 97 self-hosted calls outside the extended leg's five.** Method and URL are
  measured for all; `credentials`/headers/body for five. The implementer states this narrowing
  correctly and I confirm the narrowed claim is the accurate one.
- `verify-chain` ↔ `memories/{id}/verify` is **no longer** NOT VERIFIED: proved at source
  (`local_api.py:1210` and `managed/api.py:386` both unwrap `store.verify_chain(id)`).
