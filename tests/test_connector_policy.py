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
