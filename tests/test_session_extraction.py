"""Session extraction: an agent's own model extracts memories through claim/submit.

The engine leases pending documents to a caller, hands it the extractor prompt, and applies
whatever comes back through the same checks as the Gemini worker (grounding, secret filter,
dedup, certainty floors). Synthetic text only (public repo).
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from super_cortex.engine import EngineStore, HashingEmbedder
from super_cortex.engine.app import create_app
from super_cortex.engine.dreaming import run_dreaming
from super_cortex.engine.session_extraction import ClaimError, claim, release, submit

NS = "t"
REVIEW = "Priya moved the weekly design review from Tuesday to Thursday at 3pm."
COFFEE = "Priya prefers dark roast coffee. She is allergic to peanuts."
MOVED_AGAIN = "Update: the weekly design review now happens on Friday at 10am."


@pytest.fixture
def store():
    s = EngineStore(":memory:", HashingEmbedder())
    yield s
    s.close()


def ingest(store, *docs, ns=NS):
    for doc_id, text in docs:
        store.upsert_document(ns, text, doc_id, task_type="memory")


def memory(doc, text, quote, certainty="certain", kind="fact", inference=False, updates=None):
    return {"doc": doc, "memory": text, "quote": quote, "certainty": certainty, "kind": kind,
            "inference": inference, "updates": updates}


def test_claim_hands_out_documents_with_the_extractor_prompt(store):
    ingest(store, ("a", REVIEW), ("b", COFFEE))
    c = claim(store, NS, limit=5)
    assert [d["label"] for d in c["documents"]] == ["D1", "D2"]
    assert {d["id"] for d in c["documents"]} == {"a", "b"}
    assert "character-for-character" in c["instructions"]
    assert "<D1" in c["prompt"] and REVIEW in c["prompt"]
    assert c["responseSchema"]["required"] == ["documents"]
    assert c["claimId"] and c["expiresAt"]


def test_claimed_documents_are_not_handed_out_twice_or_to_the_worker(store):
    ingest(store, ("a", REVIEW))
    claim(store, NS, limit=5)
    assert claim(store, NS, limit=5)["documents"] == []
    assert store.pending_documents() == []  # the Gemini worker skips leased documents


def test_submit_stores_grounded_memories_labelled_with_the_session_model(store):
    ingest(store, ("a", REVIEW), ("b", COFFEE))
    c = claim(store, NS, limit=5)
    labels = {d["id"]: d["label"] for d in c["documents"]}
    stats = submit(store, c["claimId"], model="claude-test", documents=[
        {"doc": labels["a"], "memories": [memory(labels["a"], "The weekly design review is on Thursday at 3pm.",
                                                 "moved the weekly design review from Tuesday to Thursday at 3pm",
                                                 kind="event")]},
        {"doc": labels["b"], "memories": [
            memory(labels["b"], "Priya prefers dark roast coffee.", "Priya prefers dark roast coffee", kind="preference"),
            memory(labels["b"], "Priya owns a cat.", "Priya has a cat named Miso"),  # not in the document
        ]},
    ])
    assert stats["stored"] == 2 and stats["ungrounded"] == 1 and stats["documents"] == 2
    listed = store.list_memories(NS, "latest", 1, 10)["memories"]
    assert {m["extractor"] for m in listed} == {"session:claude-test"}
    assert store.dream_counts() == {"done": 2}


def test_flat_proposals_are_accepted_too(store):
    ingest(store, ("a", REVIEW))
    c = claim(store, NS)
    stats = submit(store, c["claimId"], model="m", proposals=[
        memory("D1", "The weekly design review is on Thursday at 3pm.", "the weekly design review from Tuesday to Thursday")])
    assert stats["stored"] == 1


def test_certainty_floors_still_apply(store):
    ingest(store, ("a", REVIEW))
    c = claim(store, NS)
    submit(store, c["claimId"], model="m", proposals=[
        memory("D1", "The review might move again.", "moved the weekly design review", certainty="uncertain")])
    assert store.list_memories(NS, "latest", 1, 10)["memories"] == []
    assert len(store.list_memories(NS, "candidate", 1, 10)["memories"]) == 1


def test_secrets_are_rejected(store):
    ingest(store, ("a", "The staging api_key: abcd1234efgh5678 was rotated on Monday."))
    c = claim(store, NS)
    stats = submit(store, c["claimId"], model="m", proposals=[
        memory("D1", "The staging api_key is abcd1234efgh5678.", "api_key: abcd1234efgh5678 was rotated")])
    assert stats["rejected_secret"] == 1 and stats["stored"] == 0


def test_updates_refer_to_the_related_memories_the_claim_showed(store):
    ingest(store, ("a", REVIEW))
    first = claim(store, NS)
    submit(store, first["claimId"], model="m", proposals=[
        memory("D1", "The weekly design review is on Thursday at 3pm.", "the weekly design review from Tuesday to Thursday")])
    ingest(store, ("b", MOVED_AGAIN))
    second = claim(store, NS, related_similarity=0.0)
    assert second["related"] and second["related"][0]["label"] == "M1"
    stats = submit(store, second["claimId"], model="m", proposals=[
        memory("D1", "The weekly design review is on Friday at 10am.", "the weekly design review now happens on Friday at 10am",
               updates="M1")])
    assert stats["superseded"] == 1


def test_a_claim_can_be_submitted_only_once(store):
    ingest(store, ("a", REVIEW))
    c = claim(store, NS)
    submit(store, c["claimId"], model="m", proposals=[])
    with pytest.raises(ClaimError):
        submit(store, c["claimId"], model="m", proposals=[])


def test_an_expired_claim_is_refused_and_its_documents_return_to_the_queue(store):
    ingest(store, ("a", REVIEW))
    c = claim(store, NS, lease_seconds=0)
    assert [d["id"] for d in store.pending_documents()] == ["a"]
    with pytest.raises(ClaimError):
        submit(store, c["claimId"], model="m", proposals=[])
    assert store.dream_counts() == {"pending": 1}


def test_release_returns_documents_without_counting_an_attempt(store):
    ingest(store, ("a", REVIEW))
    c = claim(store, NS)
    release(store, c["claimId"])
    again = claim(store, NS)
    assert [d["id"] for d in again["documents"]] == ["a"]
    assert store.dream_counts() == {"pending": 1}  # release is not a failure: no attempt used
    assert store.pending_documents() == []  # leased again by `again`


def test_a_namespace_with_dreaming_off_is_never_handed_out(store):
    ingest(store, ("a", REVIEW), ns="private")  # queued while the policy was auto
    store.set_policy("private", "standard", {"dreaming": "off"})
    assert claim(store, "private")["documents"] == []
    assert store.pending_documents() == []  # nor to the Gemini worker


def test_the_worker_leases_what_it_works_on(store):
    ingest(store, ("a", REVIEW))
    seen = []

    class Extractor:
        model = "fake"

        def propose(self, documents, related):
            seen.append(claim(store, NS)["documents"])  # a session claiming mid-batch gets nothing
            return []

    run_dreaming(store, Extractor(), max_requests=1, rpm=0, daily_budget=10)
    assert seen == [[]]
    assert store.dream_counts() == {"done": 1}


def test_http_claim_submit_round_trip(store):
    ingest(store, ("a", REVIEW))
    client = TestClient(create_app(store, api_key="k"))
    auth = {"authorization": "Bearer k"}
    assert client.post(f"/ns/{NS}/extraction/claim", json={}).status_code == 401
    c = client.post(f"/ns/{NS}/extraction/claim", json={"limit": 3}, headers=auth).json()
    r = client.post(f"/extraction/claims/{c['claimId']}/submit", headers=auth, json={
        "model": "claude-test",
        "documents": [{"doc": "D1", "memories": [memory("D1", "The weekly design review is on Thursday at 3pm.",
                                                         "the weekly design review from Tuesday to Thursday")]}],
    })
    assert r.status_code == 200 and r.json()["stored"] == 1
    again = client.post(f"/extraction/claims/{c['claimId']}/submit", headers=auth, json={"model": "m", "proposals": []})
    assert again.status_code == 409


def test_http_release(store):
    ingest(store, ("a", REVIEW))
    client = TestClient(create_app(store, api_key="k"))
    auth = {"authorization": "Bearer k"}
    c = client.post(f"/ns/{NS}/extraction/claim", json={}, headers=auth).json()
    assert client.post(f"/extraction/claims/{c['claimId']}/release", headers=auth).status_code == 200
    assert [d["id"] for d in store.pending_documents()] == ["a"]


def _mcp_text(result) -> dict:
    """The JSON a tool returned, across mcp result shapes (content list, or (content, structured))."""
    content = result[0] if isinstance(result, tuple) else result
    content = getattr(content, "content", content)
    return __import__("json").loads(content[0].text)


@pytest.mark.asyncio
async def test_mcp_tools_claim_and_submit_against_the_engine(store, monkeypatch, tmp_path):
    import httpx

    from super_cortex import client as client_module
    from super_cortex.config import SuperCortexConfig
    from super_cortex.server import create_server

    app = create_app(store, api_key="k")
    real = httpx.AsyncClient
    monkeypatch.setattr(client_module.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.ASGITransport(app=app), **kw))
    ingest(store, ("a", REVIEW), ns="agent-test")
    server = create_server(SuperCortexConfig(db_path=tmp_path / "p.db", default_namespace="agent-test",
                                             supermemory_url="http://engine", supermemory_api_key="k"))

    claimed = _mcp_text(await server.call_tool("memory_extraction_claim", {}))
    assert claimed["namespace"] == "agent-test" and claimed["documents"][0]["id"] == "a"
    submitted = _mcp_text(await server.call_tool("memory_extraction_submit", {
        "claim_id": claimed["claimId"], "model": "claude-test",
        "documents": [{"doc": "D1", "memories": [memory("D1", "The weekly design review is on Thursday at 3pm.",
                                                         "the weekly design review from Tuesday to Thursday")]}],
    }))
    assert submitted["stored"] == 1 and submitted["extractor"] == "session:claude-test"


# -- CLI: `super-cortex extract` ------------------------------------------------------------------

AGENT = """import json, sys
prompt = sys.stdin.read()
assert "<D1" in prompt and "responseSchema" not in prompt
print("Sure! Here you go:\\n```json")
print(json.dumps({"documents": [{"doc": "D1", "memories": [{"memory": "The weekly design review is on Thursday at 3pm.",
    "quote": "the weekly design review from Tuesday to Thursday", "certainty": "certain", "inference": False,
    "kind": "event", "updates": None}]}]}))
