# Cortex accounts and agent registration — design

**Date:** 2026-10-26
**Status:** design approved in conversation; decisions recorded below; not yet planned
or implemented. Scope was widened on 2026-10-26 from "the registration flow" to
"production readiness", so the work is decomposed into sequenced sub-projects.
**Branch:** `docs/account-registration-design`, cut from `origin/local`

## Intended outcome

A user arriving at Cortex can create an account, sign in, register an agent — by CLI,
by claiming a DID, or on-chain — and land in the knowledge-graph / timeline view with
that agent selected. One flow, one account system, in both the self-hosted and managed
editions.

**Success criteria**

1. A new managed account reaches a populated Graph lens without reading documentation.
2. A fresh account with no agents is shown how to connect one as its *first* screen.
3. An agent/device binding is proved by the device, not asserted by an operator.
4. The self-hosted console flow does not regress.
5. `viewer` CI is green, and the deployed Render commit equals the merged commit.

## What already exists (verified, not assumed)

Checked against `origin/main` and `origin/local`.

| Capability | Console (self-hosted) | Managed |
|---|---|---|
| Create account | yes — `SignIn` signup | yes — separate, plus email verification |
| Log in | yes — HttpOnly cookie | yes — separate cookie + CSRF |
| Password reset | yes — `passwordReset.ts` | yes — separate `recovery/{action}` |
| Register agent, CLI | yes — `cortex connect` (`src/xibalba_cortex/connect.py`) | same CLI, not surfaced in UI |
| Register agent, DID -> API key | no | yes — DID textarea -> `agent_ids` |
| Register agent, on-chain ERC-8004 | yes on `origin/local`, unmerged | yes on `origin/local`, unmerged |
| Device pairing | operator-typed `deviceId` | no |
| Graph + Timeline main view | yes — `GraphLens` / `TimelineLens` | yes — `ManagedLenses` + Graph/Timeline nav |

**Therefore this is a consolidation, not a greenfield build.** Nearly every capability
exists; it exists *twice*, divergently, and the unification work (PR #73, commit
`9f43f50` "Unify Agent0 flows across local and managed Cortex") is blocked behind a red
`viewer` CI job.

Two earlier readings of mine were wrong and are corrected here, because the design was
briefly argued from them:

- Managed **does** reach the graph and timeline. `ManagedApp.tsx` imports
  `ManagedGraphLens` / `ManagedTimelineLens`, holds
  `lens: 'workspace' | 'graph' | 'timeline'`, and renders a Graph/Timeline nav.
- The in-flight on-chain path does **not** generate key material in the page.
  `viewer/src/agent0_wallet.ts` uses viem over an **EIP-1193 injected provider**
  (`window.ethereum`) to call `register(...)` on the ERC-8004 identity registry
  `0x8004A818BFB912233c491871b3d84c89A494BD9e` on Base Sepolia (84532). It greps clean
  for `privateKey`, `mnemonic` and `randomBytes`; signing happens in the wallet extension.

## Architecture

### One auth contract

The console's cookie session is the model. Managed keeps what is genuinely its own —
tenant records, email verification, Stripe entitlement — and **stops owning
authentication**: it issues the same session the console does. One `SignIn` component,
one `/api/auth/*` contract, an edition adapter behind it. The duplicated
login / signup / forgot / reset / verify surface is deleted rather than maintained twice.

Session shape (already true of both editions; the design stops duplicating it): HttpOnly
cookie, `SameSite=Lax`, `Secure` when the public origin is HTTPS, CSRF token required on
mutations.

### One app. The console is the app.

**Decision: there is one application, and it is the console.** The managed edition is that
same application configured for hosting — not a sibling, not a variant shell.

Deleted outright:

- `viewer/src/console/ManagedApp.tsx`
- `viewer/src/console/ManagedLenses.tsx`
- `viewer/src/console/managed.css`
- the `main.tsx` branch that chooses between two roots

`main.tsx` boots `ConsoleApp` unconditionally. Every user, hosted or self-hosted, gets the
console: the same `Shell` (`TopBar`, `Rail`, `WorkspaceHeader`, `FacetRail`, `ChainRail`,
`Inspector`, `StatusBar`), the same `SignIn`, the same `GraphLens` / `TimelineLens`, the
same Industry grammar.

Managed then contributes exactly three things, none of them layout:

