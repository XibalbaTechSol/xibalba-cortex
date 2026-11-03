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

## Phase 1 — One auth contract, with bounded sessions and real revocation

The spec's P1, amended 2026-11-02: short-lived scoped sessions and working
revocation/rotation move **in**; federated identity, audited issuance and tenant-bound
membership stay in Phase 4.

### File Structure

- `src/xibalba_cortex/managed/auth.py` — **create.** The managed edition's implementation of
  the one auth contract: issue, validate, expire, revoke, rotate. Managed's login/signup/me/
  logout/recovery handlers become thin callers.
- `src/xibalba_cortex/managed/api.py` — **modify.** Route handlers delegate to `auth.py`;
  they hold no session logic.
- `viewer/src/console/SignIn.tsx` — **modify.** One component for both editions.
- `viewer/src/hostedApi.ts` — **modify.** Map `login`, `signup`, `me`, `logout`,
  `recovery/{action}` onto the single `/api/auth/*` contract and `keys` onto `auth/tokens`.
- `tests/test_managed_auth.py` — **create.**

### Task 1: Sessions carry a bounded lifetime and an enforced scope

**Files:**
- Create: `src/xibalba_cortex/managed/auth.py`
- Create: `tests/test_managed_auth.py`
- Modify: `src/xibalba_cortex/managed/api.py`

**Interfaces:**
- Consumes: the `accounts` and `tenants` tables `api.py` already reads; `profile_id` as the
  workspace key.
- Produces: `issue_session(account_id: str, *, scopes: tuple[str, ...], ttl_seconds: int) -> str`,
  `validate_session(token: str, *, required_scope: str | None = None) -> dict | None`
  returning the principal or `None`, and `SESSION_TTL_SECONDS: int`.

- [ ] **Step 1: Write the failing tests**

```python
def test_session_expires_after_its_ttl(tmp_home, frozen_clock):
    token = issue_session("acct-1", scopes=("memory:read",), ttl_seconds=60)
    assert validate_session(token) is not None
    frozen_clock.advance(61)
    assert validate_session(token) is None

def test_session_scope_is_enforced_not_advisory(tmp_home):
    token = issue_session("acct-1", scopes=("memory:read",), ttl_seconds=60)
    assert validate_session(token, required_scope="memory:read") is not None
    assert validate_session(token, required_scope="memory:write") is None
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/test_managed_auth.py -v`
Expected: FAIL — `managed.auth` does not exist.

- [ ] **Step 3: Implement `auth.py`**

Store expiry as an absolute UTC ISO timestamp, not a duration, so a restart cannot extend a
session. Compare against `datetime.now(timezone.utc)`. Scope check is exact membership, not
a prefix match.

- [ ] **Step 4: Run them and confirm they pass**

- [ ] **Step 5: Prove each check can fail**

Remove the expiry comparison; confirm only `test_session_expires_after_its_ttl` goes red.
Replace the scope membership test with `True`; confirm only
`test_session_scope_is_enforced_not_advisory` goes red. Restore both.

- [ ] **Step 6: Commit**

### Task 2: Existing managed cookies keep working

**Files:**
- Modify: `src/xibalba_cortex/managed/auth.py`
- Modify: `tests/test_managed_auth.py`

**Interfaces:**
- Produces: nothing new; `validate_session` gains a legacy path.

- [ ] **Step 1: Write the failing test**

```python
def test_a_cookie_issued_before_the_migration_still_authenticates(tmp_home, legacy_cookie):
    assert validate_session(legacy_cookie) is not None
```

Build `legacy_cookie` with the pre-migration writer, not by hand — a hand-built fixture
proves only that the test author understood the old format.

- [ ] **Step 2: Run it and confirm it fails**
- [ ] **Step 3: Accept the legacy shape in `validate_session`**, treating a legacy cookie as
      carrying the full scope set and the default TTL from its issue time.
- [ ] **Step 4: Run it and confirm it passes**
- [ ] **Step 5: Prove it can fail** — reject unknown shapes unconditionally; confirm this
      test alone goes red.
- [ ] **Step 6: Commit**

### Task 3: Revocation takes effect on the next request, and rotation does not sign anyone out

**Files:**
- Modify: `src/xibalba_cortex/managed/auth.py`
- Modify: `tests/test_managed_auth.py`

**Interfaces:**
- Produces: `revoke_session(token: str) -> bool`,
  `rotate_session(token: str) -> str | None`.

- [ ] **Step 1: Write the failing tests** — this is Review Focus item 1.

