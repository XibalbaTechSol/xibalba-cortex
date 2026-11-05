"""The optional local-Postgres tests prove import and rollback against real SQL types."""
from __future__ import annotations

import os
import sqlite3
import uuid

import pytest

from xibalba_cortex.managed.storage import SupabaseManagedDbFactory
from xibalba_cortex.managed_storage_migrate import MigrationConflict, migrate_storage


pytestmark = pytest.mark.skipif(
    not os.environ.get("CORTEX_MANAGED_TEST_DSN"), reason="requires local Supabase Postgres"
)


def _source(path, tenant_id, account_id):
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE tenants (
        id TEXT PRIMARY KEY, owner_account_id TEXT NOT NULL UNIQUE,
        plan TEXT NOT NULL DEFAULT 'free', status TEXT NOT NULL DEFAULT 'free',
        customer_id TEXT UNIQUE, subscription_id TEXT, period_end INTEGER,
        cancel_at_period_end INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL
      );
      CREATE TABLE usage (
        tenant_id TEXT NOT NULL, month TEXT NOT NULL, meter TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (tenant_id,month,meter)
      );
      CREATE TABLE operations (
        tenant_id TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
        PRIMARY KEY (tenant_id,request_key)
      );
      CREATE TABLE stripe_events (id TEXT PRIMARY KEY, processed_at INTEGER NOT NULL);
      CREATE TABLE checkout_requests (
        tenant_id TEXT PRIMARY KEY, plan TEXT NOT NULL, attempt TEXT NOT NULL,
        checkout_id TEXT, url TEXT
      );
      CREATE TABLE email_verifications (
        token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires_at INTEGER NOT NULL
      );
    """)
    db.execute("INSERT INTO tenants(id,owner_account_id,created_at) VALUES(?,?,?)",
               (tenant_id, account_id, 1_700_000_000))
    db.execute("INSERT INTO usage VALUES(?,?,?,?)", (tenant_id, "2026-11", "writes", 5))
    db.execute("INSERT INTO operations VALUES(?,?,?)", (tenant_id, "request-1", "fingerprint-1"))
    db.execute("INSERT INTO stripe_events VALUES(?,?)", ("evt_" + tenant_id, 1_700_000_001))
    db.execute("INSERT INTO checkout_requests VALUES(?,?,?,?,?)",
               (tenant_id, "pro", "attempt-1", "cs_test_1", "https://checkout.example/1"))
    db.execute("INSERT INTO email_verifications VALUES(?,?,?)", ("hash_" + tenant_id, account_id, 1_900_000_000))
    db.commit()
    db.close()


def _factory():
    return SupabaseManagedDbFactory(os.environ["CORTEX_MANAGED_TEST_DSN"])


def _cleanup(factory, batch_id, tenant_id):
    with factory(write=True) as db:
        db.execute("DELETE FROM managed_storage_migration_rows WHERE batch_id=?", (batch_id,))
        db.execute("DELETE FROM email_verifications WHERE token_hash=?", ("hash_" + tenant_id,))
        db.execute("DELETE FROM checkout_requests WHERE tenant_id=?", (tenant_id,))
        db.execute("DELETE FROM stripe_events WHERE id=?", ("evt_" + tenant_id,))
        db.execute("DELETE FROM operations WHERE tenant_id=?", (tenant_id,))
        db.execute("DELETE FROM usage WHERE tenant_id=?", (tenant_id,))
        db.execute("DELETE FROM tenants WHERE id=?", (tenant_id,))


def test_control_plane_import_is_idempotent_and_rollback_preserves_changed_rows(tmp_path):
    factory = _factory()
    suffix = uuid.uuid4().hex
    tenant_id, account_id, batch = "t-" + suffix, "legacy-" + suffix, "storage-" + suffix
    source = tmp_path / "managed.sqlite3"
    _source(source, tenant_id, account_id)
    try:
        preview = migrate_storage(source, factory, batch_id=batch, action="preview")
        assert preview["tables"]["tenants"]["to_import"] == 1
        assert preview["tables"]["email_verifications"]["to_import"] == 1

        applied = migrate_storage(source, factory, batch_id=batch, action="apply")
        assert applied["tables"]["tenants"]["to_import"] == 1
        repeated = migrate_storage(source, factory, batch_id=batch, action="apply")
        assert repeated["tables"]["tenants"]["already_present"] == 1
        with factory() as db:
            tenant = db.execute("SELECT owner_account_id,owner_user_id,created_at FROM tenants WHERE id=?",
                                 (tenant_id,)).fetchone()
            assert tenant["owner_account_id"] == account_id
            assert tenant["owner_user_id"] is None
            assert tenant["created_at"] == 1_700_000_000
            assert db.execute("SELECT amount FROM usage WHERE tenant_id=?", (tenant_id,)).fetchone()["amount"] == 5

        with factory(write=True) as db:
            db.execute("UPDATE usage SET amount=6 WHERE tenant_id=?", (tenant_id,))
        with pytest.raises(MigrationConflict, match="modified usage row"):
            migrate_storage(source, factory, batch_id=batch, action="rollback")
        with factory() as db:
            assert db.execute("SELECT 1 FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        with factory(write=True) as db:
            db.execute("UPDATE usage SET amount=5 WHERE tenant_id=?", (tenant_id,))

        result = migrate_storage(source, factory, batch_id=batch, action="rollback")
        assert result["rolled_back"] == 6
        with factory() as db:
            assert db.execute("SELECT 1 FROM tenants WHERE id=?", (tenant_id,)).fetchone() is None
            assert db.execute("SELECT 1 FROM usage WHERE tenant_id=?", (tenant_id,)).fetchone() is None
    finally:
        _cleanup(factory, batch, tenant_id)


def test_import_preflight_detects_conflicts_before_writing_any_table(tmp_path):
    factory = _factory()
    suffix = uuid.uuid4().hex
    tenant_id, account_id, batch = "t-" + suffix, "legacy-" + suffix, "conflict-" + suffix
    source = tmp_path / "managed.sqlite3"
    _source(source, tenant_id, account_id)
    try:
        with factory(write=True) as db:
            db.execute("INSERT INTO tenants(id,owner_account_id,status,created_at) VALUES(?,?,?,?)",
                       (tenant_id, account_id, "canceled", 1_700_000_000))
        result = migrate_storage(source, factory, batch_id=batch, action="apply")
        assert result["conflicts"] == [{"table": "tenants", "key": {"id": tenant_id}}]
        with factory() as db:
            assert db.execute("SELECT 1 FROM usage WHERE tenant_id=?", (tenant_id,)).fetchone() is None
    finally:
        _cleanup(factory, batch, tenant_id)
