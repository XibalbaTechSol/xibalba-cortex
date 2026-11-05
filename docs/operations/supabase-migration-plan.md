# Supabase migration plan

**Status date:** 2026-11-05  
**Scope:** Cortex first, then the shared Integrity ecosystem. Supabase is the
backend authority; Render hosts user interfaces and any explicitly retained
service adapters. This plan distinguishes Auth and managed control-plane
cutover from moving Cortex's canonical memory store.

## Current evidence

- Supabase project `integrity-userapi` (`ftspunijfgcbkuybobhf`) has migrations
  through `20261105113334_auth_identity_account_snapshot` applied.
- Google and GitHub provider handoffs and product redirect allow-lists were
  validated. A completed user-consent callback has not yet been observed.
- A read-only post-deploy Supabase query found one confirmed Auth user and
  zero rows in `cortex.tenants`, `cortex.tenant_memberships`, and
  `cortex.auth_identity_migrations`. The user therefore still has no Cortex
  mapping; no authenticated sign-in has created a workspace yet.
- Cortex PR #104 contains signature-verified Supabase sessions, explicit
  subject-to-account migration, rollback, a gated new-account provisioner, and
  Render Blueprint settings for Supabase Auth and managed control storage. It
  also fails startup if Supabase is unreachable or required migrations are
  missing. It merged at `3db967c` after Python and viewer CI passed on
  `0cc72d9`; Render deploy `dep-dbm7i7p7lnhs738pjae0` is live on that merge
  commit.
- Live `GET /healthz` returns `{"ok":true,"edition":"managed"}`. `GET /readyz`
  returns 503 for the unconfigured Stripe sandbox; its other reported checks
  are ready. `GET /api/managed/plans` reports signup enabled and billing
  unconfigured.
- The first post-deploy Supabase-backed sign-in has not yet been exercised.
  The last production query before deploy found zero Cortex tenant/membership/
  subject mappings. Do not infer backend selection from `/healthz` or the
  generic writable-storage readiness check; confirm the actual Postgres path
  with the first authenticated database-backed request and its resulting row.
- The live `cortex-managed-pilot` service is Render Free, tracks `main`, and
  has no persistent disk. Before this cutover it used SQLite. The operator
  accepted that old profiles may be recreated. No claim is made that runtime
  SQLite state was exported.
- `/readyz` returned 503 because Stripe sandbox credentials/prices are not
  configured. SMTP and signup reported ready. This pilot readiness endpoint
  does not prove durable storage or the selected database backend.
- `GraphStore` still creates a per-tenant local SQLite store under
  `CORTEX_MANAGED_HOME/tenants/`. PR #104 moves managed control-plane state and
  identity mapping to Supabase; it does **not** yet move canonical memories,
  entities, relations, event chains, embeddings metadata, or related GraphStore
  state to Supabase.

## Ordered remaining work

### A. Cortex Auth and managed control-plane cutover

1. **DONE — merge and deploy the Auth/control-plane cutover.** PR #104 merged
   with CI green at `0cc72d9`; Render deploy `dep-dbm7i7p7lnhs738pjae0` is live
   on `3db967c`.
2. **Verify Render deployment inputs without printing secrets.** Confirm
   `CORTEX_MANAGED_DATABASE_URL` exists, points to the `integrity-userapi`
   Postgres connection, and is reachable from Render. Confirm the deployed
   service has `CORTEX_MANAGED_STORAGE_BACKEND=supabase`,
   `CORTEX_MANAGED_IDENTITY_BACKEND=supabase_auth`, the expected project URL,
   and the public publishable key. Treat `render.yaml` as desired configuration
   until the live runtime proves it took effect. Render Free rejected creation
   of a one-off probe job, so the startup preflight and first authenticated
   database-backed request are the available runtime checks on this plan.
3. **Verify live Supabase storage.** Check health and logs, then confirm server
   writes land in `cortex` tables and RLS remains enabled with no client write
   policies. A green `/healthz` alone is not sufficient.
4. **Exercise Auth end to end.** Complete sign-in for the confirmed account;
   verify the Supabase token is exchanged for the HttpOnly Cortex session,
   `/api/managed/me` resolves the same subject, tenant membership is created,
   and a subsequent sign-in reuses the same mapping. Test Google and GitHub
   independently. Provider redirects alone do not prove callback success.
5. **Verify identity safety and rollback.** Confirm no email-only linking,
   reject an unverified Auth user and an unmapped legacy collision, and prove a
   migration rollback removes only links created by that batch. Document that
   recreating old profiles creates new account IDs unless a reviewed mapping is
   explicitly imported.
6. **Resolve operational readiness.** Signup is enabled and verified Auth
   users are required by provisioning. Decide whether to keep pilot signup
   enabled while `/readyz` remains blocked on Stripe sandbox. Record Stripe as
   a separate billing gate, not an Auth or storage failure.

### B. Cortex canonical memory storage

7. **Design the GraphStore target before implementation.** Inventory every
   table, trigger, transaction boundary, integrity hash, backup/restore path,
   worker, and query used by managed routes. Define a tenant-keyed Supabase
   Postgres representation, ownership model, RLS policies, and a tested
   rollback/export format. Do not treat the current control-plane importer as a
   GraphStore migration.
8. **Build a Postgres-backed managed store behind a narrow store interface.**
   Preserve canonical event-chain and tamper-evidence semantics; avoid loading
   or replacing whole SQLite database files per request. Keep local operator
   profiles working during the hosted migration.
9. **Migrate and verify data.** Provide preview, idempotent apply, row-level
   reconciliation, and rollback tooling. Test counts, content hashes, graph
   relationships, attachments, embeddings metadata, and export verification.
   The operator has accepted profile recreation for the current ephemeral
   pilot; that does not waive correctness or rollback tests for future tenants.
10. **Remove Render-local durability assumptions.** Confirm user data,
    queues/outboxes, and worker state that must survive restarts are in
    Supabase or another approved durable service before treating the backend
    migration as complete.

### C. Shield, Console, and Integrity ecosystem

11. **Adopt the shared Supabase Auth project per app.** Keep the same provider
    configuration and Supabase callback, while adding only each product's
    exact return URLs. Implement server-side JWT verification and a
    product-specific subject-to-tenant authorization mapping in Shield and
    Console; shared OAuth credentials do not share application authorization.
12. **Keep service ownership explicit.** For each of Shield, Cortex, Core, and
    Console, record which data is authoritative in Supabase, which process
    performs privileged writes, and which UI is served by Render. Move each
    backend in its own reviewed slice with isolated rollback and live evidence.
13. **Close with an ecosystem audit.** Verify provider callback completion,
    tenant isolation, RLS, key boundaries, migration/rollback evidence, service
    health, and UI origin allow-lists for all four products. Update the
    ecosystem plan and each repo's resume ledger with exact commit, CI, deploy,
    and runtime evidence.

## Stop and rollback rules

- Do not enable live Supabase Auth in a service unless its database DSN is
  present and connectivity is verified without exposing the value.
- Do not infer account identity from email. Use verified Supabase subject plus
  an explicit migration manifest or the gated new-account path.
- If health, Auth exchange, or tenant isolation fails after deployment, roll
  back the service code/config to the last known compatible version; preserve
  Supabase rows and migration history for diagnosis. Do not delete user or
  tenant rows as a rollback shortcut.
- Keep billing readiness, OAuth provider handoff, Auth callback completion,
  storage durability, and production readiness as separate evidence states.