1. a **plans/billing panel**, mounted as a destination like any other;
2. **email verification before first sign-in**, as a policy flag;
3. a **server-declared capability set**, below.

### Capabilities, not a second UI

The two editions' APIs are not the same size. Managed serves 20 routes under
`/api/managed/*` (auth, memories, graph, timeline, keys, plans, billing, export/import);
the console's client calls roughly 27 distinct `/api/*` paths, including `agent-devices`,
`auth/tokens`, `backup`, `connectors`, `context/assemble`, `operations`,
`retrieval/hybrid`, `settings/inference`, `stats`, `status` and `workers`. Most do not
overlap.

So "one app, like the console" cannot mean the hosted edition pretends to have a worker
pool. It means the **same app, same shell, same grammar, with the navigation narrowed to
what the server declares it can serve.**

The seam for this already exists and must be reused rather than reinvented. `nav.ts`
already resolves destinations through a built-set filter:

    export const DESTINATIONS = ALL_DESTINATIONS.filter((d) => BUILT.has(d.id))

The change is to source that set from the server for the current edition instead of a
compile-time constant. `nav.ts`'s own comment states the property that makes this safe —
a destination is declared in one place, appears in all three (nav, routes, surfaces) and
"cannot drift between them".

Consequence to accept deliberately: a hosted workspace initially lists fewer destinations
than a self-hosted one. That is an honest statement about which endpoints exist, and each
one closes by implementing the endpoint, not by changing the UI. The alternative —
shrinking the console to managed's surface — was rejected: it would degrade the
self-hosted product to match the hosted one.

### API path shape

The console client's base path becomes edition-aware so one data layer serves both. The
hosted edition's `/api/managed/*` prefix is a deployment detail, not a second client:
`login`, `signup`, `me`, `logout`, `recovery/{action}` map onto the single `/api/auth/*`
contract, and `keys` onto `auth/tokens`. Where a managed route has no console equivalent
(`plans`, `checkout`, `portal`), it is reached by the billing panel alone.

### Why the two editions diverged, and what stops it recurring

They are two applications, not two skins. `main.tsx` selects `ManagedApp` or `ConsoleApp`
and they share no layout: `ConsoleApp` composes `TopBar`, `Rail`, `WorkspaceHeader`,
`FacetRail`, `ChainRail`, `Inspector` and `StatusBar`, and a grep of `ManagedApp` for any
of those returns **0**. `ManagedApp` instead defines ~20 classes of its own
(`xc-managed`, `xc-managed-inner`, `xc-managed-head`, `xc-managed-panel`, ...) while
borrowing the Industry primitives (`xc-win`, `xc-btn`, `xc-field`, `xc-input`), which is
why it reads as related rather than foreign. It arrived this way in one commit: PR #64 added
`ManagedApp.tsx` (+204), `managed.css` (+31) and the `main.tsx` branch (+11) together.

**The divergence was never caught because nothing tests it.** The Industry grammar sweep
runs over console hash routes only —

    const ROUTES = ['', 'timeline', 'memories', 'entities', 'sessions', 'operations', 'agents', 'settings']

— and across the whole e2e suite `grammarSweep` appears 5 times while `/managed` appears 0
times. Managed can drift arbitrarily far without a single red test.

**Requirement:** `/managed` joins the swept destinations, so that after the consolidation
the two editions are held identical by a test rather than by intent. This must be proved
able to fail: add the route, confirm the sweep goes red against today's managed UI, and only
then let the consolidation turn it green. A sweep that passes on first run has measured
nothing.

### Registration: one surface, three proven paths

| Path | Where the key lives | Status |
|---|---|---|
| CLI `cortex connect` | in the harness | exists (`connect.py`) |
| Claim a DID -> DID-bound API key | in the harness | exists (managed DID textarea) |
| On-chain ERC-8004 via injected wallet | in the wallet extension | exists on `origin/local` |

**In-page key generation is explicitly rejected.** It was one of four options originally
selected, but `agent0_wallet.ts` already delivers browser-based registration with the key
held by the wallet extension. Generating agent key material in the page would add real
custody risk for no capability that is not already available.

### The enrollment code (the only genuinely new mechanism)

Pairing today is operator-asserted: choose an agent from a dropdown, type any `deviceId`,
POST. Nothing proves the device controls that agent's DID.

Replace it with a proof:

