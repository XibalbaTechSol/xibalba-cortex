-- Supabase exposes the `public` schema through PostgREST, so a table without RLS is readable
-- with the anon key. Render Postgres had no such public REST layer, so this exposure is created
-- by the migration itself, not inherited.
--
-- RLS is enabled with NO policies: PostgREST's anon/authenticated roles are denied everything.
-- integrity-userapi is unaffected because it connects over direct Postgres as the table owner,
-- and an owner bypasses RLS. Deliberately NOT using FORCE ROW LEVEL SECURITY, which would also
-- apply to the owner and would break the application.
ALTER TABLE public.users            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_keys         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_agents      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.demo_runs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.revoked_tokens   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_wallets     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.policy_packs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.policy_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;;
