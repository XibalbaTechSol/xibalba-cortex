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


def test_api_agent0_search_fallback_and_filters(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "provenance.db",
        actor_did=SAMPLE_DID,
    )
    app = create_app(config=cfg)
    client = TestClient(app)

    # 1. Default search returns registry
    resp = client.get("/api/agent0/search")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert data["total"] >= 1
    assert any(a["name"] == "Super-Cortex Sovereign Memory Agent" for a in data["agents"])

    # 2. Filter by specific chain
    resp = client.post(
        "/api/agent0/search",
        json={"chains": [80002], "filters": {"equals": {"a2a": True}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all(a["chainId"] == 80002 for a in data["agents"])

    # 3. Filter by query
    resp = client.post(
        "/api/agent0/search",
        json={"query": "quant", "sort": "reputation"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["agents"]) >= 1
    assert "Quant" in data["agents"][0]["name"]


def test_api_agent0_talk_a2a_messenger_protocol(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "provenance.db",
        actor_did=SAMPLE_DID,
    )
    app = create_app(config=cfg)
    client = TestClient(app)

    # 1. Validation error on empty message
    resp = client.post("/api/agent0/talk", json={"message": ""})
    assert resp.status_code == 400

    # 2. Audit prompt generates verified response matching messenger.py
    resp = client.post(
        "/api/agent0/talk",
        json={
            "agent_id": "1",
            "message": "Audit Integrity DID & Sovereign Backlink",
            "context_id": "ctx-test-123",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "message"
    assert data["role"] == "agent"
    assert data["context_id"] == "ctx-test-123"
    assert len(data["parts"]) >= 2
    assert data["parts"][0]["kind"] == "text"
    assert "Integrity Audit" in data["parts"][0]["text"]
    assert data["parts"][1]["kind"] == "data"
    assert data["parts"][1]["data"]["walletConfined"] is True

    # 3. PID prompt generates telemetry
    resp = client.post(
        "/api/agent0/talk",
        json={
            "agent_id": "2",
            "message": "Run PID Quant Controller Health Check",
            "context_id": "ctx-test-456",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "telemetry nominal" in data["parts"][0]["text"]
    assert data["parts"][1]["data"]["status"] == "healthy"


def test_api_agent0_remember_anchors_to_cortex(tmp_path):
    cfg = SuperCortexConfig(
        db_path=tmp_path / "provenance.db",
        actor_did=SAMPLE_DID,
    )
    app = create_app(config=cfg)
    client = TestClient(app)

    resp = client.post(
        "/api/agent0/remember",
        json={
            "agent_id": "1",
            "context_id": "ctx-999",
            "text": "A2A dialogue turn: Agent 1 confirmed DID backlink verified.",
            "scope": "agent0-a2a",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "memory_id" in data
    assert data["scope"] == "agent0-a2a"
    assert data["agent_id"] == "agent0:1"
    assert "event_hash" in data
    assert "content_hash" in data
