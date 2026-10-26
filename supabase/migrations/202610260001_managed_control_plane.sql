-- Cortex managed control plane for Supabase Postgres.
-- The Python service remains the only writer through the service-role connection.
-- Tenant graph SQLite files stay on the managed API's durable volume.
create table if not exists public.cortex_tenants (
  id text primary key check (id ~ '^t-[0-9a-f]{32}$'), owner_account_id text not null unique,
  plan text not null default 'free' check (plan in ('free', 'pro', 'team')),
  status text not null default 'free', customer_id text unique, subscription_id text,
  period_end bigint, cancel_at_period_end boolean not null default false,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.cortex_usage (
  tenant_id text not null references public.cortex_tenants(id) on delete cascade,
  month date not null, meter text not null check (meter in ('writes', 'retrievals')),
  amount bigint not null default 0 check (amount >= 0), primary key (tenant_id, month, meter)
);
create table if not exists public.cortex_operations (
  tenant_id text not null references public.cortex_tenants(id) on delete cascade,
  request_key text not null, fingerprint text not null, created_at timestamptz not null default now(),
  primary key (tenant_id, request_key)
);
create table if not exists public.cortex_stripe_events (id text primary key, processed_at timestamptz not null default now());
create table if not exists public.cortex_checkout_requests (
  tenant_id text primary key references public.cortex_tenants(id) on delete cascade,
  plan text not null check (plan in ('pro', 'team')), attempt text not null, checkout_id text, url text,
  created_at timestamptz not null default now()
);
create table if not exists public.cortex_email_verifications (token_hash text primary key, account_id text not null, expires_at timestamptz not null);
create index if not exists cortex_tenants_customer_idx on public.cortex_tenants(customer_id);
create index if not exists cortex_usage_month_idx on public.cortex_usage(tenant_id, month);
create index if not exists cortex_email_verifications_account_idx on public.cortex_email_verifications(account_id);
alter table public.cortex_tenants enable row level security;
alter table public.cortex_usage enable row level security;
alter table public.cortex_operations enable row level security;
alter table public.cortex_stripe_events enable row level security;
alter table public.cortex_checkout_requests enable row level security;
alter table public.cortex_email_verifications enable row level security;
create or replace function public.cortex_touch_updated_at() returns trigger language plpgsql as 'begin new.updated_at = now(); return new; end;';
drop trigger if exists cortex_tenants_updated_at on public.cortex_tenants;
create trigger cortex_tenants_updated_at before update on public.cortex_tenants for each row execute function public.cortex_touch_updated_at();
