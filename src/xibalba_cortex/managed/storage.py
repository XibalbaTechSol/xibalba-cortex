"""Storage seams for the managed control plane.

The first implementation remains SQLite. The callable contract is deliberately
small so a Postgres/Supabase implementation can be introduced without changing
the managed API, billing rules, or tenant authorization code.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Callable, Protocol


class ManagedDbFactory(Protocol):
    def __call__(self, *, write: bool = False) -> AbstractContextManager[Any]:
        """Open a managed control-plane transaction."""


ManagedDbFactoryLike = Callable[..., AbstractContextManager[Any]]
