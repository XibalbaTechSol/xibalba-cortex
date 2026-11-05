-- Reversible bridge from existing Cortex account IDs to Supabase Auth subjects.
-- The legacy account ID remains stable and is never replaced by the auth UUID.
create table if not exists cortex.auth_identity_migrations (
  auth_user_id uuid primary key references auth.users(id) on delete restrict,
  legacy_account_id text not null unique,
  tenant_id text not null unique references cortex.tenants(id) on delete restrict,
  migrated_at timestamptz not null default now(),
  migration_batch text not null
);

alter table cortex.auth_identity_migrations enable row level security;
revoke all on cortex.auth_identity_migrations from anon, authenticated;

-- Rollback: delete mapping rows for the selected migration_batch, then clear
-- tenant_memberships and tenants.owner_user_id for those auth_user_id values.
-- Legacy account rows, password hashes, tenant IDs and GraphStore volumes stay intact.
