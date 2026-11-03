# Cortex Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one Cortex application — the console — that a hosted customer can sign up
for, register any agent harness against, ingest full provenance-bearing turns into, and pay
for.

**Architecture:** There is one app and it is the console; the managed edition is that same
app configured for hosting, with its navigation narrowed to a server-declared destination
set. Authentication is one cookie-session contract with an edition adapter behind it.
Ingestion reuses the handler that already exists — `GraphStore.ingest_agent_turn` — exposed
over two transports that hold no logic of their own, so a Grok bot, a Cindy desktop, an
adapted harness and a `curl` all produce the same stored record.

**Tech Stack:** Python 3.12 with Starlette and the MCP Python SDK; TypeScript, React 18 and
Vite; Playwright and vitest; SQLite; Stripe; uv.

**Spec:** `docs/superpowers/specs/2026-10-26-cortex-account-and-agent-registration-design.md`
(approved 2026-10-26, reaffirmed and amended 2026-11-02). The plan argues from the spec;
executors read both.

**Scope note.** This document covers six subsystems, which would normally be six plans. It
is deliberately one document, sequenced into phases, because the phases share one branch and
one deploy gate. **Each phase is independently shippable and independently reviewable.** Do
not start a phase before its predecessor's "Phase done when" holds. Phase 0's task detail is
**not duplicated here** — it lives in
`docs/superpowers/plans/2026-10-26-p0-one-app-console.md`, which is still the authority for
those steps.

---

## Resume Brief — read this first after a context reset

**Branch:** `docs/account-registration-design`, worktree
`/mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design`.
Pushed and verified; `git log --oneline -1` should be at or after `e4b8a60`.

**Repo state, verified 2026-11-02:**

- `origin/main` does **not** carry the code work. PR #74 squash-merged **only the docs**
  (`152f7c4f`). `hostedApi.ts`, `edition.ts`, `BillingPage.tsx` and `HostedLanding.tsx` are
  absent from `origin/main`, and its `main.tsx` still forks to `ManagedApp`. **The live
  pilot is untouched.**
- The branch is **behind `origin/main`** and must be rebased before any merge. The gap was
  8 commits at 23:50Z and had grown to 12 shortly after, so re-measure rather than trusting
  this number: `git rev-list --left-right --count origin/main...HEAD`.
- `main` **auto-deploys** Render `cortex-managed-pilot` (`srv-dbfavo67bikc73crb8u0`).
  Merging is a deploy. **Stop and get operator approval before merging.**
- PR #73 is **merged**, so P0's recorded blocker is cleared and `agent0_wallet.ts` /
  `agent0_integration.py` are present.

**Suite state, measured 2026-11-02:**

- `npx tsc -b` clean; `npx oxlint` clean (13 pre-existing warnings, 0 errors).
- `npx vitest run` — **368 passed / 368**.
- `npx playwright test` — **no baseline exists.** A `--project=desktop` run was killed at
  27 minutes having emitted nothing, because it was piped through `tail`. Re-take the
  baseline with `--reporter=line` redirected to a file, run in the background, and read the
  file. **Phase 0 Task 5 Step 2 depends on this baseline.**

**Environment prerequisite for any e2e run from a worktree.** `pyproject.toml`'s
`[tool.uv.sources]` makes `integrity-sdk` an editable path dependency at
`../integrity-core/integrity-sdk`, which CI satisfies by checking both repos out as
siblings (`ci.yml:57` asserts it). A worktree has no such sibling, so `uv run` fails
metadata generation before any browser starts. Create the sibling once per worktree root:

```bash
ln -sfn /home/xibalba/Projects/integrity-core \
        /mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/integrity-core
```

Verified harmless on 2026-11-02: integrity-core's base stayed clean and `uv.lock` was
untouched. `E2E_PYTHON` alone is **not** sufficient — `viewer/vite.config.ts` separately
shells out to `uv run xibalba-cortex-ingest-tokens`.

**Local green is not CI green.** Two known divergences, both of which must be closed before
the merge gate:

1. The integrity-core base is **3,662 insertions ahead** of the SHA CI pins (`4ddaae19`),
   and the symlink points at the base. Check with
   `git -C ~/Projects/integrity-core diff --stat 4ddaae1965635224958e147f6eaaead06e3cdc41 HEAD -- integrity-sdk`.
2. CI runs **every** Playwright project; a `--project=desktop` run skips the rail and phone
   projects this branch added tests for.

Run exactly what CI runs before claiming green:

```bash
npm run build && npx oxlint src e2e && npx vitest run --maxWorkers=1 && CI=true npx playwright test
```

**A stale managed instance is running locally** at `http://127.0.0.1:8430/managed`. It
serves `ManagedApp` and predates the `/readyz` route (`/readyz` returns the SPA HTML, so the
request falls through to the `{path:path}` catch-all). It is useful only as the *before*
screenshot for Phase 0. Do not treat it as a current build.

**Open question, unresolved, owned by Phase 5 Task 6.** The README claims "80 tools" in two
places and cites `tests/test_server.py`'s inventory assertion as the enforcer, but
`server.py` carries 89 `@server.tool` decorators and the assertion could not be located by
name. **Do not put any tool count in the README until the test is read and the real number
established.** Both numbers are currently unsupported.

---

## Global Constraints

Values copied verbatim from the spec. Every task's requirements implicitly include this
section.

- **One application.** `main.tsx` boots `ConsoleApp` unconditionally. `VITE_CORTEX_EDITION`
  selects configuration inside `console/edition.ts`, never a component.
- **Session shape.** HttpOnly cookie, `SameSite=Lax`, `Secure` when the public origin is
  HTTPS, CSRF token required on mutations.
- **Cortex must not become an identity authority.** "Agent0 remains external chain evidence,
  not workspace authorization." On-chain registration alone grants no workspace access.
- **No in-page key generation.** `agent0_wallet.ts` registers through an EIP-1193 injected
  provider; signing stays in the wallet extension. Ship no key material.
- **Existing managed cookies must keep working** across every auth change. No pilot user is
  signed out by a migration.
- **No credential is committed, printed, or retained.** Base Sepolia credentials have
  previously been found exposed in local env files. Alchemy is preferred for Base Sepolia
  RPC with `https://sepolia.base.org` as the approved read-only fallback.
- **Every check must be proved able to fail.** Revert the check, confirm the specific test
  goes red, restore. A conformance pass that cannot fail has measured nothing. This is a
  step in every task below, not a preference.
- **Destinations are server-declared.** A destination is declared in one place and appears
  in nav, routes and surfaces; it cannot drift between them.
