# Cortex accounts and agent registration — design

**Date:** 2026-10-26
**Status:** design approved in conversation; not yet planned or implemented
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

### Editions become a flag, not a second application

`ManagedApp` dissolves into two panels — plans/billing, and tenant onboarding — mounted
inside the console's existing `Shell`. `VITE_CORTEX_EDITION=managed` then selects which
panels mount, not which application boots. `ManagedLenses.tsx` collapses into
`GraphLens` / `TimelineLens` over an edition-aware data source, so the lenses stop being
a managed-specific reimplementation.

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

## Out of scope

- Federated identity (SSO/OIDC), tenant-bound membership and short-lived scoped sessions —
  required for production, but a separate project from this flow.
- Stripe configuration and paid-plan validation.
- Any change to the Shield identity model.

## Dependencies

1. **PR #72 must land first.** It takes `viewer` CI from 5 failures to 0. The `viewer` job
   has never been green since it was added at 00:15Z on 2026-10-26, so no merge gate is
   satisfiable until it does.
2. **PR #73** (`local` -> `main`) carries the Agent0 unification this design builds on.
