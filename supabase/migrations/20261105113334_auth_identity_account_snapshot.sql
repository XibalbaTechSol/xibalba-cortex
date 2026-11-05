-- Persist the minimum account profile needed by Cortex after legacy SQLite
-- identity storage is retired. Authorization still comes from the server's
-- explicit mapping and tenant ownership, never from these profile fields.
alter table cortex.auth_identity_migrations
  add column if not exists account_email text not null default '',
  add column if not exists account_display_name text not null default '',
  add column if not exists account_role text not null default 'operator',
  add column if not exists account_status text not null default 'active',
  add column if not exists account_email_verified boolean not null default false,
  add column if not exists account_approval_status text not null default 'pending';

alter table cortex.auth_identity_migrations enable row level security;
revoke all on cortex.auth_identity_migrations from anon, authenticated;
