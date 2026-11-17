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
        epistemic_class: str | None = None,
        scope: str | None = None,
        agent_id: str | None = None,
        namespace: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        source_origin: str | None = None,
    ) -> str:
        """Store a new memory item into Supermemory semantic index and Cortex cryptographic provenance ledger.

        Automatically performs cognitive extraction:
        - Epistemic classification (rule, fact, decision, inference, belief, goal)
        - PARA categorization (project, area, resource, archive)
        - Entity triples extraction ((subject, predicate, object))
        - Scope isolation (e.g. 'shared' or 'agent:<id>')
        """
        import os
        eff_agent = agent_id or os.getenv("SUPER_CORTEX_AGENT_ID") or os.getenv("AGENT_ID")
        eff_scope = scope
        if not eff_scope:
            eff_scope = f"agent:{eff_agent}" if eff_agent else "shared"
        elif eff_scope.startswith("agent:") and not eff_agent:
            eff_agent = eff_scope.split(":", 1)[1]

        res = await cortex.remember(
            text=text,
            epistemic_class=epistemic_class,
            scope=eff_scope,
            agent_id=eff_agent,
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
        scope: str | None = None,
        agent_id: str | None = None,
        namespace: str | None = None,
        limit: int = 10,
    ) -> str:
        """Perform semantic hybrid retrieval against Supermemory Local with cryptographic provenance metadata."""
        res = await cortex.hybrid_retrieve(
            query=query,
            scope=scope,
            agent_id=agent_id,
            namespace=namespace,
            limit=limit,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_scopes_list() -> str:
        """List all registered memory scopes (Shared Memory Fabric & Single-Agent scopes)."""
        res = cortex.list_scopes()
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_scope_create(
        scope_id: str,
        name: str,
        scope_type: str = "single_agent",
        agent_id: str | None = None,
        description: str = "",
    ) -> str:
        """Create a new memory scope ('shared' or 'single_agent' tied to an agent_id)."""
        res = cortex.create_scope(
            scope_id=scope_id,
            name=name,
            scope_type=scope_type,
            agent_id=agent_id,
            description=description,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_agents_list() -> str:
        """List all registered AI agents in the fleet with their default memory scopes and activity statuses."""
        res = cortex.list_agents()
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_agent_register(
        agent_id: str,
        name: str,
        default_scope_id: str = "shared",
        client_type: str = "custom",
    ) -> str:
        """Register or update an AI agent connected to Super-Cortex via MCP."""
        res = cortex.register_agent(
            agent_id=agent_id,
            name=name,
            default_scope_id=default_scope_id,
            client_type=client_type,
        )
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
        thinking_text: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        context_hashes: list[str] | None = None,
        agent_id: str | None = None,
        scope: str | None = None,
    ) -> str:
        """Record an interaction turn and update the session's Merkle root."""
        res = cortex.record_exchange(
            session_id=session_id,
            prompt_text=prompt_text,
            response_text=response_text,
            thinking_text=thinking_text,
            tool_calls=tool_calls,
            context_hashes=context_hashes,
            agent_id=agent_id,
            scope_id=scope,
        )
        if thinking_text:
            res["graph_thought_id"] = f"thought_{res.get('exchange_id', '')}"
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_record_thought(
        session_id: str,
        thought_text: str,
        step_phase: str = "planning",
        prompt_context: str | None = None,
        agent_id: str | None = None,
        scope: str | None = None,
    ) -> str:
        """Record an agent's real-time internal chain-of-thought (COT), deliberation, or guardrail check into Super-Cortex and dispatch it to the main graph."""
        res = cortex.record_exchange(
            session_id=session_id,
            prompt_text=prompt_context or "Internal cognitive deliberation",
            response_text="Thought anchored to cognitive ledger.",
            thinking_text=thought_text,
            tool_calls=[],
            agent_id=agent_id,
            scope_id=scope,
        )
        exchange_id = res.get("exchange_id", "")
        return json.dumps({
            "status": "recorded",
            "session_id": session_id,
            "exchange_id": exchange_id,
            "step_phase": step_phase,
            "turn_hash": res.get("turn_hash"),
            "session_merkle_root": res.get("session_merkle_root"),
            "agent_id": res.get("agent_id"),
            "scope_id": res.get("scope_id"),
            "graph_node_id": f"thought_{exchange_id}",
            "graph_dispatched": True,
        }, indent=2)

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
    def memory_session_rebuild(session_id: str, format: str = "json") -> str:
        """Reconstruct the complete chronological session timeline between user and agent.
        
        Unfolds every turn into sequential atomic steps with exact timestamps, user prompts,
        agent reasoning (chain-of-thought), tool executions (commands, file operations, MCP calls),
        synthesis responses, and cryptographic Merkle leaf anchors.
        
        Args:
            session_id: The session ID to reconstruct.
            format: 'json' for full structured audit manifest, or 'markdown' for human-readable audit report.
        """
        rebuilt = cortex.rebuild_session(session_id)
        if format.lower() == "markdown":
            return rebuilt.get("markdown_transcript", "")
        return json.dumps(rebuilt, indent=2)

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