- **Plan limits** are `max_memories`, `writes_per_month`, `retrievals_per_month`. Tiers are
  Free $0 / Pro $2900 cents / Team $14900 cents.
- **Merge only on green CI**, with `gh pr merge --match-head-commit <sha-CI-ran-on>`.
- **Never `git stash`** — the stack is shared across worktrees. Use a WIP commit.
- Push with `xb-wt push` and verify with `ls-remote` or `rev-parse`; `push -u` can print
  "Everything up-to-date" and send nothing.
- **The worktree already exists**, created by `xb-wt` at
  `/mnt/storage/xibalba/Projects/worktrees/xibalba-cortex/account-registration-design`. Do
  **not** create another, and never `EnterWorktree(name=...)` — that puts the tree in a
  fifth location. If an execution sub-skill routes through `using-git-worktrees`, skip that
  step: this constraint overrides it.
- **There is no `tests/conftest.py`.** Every fixture a task names — `tmp_home`,
  `frozen_clock`, `managed_client`, `managed_app`, `legacy_cookie`, `api_key` — must be
  created by the first task that uses it, in `tests/conftest.py`, as part of that task's
  Step 1. Do not assume any of them exist.

---

## Review Focus

Five input classes the spec implies but no phase's happy path exercises, most likely to bite
a real user first. Each has its test pinned to the task that owns the code.

1. **A revoked credential that keeps working.** Revocation that updates a row but is not
   consulted on the next request is the default failure of every token system. Phase 1
   Task 3 asserts the request succeeds before revocation and fails after.
2. **A cross-workspace write that succeeds.** Mounting MCP publicly means a token from
   workspace A reaching workspace B is now possible in a way it never was on localhost.
   Phase 5 Task 2 attempts it and requires refusal.
3. **Two transports drifting.** MCP and REST were both chosen with that risk stated. Phase 5
   Task 4 asserts the same turn over both produces identical stored records, and proves it
   by changing one transport alone.
4. **A webhook replayed.** Stripe retries. An entitlement that advances twice on one event
   over-grants or double-charges. Phase 3 Task 2 replays the same event and asserts the
   second is a no-op.
5. **An enrollment code used twice, late, or from the wrong workspace.** It is a bearer
   secret. Phase 2 Task 2 covers expired, already-redeemed, wrong-workspace and
   bad-signature redemptions as four distinct non-enumerating refusals.

---

## Execution order — amended 2026-11-03

**Phase 5 Tasks 1 and 2 run immediately after Phase 0**, ahead of Phases 1, 2 and 3.
Operator decision: reach a deployable test build sooner. Those two tasks are what make the
hosted product able to do the thing it currently cannot — record provenance-bearing turns —
and Phases 1-3 harden auth and billing without unblocking testing.

Running order: **Phase 0 → Phase 5 T1, T2 → Phase 1 → Phase 2 → Phase 3 → Phase 5 T3-T6.**

**The reorder breaks no dependency.** Phase 5 Task 1 Step 6 was written as "call the
enforcement Phase 3 Task 3 built". Verified 2026-11-03: **that enforcement already exists
on `main`** and needs nothing from Phase 3 —

- `ManagedControl.consume(tenant, meter, *, request_key=None, fingerprint="")`
  (`control.py:183`) enforces `writes_per_month` and `retrievals_per_month` atomically
  (`UPDATE usage SET amount=amount+1 WHERE ... AND amount<?`, raising `LimitExceeded` when
  the row does not change), refuses writes on a read-only entitlement, and carries
  idempotency through `request_key` + `fingerprint`.
- `max_memories` is enforced by `GraphStore`'s own quotas, passed in `control.store()`
  (`control.py:229`).
- Routes already call it: `api.py:161, 369, 378, 405, 426`, inside
  `service.write_guard(tenant)` and `service.store(tenant)`. `LimitExceeded` is mapped to a
  response by the handler at `api.py:491` and registered at `api.py:534`.

So Phase 5 Task 1 **calls the existing `service.consume(tenant, "writes", ...)`** rather
than building anything, copying the shape of `api.py:368-370`. This also means **Phase 3
Task 3 is mostly already implemented**; its remaining value is the three
proved-able-to-fail tests, which is why it stays in the plan.

**`control.store()` is also the workspace scoping Phase 5 Task 2 needs**, already hardened:
it validates the tenant id's shape, rejects a symlinked tenant root, and rejects a resolved
path whose parent is not the storage root (`control.py:216-224`). Task 2's job is therefore
to prove the route derives its tenant from the **token** and never from the payload — not to
build path isolation.

**Fixture ownership moves with the order.** Phase 1 Task 4 was to create `managed_app` and
`api_key` in `tests/conftest.py`; Phase 5 Task 1 now runs first, so **Phase 5 Task 1 creates
them**. Phase 1 Task 4 reuses them.

**Phase 1 Task 4's `xfail` inverts.** It was marked
`@pytest.mark.xfail(strict=True)` because the ingest route did not exist yet. Under the new
order it **does** exist, so Phase 1 Task 4 writes that test as an ordinary passing test with
no marker, and Phase 5 Task 1 has no marker to remove.

---

## Phase 0 — One app, and it is the console

**Task detail lives in `docs/superpowers/plans/2026-10-26-p0-one-app-console.md`.** Do not
re-plan it. Tasks 1–4 and Task 5 Step 3 have landed; that plan's "Execution status" section
records what shipped against which commit.

**Remaining work is Task 5, starting at Step 1**, in this order, because the order is the
whole point: `managed.spec.ts` currently asserts against `ManagedApp.tsx:177` and `:209`, so
deleting the file first would leave tests pointing at nothing.

1. Re-take the Playwright baseline (see Resume Brief) and record it.
2. Step 1 — write the replacement assertions in `viewer/e2e/managed.spec.ts`: after sign-in
   at `/managed`, `.xc-shell` is visible, the rail lists Billing, `.xc-managed-inner` has
   count 0.
3. Step 2 — run and **record the failure**. It must fail, because `ManagedApp` renders
   `.xc-managed-inner`.
4. Step 4 — `git rm` `ManagedApp.tsx`, `ManagedLenses.tsx`, `managed.css`; remove
   `Landing.tsx`'s `managed` prop and its ten branches; remove every remaining
   `xc-managed-*` reference outside `BillingPage`.
5. Steps 5–7 — confirm the suite green with CI's exact command, confirm
   `grep -rn "xc-managed-" viewer/src | grep -v BillingPage` is silent, commit.

