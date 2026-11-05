"""Shared managed-service backend selection for parity tests."""
from __future__ import annotations

import os
from dataclasses import replace

from xibalba_cortex.managed.config import ManagedConfig
from xibalba_cortex.managed.storage import SupabaseManagedDbFactory


def managed_control_options(config: ManagedConfig) -> tuple[ManagedConfig, dict[str, object]]:
    """Use live local Postgres when CORTEX_MANAGED_TEST_DSN is provided."""
    dsn = os.environ.get("CORTEX_MANAGED_TEST_DSN", "").strip()
    if not dsn:
        return config, {}
    import psycopg

    # Each fixture gets a fresh identity home, so clear only the shared
    # managed control-plane tables before constructing its service. This keeps
    # Postgres parity hermetic while leaving the production factory untouched.
    with psycopg.connect(dsn) as connection:
        with connection.transaction():
            connection.execute(
                "TRUNCATE cortex.email_verifications, cortex.checkout_requests, "
                "cortex.stripe_events, cortex.operations, cortex.usage, "
                "cortex.tenant_memberships, cortex.tenants CASCADE"
            )
    # The local Postgres instance is shared by the parity process while the
    # identity home remains per-test.  Keep the production registration cap
    # intact, but prevent unrelated test cases from consuming the shared
    # database's daily counter.
    return replace(config, storage_backend="supabase", signup_daily_limit=10000), {
        "db_factory": SupabaseManagedDbFactory(dsn),
        "bootstrap_schema": False,
    }
