from __future__ import annotations

from pathlib import Path

from xibalba_cortex.embedding_worker import eligible_memories, embed_memories
from xibalba_cortex.store import EMBEDDING_DIM, GraphStore


class FakeModel:
    def encode(self, texts, **kwargs):
        return [[float(index + 1)] + [0.0] * (EMBEDDING_DIM - 1) for index, _ in enumerate(texts)]


def test_eligible_memories_excludes_non_active_and_already_embedded(tmp_path: Path):
    store = GraphStore(tmp_path)
    active = store.store_memory("active memory", source={"kind": "test"}, status="active")
    confirmed = store.store_memory("confirmed memory", source={"kind": "test"}, status="confirmed")
    candidate = store.store_memory("candidate memory", source={"kind": "test"}, status="candidate")
    store.store_embedding(confirmed["id"], [1.0] + [0.0] * (EMBEDDING_DIM - 1))

    rows = eligible_memories(store)

    assert [row["id"] for row in rows] == [active["id"]]
    assert candidate["id"] not in {row["id"] for row in rows}


def test_embed_memories_writes_vectors_and_reports_progress(tmp_path: Path):
    store = GraphStore(tmp_path)
    first = store.store_memory("first memory", source={"kind": "test"}, status="active")
    second = store.store_memory("second memory", source={"kind": "test"}, status="confirmed")

    result = embed_memories(store, FakeModel(), batch_size=2)

    assert result == {"processed": 2, "embedded": 2, "failed": 0, "remaining": 0}
    assert store.counts()["embedded_memories"] == 2
    assert {row["id"] for row in eligible_memories(store)} == set()
    assert first["id"] != second["id"]


def test_embed_memories_isolates_bad_vector_and_reports_remaining(tmp_path: Path):
    store = GraphStore(tmp_path)
    good = store.store_memory("good memory", source={"kind": "test"}, status="active")
    bad = store.store_memory("bad memory", source={"kind": "test"}, status="active")

    class BadModel:
        def encode(self, texts, **kwargs):
            return [[0.0] * EMBEDDING_DIM, [0.0] * (EMBEDDING_DIM - 1)]

    result = embed_memories(store, BadModel(), batch_size=2)

    assert result == {"processed": 2, "embedded": 0, "failed": 2, "remaining": 2}
    remaining_ids = {row["id"] for row in eligible_memories(store)}
    assert len(remaining_ids) == 2
    assert remaining_ids <= {good["id"], bad["id"]}
    assert store.counts()["embedded_memories"] == 0


def test_embed_memories_rejects_zero_vector_before_store_write(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("zero vector memory", source={"kind": "test"}, status="active")

    class ZeroModel:
        def encode(self, texts, **kwargs):
            return [[0.0] * EMBEDDING_DIM for _ in texts]

    result = embed_memories(store, ZeroModel())

    assert result == {"processed": 1, "embedded": 0, "failed": 1, "remaining": 1}
    assert memory["id"] in {row["id"] for row in eligible_memories(store)}
    coverage = store.embedding_coverage()
    assert coverage["failed"] == 1
    failure = store._connection.execute("SELECT attempts, last_error FROM embedding_failures WHERE memory_id = ?", (memory["id"],)).fetchone()
    assert failure["attempts"] == 1
    assert "zero" in failure["last_error"].lower()