**Phase done when:** one app root; `/managed` renders the console `Shell` and lenses; the
grammar sweep covers `/managed` and is green; no `xc-managed-*` layout class survives except
the billing panel's.

---

## Phase 1 — One auth contract, with scoped sessions and real revocation

The spec's P1, amended 2026-11-02. **Corrected 2026-11-03 after reading the code:** an
earlier revision of this phase planned a new `managed/auth.py` with a fresh
`issue_session`. That would have built a *third* auth system. It is wrong, and here is what
is actually true.

**`accounts.py` is already the one shared implementation.** `issue_account_session(home, *,
email, password, ttl_hours=24)` at `accounts.py:209` and `revoke_account_session` at `:473`
are called by **both** editions — `managed/api.py:232` and `:253` go straight to them. So
"managed stops owning authentication" is **largely already true**; what managed still owns
separately is its cookie name (`cortex_managed_session`, `api.py:37`), its CSRF derivation
(`api.py:99`) and its `recovery/{action}` routes.

**Three of the four things this phase was going to build already exist:**

| Claimed gap | Reality |
|---|---|
| Sessions expire | **Already.** `ttl_hours=24`, stored as `expires_at` on an `ingest_tokens` row (`accounts.py:244,253`) |
| Expiry is enforced | **Already.** `ingest_tokens.py:147` verifies `revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)` |
| Revocation is effective | **Already.** `revoke_account_session` sets `revoked_at`; the same verify consults it |
| Sessions are scoped | **No — this is the real gap.** `accounts.py:252` issues `all_known_scopes`: every scope any role grants |

So the genuine work is narrower and sharper than "build auth": **narrow the session's
scopes, shorten its lifetime, add rotation, and keep both editions on the one
implementation.** The revocation tests still get written — a behaviour that works today and
is untested is one refactor away from not working — but their "implement" step is mostly
already done, which is the expected and correct outcome.

### File Structure

- `src/xibalba_cortex/accounts.py` — **modify.** The single auth implementation. Scope
  narrowing, a shorter default TTL, and rotation land here, not in an edition.
- `src/xibalba_cortex/managed/api.py` — **modify.** Keeps its cookie, CSRF and recovery
  routes; gains nothing that belongs in `accounts.py`.
- `viewer/src/console/SignIn.tsx`, `viewer/src/hostedApi.ts` — **modify.** One component,
  one client contract.
- `tests/conftest.py` — **create** (does not exist; see Global Constraints).
- `tests/test_account_sessions.py` — **create.**

### Task 1: Record what session auth does today, before changing it

The branch already set this precedent: `a23b01e` recorded the self-hosted wire contract
before changing it. Do the same here, because this phase edits the one code path that can
sign out every pilot user.

**Files:**
- Create: `tests/conftest.py`, `tests/test_account_sessions.py`

**Interfaces:**
- Consumes: `accounts.issue_account_session(home, *, email, password, ttl_hours=24) -> tuple[str, dict]`,
  `accounts.revoke_account_session(home, token) -> bool`, and `ingest_tokens.verify_token_record`.
- Produces: the `tmp_home` and `frozen_clock` fixtures every later task uses.

- [ ] **Step 1: Write the tests — and expect them to PASS**

These are characterisation tests. They assert current behaviour so a later task cannot break
it silently. This is the one place in the plan where a passing first run is correct.

```python
def test_a_session_expires_at_its_ttl_today(tmp_home, frozen_clock):
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW, ttl_hours=1)
    assert verify_token_record(tmp_home, token) is not None
    frozen_clock.advance(hours=1, seconds=1)
    assert verify_token_record(tmp_home, token) is None

def test_revocation_is_consulted_on_the_next_request_today(tmp_home):
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW)
    assert verify_token_record(tmp_home, token) is not None   # passes BEFORE
    assert revoke_account_session(tmp_home, token) is True
    assert verify_token_record(tmp_home, token) is None       # fails AFTER

def test_a_session_today_carries_every_known_scope(tmp_home):
    """Characterises the gap Task 2 closes. When Task 2 lands, this test is REPLACED by
       test_a_session_carries_only_its_roles_scopes -- not deleted silently."""
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW)
    record = verify_token_record(tmp_home, token)
    assert "memory:write" in record["scopes"] and len(record["scopes"]) > 2
```

- [ ] **Step 2: Run them and confirm they PASS**

Run: `uv run pytest tests/test_account_sessions.py -v`
Expected: PASS. A failure here means this plan's reading of `accounts.py` is wrong — stop
and re-read rather than editing the test to match.

- [ ] **Step 3: Prove each can fail** — this is what makes Step 2's pass meaningful. Remove
      the `expires_at` comparison from `ingest_tokens.py:147`; confirm only the expiry test
      goes red. Make `revoke_account_session` a no-op returning `True`; confirm only the
      revocation test goes red. Restore both.
- [ ] **Step 4: Commit**

### Task 2: A session carries only the scopes its role grants

The real gap. `accounts.py:252` computes `all_known_scopes` as every scope in
`ROLE_SCOPES.values()`, so a viewer-role account session holds `memory:write`.

**Files:**
- Modify: `src/xibalba_cortex/accounts.py`
- Modify: `tests/test_account_sessions.py`

**Interfaces:**
- Produces: no signature change. `issue_account_session` keeps its shape; only the stored
  `scopes_json` narrows.

- [ ] **Step 1: Write the failing test**

```python
def test_a_session_carries_only_its_roles_scopes(tmp_home):
    token, _ = issue_account_session(tmp_home, email=VIEWER_EMAIL, password=PW)
    record = verify_token_record(tmp_home, token)
    assert "memory:read" in record["scopes"]
    assert "memory:write" not in record["scopes"]
```

Replace `test_a_session_today_carries_every_known_scope` in the same commit, so the
characterisation test's removal is visible in the diff rather than silent.

- [ ] **Step 2: Run it and confirm it fails** — today the viewer session holds
      `memory:write`.
- [ ] **Step 3: Narrow the scopes to the account's own role.** `ROLE_SCOPES["admin"]`
      literally contains `"*"`; the existing comment at `accounts.py:249-251` explains that
      storing `"*"` verbatim would never match a concrete required scope. So expand `"*"` to
      the concrete set **for an admin only**, and give every other role exactly its own
      grants.
- [ ] **Step 4: Run it and confirm it passes**, and confirm Task 1's two characterisation
      tests are **still green** — nothing about expiry or revocation may change here.
- [ ] **Step 5: Prove it can fail** — restore `all_known_scopes`; confirm this test goes red
      and Task 1's stay green.
