"""Test suite for Super-Cortex Cognitive Architecture, Enterprise RBAC, and ZKP Invariant Engine."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from super_cortex.api import create_app
from super_cortex.config import SuperCortexConfig
from super_cortex.deterministic import compute_temporal_retention
from super_cortex.hierarchical_graphrag import (
    detect_hierarchical_communities,
    query_hierarchical_graphrag,
)
from super_cortex.managed import ManagedConfig, ManagedControl
from super_cortex.truth_maintenance import (
    build_dependency_dag,
    propagate_invalidation,
    verify_belief_justification,
)
from super_cortex.zkp import (
    create_zkp_invariant_proof,
    generate_zkp_commitment,
    verify_zkp_invariant_proof,
)


@pytest.fixture
def tmp_cortex_env(tmp_path):
    cfg = SuperCortexConfig(db_path=tmp_path / "provenance.db")
    m_cfg = ManagedConfig(home=tmp_path)
    app = create_app(config=cfg, managed_config=m_cfg)
    client = TestClient(app)
    return {"cfg": cfg, "m_cfg": m_cfg, "app": app, "client": client, "home": tmp_path}


# =========================================================================
# 1. COGNITIVE REVISION: TRUTH MAINTENANCE SYSTEM (JTMS / ATMS)
# =========================================================================
def test_jtms_dependency_and_invalidation():
    memories = [
        {"id": "mem_premise_1", "text": "Company operates under GDPR rules", "epistemic_class": "fact", "lifecycle_status": "active"},
        {
            "id": "mem_inference_1",
            "text": "Data residency restricted to EU regions",
            "epistemic_class": "inference",
            "lifecycle_status": "active",
            "metadata": {"premises": ["mem_premise_1"]},
        },
        {
            "id": "mem_inference_2",
            "text": "Frankfurt cluster hosts customer data",
            "epistemic_class": "inference",
            "lifecycle_status": "active",
            "metadata": {"derived_from": ["mem_inference_1"]},
        },
        {"id": "mem_rule_1", "text": "Root encryption invariant", "epistemic_class": "rule", "lifecycle_status": "active"},
    ]
    relations = [
        {"subject": "mem_premise_1", "predicate": "implies", "object": "mem_inference_1"},
    ]

    # Verify initial DAG building
    dag = build_dependency_dag(memories, relations)
    assert "mem_inference_1" in dag["downstream"]["mem_premise_1"]

    # Verify belief justification
    just_pre = verify_belief_justification("mem_inference_2", memories, relations)
    assert just_pre["justified"] is True

    # Propagate invalidation from root premise
    res = propagate_invalidation("mem_premise_1", "contradicted", memories, relations)
    assert res["affected_count"] == 2
    affected_ids = [m["memory_id"] for m in res["affected_memories"]]
    assert "mem_inference_1" in affected_ids
    assert "mem_inference_2" in affected_ids

    # Simulate updated status
    memories[0]["lifecycle_status"] = "contradicted"
    just_post = verify_belief_justification("mem_inference_2", memories, relations)
    assert just_post["justified"] is False
    assert len(just_post["compromised_premises"]) >= 1


# =========================================================================
# 2. HIERARCHICAL GRAPHRAG COMMUNITY CLUSTERING
# =========================================================================
def test_hierarchical_graphrag_clustering():
    nodes = [
        {"id": "m1", "text": "Postgres database connection timeout and pool exhaustion"},
        {"id": "m2", "text": "Database read replica replication lag in us-east-1"},
        {"id": "m3", "text": "SQL query index optimization for accounts table"},
        {"id": "m4", "text": "Frontend React component re-render performance bottleneck"},
        {"id": "m5", "text": "Tailwind CSS zero radius UI layout design system"},
    ]
    links = [
        {"source": "m1", "target": "m2"},
        {"source": "m2", "target": "m3"},
        {"source": "m4", "target": "m5"},
    ]

    clusters = detect_hierarchical_communities(nodes, links)
    assert clusters["total_nodes"] == 5
    assert clusters["community_count"] >= 2
    assert len(clusters["macro_nodes"]) >= 2

    # Query multi-scale GraphRAG
    rag_result = query_hierarchical_graphrag(
        "database query latency", nodes, clusters["macro_nodes"]
    )
    assert len(rag_result["macro_contexts"]) >= 1
    assert any("database" in m["text"].lower() for m in rag_result["macro_contexts"])


# =========================================================================
# 3. COGNITIVE MEMORY DECAY & SPACED REHEARSAL PHYSICS
# =========================================================================
def test_cognitive_decay_spaced_rehearsal():
    now_iso = "2026-11-01T00:00:00Z"

    # Base decay for scratchpad inference with 0 citations
    scratch_cold = compute_temporal_retention(now_iso, epistemic_class="inference", access_count=0)
    
    # Reinforced decay with 10 citations
    scratch_hot = compute_temporal_retention(now_iso, epistemic_class="inference", access_count=10)

    assert scratch_hot["stability_boost"] > 1.0
    assert scratch_hot["half_life_hours"] > scratch_cold["half_life_hours"]
    assert scratch_hot["retention_score"] >= scratch_cold["retention_score"]


# =========================================================================
# 4. ZERO-KNOWLEDGE PROOFS FOR SELECTIVE DISCLOSURE
# =========================================================================
def test_zkp_invariant_proof_and_verification():
    payload = "Automated trade order execution with risk_limit = 3.5% of total capital."
    salt = "crypto_salt_998877"
    nonce = "oracle_nonce_12345"

    commit_data = generate_zkp_commitment(payload, salt)
    assert commit_data["commitment"]

    # Generate proof that risk <= 5%
    proof = create_zkp_invariant_proof(
        payload=payload,
        salt=salt,
        invariant_name="Max Risk Bound",
        invariant_predicate="risk_limit_le_5",
        verifier_nonce=nonce,
        metadata={"memory_id": "mem_order_1"},
    )
    assert proof["commitment"] == commit_data["commitment"]

    # Verify proof passes without knowing payload
    verification = verify_zkp_invariant_proof(proof, commit_data["commitment"], nonce)
    assert verification["valid"] is True

    # Bad nonce fails
    bad_nonce_verif = verify_zkp_invariant_proof(proof, commit_data["commitment"], "wrong_nonce")
    assert bad_nonce_verif["valid"] is False


# =========================================================================
# 5. MULTI-TENANT WORKSPACE SHARING & RBAC
# =========================================================================
def test_workspace_sharing_rbac(tmp_path):
    m_cfg = ManagedConfig(home=tmp_path)
    ctrl = ManagedControl(m_cfg)

    # Initial operator registration
    signup = ctrl.register(email="owner@xibalba.dev", password="Owner Password 123", display_name="Workspace Owner")
    tenant_id = signup["account"]["profile_id"]
    owner_acc_id = signup["account"]["id"]

    # List members (owner should exist)
    members = ctrl.list_workspace_members(tenant_id)
    assert len(members) == 1
    assert members[0]["role"] == "owner"

    # Owner invites engineer as member
    invite = ctrl.invite_workspace_member(
        tenant_id=tenant_id,
        email="engineer@xibalba.dev",
        role="member",
        inviter_account_id=owner_acc_id,
    )
    assert invite["invite_token"]

    # Non-owner cannot invite
    with pytest.raises(PermissionError):
        ctrl.invite_workspace_member(
            tenant_id=tenant_id,
            email="hack@xibalba.dev",
            role="admin",
            inviter_account_id="acc_stranger",
        )

    # Engineer registers & accepts invitation
    eng_signup = ctrl.register(email="engineer@xibalba.dev", password="Engineer Pass 123", display_name="Lead Engineer")
    eng_acc_id = eng_signup["account"]["id"]

    accept = ctrl.accept_workspace_invitation(invite["invite_token"], eng_acc_id)
    assert accept["status"] == "accepted"

    # Verify member list has 2 members
    updated_members = ctrl.list_workspace_members(tenant_id)
    assert len(updated_members) == 2


# =========================================================================
# 6. REST API INTEGRATION ENDPOINTS
# =========================================================================
def test_api_cognitive_endpoints(tmp_cortex_env):
    client = tmp_cortex_env["client"]

    # 1. TMS Invalidation Endpoint
    inv_res = client.post("/api/tms/invalidate", json={"root_id": "mem_nonexistent", "action": "contradicted"})
    assert inv_res.status_code == 200
    assert inv_res.json()["affected_count"] == 0

    # 2. GraphRAG Communities Endpoint
    com_res = client.get("/api/graphrag/communities")
    assert com_res.status_code == 200
    assert "communities" in com_res.json()

    # 3. GraphRAG Query Endpoint
    query_res = client.post("/api/graphrag/query", json={"query": "system architecture"})
    assert query_res.status_code == 200
    assert "hierarchical_synthesis" in query_res.json()

    # 4. Agent Traversal Beacon Endpoint
    beacon_res = client.post("/api/graph/beacon", json={"agent_id": "agent_agy", "active_nodes": ["n1", "n2"], "query": "find rules"})
    assert beacon_res.status_code == 200
    assert beacon_res.json()["nodes"] == 2

    # 5. Workspace Members Endpoint
    ws_res = client.get("/api/workspace/members?tenant_id=tenant_xibalba_core")
    assert ws_res.status_code == 200
    assert "members" in ws_res.json()
    assert len(ws_res.json()["members"]) >= 1

    # 6. ZKP Proof and Verification Endpoints
    zkp_proof_res = client.post("/api/zkp/proof", json={"statement": "salience >= 0.85 AND confidence >= 0.90"})
    assert zkp_proof_res.status_code == 200
    proof_data = zkp_proof_res.json()
    assert "commitment" in proof_data
    assert "proof_hash" in proof_data

    zkp_verify_res = client.post("/api/zkp/verify", json=proof_data)
    assert zkp_verify_res.status_code == 200
    assert zkp_verify_res.json()["valid"] is True

    # 7. TMS Justification Endpoint
    just_res = client.get("/api/tms/justification?memory_id=mem_nonexistent")
    assert just_res.status_code == 200
    assert just_res.json()["justified"] is False

    # 8. Workspace Invite Endpoint
    invite_res = client.post(
        "/api/workspace/invite",
        json={"tenant_id": "tenant_xibalba_core", "email": "test-invite@xibalba.org", "role": "auditor"}
    )
    assert invite_res.status_code == 200
    assert "invite_token" in invite_res.json()


# =========================================================================
# 7. END-TO-END MEMORY LIFECYCLE WIRING & MCP SERVER TOOLS
# =========================================================================
@pytest.mark.asyncio
async def test_cortex_lifecycle_wiring_and_mcp_tools(tmp_path):
    from super_cortex.memory import SuperCortex
    from super_cortex.server import create_server

    cfg = SuperCortexConfig(db_path=tmp_path / "test_wiring.db")
    cortex = SuperCortex(cfg)

    # 1. Store premise & derived inference
    m1 = await cortex.remember(text="All servers must run Linux", epistemic_class="rule")
    m1_id = m1["memory_id"]

    m2 = await cortex.remember(
        text="Worker nodes run Ubuntu 24.04",
        epistemic_class="inference",
        metadata={"premises": [m1_id]},
    )
    m2_id = m2["memory_id"]

    # 2. Access counting & Ebbinghaus decay updates
    r1 = await cortex.recall(m1_id)
    assert r1["temporal_retention"]["access_count"] == 1
    r2 = await cortex.recall(m1_id)
    assert r2["temporal_retention"]["access_count"] == 2

    # 3. Contradict root premise -> JTMS invalidates & quarantines downstream inference
    contra = await cortex.contradict(m1_id, reason="Migrated to BSD")
    assert contra["invalidation"]["affected_count"] >= 1
    mem2_status = cortex.store.get_memory(m2_id).lifecycle_status
    assert mem2_status == "quarantined"

    # 4. Verify all 9 MCP tools are registered on MCPServer
    server = create_server(cfg)
    tool_keys = list(server._tool_manager._tools.keys())
    required_tools = [
        "memory_tms_invalidate",
        "memory_tms_justification",
        "memory_graphrag_communities",
        "memory_graphrag_query",
        "memory_zkp_prove",
        "memory_zkp_verify",
        "workspace_members_list",
        "workspace_member_invite",
        "workspace_member_remove",
    ]
    for rt in required_tools:
        assert rt in tool_keys, f"Missing MCP tool: {rt}"
