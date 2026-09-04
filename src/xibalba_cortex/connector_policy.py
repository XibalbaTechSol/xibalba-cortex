"""Small, dependency-free connector hardening primitives.

Connectors share bounded retries and a per-profile token-bucket limiter. Credential
paths are explicitly confined to the profile home so one tenant cannot accidentally
reuse another tenant's secret file.
"""
from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


class ConnectorRateLimiter:
    """Thread-safe token bucket for one connector/profile pair."""

    def __init__(self, *, rate_per_second: float = 2.0, burst: int = 4) -> None:
        if rate_per_second <= 0 or burst < 1:
            raise ValueError("rate_per_second must be positive and burst must be at least 1")
        self.rate_per_second = float(rate_per_second)
        self.capacity = float(burst)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate_per_second)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                delay = (1 - self._tokens) / self.rate_per_second
            time.sleep(delay)


def retry_call(
    operation: Callable[[], T],
    *,
    limiter: ConnectorRateLimiter,
    attempts: int = 3,
    initial_delay: float = 0.25,
    max_delay: float = 4.0,
) -> T:
    """Run an outbound operation with bounded exponential backoff.

    Retries transport failures and Google-style HTTP 429/5xx errors. Other failures
    are surfaced immediately so auth and validation errors are not hidden.
    """
    if attempts < 1:
        raise ValueError("attempts must be positive")
    for attempt in range(attempts):
        limiter.wait()
        try:
            return operation()
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(exc, "resp", None)
            if hasattr(status, "status"):
                status = status.status
            retryable = isinstance(exc, (TimeoutError, ConnectionError, OSError)) or status == 429 or (isinstance(status, int) and status >= 500)
            if not retryable or attempt == attempts - 1:
                raise
            time.sleep(min(max_delay, initial_delay * (2**attempt)) * (0.8 + random.random() * 0.4))
    raise AssertionError("unreachable")


def profile_credential_path(profile_home: str | Path, credential_path: str | Path) -> Path:
    """Resolve and validate a credential path is inside one profile's private home."""
    home = Path(profile_home).expanduser().resolve()
    path = Path(credential_path).expanduser().resolve()
    try:
        path.relative_to(home)
    except ValueError as exc:
        raise ValueError(f"credential path must be inside profile home {home}") from exc
    return path
