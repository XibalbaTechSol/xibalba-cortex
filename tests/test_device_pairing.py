"""Tests for device pairing and authorization engine."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from xibalba_cortex import accounts
from xibalba_cortex.device_pairing import (
    create_pairing_request,
    get_pairing_request,
    approve_pairing_request,
    poll_pairing_status,
)
from xibalba_cortex.ingest_tokens import verify_token_record


@pytest.fixture
def identity_home(tmp_path):
    accounts._ensure_schema(tmp_path)
    return tmp_path


def test_pairing_lifecycle_success(identity_home):
    req = create_pairing_request(
        identity_home,
        device_id="device-macbook-1",
        device_name="Alice MacBook Pro",
        agent_did="did:integrity:1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
        agent_name="claude-desktop",
        callback_url="http://127.0.0.1:8435/callback",
    )

    device_code = req["device_code"]
    user_code = req["user_code"]
    assert device_code and user_code
    assert req["expires_in"] == 900

    # Inspect by user code
    info = get_pairing_request(identity_home, user_code)
    assert info is not None
    assert info["device_id"] == "device-macbook-1"
    assert info["device_name"] == "Alice MacBook Pro"
    assert info["status"] == "pending"

    # Poll before approval
    poll_pending = poll_pairing_status(identity_home, device_code)
    assert poll_pending["status"] == "pending"

    # Approve
    tenant_id = "t-mock-tenant-123"
    account_id = "acc-mock-456"
    mock_service = MagicMock()

    approval = approve_pairing_request(
        identity_home,
        user_code,
        account_id=account_id,
        tenant_id=tenant_id,
        service_control=mock_service,
    )
    assert approval["token"]
    assert approval["callback_url"] == "http://127.0.0.1:8435/callback"
    assert approval["device_id"] == "device-macbook-1"

    # Verify the issued token is active and valid for tenant & agent DID
    record = verify_token_record(identity_home, approval["token"])
    assert record is not None
    assert record["profile_id"] == tenant_id
    assert "memory:read" in record["scopes"]
    assert "memory:write" in record["scopes"]
    assert "did:integrity:1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff" in record["agent_ids"]

    # Poll after approval
    poll_approved = poll_pairing_status(identity_home, device_code)
    assert poll_approved["status"] == "approved"
    assert poll_approved["token"] == approval["token"]
    assert poll_approved["tenant_id"] == tenant_id


def test_pairing_expired(identity_home):
    req = create_pairing_request(
        identity_home,
        device_id="dev-2",
        device_name="Old Device",
        agent_did="did:integrity:00001111",
        ttl_seconds=0,  # Expire immediately
    )
    time.sleep(0.01)

    info = get_pairing_request(identity_home, req["device_code"])
    assert info["status"] == "expired"

    with pytest.raises(ValueError, match="expired"):
        approve_pairing_request(
            identity_home,
            req["device_code"],
            account_id="acc-1",
            tenant_id="t-1",
        )
