"""Read/write boundary for the optional Agent0 ERC-8004 SDK integration.

Agent0 is deliberately kept behind this module.  Cortex memory and Integrity
Protocol identity remain independent authorities; this adapter only exposes
ERC-8004 discovery, registration, and reputation operations.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any


class Agent0Unavailable(RuntimeError):
    """Raised when Agent0 is not installed or configured."""


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "dict"):
        return _jsonable(value.dict())
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if hasattr(value, "__dict__"):
        return _jsonable({k: v for k, v in vars(value).items() if not k.startswith("_")})
    return str(value)


class Agent0Gateway:
    """Small, explicit façade over Agent0's SDK surface."""

    def __init__(self, config: Any):
        if not getattr(config, "enabled", False):
            raise Agent0Unavailable("Agent0 integration is disabled")
        if not getattr(config, "rpc_url", None):
            raise Agent0Unavailable("XIBALBA_AGENT0_RPC_URL is required")
        try:
            from agent0_sdk import SDK
        except ImportError as exc:  # pragma: no cover - exercised in minimal installs
            raise Agent0Unavailable("install Cortex with the agent0 extra") from exc

        kwargs: dict[str, Any] = {
            "chainId": config.chain_id,
            "rpcUrl": config.rpc_url,
            "signer": config.signer,
        }
        for key in ("subgraph_url", "ipfs", "pinata_jwt", "filecoin_private_key"):
            value = getattr(config, key, None)
            if value:
                kwargs[{"subgraph_url": "subgraphOverrides", "pinata_jwt": "pinataJwt", "filecoin_private_key": "filecoinPrivateKey"}.get(key, key)] = ({config.chain_id: value} if key == "subgraph_url" else value)
        self.sdk = SDK(**kwargs)

    @staticmethod
    def _tx(handle: Any, *, wait: bool = False, timeout: int = 120) -> dict[str, Any]:
        result: dict[str, Any] = {"submitted": True, "tx_hash": str(handle.tx_hash)}
        if wait:
            mined = handle.wait_confirmed(timeout=timeout)
            result.update({"confirmed": True, "receipt": _jsonable(mined.receipt), "result": _jsonable(mined.result)})
        return result

    def register(self, *, name: str, description: str, image: str | None = None,
                 registration_mode: str = "onchain", endpoints: dict[str, str] | None = None,
                 skills: list[str] | None = None, domains: list[str] | None = None,
                 trust: dict[str, bool] | None = None, metadata: dict[str, Any] | None = None,
                 active: bool = True, x402_support: bool = False, ens: str | None = None,
                 wait: bool = False, timeout: int = 120) -> dict[str, Any]:
        agent = self.sdk.createAgent(name=name, description=description, image=image)
        endpoints = endpoints or {}
        if endpoints.get("mcp"):
            agent.setMCP(endpoints["mcp"])
        if endpoints.get("a2a"):
            agent.setA2A(endpoints["a2a"])
        for skill in skills or []:
            agent.addSkill(skill, validate_oasf=True)
        for domain in domains or []:
            agent.addDomain(domain, validate_oasf=True)
        trust = trust or {"reputation": True}
        agent.setTrust(**{k: bool(v) for k, v in trust.items() if k in {"reputation", "cryptoEconomic", "teeAttestation"}})
        if metadata:
            agent.setMetadata(metadata)
        agent.setActive(active)
        agent.setX402Support(x402_support)
        if ens:
            agent.setENS(ens)
        if registration_mode == "onchain":
            handle = agent.registerOnChain()
        elif registration_mode == "ipfs":
            handle = agent.registerIPFS()
        else:
            raise ValueError("registration_mode must be 'onchain' or 'ipfs'")
        return self._tx(handle, wait=wait, timeout=timeout)
    def search_agents(self, filters: dict[str, Any] | None = None, options: dict[str, Any] | None = None) -> list[Any]:
        return _jsonable(self.sdk.searchAgents(filters=filters or {}, options=options or {}))

    def agent(self, agent_id: str, *, full: bool = False) -> Any:
        value = self.sdk.loadAgent(agent_id) if full else self.sdk.getAgent(agent_id)
        return _jsonable(value)

    def reputation(self, agent_id: str) -> dict[str, Any]:
        return _jsonable(self.sdk.getReputationSummary(agent_id))

    def feedback(self, **kwargs: Any) -> list[Any]:
        return _jsonable(self.sdk.searchFeedback(**kwargs))

    def owner(self, agent_id: str) -> str:
        return str(self.sdk.getAgentOwner(agent_id))

    def prepare_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _jsonable(self.sdk.prepareFeedbackFile(payload))

    def give_feedback(self, *, agent_id: str, value: int | float | str, tag1: str | None = None,
                      tag2: str | None = None, endpoint: str | None = None,
                      feedback_file: dict[str, Any] | None = None, wait: bool = False,
                      timeout: int = 120) -> dict[str, Any]:
        handle = self.sdk.giveFeedback(agentId=agent_id, value=value, tag1=tag1, tag2=tag2,
                                       endpoint=endpoint, feedbackFile=feedback_file)
        return self._tx(handle, wait=wait, timeout=timeout)
