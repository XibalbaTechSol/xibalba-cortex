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


def test_supabase_backend_builds_factory_from_server_database_url(tmp_path, monkeypatch):
    config = ManagedConfig(home=tmp_path, storage_backend="supabase",
                           supabase_database_url="postgresql://example.invalid/cortex")
    monkeypatch.setattr(ManagedControl, "_validate_supabase_schema", lambda self: None)
    service = ManagedControl(config, bootstrap_schema=False, email_sender=lambda *args: None)
    assert isinstance(service._db_factory, SupabaseManagedDbFactory)


def test_supabase_backend_skips_sqlite_bootstrap_by_default(tmp_path, monkeypatch):
    config = ManagedConfig(home=tmp_path, storage_backend="supabase",
                           supabase_url="https://example.supabase.co",
                           supabase_database_url="postgresql://example.invalid/cortex")
    validations = []
    monkeypatch.setattr(ManagedControl, "_validate_supabase_schema", lambda self: validations.append(True))

    @contextmanager
    def db_factory(*, write=False):
        pytest.fail("Supabase schema must be provided by applied migrations")

    service = ManagedControl(config, db_factory=db_factory, email_sender=lambda *args: None)
    assert service._db_factory is db_factory
    assert validations == [True]


def test_supabase_backend_rejects_explicit_sqlite_bootstrap(tmp_path, monkeypatch):
    config = ManagedConfig(home=tmp_path, storage_backend="supabase",
                           supabase_url="https://example.supabase.co",
                           supabase_database_url="postgresql://example.invalid/cortex")
    monkeypatch.setattr(ManagedControl, "_validate_supabase_schema", lambda self: None)
    with pytest.raises(ValueError, match="schema must be managed by migrations"):
        ManagedControl(config, bootstrap_schema=True, email_sender=lambda *args: None)


def test_postgres_factory_requires_optional_driver(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)
    factory = SupabaseManagedDbFactory("postgresql://example.invalid/cortex")
    with pytest.raises(SupabaseStorageUnavailable, match="managed-supabase extra"):
        with factory():
            pass


def test_supabase_sqlite_snapshot_round_trip_survives_ephemeral_restart(tmp_path, monkeypatch):
    snapshots: dict[str, dict[str, object]] = {}

    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return list(self._rows)

    class FakeDb:
        def execute(self, sql: str, params=()):
            normalized = " ".join(sql.split())
            if normalized.startswith("CREATE TABLE IF NOT EXISTS system_state"):
                return FakeCursor([])
            if normalized.startswith("INSERT INTO system_state"):
                key, data, meta = params
                version = f"v-{len(snapshots) + 1}-{len(bytes(data))}"
                snapshots[str(key)] = {"key": str(key), "data": bytes(data), "meta": meta, "updated_at": version}
                return FakeCursor([{"updated_at": version}])
            if "SELECT key, data, updated_at::text AS updated_at FROM system_state" in normalized:
                return FakeCursor(list(snapshots.values()))
            if "SELECT updated_at::text AS updated_at FROM system_state WHERE key=?" in normalized:
                row = snapshots.get(str(params[0]))
                return FakeCursor([{"updated_at": row["updated_at"]}] if row else [])
            if "SELECT data, updated_at::text AS updated_at FROM system_state WHERE key=?" in normalized:
                row = snapshots.get(str(params[0]))
                return FakeCursor([row] if row else [])
            return FakeCursor([])

    @contextmanager
    def fake_db_factory(*, write=False):
        yield FakeDb()

    monkeypatch.setattr(ManagedControl, "_validate_supabase_schema", lambda self: None)
    monkeypatch.setattr(ManagedControl, "_supabase_snapshots_enabled", lambda self: True)

    home1 = tmp_path / "container-1"
    cfg1 = ManagedConfig(
        home=home1,
        storage_backend="supabase",
        supabase_url="https://example.supabase.co",
        supabase_database_url="postgresql://example.invalid/cortex",
    )
    svc1 = ManagedControl(cfg1, db_factory=fake_db_factory, email_sender=lambda *args: None)
    tenant = {"id": "t-" + "a" * 32, "plan": "free"}
    with svc1.write_guard(tenant):
        with svc1.store(tenant) as store:
            store.store_memory(
                "Persisted across Render container replacement",
                source={"kind": "agent_mcp", "agent_id": "did:integrity:test"},
            )
    assert f"tenants/{tenant['id']}/graph-memory.sqlite3" in snapshots

    # Simulate a brand-new container with an empty filesystem restoring from Supabase.
    home2 = tmp_path / "container-2"
    cfg2 = ManagedConfig(
        home=home2,
        storage_backend="supabase",
        supabase_url="https://example.supabase.co",
        supabase_database_url="postgresql://example.invalid/cortex",
    )
    svc2 = ManagedControl(cfg2, db_factory=fake_db_factory, email_sender=lambda *args: None)
    with svc2.store(tenant) as restored_store:
        assert restored_store.counts()["memories"] == 1

