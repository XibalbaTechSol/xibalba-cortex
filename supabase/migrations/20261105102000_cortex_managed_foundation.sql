-- Cortex managed foundation for Supabase.
--
-- This migration owns managed control-plane state only. The local SQLite
-- GraphStore remains canonical for local mode until the Postgres adapter and
-- parity/replay checks land. Do not apply this migration to production without
-- first creating the environment-specific Supabase project and reviewing RLS.

create schema if not exists cortex;

create table if not exists cortex.tenants (
  id text primary key,
  owner_account_id text not null unique,
  owner_user_id uuid references auth.users(id) on delete set null,
  plan text not null default 'free' check (plan in ('free', 'pro', 'team')),
  status text not null default 'free' check (status in ('free', 'active', 'past_due', 'canceled', 'read_only', 'unpaid', 'incomplete', 'incomplete_expired', 'paused', 'trialing')),
  customer_id text unique,
  subscription_id text,
  period_end bigint,
  cancel_at_period_end integer not null default 0,
  created_at bigint not null default extract(epoch from now())::bigint,
  updated_at bigint not null default extract(epoch from now())::bigint,
  unique (owner_account_id)
);

create table if not exists cortex.tenant_memberships (
  tenant_id text not null references cortex.tenants(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'owner' check (role in ('owner', 'admin', 'member', 'read_only')),
  created_at bigint not null default extract(epoch from now())::bigint,
  primary key (tenant_id, user_id)
);

create table if not exists cortex.usage (
  tenant_id text not null references cortex.tenants(id) on delete cascade,
  month text not null,
  meter text not null check (meter in ('writes', 'retrievals')),
  amount bigint not null default 0 check (amount >= 0),
  primary key (tenant_id, month, meter)
);

create table if not exists cortex.operations (
  tenant_id text not null references cortex.tenants(id) on delete cascade,
  request_key text not null,
  fingerprint text not null,
  result jsonb,
  created_at bigint not null default extract(epoch from now())::bigint,
  primary key (tenant_id, request_key)
);

create table if not exists cortex.stripe_events (
  id text primary key,
  processed_at bigint not null default extract(epoch from now())::bigint
);

create table if not exists cortex.checkout_requests (
  tenant_id text primary key references cortex.tenants(id) on delete cascade,
  plan text not null check (plan in ('pro', 'team')),
  attempt text not null,
  checkout_id text,
  url text,
  created_at bigint not null default extract(epoch from now())::bigint
);

create table if not exists cortex.email_verifications (
  token_hash text primary key,
  account_id text not null,
  expires_at bigint not null,
  created_at bigint not null default extract(epoch from now())::bigint
);

create index if not exists idx_cortex_memberships_user
  on cortex.tenant_memberships(user_id, tenant_id);

create index if not exists idx_cortex_usage_tenant_month
  on cortex.usage(tenant_id, month);

create or replace function cortex.is_member(target_tenant text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from cortex.tenant_memberships as membership
    where membership.tenant_id = target_tenant
      and membership.user_id = auth.uid()
  );
$$;

alter table cortex.tenants enable row level security;
alter table cortex.tenant_memberships enable row level security;
alter table cortex.usage enable row level security;
alter table cortex.operations enable row level security;
alter table cortex.stripe_events enable row level security;
alter table cortex.checkout_requests enable row level security;
alter table cortex.email_verifications enable row level security;

create policy tenants_member_read on cortex.tenants
  for select using (cortex.is_member(id));

create policy memberships_self_or_tenant_admin_read on cortex.tenant_memberships
  for select using (user_id = auth.uid() or cortex.is_member(tenant_id));

create policy usage_member_read on cortex.usage
  for select using (cortex.is_member(tenant_id));

create policy idempotency_member_read on cortex.operations
  for select using (cortex.is_member(tenant_id));

create policy checkout_member_read on cortex.checkout_requests
  for select using (cortex.is_member(tenant_id));

-- Stripe event processing, verification-token consumption, quota reservation,
-- and membership changes are server operations. Browser roles receive no
-- direct write policy; Render services use a restricted server-side role.
