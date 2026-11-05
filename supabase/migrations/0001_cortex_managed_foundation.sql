-- Cortex managed foundation for Supabase.
--
-- This migration owns managed control-plane state only. The local SQLite
-- GraphStore remains canonical for local mode until the Postgres adapter and
-- parity/replay checks land. Do not apply this migration to production without
-- first creating the environment-specific Supabase project and reviewing RLS.

create schema if not exists cortex;

create table if not exists cortex.tenants (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid not null references auth.users(id) on delete restrict,
  plan text not null default 'free' check (plan in ('free', 'pro', 'team')),
  status text not null default 'free' check (status in ('free', 'active', 'past_due', 'canceled', 'read_only')),
  stripe_customer_id text unique,
  stripe_subscription_id text,
  period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_user_id)
);

create table if not exists cortex.tenant_memberships (
  tenant_id uuid not null references cortex.tenants(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'owner' check (role in ('owner', 'admin', 'member', 'read_only')),
  created_at timestamptz not null default now(),
  primary key (tenant_id, user_id)
);

create table if not exists cortex.usage_counters (
  tenant_id uuid not null references cortex.tenants(id) on delete cascade,
  month date not null,
  meter text not null check (meter in ('writes', 'retrievals')),
  amount bigint not null default 0 check (amount >= 0),
  primary key (tenant_id, month, meter)
);

create table if not exists cortex.idempotency_operations (
  tenant_id uuid not null references cortex.tenants(id) on delete cascade,
  request_key text not null,
  fingerprint text not null,
  result jsonb,
  created_at timestamptz not null default now(),
  primary key (tenant_id, request_key)
);

create table if not exists cortex.stripe_events (
  event_id text primary key,
  processed_at timestamptz not null default now()
);

create table if not exists cortex.checkout_requests (
  tenant_id uuid primary key references cortex.tenants(id) on delete cascade,
  plan text not null check (plan in ('pro', 'team')),
  attempt_id text not null,
  checkout_id text,
  checkout_url text,
  created_at timestamptz not null default now()
);

create table if not exists cortex.email_verifications (
  token_hash text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_cortex_memberships_user
  on cortex.tenant_memberships(user_id, tenant_id);

create index if not exists idx_cortex_usage_tenant_month
  on cortex.usage_counters(tenant_id, month);

create or replace function cortex.is_member(target_tenant uuid)
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
alter table cortex.usage_counters enable row level security;
alter table cortex.idempotency_operations enable row level security;
alter table cortex.stripe_events enable row level security;
alter table cortex.checkout_requests enable row level security;
alter table cortex.email_verifications enable row level security;

create policy tenants_member_read on cortex.tenants
  for select using (cortex.is_member(id));

create policy memberships_self_or_tenant_admin_read on cortex.tenant_memberships
  for select using (user_id = auth.uid() or cortex.is_member(tenant_id));

create policy usage_member_read on cortex.usage_counters
  for select using (cortex.is_member(tenant_id));

create policy idempotency_member_read on cortex.idempotency_operations
  for select using (cortex.is_member(tenant_id));

create policy checkout_member_read on cortex.checkout_requests
  for select using (cortex.is_member(tenant_id));

-- Stripe event processing, verification-token consumption, quota reservation,
-- and membership changes are server operations. Browser roles receive no
-- direct write policy; Render services use a restricted server-side role.
