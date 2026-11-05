import time

import pytest

from xibalba_cortex.connector_policy import ConnectorRateLimiter, profile_credential_path, retry_call


def test_profile_credential_path_rejects_cross_profile_path(tmp_path):
    with pytest.raises(ValueError, match="inside profile home"):
        profile_credential_path(tmp_path / "tenant-a", tmp_path / "tenant-b" / "token.json")


def test_profile_credential_path_resolves_inside_profile(tmp_path):
    path = profile_credential_path(tmp_path, tmp_path / "credentials" / "token.json")
    assert path == (tmp_path / "credentials" / "token.json").resolve()


def test_retry_call_retries_transport_failures_and_is_bounded():
    attempts = 0

    def flaky():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("temporary")
        return "ok"

    started = time.monotonic()
    result = retry_call(
        flaky,
        limiter=ConnectorRateLimiter(rate_per_second=1000, burst=1),
        attempts=3,
        initial_delay=0,
    )
    assert result == "ok"
    assert attempts == 3
    assert time.monotonic() - started < 1


def test_retry_call_does_not_retry_non_transport_errors():
    attempts = 0

    def invalid():
        nonlocal attempts
        attempts += 1
        raise ValueError("bad request")

    with pytest.raises(ValueError, match="bad request"):
        retry_call(invalid, limiter=ConnectorRateLimiter(rate_per_second=1000), attempts=3, initial_delay=0)
    assert attempts == 1


def test_retry_call_retries_google_style_rate_limit_response():
    class RateLimited:
        def __init__(self):
            self.status = 429

    attempts = 0

    def flaky():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error = RuntimeError("rate limited")
            error.resp = RateLimited()
            raise error
        return "ok"

    assert retry_call(flaky, limiter=ConnectorRateLimiter(rate_per_second=1000), initial_delay=0) == "ok"
    assert attempts == 2


def test_try_acquire_sheds_instead_of_blocking_and_reports_retry_after():
    """Inbound ingress must shed load, not sleep on it.

    `wait()` is right for an outbound connector -- it paces our own calls. On an inbound
    server it converts overload into unbounded latency while holding a request thread, so
    the receiver needs a non-blocking form that tells the caller how long to wait.
    """
    clock = [0.0]
    limiter = ConnectorRateLimiter(rate_per_second=10.0, burst=2, clock=lambda: clock[0])

    assert limiter.try_acquire() is None       # burst token 1
    assert limiter.try_acquire() is None       # burst token 2
    retry_after = limiter.try_acquire()         # bucket empty
    assert retry_after is not None
    assert 0 < retry_after <= 0.1               # 1 token at 10/s

    clock[0] += 0.1                             # one token refills
    assert limiter.try_acquire() is None


def test_try_acquire_does_not_consume_a_token_when_it_sheds():
    """A shed request must not spend budget, or a flood would starve the bucket forever."""
    clock = [0.0]
    limiter = ConnectorRateLimiter(rate_per_second=1.0, burst=1, clock=lambda: clock[0])

    assert limiter.try_acquire() is None
    for _ in range(50):
        assert limiter.try_acquire() is not None

    clock[0] += 1.0
    assert limiter.try_acquire() is None


def test_injected_clock_means_the_limiter_tests_never_sleep():
    """The clock is injectable so these assertions are exact rather than timing-dependent."""
    clock = [100.0]
    limiter = ConnectorRateLimiter(rate_per_second=2.0, burst=1, clock=lambda: clock[0])
    assert limiter.try_acquire() is None
    assert limiter.try_acquire() == pytest.approx(0.5)
    clock[0] += 0.25
    assert limiter.try_acquire() == pytest.approx(0.25)
