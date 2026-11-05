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

The migration currently establishes tenant membership, plan/entitlement
metadata, usage reservation state, idempotency records, billing event
deduplication, checkout state, and email-verification state. It does not yet
change the Python managed service or migrate existing tenant data.

## Identity bridge status

The first Python adapter deliberately uses `CORTEX_MANAGED_IDENTITY_BACKEND=sqlite_compat`:
managed control-plane state is in Supabase, while password hashes, sessions,
OAuth links, and device-pairing records remain in the service's private SQLite
identity home. The `owner_account_id` text key is the compatibility boundary;
`owner_user_id` and `tenant_memberships` are reserved for the subsequent
Supabase Auth cutover. A deployment must not claim full Supabase identity until
JWT verification, subject-to-account migration, and replay/rollback tests are
complete.
