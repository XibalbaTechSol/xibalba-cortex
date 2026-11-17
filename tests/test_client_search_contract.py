"""SupermemoryClient.search must send `limit` and resolve hits to their source documents.

Two bugs this pins down:
- `limit` was never sent, so the server's default (10) silently capped every request.
- A Supermemory hit's `id` is a chunk or learned-memory id. hybrid_retrieve looked provenance
  up by that id, so no result was ever "anchored" to its ledger record.
"""

from __future__ import annotations

import json

import httpx
import pytest

from super_cortex import client as client_module
from super_cortex.client import SupermemoryClient
from super_cortex.config import SuperCortexConfig


@pytest.fixture
def captured(monkeypatch):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}")
        calls.append(payload)
        n = int(payload.get("limit", 10))
        results = [
            {"id": f"chunk{i}", "chunk": f"text {i}", "similarity": 0.9 - i / 100,
             "included": {"document": {"id": f"mem_{i}", "title": "t"}}}
            for i in range(min(n, 30))
        ]
        return httpx.Response(200, json={"results": results})

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", factory)
    return calls


async def test_search_sends_limit_and_returns_more_than_ten(captured, tmp_path):
    cfg = SuperCortexConfig(supermemory_url="http://sm.test", supermemory_api_key="k", db_path=tmp_path / "p.db")
    results = await SupermemoryClient(cfg).search(namespace="ns", query="q", limit=20)
    assert captured[0]["limit"] == 20
    assert len(results) == 20


async def test_search_requests_source_documents(captured, tmp_path):
    cfg = SuperCortexConfig(supermemory_url="http://sm.test", supermemory_api_key="k", db_path=tmp_path / "p.db")
    await SupermemoryClient(cfg).search(namespace="ns", query="q", limit=3)
    assert captured[0]["include"] == {"documents": True}


async def test_hybrid_retrieve_anchors_by_document_id(captured, tmp_path, monkeypatch):
    from super_cortex.memory import SuperCortex

    cfg = SuperCortexConfig(supermemory_url="http://sm.test", supermemory_api_key="k", db_path=tmp_path / "p.db")
    cortex = SuperCortex(cfg)
    looked_up: list[str] = []
    monkeypatch.setattr(cortex.store, "get_memory", lambda mid: looked_up.append(mid) or None)
    out = await cortex.hybrid_retrieve("q", namespace="ns", limit=3)
    assert looked_up == ["mem_0", "mem_1", "mem_2"]
    assert [r["id"] for r in out["results"]] == ["mem_0", "mem_1", "mem_2"]
    assert out["results"][0]["chunk_id"] == "chunk0"
