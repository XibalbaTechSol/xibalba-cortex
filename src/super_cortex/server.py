from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
import secrets

from mcp.server import MCPServer

from .agent0_bridge import (
    BASE_SEPOLIA_CHAIN_ID,
    BASE_SEPOLIA_ERC8004_REGISTRY,
    build_agent0_passport_card,
)
from .config import SuperCortexConfig
from .hierarchical_graphrag import detect_hierarchical_communities, query_hierarchical_graphrag
from .managed import ManagedConfig, ManagedControl
from .memory import SuperCortex
from .models import LifecycleStatus
from .truth_maintenance import propagate_invalidation, verify_belief_justification
from .zkp import create_zkp_invariant_proof, verify_zkp_invariant_proof

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

    def _extraction_namespace(namespace: str | None) -> str:
        if not namespace:
            return cfg.default_namespace
        return cfg.shared_namespace if namespace == "shared" else namespace

    @server.tool()
    async def memory_extraction_claim(namespace: str | None = None, limit: int = 5) -> str:
        """Extract memories with YOUR OWN model instead of the engine's paid/free-tier extractor.

        Leases up to `limit` (max 10) pending documents from `namespace` (default: this agent's
        namespace; "shared" for the shared one) for 15 minutes, and returns the extractor
        `instructions`, the `prompt` (documents D1..Dn, related memories M1..Mn) and the
        `responseSchema`. Follow the instructions on the prompt yourself, then call
        memory_extraction_submit with the claimId. Every memory needs a quote copied exactly from
        its document: the engine stores only quotes it can find. Returns claimId=null when there is
        nothing to do. Needs the SuperCortex engine backend.
        """
        res = await cortex.client.claim_extraction(_extraction_namespace(namespace), limit)
        return json.dumps(res, indent=2)

    @server.tool()
    async def memory_extraction_submit(
        claim_id: str,
        documents: list[dict[str, Any]] | None = None,
        proposals: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> str:
        """Submit the memories you extracted for a claim from memory_extraction_claim.

        Pass `documents` as in the claim's responseSchema ([{"doc": "D1", "memories": [{"memory",
        "quote", "certainty", "inference", "kind", "updates"}]}]) or a flat `proposals` list where
        each memory has its own "doc". `model` names the model that did the work (stored as
        session:<model> on each memory). Returns what was stored, merged, superseded, or rejected
        as ungrounded. Submit an empty list to mark documents with nothing worth keeping as done.
        """
        import os

        used = model or os.getenv("SUPER_CORTEX_SESSION_MODEL") or os.getenv("SUPER_CORTEX_AGENT_ID") or "agent"
        res = await cortex.client.submit_extraction(claim_id, used, documents=documents, proposals=proposals)
        return json.dumps(res, indent=2)

    @server.tool()
    async def memory_extraction_release(claim_id: str) -> str:
        """Give an unfinished claim back so its documents return to the extraction queue."""
        res = await cortex.client.release_extraction(claim_id)
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

    @server.tool()
    def agent0_prepare_passport(
        name: str,
        description: str,
        integrity_did: str | None = None,
        sovereign_actor_wallet: str | None = None,
        token_id: int | str = 0,
        chain_id: int = BASE_SEPOLIA_CHAIN_ID,
        registry_address: str = BASE_SEPOLIA_ERC8004_REGISTRY,
        mcp_endpoint: str | None = None,
        a2a_endpoint: str | None = None,
        x402_support: bool = False,
    ) -> str:
        """Build a canonical ERC-8004 / Agent0 Public Passport card with a cryptographic two-way Integrity DID backlink and policy-confined SovereignAgent actor wallet."""
        did = (integrity_did or cfg.actor_did).strip()
        card = build_agent0_passport_card(
            integrity_did=did,
            name=name,
            description=description,
            chain_id=chain_id,
            registry_address=registry_address,
            token_id=token_id,
            sovereign_actor_wallet=sovereign_actor_wallet,
            mcp_endpoint=mcp_endpoint,
            a2a_endpoint=a2a_endpoint,
            x402_support=x402_support,
        )
        return json.dumps(card, indent=2)

    @server.tool()
    def memory_tms_invalidate(memory_id: str, action: str = "contradicted") -> str:
        """Trigger Justification-based Truth Maintenance System (JTMS) recursive invalidation down dependency DAG."""
        mem_dicts = [m.model_dump() if hasattr(m, "model_dump") else m for m in cortex.store.list_memories()]
        rel_dicts = cortex.store.list_relations()
        res = propagate_invalidation(
            root_id=memory_id,
            action=action,
            memories=mem_dicts,
            relations=rel_dicts,
        )
        for aff in res.get("affected_memories", []):
            st = LifecycleStatus.QUARANTINED if action == "contradicted" else LifecycleStatus.SUPERSEDED
            cortex.store.update_memory_status(aff["memory_id"], st)
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_tms_justification(memory_id: str) -> str:
        """Verify whether a target belief/inference is well-founded and supported by active non-refuted premise memories."""
        mem_dicts = [m.model_dump() if hasattr(m, "model_dump") else m for m in cortex.store.list_memories()]
        rel_dicts = cortex.store.list_relations()
        res = verify_belief_justification(
            memory_id=memory_id,
            memories=mem_dicts,
            relations=rel_dicts,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_graphrag_communities(max_communities: int = 10, max_nodes: int = 200) -> str:
        """Run Hierarchical Macro-GraphRAG community detection and synthesize Level-1 macro-node abstractions."""
        mem_dicts = [m.model_dump() if hasattr(m, "model_dump") else m for m in cortex.store.list_memories()]
        rel_dicts = cortex.store.list_relations()
        res = detect_hierarchical_communities(
            memories=mem_dicts,
            relations=rel_dicts,
            max_communities=max_communities,
            max_nodes=max_nodes,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_graphrag_query(query: str, max_communities: int = 5, top_k_evidence: int = 10) -> str:
        """Execute multi-scale Macro-GraphRAG contextual synthesis across macro community summaries and micro ground-truth evidence."""
        mem_dicts = [m.model_dump() if hasattr(m, "model_dump") else m for m in cortex.store.list_memories()]
        rel_dicts = cortex.store.list_relations()
        res = query_hierarchical_graphrag(
            query=query,
            memories=mem_dicts,
            relations=rel_dicts,
            max_communities=max_communities,
            top_k_evidence=top_k_evidence,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    def memory_zkp_prove(statement: str, memory_id: str | None = None) -> str:
        """Generate a Non-Interactive Zero-Knowledge Proof (NIZKP) commitment and challenge response for an epistemic invariant."""
        salt = secrets.token_hex(16)
        verifier_nonce = secrets.token_hex(8)
        content = statement
        if memory_id:
            m = cortex.store.get_memory(memory_id)
            if m:
                content = m.text
        proof = create_zkp_invariant_proof(
            statement=statement,
            private_payload=content,
            salt=salt,
            verifier_nonce=verifier_nonce,
        )
        return json.dumps(proof, indent=2)

    @server.tool()
    def memory_zkp_verify(
        statement: str,
        commitment: str,
        proof_hash: str,
        verifier_nonce: str,
        blind_response: str,
    ) -> str:
        """Cryptographically verify a Zero-Knowledge Proof invariant commitment and Fiat-Shamir challenge response."""
        res = verify_zkp_invariant_proof(
            statement=statement,
            commitment=commitment,
            proof_hash=proof_hash,
            verifier_nonce=verifier_nonce,
            blind_response=blind_response,
        )
        return json.dumps(res, indent=2)

    @server.tool()
    def workspace_members_list(tenant_id: str | None = None) -> str:
        """List all team members and their RBAC roles (owner, admin, member, auditor, agent) in the workspace."""
        m_cfg = ManagedConfig.from_env(default_home=cfg.db_path.parent)
        ctrl = ManagedControl(m_cfg, store=cortex.store)
        tid = tenant_id or "default"
        members = ctrl.list_workspace_members(tid)
        return json.dumps({"tenant_id": tid, "members": members, "count": len(members)}, indent=2)

    @server.tool()
    def workspace_member_invite(email: str, role: str = "member", tenant_id: str | None = None) -> str:
        """Issue a cryptographically signed workspace invitation for multi-tenant seat sharing."""
        m_cfg = ManagedConfig.from_env(default_home=cfg.db_path.parent)
        ctrl = ManagedControl(m_cfg, store=cortex.store)
        tid = tenant_id or "default"
        res = ctrl.invite_workspace_member(tenant_id=tid, inviter_account_id="admin", email=email, role=role)
        return json.dumps(res, indent=2)

    @server.tool()
    def workspace_member_remove(account_id: str, tenant_id: str | None = None) -> str:
        """Revoke a workspace membership and seat."""
        m_cfg = ManagedConfig.from_env(default_home=cfg.db_path.parent)
        ctrl = ManagedControl(m_cfg, store=cortex.store)
        tid = tenant_id or "default"
        res = ctrl.remove_workspace_member(tenant_id=tid, target_account_id=account_id)
        return json.dumps(res, indent=2)

    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
