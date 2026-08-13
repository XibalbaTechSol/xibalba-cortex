from __future__ import annotations

from pathlib import Path

import pytest

from xibalba_cortex.store import GraphStore


def test_add_alias_then_resolve_by_alias_returns_same_entity(tmp_path: Path):
    store = GraphStore(tmp_path)
    entity = store._get_or_create_entity("Xibalba Solutions LLC", "organization")
    store.add_entity_alias(entity["id"], "Xibalba Solutions")

    resolved = store.resolve_entity_alias("Xibalba Solutions")
    assert resolved == entity["id"]
    # Case/whitespace-insensitive, matching _normalize_name's own behavior.
    assert store.resolve_entity_alias("  xibalba solutions  ") == entity["id"]


def test_get_or_create_entity_does_not_duplicate_a_known_alias(tmp_path: Path):
    store = GraphStore(tmp_path)
    entity = store._get_or_create_entity("Xibalba Solutions LLC", "organization")
    store.add_entity_alias(entity["id"], "Xibalba Solutions")

    same = store._get_or_create_entity("Xibalba Solutions", "organization")
    assert same["id"] == entity["id"]

    all_entities = store._connection.execute("SELECT COUNT(*) AS c FROM entities").fetchone()
    assert all_entities["c"] == 1


def test_link_entities_resolves_aliased_subject_to_the_same_node(tmp_path: Path):
    store = GraphStore(tmp_path)
    memory = store.store_memory("Xibalba Solutions LLC operates Xibalba Shield.", source={"kind": "test"}, status="active")
    canonical = store._get_or_create_entity("Xibalba Solutions LLC", "organization")
    store.add_entity_alias(canonical["id"], "Xibalba Solutions")

    store.link_entities("Xibalba Solutions", "operates", "Xibalba Shield", evidence_memory_id=memory["id"])

    neighbors = store.neighbors("Xibalba Solutions LLC")
    assert any(edge["predicate"] == "operates" and edge["object"] == "Xibalba Shield" for edge in neighbors["edges"])


def test_add_entity_alias_rejects_unknown_entity(tmp_path: Path):
    store = GraphStore(tmp_path)
    with pytest.raises(KeyError):
        store.add_entity_alias("not-a-real-entity-id", "Some Alias")


def test_add_entity_alias_is_idempotent(tmp_path: Path):
    store = GraphStore(tmp_path)
    entity = store._get_or_create_entity("Xibalba Solutions LLC", "organization")
    store.add_entity_alias(entity["id"], "Xibalba Solutions", confidence=0.7)
    store.add_entity_alias(entity["id"], "Xibalba Solutions", confidence=0.95)

    rows = store._connection.execute(
        "SELECT COUNT(*) AS c FROM entity_aliases WHERE entity_id = ?", (entity["id"],)
    ).fetchone()
    assert rows["c"] == 1
