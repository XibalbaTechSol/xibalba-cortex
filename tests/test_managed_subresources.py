import time
from urllib.parse import parse_qs, urlsplit
import pytest
from starlette.testclient import TestClient

from xibalba_cortex.managed.api import create_app
from xibalba_cortex.managed.config import ManagedConfig
from xibalba_cortex.managed.control import ManagedControl


@pytest.fixture
def managed_env(tmp_path):
    config = ManagedConfig(
        home=tmp_path,
        public_url="http://localhost:8430",
        allow_signup=True,
    )
    mail = []
    service = ManagedControl(config, email_sender=lambda *args: mail.append(args))
    with TestClient(create_app(config, control=service), base_url=config.public_url) as client:
        # Register an account
        email = "researcher@example.com"
        client.post(
            "/api/managed/signup",
            json={"email": email, "password": "correct-test-password", "display_name": "Dr. Researcher"},
        )
        token = parse_qs(urlsplit(mail[-1][2].splitlines()[-1]).query)["token"][0]
        client.get("/api/managed/verify", params={"token": token}, follow_redirects=False)
        login_res = client.post("/api/managed/login", json={"email": email, "password": "correct-test-password"})
        assert login_res.status_code == 200
        body = login_res.json()
        account = body["account"]
        csrf_token = body["csrf_token"]
        headers = {"Origin": config.public_url, "X-Cortex-CSRF-Token": csrf_token}
        yield client, service, account, headers


def test_managed_memory_subresources_and_demo_agent(managed_env):
    client, service, account, headers = managed_env
    tenant = service.tenant(account)

    # 1. Ingest sample healthcare dataset for demo agent
    resp = client.post(
        "/api/managed/graph/seed-sample",
        json={"dataset": "healthcare_researcher", "agent_id": "demo-healthcare-researcher", "force": True},
        headers=headers,
    )
    assert resp.status_code == 200
    seed_res = resp.json()
    assert seed_res["entities_created"] > 30
    assert seed_res["relations_created"] > 50

    # 2. Graph request using custom DID resolves to demo healthcare researcher partition
    custom_did = "did:integrity:healthcare-researcher-latent-space-01"
    resp = client.get(f"/api/managed/graph?agent_id={custom_did}&limit=200")
    assert resp.status_code == 200
    graph = resp.json()
    assert len(graph["nodes"]) > 20
    assert len(graph["edges"]) > 20

    # 3. Store a memory to test subresources
    with service.store(tenant) as store:
        mem = store.store_memory(
            "Osimertinib demonstrates central nervous system penetrance in EGFR-mutated NSCLC.",
            source={"kind": "direct_user", "agent_id": custom_did},
            status="active",
        )
        mem_id = mem["id"]

    # 4. GET /api/managed/memories/{memory_id}/similar
    resp = client.get(f"/api/managed/memories/{mem_id}/similar?limit=5")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 5. GET /api/managed/memories/{memory_id}/neighbors
    resp = client.get(f"/api/managed/memories/{mem_id}/neighbors")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 6. GET /api/managed/memories/{memory_id}/events
    resp = client.get(f"/api/managed/memories/{mem_id}/events")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1
    assert resp.json()[0]["event_type"] == "create"

    # 7. GET /api/managed/memories/{memory_id}/otel
    resp = client.get(f"/api/managed/memories/{mem_id}/otel")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 8. GET /api/managed/memories/{memory_id}/attachments
    resp = client.get(f"/api/managed/memories/{mem_id}/attachments")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 9. GET /api/managed/memories/{memory_id}/contradictions
    resp = client.get(f"/api/managed/memories/{mem_id}/contradictions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # 10. GET /api/managed/entity/{name}/neighbors
    resp = client.get("/api/managed/entity/Osimertinib/neighbors?max_depth=1&agent_id=demo-healthcare-researcher")
    assert resp.status_code == 200
    entity_data = resp.json()
    assert "edges" in entity_data and len(entity_data["edges"]) > 0

    # 11. GET /api/managed/entity/path
    resp = client.get(
        "/api/managed/entity/path?from=Osimertinib&to=Liquid%20Biopsy%20ctDNA&max_depth=4&agent_id=demo-healthcare-researcher"
    )
    assert resp.status_code == 200
    assert "edges" in resp.json()
