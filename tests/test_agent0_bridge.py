"""Tests for the modular Agent0 / ERC-8004 Public Passport Bridge in Super-Cortex."""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from super_cortex.agent0_bridge import (
    Agent0Gateway,
    Agent0Unavailable,
    BASE_SEPOLIA_CHAIN_ID,
    BASE_SEPOLIA_ERC8004_REGISTRY,
    build_agent0_passport_card,
    caip10_registry,
)
from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig


SAMPLE_DID = "did:integrity:68fed1331613937555a59398223e8e87520a87dd0305aac4fd7ecdc32a14a861"
SAMPLE_SOVEREIGN_ACTOR = "0x360E2a5611111111111111111111111111111111"


def test_build_agent0_passport_card_enforces_two_way_did_and_confined_wallet():
    card = build_agent0_passport_card(
        integrity_did=SAMPLE_DID,
        name="Xibalba Super-Cortex",
        description="Policy-confined agent memory fabric",
        token_id=12,
        sovereign_actor_wallet=SAMPLE_SOVEREIGN_ACTOR,
        mcp_endpoint="https://cortex.xibalba.solutions/mcp",
        a2a_endpoint="https://cortex.xibalba.solutions/.well-known/agent-card.json",
        x402_support=True,
    )
    assert card["integrity_did"] == SAMPLE_DID
    assert card["wallet_confined"] is True
    assert card["sovereign_actor_wallet"] == SAMPLE_SOVEREIGN_ACTOR
    assert card["caip10_registry"] == f"eip155:{BASE_SEPOLIA_CHAIN_ID}:{BASE_SEPOLIA_ERC8004_REGISTRY.lower()}"
    assert card["metadata"]["integrityDid"] == SAMPLE_DID
    assert card["metadata"]["agentWallet"] == SAMPLE_SOVEREIGN_ACTOR
    assert card["metadata"]["sovereignActor"] == SAMPLE_SOVEREIGN_ACTOR

    doc = card["document"]
    assert doc["type"] == "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"
    assert {"name": "DID", "endpoint": SAMPLE_DID} in doc["services"]
    assert doc["registrations"] == [
        {
            "agentId": 12,
            "agentRegistry": f"eip155:{BASE_SEPOLIA_CHAIN_ID}:{BASE_SEPOLIA_ERC8004_REGISTRY.lower()}",
        }
    ]
    decoded = json.loads(base64.b64decode(card["data_uri"].split(",", 1)[1]))
    assert decoded == doc


def test_build_agent0_passport_card_rejects_invalid_did_or_wallet():
    with pytest.raises(ValueError, match="did:integrity:"):
        build_agent0_passport_card(
            integrity_did="did:key:123",
            name="Bad DID",
            description="Invalid",
        )
    with pytest.raises(ValueError, match="20-byte EVM address"):
        build_agent0_passport_card(
            integrity_did=SAMPLE_DID,
            name="Bad Wallet",
            description="Invalid",
            sovereign_actor_wallet="not-an-address",
        )


def test_agent0_gateway_fails_closed_when_disabled():
    with pytest.raises(Agent0Unavailable, match="disabled"):
        Agent0Gateway(SimpleNamespace(enabled=False, rpc_url=None))


def test_agent0_gateway_binds_integrity_did_and_sovereign_actor(monkeypatch):
    recorded: dict[str, object] = {}

    class Handle:
        tx_hash = "0xdeadbeef"

    class FakeAgent:
        def setMCP(self, val):
            recorded["mcp"] = val

        def setA2A(self, val):
            recorded["a2a"] = val

        def addService(self, name, endpoint):
            recorded.setdefault("services", []).append((name, endpoint))

        def setAgentWallet(self, wallet):
            recorded["agent_wallet"] = wallet

        def setMetadata(self, meta):
            recorded["metadata"] = meta

        def setTrust(self, **kwargs):
            recorded["trust"] = kwargs

        def setActive(self, active):
            recorded["active"] = active

        def setX402Support(self, x402):
            recorded["x402"] = x402

        def registerOnChain(self):
            return Handle()

    class FakeSDK:
        def __init__(self, **kwargs):
            recorded["sdk_kwargs"] = kwargs

        def createAgent(self, **kwargs):
            return FakeAgent()

    monkeypatch.setitem(__import__("sys").modules, "agent0_sdk", SimpleNamespace(SDK=FakeSDK))
    gw = Agent0Gateway(
        SimpleNamespace(
            enabled=True,
            rpc_url="https://sepolia.base.org",
            chain_id=84532,
            signer="0x1111",
        )
    )
    res = gw.register(
        name="Xibalba Confined Agent",
        description="Tier 2 Passport",
        integrity_did=SAMPLE_DID,
        sovereign_actor_wallet=SAMPLE_SOVEREIGN_ACTOR,
        x402_support=True,
    )
    assert res["submitted"] is True
    assert res["tx_hash"] == "0xdeadbeef"
    assert res["integrity_did"] == SAMPLE_DID
    assert res["sovereign_actor_wallet"] == SAMPLE_SOVEREIGN_ACTOR
    assert res["wallet_confined"] is True
    assert recorded["services"] == [("DID", SAMPLE_DID)]
    assert recorded["agent_wallet"] == SAMPLE_SOVEREIGN_ACTOR
    assert recorded["metadata"] == {
        "integrityDid": SAMPLE_DID,
        "agentWallet": SAMPLE_SOVEREIGN_ACTOR,
        "sovereignActor": SAMPLE_SOVEREIGN_ACTOR,
    }


def test_api_agent0_passport_endpoint(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "provenance.db",
        actor_did=SAMPLE_DID,
    )
    app = create_app(config=cfg)
    client = TestClient(app)

    resp = client.post(
        "/api/agent0/passport",
        json={
            "name": "Hermes Prime",
            "description": "Confined SovereignAgent with ERC-8004 Passport",
            "integrity_did": SAMPLE_DID,
            "sovereign_actor_wallet": SAMPLE_SOVEREIGN_ACTOR,
            "token_id": 77,
            "x402_support": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["integrity_did"] == SAMPLE_DID
    assert body["wallet_confined"] is True
    assert body["sovereign_actor_wallet"] == SAMPLE_SOVEREIGN_ACTOR
    assert body["document"]["registrations"][0]["agentId"] == 77