1. `POST /api/agents/enrollment` — issues a short, single-use code, TTL ~10 minutes,
   scoped to the session's workspace, gated by the existing operator/admin check
   (`_assert_pair_manager` in `local_api.py`).
2. `cortex connect --code <code>` — redeems with the agent's DID, device id, public key,
   **and a signature over the code**.
3. The server verifies that signature against the DID before binding DID -> workspace.

The binding is then proved by the device holding the key, not asserted by whoever is
typing. Codes are bearer secrets: single use, short TTL, rate limited, and every issue
and redeem is audited.

## End-to-end flow

1. Landing offers *Start free* / *Sign in*.
2. Signup takes name, email, password.
3. **Email verification is an edition policy flag, not two code paths.** Managed requires
   verification before first sign-in (its signup returns "Check your email…" and asserts
   zero `login` calls); a self-hosted single-operator install signs in directly.
4. Session cookie is set as above.
5. **First-run gate.** Zero agents means "Connect an agent" *is* the first screen. The
   count is derived from the agent listing each edition already returns (the console's
   agents endpoint; managed's `me`) rather than a new endpoint — add an explicit count
   field only if that round trip proves too costly on first paint. This is the change that makes
   the stated flow work: today a fresh managed account lands on a workspace page of
   memory boxes with no agent and no prompt.
6. The user takes any one of the three registration paths.
7. On a successful bind, that agent is selected and the Graph lens opens, Timeline one
   toggle away — reusing what `AgentsPage` already does
   (`workspace.choose(agentId, store_id)` then `go('graph')`).
8. An agent with no memories yet gets an empty state carrying the `cortex connect`
   snippet, not an empty canvas.

## Error handling

- Enrollment: expired, already-redeemed, wrong-workspace and bad-signature redemptions
  each return a distinct, non-enumerating error; the UI offers a fresh code.
- Insufficient role: refused with the existing operator/admin message.
- On-chain: no injected provider, wrong chain, user rejection and a reverted transaction
  are distinguished, and none of them leave a half-registered agent in the workspace.
- Managed API `401` already resets to the sign-in surface; that behaviour is preserved.

## Testing

Every check must be proved able to fail — a conformance pass that cannot fail measured
nothing.

- **Unit:** code generation, TTL expiry, single use, rate limit; signature verification
  across valid, wrong-key, expired and replayed.
- **Integration:** redeem binds DID -> workspace; a viewer-role session is refused; a code
  issued for another workspace is refused.
- **E2E** (the `viewer` suite): signup -> verify -> zero-agent first run -> code issued ->
  redeemed via API -> lands in Graph with the agent selected. Plus the existing
  DID-bound API key test in `managed.spec.ts`.
- **Mutation pass:** revert each new check and confirm the specific test goes red — the
  discipline PR #72 used for its sweep exemptions and CSS fixes.

## Identity-boundary risks

- **Cortex must not become an identity authority.** The in-flight code states the rule:
  "Agent0 remains external chain evidence, not workspace authorization." On-chain
  registration alone grants no workspace access; authorization stays the session plus the
  enrollment proof. Inverting this would quietly make Cortex the identity provider and
  contradict the Shield/Cortex split.
- **Enrollment codes are bearer secrets** — see mitigations above.
- **Unifying auth touches live sessions.** Existing managed cookies must keep working
  across the change, or every pilot user is silently signed out.
- **Base Sepolia credentials** were previously found exposed in local env files. The
  on-chain path reads RPC configuration from the environment (Alchemy preferred,
  `https://sepolia.base.org` as the approved read-only fallback) and ships no key.

## Deploy and validation gate

Render service `cortex-managed-pilot` (`srv-dbfavo67bikc73crb8u0`) auto-deploys every
commit to `main`, so:

1. Merge only on green CI, with `gh pr merge --match-head-commit <sha-CI-ran-on>`.
2. Confirm the deployed commit equals the merge commit (Render deploy list).
3. Check `/healthz`, `/readyz`, `/managed`.
4. Walk the new flow authenticated.

Live state as validated 2026-10-26T07:16Z: `/healthz` 200 in 0.22s; `/` 307 -> `/managed`;
`signup_enabled: true`; `billing_configured: false`; `/readyz` `ready: false` with only
`stripe_sandbox` unready. **Free-tier signup is validatable end to end; paid plans are not
until Stripe test keys and Pro/Team price IDs are configured.**

## Production scope and sequencing

Scope widened to production readiness: Stripe, auth, account creation, the agent
registration workflow, and the console UI. That is five workstreams, so they are
sequenced rather than attempted at once. Each has its own definition of done and its own
implementation plan.

### P0 — One app, and it is the console

Delete `ManagedApp.tsx`, `ManagedLenses.tsx`, `managed.css` and the `main.tsx` fork.
`main.tsx` boots `ConsoleApp` unconditionally. Destinations come from a server-declared
set through the filter `nav.ts` already has. `/managed` joins the swept destinations, and
the route is proved able to fail first.

The managed **backend** is untouched and stays: `/api/managed/*`, tenants, entitlement,
the Render pilot. Only the second UI goes.

*Done when:* one app root; the hosted edition renders the console `Shell` and lenses; the
grammar sweep covers `/managed` and is green; no `xc-managed-*` layout class survives
except the billing panel's.

*Interaction with PR #73:* that PR edits `ManagedApp.tsx` (+49), a file P0 deletes, so
that half is discarded as the duplicate it is. Its console-side work is what we keep:
`agent0_wallet.ts`, `agent0_integration.py` and the `AgentsPage` ERC-8004 directory. They
are currently the **only** copies — they exist on `origin/local` and not on `main` — so
P0 must not begin until they are merged or explicitly carried onto its branch.

### P1 — One auth contract

Managed stops owning authentication and issues the same session the console does. One
`SignIn`, one `/api/auth/*` contract, an edition adapter behind it; `login`, `signup`,
`me`, `logout`, `recovery/{action}` map onto it, and `keys` onto `auth/tokens`. Email
verification before first sign-in becomes a policy flag, not a second code path.

*Decision (2026-10-26):* **pilot auth now, federated next.** Email and password with an
HttpOnly cookie session, verified signup, and DID-bound API keys — most of which already
exists. The recorded production bar (federated identity, tenant-bound membership,
short-lived scoped sessions, rotation, revocation, audited issuance) is **not** met by
this and is deferred to P4 deliberately, not forgotten.

*Done when:* a single auth client serves both editions; existing managed cookies keep
working across the change; no user is signed out by the migration.

### P2 — Agent registration workflow

The first-run gate, the three registration paths, and the signed single-use enrollment
code that replaces operator-asserted device pairing. Specified in full above.

*Done when:* a new account with no agents is shown how to connect one as its first
screen, and a binding cannot be created without a signature from the agent's key.

### P3 — Stripe

`/readyz` currently reports `stripe_sandbox` unready: "Configure real sk_test_, whsec_,
Pro and Team Price IDs". The code paths exist (`checkout`, `portal`,
`stripe/webhook`, `stripe_gateway.py`, three-tier `plans.py`); what is missing is
configuration and enforcement evidence.

