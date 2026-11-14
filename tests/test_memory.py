from __future__ import annotations

from pathlib import Path
import pytest

from super_cortex.config import SuperCortexConfig
from super_cortex.memory import SuperCortex
from super_cortex.models import LifecycleStatus
from super_cortex.store import ProvenanceStore


@pytest.fixture
def cortex_instance(tmp_path: Path) -> SuperCortex:
    db_file = tmp_path / "cortex_test.db"
    config = SuperCortexConfig(
        db_path=db_file,
        default_namespace="test-super-cortex",
        actor_did="did:test:1234",
    )
    store = ProvenanceStore(db_file)
    return SuperCortex(config=config, store=store)


@pytest.mark.asyncio
async def test_remember_and_recall(cortex_instance: SuperCortex):
    text = "Integrity Protocol enforces domain-agnostic provenance verification."
    res = await cortex_instance.remember(
        text=text,
        epistemic_class="rule",
        namespace="test-super-cortex",
    )
    assert res["memory_id"].startswith("mem_")
    assert res["epistemic_class"] == "rule"
    assert len(res["event_hash"]) == 64

    # Recall from store
    recalled = await cortex_instance.recall(res["memory_id"])
    assert recalled is not None
    assert recalled["text"] == text
    assert recalled["lifecycle_status"] == LifecycleStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_contradict_and_supersede(cortex_instance: SuperCortex):
    res = await cortex_instance.remember(
        text="All transactions run synchronously.",
        epistemic_class="fact",
    )
    mem_id = res["memory_id"]

    # Contradict
    c_res = await cortex_instance.contradict(
        target_memory_id=mem_id,
        reason="Empirical benchmarks prove async batching is active.",
    )
    assert c_res["status"] == LifecycleStatus.CONTRADICTED.value

    # Supersede with updated truth
    s_res = await cortex_instance.supersede(
        target_memory_id=mem_id,
        replacement_text="Transactions run asynchronously via event loop.",
        reason="Architecture upgrade",
    )
    assert s_res["replacement"]["memory_id"].startswith("mem_")

    recalled = await cortex_instance.recall(mem_id)
    assert recalled["lifecycle_status"] == LifecycleStatus.SUPERSEDED.value


@pytest.mark.asyncio
async def test_forget(cortex_instance: SuperCortex):
    res = await cortex_instance.remember(text="Temporary debug key: 1234")
    mem_id = res["memory_id"]

    f_res = await cortex_instance.forget(mem_id)
    assert f_res["status"] == LifecycleStatus.FORGOTTEN.value

    recalled = await cortex_instance.recall(mem_id)
    assert recalled["lifecycle_status"] == LifecycleStatus.FORGOTTEN.value


def test_entity_graph_and_neighbors(cortex_instance: SuperCortex):
    rel = cortex_instance.link_entities(
        subject="SuperCortex",
        predicate="uses",
        object_="Supermemory",
        confidence=1.0,
    )
    assert rel["predicate"] == "uses"

    neighbors = cortex_instance.get_neighbors("SuperCortex")
    assert len(neighbors) == 1
    assert neighbors[0]["object"] == "Supermemory"


def test_record_exchange_and_session_merkle(cortex_instance: SuperCortex):
    session_id = "agent_session_99"
    exch = cortex_instance.record_exchange(
        session_id=session_id,
        prompt_text="What is your mandate?",
        response_text="Quant control systems and autonomous infrastructure.",
    )
    assert exch["session_id"] == session_id
    assert len(exch["session_merkle_root"]) == 64

    # Verify chain
    chain_status = cortex_instance.verify_chain()
    assert chain_status["valid"] is True
    assert chain_status["event_count"] >= 1
