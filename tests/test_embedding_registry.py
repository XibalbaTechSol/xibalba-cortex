from __future__ import annotations

from pathlib import Path

import pytest

from xibalba_cortex.store import EMBEDDING_DIM, EMBEDDING_MODEL_ID, EMBEDDING_MODEL_REVISION, GraphStore


def _unit_vector(dim: int, hot_index: int) -> list[float]:
    vector = [0.0] * dim
    vector[hot_index] = 1.0
    return vector


def test_pinned_model_is_seeded_and_active(tmp_path: Path):
    store = GraphStore(tmp_path)
    active = store.get_active_embedding_model()
    assert active["model_id"] == EMBEDDING_MODEL_ID
    assert active["revision"] == EMBEDDING_MODEL_REVISION
    assert active["dimension"] == EMBEDDING_DIM
    assert active["vector_table"] == "memory_vectors"
    assert active["state"] == "active"


def test_list_embedding_models_includes_seeded_model(tmp_path: Path):
    store = GraphStore(tmp_path)
    models = store.list_embedding_models()
    assert any(m["model_id"] == EMBEDDING_MODEL_ID for m in models)


def test_store_embedding_validates_against_active_model(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Some content.", source={"kind": "test"}, status="active")
    with pytest.raises(ValueError, match="dimension"):
        store.store_embedding(memory["id"], [0.1, 0.2])
    with pytest.raises(ValueError, match="unsupported embedding model_id"):
        store.store_embedding(memory["id"], _unit_vector(EMBEDDING_DIM, 0), model_id="not-the-active-model")


def test_store_embedding_rejects_zero_norm_vector(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Some content.", source={"kind": "test"}, status="active")
    with pytest.raises(ValueError, match="non-zero norm"):
        store.store_embedding(memory["id"], [0.0] * EMBEDDING_DIM)


def test_register_new_model_creates_its_own_vector_table(tmp_path: Path):
    store = GraphStore(tmp_path)
    registered = store.register_embedding_model("some-other-model", "r1", dimension=8, distance_metric="cosine")
    assert registered["vector_table"] == "memory_vectors_some_other_model_r1"
    assert registered["state"] == "shadow"

    table_exists = store._connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ?", (registered["vector_table"],)
    ).fetchone()
    assert table_exists is not None


def test_promote_embedding_model_swaps_active_and_deprecates_previous(tmp_path: Path):
    store = GraphStore(tmp_path)
    original_active = store.get_active_embedding_model()
    store.register_embedding_model("some-other-model", "r1", dimension=8)

    promoted = store.promote_embedding_model("some-other-model@r1")
    assert promoted["state"] == "active"
    assert store.get_active_embedding_model()["model_key"] == "some-other-model@r1"

    previous = store.get_embedding_model(original_active["model_key"])
    assert previous["state"] == "deprecated"

    # Rollback is just promoting the previous key again -- neither table was dropped.
    rolled_back = store.promote_embedding_model(original_active["model_key"])
    assert rolled_back["state"] == "active"
    assert store.get_embedding_model("some-other-model@r1")["state"] == "deprecated"


def test_promote_unknown_model_raises(tmp_path: Path):
    store = GraphStore(tmp_path)
    with pytest.raises(KeyError):
        store.promote_embedding_model("not-a-real-model@r1")


def test_embeddings_meta_records_model_key_and_revision(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Some content.", source={"kind": "test"}, status="active")
    store.store_embedding(memory["id"], _unit_vector(EMBEDDING_DIM, 0))
    row = store._connection.execute(
        "SELECT model_key, revision FROM embeddings_meta WHERE memory_id = ?", (memory["id"],)
    ).fetchone()
    assert row["model_key"] == f"{EMBEDDING_MODEL_ID}@{EMBEDDING_MODEL_REVISION}"
    assert row["revision"] == EMBEDDING_MODEL_REVISION


def test_promoted_embedding_model_drives_vector_reads(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("model-specific vector", source={"kind": "test"}, status="active")
    registered = store.register_embedding_model("small-model", "r2", dimension=8)
    store.promote_embedding_model(registered["model_key"])
    store.store_embedding(memory["id"], _unit_vector(8, 0), model_id="small-model")

    results = store.hybrid_retrieve("model-specific", query_vector=_unit_vector(8, 0), limit=5)

    assert results["channel_status"]["vector"] == "available"
    assert results["results"][0]["id"] == memory["id"]
    store.close()