- [ ] **Step 6: Commit**

### Task 3: Shorten the lifetime, and add rotation so shortening it is survivable

A 24-hour session is not "short-lived". Shortening it alone would make users re-authenticate
constantly, so the two land together: rotation is what makes a short TTL usable.

**Files:**
- Modify: `src/xibalba_cortex/accounts.py`, `src/xibalba_cortex/managed/api.py`,
  `src/xibalba_cortex/local_api.py`
- Modify: `tests/test_account_sessions.py`

**Interfaces:**
- Produces: `rotate_account_session(home: str | Path, token: str) -> tuple[str, dict] | None`,
  and a shortened `ttl_hours` default.

- [ ] **Step 1: Write the failing tests**

```python
def test_rotation_replaces_the_credential_without_signing_the_holder_out(tmp_home):
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW)
    fresh, account = rotate_account_session(tmp_home, token)
    assert fresh != token
    assert verify_token_record(tmp_home, fresh) is not None
    assert verify_token_record(tmp_home, token) is None

def test_rotating_a_revoked_session_is_refused(tmp_home):
    token, _ = issue_account_session(tmp_home, email=EMAIL, password=PW)
    revoke_account_session(tmp_home, token)
    assert rotate_account_session(tmp_home, token) is None

def test_a_cookie_issued_before_the_change_still_authenticates(tmp_home):
    """Build this with the PRE-change issuer, not by hand -- a hand-built fixture proves only
       that the test author understood the old format."""
    token = legacy_issued_session(tmp_home)
    assert verify_token_record(tmp_home, token) is not None
```

- [ ] **Step 2: Run them and confirm they fail**
- [ ] **Step 3: Implement rotation and shorten the TTL.** ⚠️ **`local_api.py:453` carries a
      comment that the cookie `max_age` must track `issue_account_session`'s `ttl_hours`
      default**, and `managed/api.py:236` hardcodes `max_age=86400`. Change **all three**
      together or a cookie will outlive its server-side session, which presents to the user
      as a silent random logout.
- [ ] **Step 4: Run them and confirm they pass**, and confirm every earlier test is green.
- [ ] **Step 5: Prove each can fail** — have rotation return the same token; confirm only the
      rotation test goes red.
- [ ] **Step 6: Commit**

### Task 4: API-key revocation stops ingestion

`ingest_tokens.py:147` already consults `revoked_at`, so this is expected to need little or
no implementation. It is here because it is Review Focus item 1 at the layer a customer
actually touches, and because Phase 5 adds two new routes that must honour it.

**Files:**
- Create: `tests/test_managed_keys.py`
- Modify: `tests/conftest.py` (add `managed_app`, `api_key`)

- [ ] **Step 1: Write the test**

```python
def test_revoking_an_api_key_stops_ingestion_on_the_next_call(managed_app, api_key):
    assert managed_app.ingest(api_key).status_code == 200
    managed_app.revoke_key(api_key)
    assert managed_app.ingest(api_key).status_code == 401
```

The `ingest` call depends on Phase 5 Task 1. Mark it
`@pytest.mark.xfail(reason="ingestion route lands in Phase 5 Task 1", strict=True)` and
remove the marker in Phase 5 Task 1 Step 4. `strict=True` fails the suite if it starts
passing early, so the marker cannot be forgotten.

- [ ] **Step 2: Run it and confirm it xfails**
- [ ] **Step 3: No implementation expected.** If it fails for a reason other than the missing
      route, revocation is **not** consulted on that path — that is a real bug; fix it here.
- [ ] **Step 4: Commit**

### Task 5: One `SignIn`, one client contract

**Files:**
- Modify: `viewer/src/console/SignIn.tsx`, `viewer/src/hostedApi.ts`,
  `viewer/src/hostedApi.test.ts`
- Delete: managed's duplicated login / signup / forgot / reset / verify surface

**Interfaces:**
- Consumes: `supports(method, path, param?)` from `hostedApi.ts`.
- Produces: no second auth client.

- [ ] **Step 1: Write the failing test** — assert the hosted mapping issues
      `/api/managed/login` for a console `/api/auth/login` call, and that signup on the
      hosted edition makes **zero** `login` calls (verification precedes first sign-in).
- [ ] **Step 2: Run it and confirm it fails**
- [ ] **Step 3: Map the five auth paths and `keys` -> `auth/tokens`** in the existing hosted
      target table. Email verification is a policy flag read from the server declaration,
      not a second code path.
- [ ] **Step 4: Run it and confirm it passes**
- [ ] **Step 5: Prove it can fail** — drop the `login` mapping; confirm the request-path
      assertion goes red.
- [ ] **Step 6: Preserve the 401 reset.** The spec requires that managed's existing
      behaviour — a `401` resets to the sign-in surface — survives the consolidation. Write
      the test that a `401` from any mapped auth path returns the user to `SignIn` with no
      stale session state, run it, and prove it can fail by swallowing the `401`.
- [ ] **Step 7: Commit**

**Phase done when:** one auth implementation serves both editions; a session carries only
its role's scopes; the TTL is short and rotation makes that usable; cookie `max_age` and
server TTL agree in all three places; a pre-change cookie still authenticates; and
revocation is proved effective at both the session and API-key layers.

---

## Phase 2 — Agent registration

The spec's P2, unamended. Three proven paths plus a first-run gate, and one new mechanism.

### Task 1: Zero agents means "connect an agent" is the first screen

**Files:**
- Modify: `viewer/src/console/pages/AgentsPage.tsx`, `viewer/src/console/state.tsx`
- Test: `viewer/e2e/registration.spec.ts` (create)

**Interfaces:**
- Consumes: the agent listing each edition already returns — the console's agents endpoint,
  managed's `me`. Add an explicit count field **only** if that round trip proves too costly
  on first paint.
- Produces: nothing later tasks consume.

- [ ] **Step 1: Write the failing test** — a fresh signed-in account with zero agents lands
      on the connect-an-agent surface, not a workspace of memory boxes.
- [ ] **Step 2: Run it and confirm it fails** (today a fresh managed account lands on a
      workspace page with no agent and no prompt)
- [ ] **Step 3: Derive the count from the existing listing and gate the first screen on it**
- [ ] **Step 4: Run it and confirm it passes**
- [ ] **Step 5: Prove it can fail** — seed one agent; confirm the gate test goes red and the
      normal-landing test stays green.
- [ ] **Step 6: Commit**

### Task 2: The signed, single-use enrollment code

