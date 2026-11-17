"""The shared scope ("Xibalba Solutions") must resolve to ONE fixed namespace for every
agent. It used to resolve to each client's own default namespace, so once each agent got
its own namespace, "shared" silently meant "mine" and nothing reached a common pool."""

from __future__ import annotations

from pathlib import Path

import pytest

from super_cortex.config import SuperCortexConfig
from super_cortex.memory import SuperCortex
from super_cortex.store import ProvenanceStore


class RecordingClient:
    def __init__(self) -> None:
        self.namespaces: list[str] = []

    async def ingest_document(self, namespace, content, doc_id, metadata=None):
        self.namespaces.append(namespace)
        return {"id": doc_id}

    async def search(self, namespace, query, limit=10):
        self.namespaces.append(namespace)
        return []


def _cortex(tmp_path: Path, own_namespace: str) -> tuple[SuperCortex, RecordingClient]:
    db = tmp_path / f"{own_namespace}.db"
    client = RecordingClient()
    cfg = SuperCortexConfig(db_path=db, default_namespace=own_namespace, actor_did="did:test:1")
    return SuperCortex(config=cfg, client=client, store=ProvenanceStore(db)), client


@pytest.mark.asyncio
@pytest.mark.parametrize("own", ["agent-claude", "agent-xibalba", "agent-agy"])
async def test_shared_write_lands_in_the_one_company_namespace(tmp_path: Path, own: str):
    cortex, client = _cortex(tmp_path, own)
    await cortex.remember(text="Company fact.", scope="shared")
    assert client.namespaces == ["xibalba-solutions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("own", ["agent-claude", "agent-xibalba"])
async def test_shared_read_hits_the_one_company_namespace(tmp_path: Path, own: str):
    cortex, client = _cortex(tmp_path, own)
    await cortex.hybrid_retrieve(query="anything", scope="shared")
    assert client.namespaces == ["xibalba-solutions"]


@pytest.mark.asyncio
async def test_agent_scope_stays_private(tmp_path: Path):
    cortex, client = _cortex(tmp_path, "agent-xibalba")
    await cortex.remember(text="Private.", agent_id="xibalba")
    await cortex.hybrid_retrieve(query="q")
    assert client.namespaces == ["agent-xibalba", "agent-xibalba"]


def test_shared_namespace_is_overridable(monkeypatch):
    monkeypatch.setenv("SUPER_CORTEX_SHARED_NAMESPACE", "other-co")
    assert SuperCortexConfig().shared_namespace == "other-co"


def test_shared_scope_is_named_xibalba_solutions(tmp_path: Path):
    scope = ProvenanceStore(tmp_path / "s.db").get_scope("shared")
    assert scope is not None and scope.name == "Xibalba Solutions"
