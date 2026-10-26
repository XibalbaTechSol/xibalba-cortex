# Supabase-backed managed pilot

Supabase will supply the durable control plane for a hosted Cortex pilot: tenant subscription state, usage counters, idempotency records, Stripe event deduplication, checkout attempts, and verification tokens. The Cortex API remains the compute layer, and each tenant's hash-chained graph remains in its own durable SQLite file.

Install the Supabase CLI, authenticate, link the selected project, and apply the migration:

    supabase login
    supabase link --project-ref YOUR_PROJECT_REF
    supabase db push

Store the service-role key only in the API deployment secret manager as SUPABASE_SERVICE_ROLE_KEY. Keep SUPABASE_URL server-side. Do not expose either value to the browser, Stripe, or customer API keys.

The current Python control implementation still uses its local SQLite control plane. The Supabase adapter must migrate ManagedControl transaction boundaries to these tables before customer traffic uses the project. Do not point a running pilot at an empty Supabase project.

Pilot sequence: create or select the project, apply the migration, verify RLS denies anon and authenticated reads, implement and test atomic quota reservations and idempotency, keep tenant graph volumes on encrypted durable storage with tested backups, then configure Stripe test prices/webhooks and SMTP.

Supabase Auth is disabled in this migration because Cortex currently owns verified account sessions and password recovery. Introducing two account systems in the pilot would create ambiguous identity ownership.
