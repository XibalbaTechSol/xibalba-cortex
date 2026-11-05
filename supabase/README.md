# Cortex Supabase migrations

This directory contains the managed Cortex migration path. It is deliberately
separate from the local SQLite GraphStore:

- local Cortex mode continues to use its existing SQLite store;
- managed control-plane state is the first Supabase slice;
- memory/provenance tables move only after schema parity, replay, tenant-RLS,
  and evidence-verification tests exist;
- Supabase rows are not themselves Integrity evidence; signed receipts and
  canonical payloads remain independently verifiable.

## Environment rules

Use a separate Supabase project for development, staging, and production. Do
not put a service-role key in the Vite viewer or any Render static-site
environment variable. Render Python services may use a server-side credential
only through the configured secret store.

## Local validation

With the Supabase CLI and a local project running:

```sh
supabase start
supabase db reset
supabase db lint
```

The migrations establish managed tenant, entitlement, usage, billing, and
email-verification state. Migration `20261105102100_auth_subject_mapping.sql`
adds the reversible identity bridge used by the Python managed service; existing
account links still require an explicit manifest and apply operation. The
timestamped `20261105064544` and `20261105064615` migrations establish the
existing Integrity User API baseline already present in the linked Supabase
project, so local and hosted migration histories stay ordered and consistent.

## Supabase Auth identity bridge

The managed API can use `CORTEX_MANAGED_IDENTITY_BACKEND=supabase_auth` with
`CORTEX_MANAGED_STORAGE_BACKEND=supabase` and `SUPABASE_URL`. It verifies access
tokens against the project's JWKS, resolves the verified `sub` through
`cortex.tenants.owner_user_id`, and issues the existing HttpOnly Cortex session
cookie. API keys continue to use their existing machine-identity path. Legacy
password login is disabled in this mode.

Existing operators must be linked explicitly; the adapter never matches a
Supabase identity to a legacy account by email. Preview a JSON manifest with
`xibalba-cortex-managed-identity-migrate preview --batch <id> --manifest
<manifest.json>`, apply it with `apply`, and reverse only that batch with
`rollback`. The legacy SQLite account, password record, tenant ID, and graph
volume remain intact during rollback. Apply migration
`20261105102100_auth_subject_mapping.sql` before running the CLI.

For local Google or GitHub sign-in, set the provider's client ID and secret in
the root `.env`; never commit that file. Local Supabase development needs OAuth
apps whose callback URL is `http://127.0.0.1:54321/auth/v1/callback`. Hosted
products can share the production Supabase project's provider credentials and
callback (`https://ftspunijfgcbkuybobhf.supabase.co/auth/v1/callback`); add each
product's return URL to that project's Auth redirect allow-list. The viewer
uses PKCE, then exchanges the verified access token for the managed Cortex
cookie. Do not enable hosted sign-in until existing operators have been
migrated and the project URL, publishable/anon key, redirect allow-list, and
provider callback are configured for that environment.

The Vite viewer reads `VITE_SUPABASE_URL` and
`VITE_SUPABASE_PUBLISHABLE_KEY`; use `viewer/.env.example` as the local template.
The redirect allow-list includes the viewer's local development port, 5190.
