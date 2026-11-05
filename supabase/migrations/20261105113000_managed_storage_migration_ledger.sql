-- Track only control-plane rows inserted from the legacy SQLite database.
-- Rollback deletes a row only while its captured post-import state is unchanged.
create table if not exists cortex.managed_storage_migration_rows (
  batch_id text not null,
  table_name text not null check (table_name in (
    'tenants', 'usage', 'operations', 'stripe_events', 'checkout_requests', 'email_verifications'
  )),
  row_key jsonb not null,
  row_digest text not null check (length(row_digest) = 64),
  migrated_at timestamptz not null default now(),
  primary key (batch_id, table_name, row_key),
  unique (table_name, row_key)
);

alter table cortex.managed_storage_migration_rows enable row level security;
revoke all on cortex.managed_storage_migration_rows from anon, authenticated;
