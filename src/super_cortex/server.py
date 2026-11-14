from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server import MCPServer

from .config import SuperCortexConfig
from .memory import SuperCortex

logger = logging.getLogger(__name__)


def create_server(config: SuperCortexConfig | None = None) -> MCPServer:
    cfg = config or SuperCortexConfig()
    cortex = SuperCortex(cfg)
    server = MCPServer("super-cortex")

    @server.tool()
    async def memory_remember(
        text: str,
        epistemic_class: str = "fact",
        namespace: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        source_origin: str | None = None,
    ) -> str:
        """Store a new memory item into Supermemory semantic index and Cortex cryptographic provenance ledger."""
        res = await cortex.remember(
            text=text,
            epistemic_class=epistemic_class,
            namespace=namespace,
            metadata=metadata,
            session_id=session_id,
            source_origin=source_origin,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    async def memory_recall(memory_id: str) -> str:
        """Recall a specific memory by its ID, returning its content and epistemic status."""
        res = await cortex.recall(memory_id)
        if not res:
            return json.dumps({"error": f"Memory '{memory_id}' not found"}, indent=2)
        return json.dumps(res, indent=2)

    @server.tool()
    async def memory_hybrid_retrieve(
        query: str,
        namespace: str | None = None,
        limit: int = 10,
    ) -> str:
        """Perform semantic hybrid retrieval against Supermemory Local with cryptographic provenance metadata."""
        res = await cortex.hybrid_retrieve(query=query, namespace=namespace, limit=limit)
        return json.dumps(res, indent=2)

    @server.tool()
    async def memory_profile(
        namespace: str | None = None,
        buckets: list[str] | None = None,
    ) -> str:
        """Synthesize and retrieve profile buckets (facts, goals, interests) from Supermemory Local."""
        res = await cortex.get_profile(namespace=namespace, buckets=buckets)
        return json.dumps(res, indent=2)

    @server.tool()
    async def memory_contradict(
        target_memory_id: str,
        reason: str,
        counter_evidence: str | None = None,
    ) -> str:
        """Mark an existing memory as contradicted in the immutable provenance ledger."""
        res = await cortex.contradict(
            target_memory_id=target_memory_id,
            reason=reason,
            counter_evidence=counter_evidence,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    async def memory_supersede(
        target_memory_id: str,
        replacement_text: str,
        reason: str | None = None,
        namespace: str | None = None,
    ) -> str:
        """Supersede a prior memory with an updated replacement."""
        res = await cortex.supersede(
            target_memory_id=target_memory_id,
            replacement_text=replacement_text,
            reason=reason,
            namespace=namespace,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    async def memory_forget(
        target_memory_id: str,
        namespace: str | None = None,
    ) -> str:
        """Quarantine/forget a memory while preserving cryptographic audit trail."""
        res = await cortex.forget(target_memory_id=target_memory_id, namespace=namespace)
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_link_entities(
        subject: str,
        predicate: str,
        object: str,
        confidence: float = 1.0,
        evidence_links: list[str] | None = None,
    ) -> str:
        """Create or update a directed relationship edge between two entities."""
        res = cortex.link_entities(
            subject=subject,
            predicate=predicate,
            object_=object,
            confidence=confidence,
            evidence_links=evidence_links,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_neighbors(node: str, max_depth: int = 1) -> str:
        """Query neighboring entity edges in the knowledge graph."""
        res = cortex.get_neighbors(node=node, max_depth=max_depth)
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_record_model_exchange(
        session_id: str,
        prompt_text: str,
        response_text: str,
        tool_calls: list[dict[str, Any]] | None = None,
        context_hashes: list[str] | None = None,
    ) -> str:
        """Record an interaction turn and update the session's Merkle root."""
        res = cortex.record_exchange(
            session_id=session_id,
            prompt_text=prompt_text,
            response_text=response_text,
            tool_calls=tool_calls,
            context_hashes=context_hashes,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_verify_chain() -> str:
        """Verify the cryptographic hash-chain across all historical state transitions."""
        res = cortex.verify_chain()
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_session_merkle_root(session_id: str) -> str:
        """Compute the domain-separated Merkle root for a given session."""
        root = cortex.session_merkle_root(session_id)
        return json.dumps({"session_id": session_id, "merkle_root": root}, indent=2)

    @server.tool()
    def memory_session_distribution() -> str:
        """Retrieve temporal distribution, turn counts, and Merkle roots across all agent sessions."""
        sessions = cortex.get_session_distribution()
        return json.dumps({"session_count": len(sessions), "sessions": sessions}, indent=2)

    @server.tool()
    def memory_session_inspect(session_id: str) -> str:
        """Inspect all turns and cryptographic hashes for a specific agent session."""
        turns = cortex.get_session_turns(session_id)
        root = cortex.session_merkle_root(session_id)
        return json.dumps(
            {
                "session_id": session_id,
                "merkle_root": root,
                "turn_count": len(turns),
                "turns": turns,
            },
            indent=2,
        )

    @server.tool()
    async def supermemory_status() -> str:
        """Check Supermemory Local daemon status and active namespaces."""
        alive = await cortex.client.ping()
        namespaces = []
        if alive:
            try:
                namespaces = await cortex.client.list_namespaces()
            except Exception:
                pass
        return json.dumps(
            {
                "supermemory_local_alive": alive,
                "url": cfg.supermemory_url,
                "api_key_configured": bool(cfg.supermemory_api_key),
                "namespaces": namespaces,
            },
            indent=2,
        )

    @server.tool()
    def super_cortex_health() -> str:
        """Return full operational status of Super-Cortex."""
        chain_info = cortex.verify_chain()
        return json.dumps(
            {
                "status": "healthy",
                "default_namespace": cfg.default_namespace,
                "actor_did": cfg.actor_did,
                "db_path": str(cfg.db_path),
                "chain_valid": chain_info.get("valid", False),
                "event_count": chain_info.get("event_count", 0),
                "head_hash": chain_info.get("head_hash"),
            },
            indent=2,
        )

    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