*Blocked on the operator:* the test secret key, webhook signing secret and Pro/Team price
IDs must be supplied as Render environment variables. **No key is committed, printed or
retained** — local env files have previously been found holding exposed credentials.

*Done when:* `/readyz` reports `stripe_sandbox` ready; a sandbox checkout upgrades a
tenant's entitlement; a webhook replay is idempotent; and plan limits
(`max_memories`, `writes_per_month`, `retrievals_per_month`) are proved enforced by a
test that fails when the limit check is removed.

### P4 — Deferred production hardening

Federated identity (OIDC/SSO), tenant-bound membership, short-lived scoped sessions,
rotation, revocation, audited issuance. Out of scope for the pilot by the decision in P1,
recorded here so the gap is visible rather than implied.

## Out of scope

- The P4 hardening set — deferred by decision, tracked above, not abandoned.
- Any change to the Shield identity model.
- Migrating the managed backend's storage or tenancy model.

## Dependencies

1. **PR #72 — landed.** Merged at `6ad9428` on 2026-10-26T07:36Z with
   `--match-head-commit`; `viewer` CI green for the first time; Render redeployed that
   exact SHA and was validated at the artifact level.
2. **PR #73** (`local` -> `main`, OPEN, MERGEABLE) holds the only copies of
   `agent0_wallet.ts` and `agent0_integration.py`. **P0 is blocked on it**, per the
   interaction note above.
3. **Stripe credentials** from the operator block P3 and nothing else.
