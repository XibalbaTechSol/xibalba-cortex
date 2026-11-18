"""Modular Agent0 / ERC-8004 Public Passport Bridge for Super-Cortex.

Agent0 (ERC-8004) is strictly an optional external discovery and payment-directory
projection (Tier 2). Super-Cortex memory provenance and Integrity Protocol Ed25519
DIDs (`did:integrity:<sha256(pubkey)>`) + policy-confined `SovereignAgent` actors
remain the sole authoritative identity and enforcement primitives.

This module:
1. Generates canonical ERC-8004 `registration-v1` JSON cards carrying the
   cryptographic two-way `DID` service backlink (`services[name=DID]`) and CAIP-10
   registry backlink (`eip155:<chain_id>:<registry>`), matching the Integrity
   Oracle's `erc8004::validate_registration` rule.
2. Binds the agent's policy-confined `SovereignAgent` contract address as the
   ERC-8004 `agentWallet` metadata when provided, preventing unconfined EOA exposure.
3. Provides an optional `Agent0Gateway` facade around `agent0_sdk` when installed,
   failing closed (`Agent0Unavailable`) when disabled or unconfigured.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Optional

REGISTRATION_TYPE = "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"
BASE_SEPOLIA_CHAIN_ID = 84532
BASE_SEPOLIA_ERC8004_REGISTRY = "0x8004A818BFB912233c491871b3d84c89A494BD9e"
_DID_PREFIX = "did:integrity:"


class Agent0Unavailable(RuntimeError):
    """Raised when the optional Agent0 SDK is disabled, unconfigured, or not installed."""


@dataclass(frozen=True)
class Agent0Config:
    enabled: bool = False
    chain_id: int = BASE_SEPOLIA_CHAIN_ID
    rpc_url: Optional[str] = None
    registry_address: str = BASE_SEPOLIA_ERC8004_REGISTRY
    subgraph_url: Optional[str] = None
    signer: Optional[str] = None
    ipfs: Optional[str] = None
    pinata_jwt: Optional[str] = None
    filecoin_private_key: Optional[str] = None


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


def caip10_registry(chain_id: int, registry_address: str) -> str:
    """Return the CAIP-10 identifier (`eip155:<chain_id>:<lowercase_registry>`)."""
    if chain_id <= 0:
        raise ValueError(f"chain_id must be positive, got {chain_id}")
    addr = registry_address.strip()
    if not (addr.startswith("0x") and len(addr) == 42):
        raise ValueError(f"invalid EVM registry address: {registry_address!r}")
    return f"eip155:{chain_id}:{addr.lower()}"


def build_agent0_passport_card(
    *,
    integrity_did: str,
    name: str,
    description: str,
    image: str = "https://integrity.xibalba.solutions/agent-avatar.png",
    chain_id: int = BASE_SEPOLIA_CHAIN_ID,
    registry_address: str = BASE_SEPOLIA_ERC8004_REGISTRY,
    token_id: int | str = 0,
    sovereign_actor_wallet: Optional[str] = None,
    mcp_endpoint: Optional[str] = None,
    a2a_endpoint: Optional[str] = None,
    a2a_version: str = "0.3.0",
    x402_support: bool = False,
    active: bool = True,
    supported_trust: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build a canonical ERC-8004 registration-v1 card with a two-way Integrity DID backlink."""
    did = integrity_did.strip()
    if not did.startswith(_DID_PREFIX) or len(did) <= len(_DID_PREFIX):
        raise ValueError(f"integrity_did must start with {_DID_PREFIX!r}")
    if not name.strip() or not description.strip() or not image.strip():
        raise ValueError("name, description, and image are required")

    services: list[dict[str, Any]] = [{"name": "DID", "endpoint": did}]
    if mcp_endpoint and mcp_endpoint.strip():
        services.append({"name": "MCP", "endpoint": mcp_endpoint.strip()})
    if a2a_endpoint and a2a_endpoint.strip():
        a2a_svc: dict[str, Any] = {"name": "A2A", "endpoint": a2a_endpoint.strip()}
        if a2a_version and a2a_version.strip():
            a2a_svc["version"] = a2a_version.strip()
        services.append(a2a_svc)

    caip10 = caip10_registry(chain_id, registry_address)
    tok: int | str = (
        int(token_id)
        if isinstance(token_id, int) or (isinstance(token_id, str) and token_id.isdigit())
        else str(token_id)
    )

    document: dict[str, Any] = {
        "type": REGISTRATION_TYPE,
        "name": name.strip(),
        "description": description.strip(),
        "image": image.strip(),
        "services": services,
        "x402Support": bool(x402_support),
        "active": bool(active),
        "registrations": [
            {
                "agentId": tok,
                "agentRegistry": caip10,
            }
        ],
        "supportedTrust": list(supported_trust) if supported_trust is not None else ["reputation", "crypto-economic"],
    }

    raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sha256_hex = hashlib.sha256(raw).hexdigest()
    data_uri = f"data:application/json;base64,{base64.b64encode(raw).decode('ascii')}"

    metadata: dict[str, str] = {"integrityDid": did}
    if sovereign_actor_wallet and sovereign_actor_wallet.strip():
        wallet_addr = sovereign_actor_wallet.strip()
        if not (wallet_addr.startswith("0x") and len(wallet_addr) == 42):
            raise ValueError(f"sovereign_actor_wallet must be a 0x-prefixed 20-byte EVM address, got {wallet_addr!r}")
        metadata["agentWallet"] = wallet_addr
        metadata["sovereignActor"] = wallet_addr

    return {
        "integrity_did": did,
        "caip10_registry": caip10,
        "token_id": str(tok),
        "sovereign_actor_wallet": metadata.get("sovereignActor"),
        "wallet_confined": "sovereignActor" in metadata,
        "sha256": sha256_hex,
        "data_uri": data_uri,
        "metadata": metadata,
        "document": document,
    }


