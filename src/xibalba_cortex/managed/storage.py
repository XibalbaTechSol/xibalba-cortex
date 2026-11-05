"""Storage seams for the managed control plane.

The first implementation remains SQLite. The callable contract is deliberately
small so a Postgres/Supabase implementation can be introduced without changing
the managed API, billing rules, or tenant authorization code.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from contextlib import contextmanager
import re
from typing import Any, Callable, Protocol


class ManagedDbFactory(Protocol):
    def __call__(self, *, write: bool = False) -> AbstractContextManager[Any]:
        """Open a managed control-plane transaction."""


ManagedDbFactoryLike = Callable[..., AbstractContextManager[Any]]


class SupabaseStorageUnavailable(RuntimeError):
    """Raised when the optional Postgres driver is not installed."""


class _CompatRow(dict):
    """Mapping row with SQLite-style numeric access for the existing control code."""

    def __init__(self, values: tuple[Any, ...], columns: tuple[str, ...]):
        super().__init__(zip(columns, values))
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    columns = tuple(column.name for column in cursor.description)

    def make_row(values):
        return _CompatRow(values, columns)

    return make_row


_INSERT_OR_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", re.IGNORECASE)


def _postgres_sql(sql: str) -> str:
    """Translate only the SQLite syntax still used by managed control code."""
    translated = sql.replace("?", "%s")
    if _INSERT_OR_IGNORE.match(translated):
        translated = _INSERT_OR_IGNORE.sub("INSERT INTO ", translated, count=1)
        translated += " ON CONFLICT DO NOTHING"
    return translated


class _CompatConnection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql: str, params=()):
        return self._connection.execute(_postgres_sql(sql), params)

    def cursor(self):
        return self._connection.cursor()

    def transaction(self):
        return self._connection.transaction()

    def close(self):
        return self._connection.close()

    def __getattr__(self, name):
        return getattr(self._connection, name)


class SupabaseManagedDbFactory:
    """Opt-in Postgres transaction factory for the managed control plane.

    The migration must be applied before this factory is enabled. Identity
    remains a separate compatibility concern until the account migration lands;
    the current control contract therefore keeps ``owner_account_id`` as text.
    """

    def __init__(self, dsn: str):
        if not dsn.strip():
            raise ValueError("Supabase Postgres DSN is required")
        self.dsn = dsn

    @contextmanager
    def __call__(self, *, write: bool = False):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised in deployment packaging
            raise SupabaseStorageUnavailable(
                "Install the managed-supabase extra to enable Supabase storage"
            ) from exc

        raw_connection = psycopg.connect(self.dsn, row_factory=_row_factory)
        connection = _CompatConnection(raw_connection)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET search_path TO cortex, public")
            with connection.transaction():
                yield connection
        finally:
            connection.close()

    @staticmethod
    def execute(connection, sql: str, params=()):
        """Execute a managed-control query with the legacy placeholder contract."""
        return connection.execute(_postgres_sql(sql), params)
