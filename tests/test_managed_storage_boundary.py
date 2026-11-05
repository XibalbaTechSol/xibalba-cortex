"""Regression tests for the managed control-plane storage seam."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from xibalba_cortex.managed.config import ManagedConfig
from xibalba_cortex.managed.control import ManagedControl


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
