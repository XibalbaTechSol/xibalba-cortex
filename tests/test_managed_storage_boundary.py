"""Regression tests for the managed control-plane storage seam."""
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager

import pytest

from xibalba_cortex.managed.config import ManagedConfig
from xibalba_cortex.managed.control import ManagedControl
from xibalba_cortex.managed.storage import SupabaseManagedDbFactory, SupabaseStorageUnavailable


def test_managed_control_uses_injected_transaction_factory(tmp_path):
    config = ManagedConfig(home=tmp_path, public_url="http://localhost:8430")
    calls: list[bool] = []

    @contextmanager
    def factory(*, write=False):
        calls.append(write)
        connection = sqlite3.connect(config.home / "managed.sqlite3", timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    service = ManagedControl(config, email_sender=lambda *args: None, db_factory=factory)

    with service.db() as db:
        assert db.execute("SELECT COUNT(*) FROM tenants").fetchone()[0] == 0

    assert calls[0] is False  # schema bootstrap
    assert calls[-1] is False  # explicit read transaction above


def test_supabase_backend_fails_closed_without_a_database_url(tmp_path):
    config = ManagedConfig(home=tmp_path, storage_backend="supabase")
    with pytest.raises(RuntimeError, match="CORTEX_MANAGED_DATABASE_URL"):
        ManagedControl(config, email_sender=lambda *args: None)


def test_supabase_backend_builds_factory_from_server_database_url(tmp_path):
    config = ManagedConfig(home=tmp_path, storage_backend="supabase",
                           supabase_database_url="postgresql://example.invalid/cortex")
    service = ManagedControl(config, bootstrap_schema=False, email_sender=lambda *args: None)
    assert isinstance(service._db_factory, SupabaseManagedDbFactory)


def test_supabase_backend_skips_sqlite_bootstrap_by_default(tmp_path):
    config = ManagedConfig(home=tmp_path, storage_backend="supabase",
                           supabase_url="https://example.supabase.co",
                           supabase_database_url="postgresql://example.invalid/cortex")

    @contextmanager
    def db_factory(*, write=False):
        pytest.fail("Supabase schema must be provided by applied migrations")

    service = ManagedControl(config, db_factory=db_factory, email_sender=lambda *args: None)
    assert service._db_factory is db_factory


def test_supabase_backend_rejects_explicit_sqlite_bootstrap(tmp_path):
    config = ManagedConfig(home=tmp_path, storage_backend="supabase",
                           supabase_url="https://example.supabase.co",
                           supabase_database_url="postgresql://example.invalid/cortex")
    with pytest.raises(ValueError, match="schema must be managed by migrations"):
        ManagedControl(config, bootstrap_schema=True, email_sender=lambda *args: None)


def test_postgres_factory_requires_optional_driver(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)
    factory = SupabaseManagedDbFactory("postgresql://example.invalid/cortex")
    with pytest.raises(SupabaseStorageUnavailable, match="managed-supabase extra"):
        with factory():
            pass
