from types import SimpleNamespace

import pytest

from xibalba_cortex.agent0_integration import Agent0Gateway, Agent0Unavailable


def test_disabled_agent0_fails_closed():
    with pytest.raises(Agent0Unavailable, match="disabled"):
        Agent0Gateway(SimpleNamespace(enabled=False, rpc_url=None))


def test_gateway_serializes_sdk_models_and_submits_without_wait(monkeypatch):
    class Handle:
        tx_hash = "0xabc"

    class Agent:
        def registerOnChain(self):
            return Handle()

        def setActive(self, value):
            return self

        def setX402Support(self, value):
            return self

        def setTrust(self, **kwargs):
            return self

    class FakeSDK:
        def __init__(self, **kwargs):
            assert kwargs["signer"] == "test-signer"

        def createAgent(self, **kwargs):
            return Agent()

    monkeypatch.setitem(__import__("sys").modules, "agent0_sdk", SimpleNamespace(SDK=FakeSDK))
    gateway = Agent0Gateway(SimpleNamespace(enabled=True, rpc_url="http://rpc", chain_id=8453, signer="test-signer"))
    result = gateway.register(name="Cortex", description="Cortex agent")
    assert result == {"submitted": True, "tx_hash": "0xabc"}