print("```")
"""


@pytest.fixture
def engine_client(store, monkeypatch):
    import httpx

    from super_cortex import client as client_module
    from super_cortex.client import SupermemoryClient
    from super_cortex.config import SuperCortexConfig

    app = create_app(store, api_key="k")
    real = httpx.AsyncClient
    monkeypatch.setattr(client_module.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.ASGITransport(app=app), **kw))
    return SupermemoryClient(SuperCortexConfig(supermemory_url="http://engine", supermemory_api_key="k"))


def test_parse_answer_tolerates_fences_and_chatter():
    from super_cortex.extract_cli import parse_answer

    assert parse_answer('ok\n```json\n{"documents": []}\n```') == []
    with pytest.raises(ValueError):
        parse_answer("I could not do that.")


@pytest.mark.asyncio
async def test_cli_run_pipes_claims_through_an_agent_command(store, engine_client, tmp_path):
    import sys

    from super_cortex.extract_cli import run_extraction

    agent = tmp_path / "agent.py"
    agent.write_text(AGENT)
    ingest(store, ("a", REVIEW))
    totals = await run_extraction(engine_client, NS, f"{sys.executable} {agent}", "fake-agent")
    assert totals["claims"] == 1 and totals["stored"] == 1 and "failed" not in totals
    assert store.list_memories(NS, "latest", 1, 10)["memories"][0]["extractor"] == "session:fake-agent"
    assert store.dream_counts() == {"done": 1}


@pytest.mark.asyncio
async def test_cli_run_releases_the_claim_when_the_agent_fails(store, engine_client, tmp_path):
    import sys

    from super_cortex.extract_cli import run_extraction

    agent = tmp_path / "agent.py"
    agent.write_text("import sys; sys.stdin.read(); print('no idea')")
    ingest(store, ("a", REVIEW))
    totals = await run_extraction(engine_client, NS, f"{sys.executable} {agent}", "fake-agent")
    assert totals["failed"] == 1 and totals["stored"] == 0
    assert [d["id"] for d in store.pending_documents()] == ["a"]  # released, not burnt


@pytest.mark.asyncio
async def test_client_says_when_the_backend_is_not_the_engine(monkeypatch):
    import httpx

    from super_cortex import client as client_module
    from super_cortex.client import SupermemoryClient, SupermemoryClientError
    from super_cortex.config import SuperCortexConfig

    real = httpx.AsyncClient
    not_found = httpx.MockTransport(lambda request: httpx.Response(404, json={"error": "not found"}))
    monkeypatch.setattr(client_module.httpx, "AsyncClient", lambda **kw: real(transport=not_found, **kw))
    client = SupermemoryClient(SuperCortexConfig(supermemory_url="http://supermemory", supermemory_api_key="k"))
    with pytest.raises(SupermemoryClientError, match="SuperCortex engine"):
        await client.claim_extraction("t")