**Files:**
- Create: `src/xibalba_cortex/enrollment.py`
- Create: `tests/test_enrollment.py`
- Modify: `src/xibalba_cortex/local_api.py` (issue route), `src/xibalba_cortex/connect.py`
  (`--code` redemption)

**Interfaces:**
- Consumes: the existing operator/admin check `_assert_pair_manager` in `local_api.py`.
- Produces: `issue_code(workspace_id: str, *, ttl_seconds: int = 600) -> str`,
  `redeem_code(code: str, *, did: str, device_id: str, public_key: str, signature: str) -> dict`.

- [ ] **Step 1: Write the failing tests** — this is Review Focus item 5.

Cover: generation; TTL expiry; single use (second redemption refused); rate limit; signature
verification across valid, wrong-key, expired and replayed. Then the four refusals as
**distinct, non-enumerating** errors — expired, already-redeemed, wrong-workspace,
bad-signature — plus a viewer-role session refused with the existing operator/admin message.

```python
def test_a_binding_cannot_be_created_without_a_signature_from_the_agents_key(tmp_home):
    code = issue_code("ws-1")
    with pytest.raises(EnrollmentRefused):
        redeem_code(code, did="did:example:a", device_id="d1",
                    public_key=OTHER_PUBKEY, signature=sign(OTHER_PRIVKEY, code))
```

- [ ] **Step 2: Run them and confirm they fail**
- [ ] **Step 3: Implement issue and redeem.** Verify the signature **over the code** against
      the DID before binding DID -> workspace. Codes are bearer secrets: single use, short
      TTL, rate limited, and every issue and redeem audited.
- [ ] **Step 4: Run them and confirm they pass**
- [ ] **Step 5: Prove each can fail** — remove the signature verification and confirm only
      the signature tests go red; remove the single-use marking and confirm only that test
      goes red.
- [ ] **Step 6: Commit**

### Task 3: A successful bind selects the agent and opens the Graph lens

**Files:**
- Modify: `viewer/src/console/pages/AgentsPage.tsx`
- Modify: `viewer/e2e/registration.spec.ts`

**Interfaces:**
- Consumes: `workspace.choose(agentId, store_id)` then `go('graph')`, which `AgentsPage`
  already does.

- [ ] **Step 1: Write the failing e2e test** — signup, verify, zero-agent first run, code
      issued, redeemed via API, lands in Graph with that agent selected. Then: an agent with
      no memories yet shows an empty state carrying the `cortex connect` snippet, not an
      empty canvas.
- [ ] **Step 2: Run it and confirm it fails**
- [ ] **Step 3: Wire the bind result into the existing choose-then-go path**
- [ ] **Step 4: Run it and confirm it passes**
- [ ] **Step 5: Prove it can fail** — return a bind without an agent id; confirm the
      selection assertion goes red.
- [ ] **Step 6: Commit**

### Task 4: The DID-bound API key path keeps working

The spec's second registration path, and the one that already exists — managed's DID textarea
issuing a key bound to `agent_ids`. It has a test in `managed.spec.ts` today, and Phase 0
deletes the `ManagedApp` surface that test drives, so the path needs its assertion re-homed
onto the console's API-keys surface rather than quietly losing coverage.

**Files:**
- Modify: `viewer/e2e/registration.spec.ts`
- Modify: `viewer/src/console/pages/AgentsPage.tsx` if the re-homed surface needs it

