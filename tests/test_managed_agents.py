"""Agent workspace discovery and agent-scoped memories on managed edition."""
from xibalba_cortex.ingest_tokens import issue_token


def bearer(token, key="idem-agent-test-1"):
    return {"Authorization": "Bearer " + token, "Idempotency-Key": key}


def test_managed_agents_list_and_auth_agents_route(managed_app):
    account, headers = managed_app.register("alice")

    # Issue an agent token for a specific DID
    agent_did = "did:integrity:agent-agy-001"
    issue_token(
        managed_app.service.identity_home,
        "managed-api:agy@workstation",
        profile_id=account["profile_id"],
        roles=("writer",),
        scopes=("memory:read", "memory:write"),
        agent_ids=(agent_did,),
    )

    # 1. Test /api/managed/agents via session
    r = managed_app.owner.get("/api/managed/agents", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "agents" in data
    assert data["oracle_reachable"] is True
    assert any(a["agent_id"] == agent_did and a["agent_name"] == "agy" for a in data["agents"])

    # 2. Test /api/auth/agents alias
    r2 = managed_app.owner.get("/api/auth/agents", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["agents"] == data["agents"]

    # 3. Test me payload includes agents
    r_me = managed_app.owner.get("/api/managed/me")
    assert r_me.status_code == 200
    assert "agents" in r_me.json()
    assert any(a["agent_id"] == agent_did for a in r_me.json()["agents"])


def test_memories_scoped_by_agent_id(managed_app):
    account, headers = managed_app.register("bob")

    did1 = "did:integrity:agent-hermes"
    did2 = "did:integrity:agent-claude"

    # Store memory for did1
    r1 = managed_app.owner.post(
        "/api/managed/memories",
        headers={**headers, "Idempotency-Key": "key-mem-1"},
        json={"content": "Note from Hermes agent", "source": {"agent_id": did1}},
    )
    assert r1.status_code == 201, r1.text

    # Store memory for did2
    r2 = managed_app.owner.post(
        "/api/managed/memories",
        headers={**headers, "Idempotency-Key": "key-mem-2"},
        json={"content": "Note from Claude agent", "source": {"agent_id": did2}},
    )
    assert r2.status_code == 201, r2.text

    # Query all memories (no agent_id)
    r_all = managed_app.owner.get("/api/managed/memories")
    assert r_all.status_code == 200
    memories_all = r_all.json()["memories"]
    assert len(memories_all) == 2

    # Query scoped to did1
    r_did1 = managed_app.owner.get(f"/api/managed/memories?agent_id={did1}")
    assert r_did1.status_code == 200
    memories_did1 = r_did1.json()["memories"]
    assert len(memories_did1) == 1
    assert memories_did1[0]["content"] == "Note from Hermes agent"

    # Query scoped to did2
    r_did2 = managed_app.owner.get(f"/api/managed/memories?agent_id={did2}")
    assert r_did2.status_code == 200
    memories_did2 = r_did2.json()["memories"]
    assert len(memories_did2) == 1
    assert memories_did2[0]["content"] == "Note from Claude agent"

    # Search scoped to did1
    r_search = managed_app.owner.get(f"/api/managed/memories?q=Note&agent_id={did1}")
    assert r_search.status_code == 200
    search_memories = r_search.json()["memories"]
    assert len(search_memories) == 1
    assert search_memories[0]["content"] == "Note from Hermes agent"