```python
def test_revocation_is_consulted_on_the_next_request(tmp_home):
    token = issue_session("acct-1", scopes=("memory:read",), ttl_seconds=600)
    assert validate_session(token) is not None      # passes BEFORE
    assert revoke_session(token) is True
    assert validate_session(token) is None          # fails AFTER

def test_rotation_replaces_the_credential_without_signing_the_holder_out(tmp_home):
    token = issue_session("acct-1", scopes=("memory:read",), ttl_seconds=600)
    fresh = rotate_session(token)
    assert fresh is not None and fresh != token
    assert validate_session(fresh) is not None
    assert validate_session(token) is None

def test_revoking_an_api_key_stops_ingestion_on_the_next_call(tmp_home, managed_client):
    key = managed_client.create_key(agent_dids=["did:example:a"])
    assert managed_client.ingest(key).status_code == 200
    managed_client.revoke_key(key)
    assert managed_client.ingest(key).status_code == 401
```

The third test's `ingest` call depends on Phase 5 Task 1. Write it now, mark it
`@pytest.mark.xfail(reason="ingestion route lands in Phase 5 Task 1", strict=True)`, and
remove the marker in Phase 5 Task 1 Step 4. `strict=True` means it fails the suite if it
starts passing early, so the marker cannot be forgotten.

- [ ] **Step 2: Run them and confirm they fail**
- [ ] **Step 3: Implement revoke and rotate**, consulting the revocation state inside
      `validate_session` so no caller can skip it.
- [ ] **Step 4: Run them and confirm they pass** (the third still `xfail`)
- [ ] **Step 5: Prove each can fail** — make `revoke_session` a no-op returning `True`;
      confirm the revocation test goes red while rotation stays green.
- [ ] **Step 6: Commit**

### Task 4: One `SignIn`, one client contract

**Files:**
- Modify: `viewer/src/console/SignIn.tsx`, `viewer/src/hostedApi.ts`
- Modify: `viewer/src/hostedApi.test.ts`
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
      not a code path.
- [ ] **Step 4: Run it and confirm it passes**
- [ ] **Step 5: Prove it can fail** — drop the `login` mapping; confirm the request-path
      assertion goes red.
- [ ] **Step 6: Preserve the 401 reset.** The spec requires that managed's existing
      behaviour — a `401` resets to the sign-in surface — survives the consolidation. Write
      the test that a `401` from any mapped auth path returns the user to `SignIn` with no
      stale session state, run it, and prove it can fail by swallowing the `401`.
- [ ] **Step 7: Commit**

**Phase done when:** a single auth client serves both editions; sessions expire and are
scope-checked; revocation is effective on the next request and rotation preserves the
holder; a pre-migration cookie still authenticates.

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
  `ingest_tokens`; `account["profile_id"]` as the workspace key.
- Produces: `ingest_turn(token: str, payload: dict) -> dict` and the route
  `POST /api/managed/ingest`.

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
- [ ] **Step 6: Commit**

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

### Task 3: Mount the MCP app on the managed service

**Files:**
- Modify: `src/xibalba_cortex/managed/api.py`, `deploy/managed/Dockerfile`
- Modify: `tests/test_managed_ingest.py`

**Interfaces:**
- Consumes: `server.streamable_http_app(streamable_http_path=..., host=...)` and
  `BearerTokenAuth(app, *, home, profile_id=None, required_scopes=(), rate_limit_per_minute=None)`
  from `auth_middleware`, both as `server.py`'s `main()` already uses them.

- [ ] **Step 1: Write the failing test** — an MCP `initialize` against `/mcp` with a valid
      `managed-api:` bearer token succeeds; the same request with no token, and with a
      revoked token, is refused.
- [ ] **Step 2: Run it and confirm it fails**
- [ ] **Step 3: Mount the MCP app behind `BearerTokenAuth`** with
      `required_scopes=("memory:read",)` and a `rate_limit_per_minute`. Resolve `profile_id`
      per request from the token, not from process configuration — the managed service is
      multi-tenant where `server.py`'s `main()` is single-profile.
- [ ] **Step 4: Run it and confirm it passes**
- [ ] **Step 5: Prove it can fail** — mount without the auth wrapper; confirm the
      no-token and revoked-token assertions go red.
- [ ] **Step 6: Document the TLS boundary.** `server.py`'s startup warning records why:
      the MCP server has no TLS of its own and bearer tokens travel in plaintext without a
      TLS-terminating proxy. Render terminates TLS; a self-hosted operator must be told it
      is required.
- [ ] **Step 7: Commit**

### Task 4: The two transports cannot drift

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

- [ ] **Step 1: Resolve the tool count.** Read `tests/test_server.py`'s inventory assertion
      and establish the real number. `README.md:164` and `README.md:336` both claim 80;
      `server.py` has 89 `@server.tool` decorators. **Both current numbers are unsupported.**
      Put no count in the README until the test settles it, then make the README quote the
      test's number and say the test enforces it.
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

**Phase done when:** a Grok bot and a `curl` both record a full turn into a hosted workspace
with tool calls present and the chain verifying; the identical-records test passes and is
proved able to fail; a cross-workspace write is refused; and no README sentence lacks a
backing file.

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