- [ ] **Step 1: Write the failing test** — on the console's API-keys surface, "Create API
      key" stays disabled until the required Agent DIDs field has a value, and the issued key
      carries those `agent_ids`. (The disabled-until-filled rule is real and was the cause of
      a 90-second CI hang in PR #72; do not drop it.)
- [ ] **Step 2: Run it and confirm it fails**
- [ ] **Step 3: Make the console surface carry the DID binding**
- [ ] **Step 4: Run it and confirm it passes**
- [ ] **Step 5: Prove it can fail** — allow an empty DIDs field; confirm the disabled
      assertion goes red.
- [ ] **Step 6: Commit**

### Task 5: On-chain failures leave nothing half-registered

**Files:**
- Modify: `viewer/src/agent0_wallet.ts`
- Test: `viewer/src/agent0_wallet.test.ts` (create)

- [ ] **Step 1: Write the failing tests** — no injected provider, wrong chain, user
      rejection and a reverted transaction are four distinguished outcomes, and **none**
      leaves a half-registered agent in the workspace.
- [ ] **Step 2: Run them and confirm they fail**
- [ ] **Step 3: Distinguish the four and make the workspace write conditional on receipt
      success**
- [ ] **Step 4: Run them and confirm they pass**
- [ ] **Step 5: Prove they can fail** — write the agent before awaiting the receipt; confirm
      the revert test goes red.
- [ ] **Step 6: Commit**

**Phase done when:** a new account with no agents is shown how to connect one as its first
screen, and a binding cannot be created without a signature from the agent's key.

---

## Phase 3 — Stripe

The spec's P3, split as recorded. Build against a dummy key:
`ManagedConfig.billing_ready` already rejects any secret key containing `dummy`, `replace`
or `placeholder`, so the service stays healthy, `billing_configured` stays `false`,
`/readyz` keeps reporting `stripe_sandbox` **not ready**, and no customer can be charged
against a fake gateway.

### Task 1: Checkout and portal against a fake gateway

**Files:**
- Modify: `src/xibalba_cortex/managed/stripe_gateway.py`
- Create: `tests/test_stripe_gateway.py`

**Interfaces:**
- Produces: a `FakeGateway` test double satisfying the same protocol as the real gateway.

- [ ] **Step 1: Write the failing tests** — checkout returns a session for a known price id
      and refuses an unknown one; portal refuses an account with no customer record.
- [ ] **Step 2: Run them and confirm they fail**
- [ ] **Step 3: Introduce the gateway protocol and the fake**, leaving the real gateway's
      wire calls untouched.
- [ ] **Step 4: Run them and confirm they pass**
- [ ] **Step 5: Prove each can fail**
- [ ] **Step 6: Commit**

### Task 2: Webhook signature verification and replay idempotency

**Files:**
- Modify: `src/xibalba_cortex/managed/stripe_gateway.py`,
  `src/xibalba_cortex/managed/control.py`
- Modify: `tests/test_stripe_gateway.py`

- [ ] **Step 1: Write the failing tests** — this is Review Focus item 4.

```python
def test_an_unsigned_webhook_is_refused(managed_app):
    assert managed_app.post("/api/managed/stripe/webhook", json=EVENT).status_code == 400

def test_replaying_the_same_event_does_not_advance_entitlement_twice(managed_app):
    first = managed_app.post_signed_webhook(SUBSCRIPTION_ACTIVE)
    entitlement = managed_app.entitlement("acct-1")
    second = managed_app.post_signed_webhook(SUBSCRIPTION_ACTIVE)
    assert second.status_code == 200
    assert managed_app.entitlement("acct-1") == entitlement
```

- [ ] **Step 2: Run them and confirm they fail**
- [ ] **Step 3: Verify the signature, and key idempotency on the Stripe event id**
- [ ] **Step 4: Run them and confirm they pass**
- [ ] **Step 5: Prove each can fail** — drop the event-id check; confirm only the replay
      test goes red.
- [ ] **Step 6: Commit**

### Task 3: Plan limits are enforced, not decorative

**Files:**
- Modify: `src/xibalba_cortex/managed/plans.py`, `src/xibalba_cortex/managed/api.py`
- Create: `tests/test_plan_limits.py`

- [ ] **Step 1: Write the failing tests** — each of `max_memories`,
      `writes_per_month` and `retrievals_per_month` refuses at its boundary on the Free tier
      and allows the same call on Pro. Limits reset monthly in UTC.
- [ ] **Step 2: Run them and confirm they fail**
- [ ] **Step 3: Enforce each limit at its route**
- [ ] **Step 4: Run them and confirm they pass**
- [ ] **Step 5: Prove each can fail** — remove one check at a time and confirm **only** that
      limit's test goes red. Three separate reverts, not one.
- [ ] **Step 6: Commit**

### Task 4: Operator credential handover (blocked — not an implementation task)

Not startable by an implementer. The operator sets real `sk_test_`, `whsec_` and Pro/Team
`price_` IDs as Render environment variables. `/readyz` flipping `stripe_sandbox` to ready
is the evidence they took effect. **No key is committed, printed or retained.**

- [ ] Operator confirms the four values are set in Render
- [ ] `curl https://<pilot>/readyz` shows `stripe_sandbox` ready
- [ ] A paid-plan checkout completes in Stripe test mode

**Phase done when:** Tasks 1–3 pass and are proved able to fail, and `/readyz` still
reports `stripe_sandbox` unready — correctly — until Task 4 supplies real keys.

---

## Phase 5 — Managed ingestion, and the custom-architecture story

The spec's P5, added 2026-11-02. **The finding that motivates it:** `managed/api.py` serves
25 routes and no ingestion path. The managed Dockerfile runs
`python -m xibalba_cortex.managed.api` alone, so the MCP app is never mounted. The only
route a `managed-api:` token can write to is `POST /api/managed/memories`, which takes
content only and stores every memory `active` (`managed/api.py:376`).

**The shared handler already exists.** `GraphStore.ingest_agent_turn` (`store.py:4923`) is
the one-call primitive; the MCP tool `memory_ingest_agent_turn` (`server.py:865`) and
`provider_bridge.py:128` are both already thin wrappers over it. So "two transports over one
handler" is **a constraint to preserve, not a refactor to perform.** No task below may put
ingestion logic in a transport.

### File Structure

- `src/xibalba_cortex/managed/ingest.py` — **create.** Resolves a bearer token to a
  workspace and calls `GraphStore.ingest_agent_turn`. The only new logic in this phase.
- `src/xibalba_cortex/managed/api.py` — **modify.** Mounts the MCP app; adds one REST route.
  Both delegate.
- `src/xibalba_cortex/grok_adapter.py` — **create.** Identity and policy for the `grok`
  runtime. Calls the same handler; adds no third path.
- `tests/test_managed_ingest.py` — **create.**

### Task 1: REST ingestion, scoped to the caller's workspace

**Files:**
- Create: `src/xibalba_cortex/managed/ingest.py`, `tests/test_managed_ingest.py`
- Modify: `src/xibalba_cortex/managed/api.py`

**Interfaces:**
- Consumes: `GraphStore.ingest_agent_turn(external_session_id, *, runtime, prompt, response,
  tool_calls=(), agent_id=None, prompt_id=None, prompt_time=None, response_time=None,
  metadata=None, idempotency_key=None) -> dict`; `verify_token_record` from
  `ingest_tokens`; and the three managed primitives this route must reuse rather than
  reinvent — `service.write_guard(tenant)`, `service.store(tenant)` (per-tenant `GraphStore`
  with path-escape validation and `max_memories` quota) and
  `service.consume(tenant, "writes", request_key=..., fingerprint=...)`. Copy the shape of
  `api.py:368-370`.
- Produces: `ingest_turn(token: str, payload: dict) -> dict`, the route
  `POST /api/managed/ingest`, and the `managed_app` and `api_key` fixtures in
  `tests/conftest.py` (which does not exist yet — create it).

- [ ] **Step 1: Write the failing test**

```python
def test_a_full_turn_lands_with_its_tool_calls(managed_app, api_key):
    r = managed_app.post("/api/managed/ingest", headers=bearer(api_key), json={
        "external_session_id": "s-1", "runtime": "grok",
        "prompt": "hello", "response": "hi",
        "tool_calls": [{"name": "web_search"}],
    })
    assert r.status_code == 200
    stored = managed_app.store("acct-1").session_exchanges("s-1")
    assert stored[0]["tool_call_otel_event_ids"]       # tool calls are committed
    assert managed_app.store("acct-1").verify_chain()["valid"] is True
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/test_managed_ingest.py -v`
Expected: FAIL — 404; the route does not exist.

- [ ] **Step 3: Implement `ingest_turn` and the route.** Resolve the token to its
      `profile_id`, open that profile's store, and call `ingest_agent_turn` with the
      payload. Require the `memory:write` scope the managed key already carries. **Put no
      session, exchange or otel logic here** — the handler owns all of it.
- [ ] **Step 4: Run it and confirm it passes.** Then remove the
      `xfail` marker from Phase 1 Task 3's
      `test_revoking_an_api_key_stops_ingestion_on_the_next_call` and confirm it passes.
- [ ] **Step 5: Prove it can fail** — drop `tool_calls` from the handler call; confirm the
      committed-tool-calls assertion goes red.
- [ ] **Step 6: Meter this route like every other write.** A new route bypasses the limits
      by default, and ingestion is the highest-volume write path in the product — unmetered
      is the expensive failure, and it is reachable by anyone who signs up free. The
      mechanism already exists (see **Execution order**), so this is a call, not a build:
      wrap the write in `service.write_guard(tenant)` and call
      `service.consume(tenant, "writes", request_key=..., fingerprint=...)` exactly as
      `api.py:368-370` does. Write the test that a Free-tier ingest at the
      `writes_per_month` boundary is refused with `LimitExceeded` and the same call succeeds
      on Pro; prove it can fail by removing the `consume` call. Take `request_key` from an
      `Idempotency-Key` header so a retried ingest does not double-charge.
- [ ] **Step 7: Commit**

### Task 2: A token reaches its own workspace and no other

**Files:**
- Modify: `src/xibalba_cortex/managed/ingest.py`, `tests/test_managed_ingest.py`

- [ ] **Step 1: Write the failing test** — this is Review Focus item 2.

```python
def test_a_token_cannot_write_into_another_workspace(managed_app, api_key_a):
    r = managed_app.post("/api/managed/ingest", headers=bearer(api_key_a),
                         json={**TURN, "workspace_id": "ws-b"})
    assert r.status_code in (401, 403)
    assert managed_app.store("ws-b").session_exchanges("s-1") == []
```

The workspace must come from the **token**, never from the payload. The test passes a
payload workspace precisely to prove it is ignored.

- [ ] **Step 2: Run it and confirm it fails**
- [ ] **Step 3: Derive the workspace from the token record only**, ignoring any
      client-supplied workspace field.
- [ ] **Step 4: Run it and confirm it passes**
- [ ] **Step 5: Prove it can fail** — honour the payload's workspace; confirm this test goes
      red.
- [ ] **Step 6: Commit**

### Task 3: Extend `hosted_connector.py` with ingest and per-request profile resolution

**Decided 2026-11-03.** The operator chose: extend `hosted_connector.py`, exposing its
existing three tools plus `memory_ingest_agent_turn`, with the profile resolved per request.
The alternative — mounting `server.py`'s MCP app — is **rejected and must not be
reconsidered by an implementer**: `server.py:91` holds a process-global `_store`, so all ~89
tools would serve one workspace regardless of caller, and it would publish `memory_backup`,
`memory_vault_inspect`, `memory_forget` and the inference-task lifecycle to the internet.

**Files:**
- Modify: `src/xibalba_cortex/hosted_connector.py`
- Modify: `src/xibalba_cortex/managed/api.py` (mount the connector app)
- Modify: `tests/test_managed_ingest.py`

**Interfaces:**
- Consumes: `GraphStore.ingest_agent_turn` (same handler as Task 1 — **no second ingestion
  path**); `ingest_tokens.verify_token_record`; the connector's existing per-request
  subject-to-profile check at `hosted_connector.py:50` and `:58`.
- Produces: a fourth connector tool, `cortex_ingest_turn`, and a connector instance whose
  profile comes from the request's credential rather than from `self.profile`.

- [ ] **Step 0: Devil's Advocate review — BLOCKING.** This changes a security boundary
      (a previously single-profile component becomes multi-tenant, on a public host), so
      `SOUL.md` requires the review **before** implementation, not after. Record the outcome
      in the task. ⚠️ The Devil's Advocate MCP connector is **not authenticated** in this
      environment — it appears only as `authenticate` / `complete_authentication`. Either
      authenticate it or run the review another way, but do not skip it and do not mark this
      step done without a recorded outcome.

- [ ] **Step 1: Write the failing tests**

The isolation test is the point of the task, so it is written first and written to fail for
the right reason.

```python
def test_each_credential_reaches_only_its_own_profile(connector_app, key_a, key_b):
    connector_app.ingest(key_a, {**TURN, "external_session_id": "s-a"})
    assert connector_app.store("profile-a").session_exchanges("s-a") != []
    assert connector_app.store("profile-b").session_exchanges("s-a") == []

def test_a_revoked_credential_is_refused_on_the_next_call(connector_app, key_a):
    assert connector_app.ingest(key_a, TURN).ok
    connector_app.revoke(key_a)
    assert not connector_app.ingest(key_a, TURN).ok

def test_the_connector_exposes_exactly_four_tools(connector_app):
    """The surface IS the security decision, so it is asserted, not assumed. A fifth tool
       appearing without this test changing is the failure this catches."""
    assert sorted(connector_app.tool_names()) == [
        "cortex_connection_status", "cortex_ingest_turn", "cortex_recall", "cortex_remember",
    ]
```

- [ ] **Step 2: Run them and confirm they fail**
- [ ] **Step 3: Resolve the profile per request.** Replace the instance-level `self.profile`
      comparison with the profile carried by the verified credential, keeping the existing
      shape of the check at `:50` and `:58`. Add `cortex_ingest_turn` as a thin call into
      `GraphStore.ingest_agent_turn` for the resolved profile — **no ingestion logic in the
      tool.**
- [ ] **Step 4: Run them and confirm they pass**
- [ ] **Step 5: Prove each can fail** — restore the instance-level profile so a credential
      reaches a fixed profile; confirm **only** the isolation test goes red. Add a fifth
      tool; confirm only the surface test goes red. Restore both.
- [ ] **Step 6: Enforce the plan limits here too**, by calling the same enforcement Phase 3
      Task 3 built — the same reasoning as Task 1 Step 6. A Free-tier ingest at the
      `writes_per_month` boundary is refused over MCP exactly as over REST.
- [ ] **Step 7: Document the TLS boundary.** `server.py`'s startup warning records why: the
      MCP transport has no TLS of its own and bearer tokens travel in plaintext without a
      TLS-terminating proxy. Render terminates TLS; a self-hosted operator must be told it
      is required.
- [ ] **Step 8: Commit**

### Task 4: The two transports cannot drift

Unblocked 2026-11-03 with Task 3. REST (Task 1) and the connector's `cortex_ingest_turn`
(Task 3) are now two transports over `GraphStore.ingest_agent_turn`, so this is the test
that stops them diverging — the hard requirement the spec records for having taken both.

**Files:**
- Modify: `tests/test_managed_ingest.py`

- [ ] **Step 1: Write the failing test** — this is Review Focus item 3, and the structural
      mitigation the spec requires for having taken both transports.

```python
def test_the_same_turn_over_mcp_and_rest_produces_identical_records(managed_app, api_key):
    via_rest = managed_app.ingest_rest(api_key, TURN, external_session_id="s-rest")
    via_mcp  = managed_app.ingest_mcp(api_key, TURN, external_session_id="s-mcp")
    assert normalise(via_rest) == normalise(via_mcp)
```

`normalise` strips only the fields that must differ — ids, timestamps, the session id — and
nothing else. Everything it strips is a field this test is choosing not to check, so keep
the list short and justify each entry in a comment.

- [ ] **Step 2: Run it and confirm it fails** if the transports differ today; if it passes on
      the first run it has measured nothing, so go to Step 3 regardless.
- [ ] **Step 3: Prove it can fail by changing one transport alone** — have the REST route
      default `runtime` to `"rest"`; confirm this test goes red while every other ingestion
      test stays green. Restore.
- [ ] **Step 4: Commit**

### Task 5: The Grok adapter

**Files:**
- Create: `src/xibalba_cortex/grok_adapter.py`, `tests/test_grok_adapter.py`

**Interfaces:**
- Consumes: the same `GraphStore.ingest_agent_turn`; the conventions of the existing
  `claude_adapter.py` / `cursor_adapter.py` / `gemini_adapter.py` /
  `openai_compatible_adapter.py` family.
- Produces: a `grok` runtime adapter. **No new ingestion path.**

Grok needs no adapter to *connect* — Grok 4.3 supports remote MCP tools natively through the
xAI SDK, the OpenAI-compatible Responses API and the Voice Agent API, and Grok Build supports
bring-your-own MCP. This task exists only to make `grok` an adapted runtime with identity and
policy handling rather than a free-string one.

- [ ] **Step 1: Write the failing test** — a Grok turn is recorded with
      `runtime == "grok"`, its tool calls committed, and its identity resolved the way the
      existing adapters resolve theirs.
- [ ] **Step 2: Run it and confirm it fails**
- [ ] **Step 3: Implement the adapter** following the existing family's structure. Read xAI
      request/response shapes from the live SDK contract at implementation time rather than
      from this plan — the research behind this task is dated 2026-11-02 and several sources
      were secondary blogs.
- [ ] **Step 4: Run it and confirm it passes**
- [ ] **Step 5: Prove it can fail**
- [ ] **Step 6: Commit**

### Task 6: README rewrite

**Files:**
- Modify: `README.md`
- Modify: `docs/operations/cortex-plugin-distribution.md` (cross-reference only)

**Decisions taken with the operator 2026-11-02:** write the **target managed-service
narrative** with **per-surface status markers** (Shipped / Pilot / Planned), and a lede that
leads with the builder hook **then** the evidence claim, in that order.

Why this task sits last in the phase: the README's claims become true as Tasks 1–5 land, so
writing it earlier would publish a roadmap as a capability. **It is also the task most
likely to introduce an unsupported claim**, so every row of its matrix must cite a file.

- [x] **Step 1: Resolve the tool count — DONE by the controller 2026-11-03.** The
      authoritative number is **89**.
      `tests/test_server.py::test_all_tools_are_advertised` asserts an exact set of **89
      unique** tool names (no duplicates), it matches the 89 `@server.tool` decorators in
      `server.py`, and it **passes** today. So `README.md:164` and `README.md:336` are both
      wrong by nine — correct them to 89, and keep the existing claim that a test enforces
      the inventory, because it genuinely does. Cite the test by name,
      `test_all_tools_are_advertised`, rather than "the exact inventory assertion".
- [ ] **Step 2: Write the capability matrix first, before any prose.** One row per surface —
      local stdio MCP, hooks via `bridge.py`, Claude Code, Codex, Gemini CLI, Cindy, Grok,
      Perplexity, Spark, openclaw, generic `memory_ingest_agent_turn`, managed REST ingest,
      managed MCP. Each row carries a status and **the file or repo that backs it**. These
      facts were verified on 2026-11-02 and must be re-verified, not copied:
      - hooks via `bridge.py` are configured by `XIBALBA_CORTEX_HOME` and
        `XIBALBA_CORTEX_CAPTURE_MODE` and have **no remote-endpoint support** — local only;
      - `plugins/cortex-claude/.mcp.json` runs `xibalba-cortex` as a **local stdio** command;
      - the hosted memory connector exposes **three** tools (`cortex_remember`,
        `cortex_recall`, `cortex_connection_status`) over OAuth and its own doc states it is
        "not a complete managed hosting product" with "arbitrary runtime-ingestion tools
        absent";
      - Cindy ships as `cortex-cindy` 0.3.2, an importable `.cindy` package.
- [ ] **Step 3: Write the lede and the three ways in** — drop-in adapters, MCP for anything
      that speaks it, hooks plus `memory_ingest_agent_turn` for fully custom builds. Builder
      hook first, evidence claim immediately after. The current `uv sync` opening becomes the
      self-hosted path, not the headline. Keep the provenance, hybrid-retrieval and
      reviewable-extraction depth; move it below the fold.
- [ ] **Step 4: Verify every claim.** For each capability sentence, name the file, route or
      test that backs it. Delete any sentence that cannot be backed. A README is a capability
      claim and needs payload evidence like any other.
- [ ] **Step 5: Check the links** — every relative path resolves and every external URL is
      reachable.
- [ ] **Step 6: Commit**

**Phase done when:** a Grok bot, a Cindy desktop and a `curl` all record a full turn into a
hosted workspace — over MCP or REST — with tool calls present and the chain verifying; the
identical-records test passes and is proved able to fail; a cross-workspace write is refused
and each credential reaches only its own profile; the connector exposes exactly four tools;
a Free-tier ingest is refused at its `writes_per_month` boundary on **both** transports; and
no README sentence lacks a backing file.

Task 3 Step 0 (Devil's Advocate) gates the MCP half. Tasks 1, 2, 5 and 6 do not depend on
it, so REST ingestion ships even if that review sends Task 3 back.

---

## Phase 4 — Deferred production hardening

Out of scope for the pilot by decision, recorded so the gap is visible rather than implied.
Federated identity (OIDC/SSO), audited issuance, and tenant-bound membership — which belongs
here because it means nothing until an identity provider supplies the tenant.

Not planned. When it is taken up it gets its own spec and plan, and because it changes an
identity boundary it gets the Devil's Advocate review first.

---

## Merge and deploy gate

Not a task. The operator's call, every time.

1. Rebase onto `origin/main` and re-measure the gap.
2. Close both local-vs-CI divergences: the integrity-core pin, and every Playwright project.
3. Run CI's exact command set and get it green.
4. **Ask the operator before merging.** `main` auto-deploys `cortex-managed-pilot`.
5. Merge with `gh pr merge --match-head-commit <sha-CI-ran-on>`.
6. Confirm the deployed commit equals the merge commit in Render's deploy list.
7. Check `/healthz`, `/readyz`, `/managed`, and walk the new flow authenticated.
