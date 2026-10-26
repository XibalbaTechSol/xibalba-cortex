# Supabase-backed managed pilot

Railway runs the Cortex API and mounts its persistent volume at /data/cortex-managed. Supabase supplies the durable control plane for a hosted pilot: tenant subscription state, usage counters, idempotency records, Stripe event deduplication, checkout attempts, and verification tokens. Each tenant's hash-chained graph remains in its own durable SQLite file.

Create a Railway project from the repository and deploy with railway.toml. Add the volume at the declared mount path, then set the server variables from deploy/managed/managed.env.example in Railway's Variables panel. Deploy the service before enabling signup.

Install the Supabase CLI, authenticate, link the selected project, and apply the migration:

    supabase login
    supabase link --project-ref YOUR_PROJECT_REF
    supabase db push

Store the service-role key only in the API deployment secret manager as SUPABASE_SERVICE_ROLE_KEY. Keep SUPABASE_URL server-side. Do not expose either value to the browser, Stripe, or customer API keys.

The current Python control implementation keeps SQLite authoritative and mirrors tenant, usage, and subscription state to Supabase when both Supabase variables are set. The adapter must migrate transaction boundaries and pass concurrent isolation tests before Supabase becomes authoritative. Do not point a running pilot at an empty Supabase project.

Pilot sequence: create or select the project, apply the migration, verify RLS denies anon and authenticated reads, implement and test atomic quota reservations and idempotency, keep tenant graph volumes on encrypted durable storage with tested backups, then configure Stripe test prices/webhooks and SMTP.

Supabase Auth is disabled in this migration because Cortex currently owns verified account sessions and password recovery. Introducing two account systems in the pilot would create ambiguous identity ownership.