class Agent0Gateway:
    """Explicit, modular facade over Agent0's ERC-8004 SDK surface with Integrity DID & SovereignAgent binding."""

    def __init__(self, config: Any):
        if not getattr(config, "enabled", False):
            raise Agent0Unavailable("Agent0 integration is disabled")
        if not getattr(config, "rpc_url", None):
            raise Agent0Unavailable("XIBALBA_AGENT0_RPC_URL is required")
        try:
            from agent0_sdk import SDK
        except ImportError as exc:
            raise Agent0Unavailable("install Super-Cortex with the agent0 extra") from exc

        self.chain_id = int(getattr(config, "chain_id", BASE_SEPOLIA_CHAIN_ID))
        self.registry_address = str(
            getattr(config, "registry_address", BASE_SEPOLIA_ERC8004_REGISTRY)
        )
        kwargs: dict[str, Any] = {
            "chainId": self.chain_id,
            "rpcUrl": config.rpc_url,
            "signer": getattr(config, "signer", None),
        }
        for key in ("subgraph_url", "ipfs", "pinata_jwt", "filecoin_private_key"):
            value = getattr(config, key, None)
            if value:
                mapped_key = {
                    "subgraph_url": "subgraphOverrides",
                    "pinata_jwt": "pinataJwt",
                    "filecoin_private_key": "filecoinPrivateKey",
                }.get(key, key)
                kwargs[mapped_key] = {self.chain_id: value} if key == "subgraph_url" else value
        self.sdk = SDK(**kwargs)

    @staticmethod
    def _tx(handle: Any, *, wait: bool = False, timeout: int = 120) -> dict[str, Any]:
        result: dict[str, Any] = {"submitted": True, "tx_hash": str(handle.tx_hash)}
        if wait:
            mined = handle.wait_confirmed(timeout=timeout)
            result.update(
                {
                    "confirmed": True,
                    "receipt": _jsonable(mined.receipt),
                    "result": _jsonable(mined.result),
                }
            )
        return result

    def register(
        self,
        *,
        name: str,
        description: str,
        integrity_did: Optional[str] = None,
        sovereign_actor_wallet: Optional[str] = None,
        image: Optional[str] = None,
        registration_mode: str = "onchain",
        endpoints: Optional[dict[str, Optional[str]]] = None,
        skills: Optional[list[str]] = None,
        domains: Optional[list[str]] = None,
        trust: Optional[dict[str, bool]] = None,
        metadata: Optional[dict[str, Any]] = None,
        active: bool = True,
        x402_support: bool = False,
        ens: Optional[str] = None,
        wait: bool = False,
        timeout: int = 120,
    ) -> dict[str, Any]:
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
        agent.setTrust(
            **{
                k: bool(v)
                for k, v in trust.items()
                if k in {"reputation", "cryptoEconomic", "teeAttestation"}
            }
        )

        merged_metadata: dict[str, Any] = dict(metadata or {})
        if integrity_did:
            if not integrity_did.startswith(_DID_PREFIX):
                raise ValueError(f"integrity_did must start with {_DID_PREFIX!r}")
            merged_metadata["integrityDid"] = integrity_did
            if hasattr(agent, "addService"):
                agent.addService("DID", integrity_did)
        if sovereign_actor_wallet:
            merged_metadata["agentWallet"] = sovereign_actor_wallet
            merged_metadata["sovereignActor"] = sovereign_actor_wallet
            if hasattr(agent, "setAgentWallet"):
                agent.setAgentWallet(sovereign_actor_wallet)

        if merged_metadata:
            agent.setMetadata(merged_metadata)
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
        tx_res = self._tx(handle, wait=wait, timeout=timeout)
        if integrity_did:
            tx_res["integrity_did"] = integrity_did
        if sovereign_actor_wallet:
            tx_res["sovereign_actor_wallet"] = sovereign_actor_wallet
            tx_res["wallet_confined"] = True
        return tx_res

    def search_agents(
        self, filters: Optional[dict[str, Any]] = None, options: Optional[dict[str, Any]] = None
    ) -> list[Any]:
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

    def give_feedback(
        self,
        *,
        agent_id: str,
        value: int | float | str,
        tag1: Optional[str] = None,
        tag2: Optional[str] = None,
        endpoint: Optional[str] = None,
        feedback_file: Optional[dict[str, Any]] = None,
        wait: bool = False,
        timeout: int = 120,
    ) -> dict[str, Any]:
        handle = self.sdk.giveFeedback(
            agentId=agent_id,
            value=value,
            tag1=tag1,
            tag2=tag2,
            endpoint=endpoint,
            feedbackFile=feedback_file,
        )
        return self._tx(handle, wait=wait, timeout=timeout)
