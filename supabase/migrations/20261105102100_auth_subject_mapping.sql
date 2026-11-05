-- Reversible bridge from existing Cortex account IDs to Supabase Auth subjects.
-- The legacy account ID remains stable and is never replaced by the auth UUID.
create table if not exists cortex.auth_identity_migrations (
  auth_user_id uuid primary key references auth.users(id) on delete restrict,
  legacy_account_id text not null unique,
  tenant_id text not null unique references cortex.tenants(id) on delete restrict,
  migrated_at timestamptz not null default now(),
  migration_batch text not null,
  owner_link_created boolean not null default false,
  membership_role_before text
);

-- Keep this migration safely re-runnable for databases that applied an earlier
-- version of 0002 before the rollback snapshot columns were added.
alter table cortex.auth_identity_migrations
  add column if not exists owner_link_created boolean not null default false,
  add column if not exists membership_role_before text;

alter table cortex.auth_identity_migrations enable row level security;
revoke all on cortex.auth_identity_migrations from anon, authenticated;

-- Rollback restores only state changed by the link: a prior membership role is
-- restored, an inserted membership is removed, and a pre-existing tenant owner
-- link is preserved. Legacy account data and GraphStore volumes stay intact.
