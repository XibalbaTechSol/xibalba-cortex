from xibalba_cortex.store import GraphStore


def test_structured_bundle_round_trip_preserves_graph_and_provenance(tmp_path):
    source = GraphStore(tmp_path / "source")
    memory = source.store_memory(
        "Alice works at Cortex",
        source={"kind": "direct_user", "agent_id": "did:integrity:agent-a", "locator": "import-test"},
        status="confirmed",
        evidence_class="observed_event",
    )
    relation = source.link_entities("Alice", "works_at", "Cortex", evidence_memory_id=memory["id"])
    bundle = source.export_structured_bundle()
    target = GraphStore(tmp_path / "target")
    counts = target.import_structured_bundle(bundle)
    assert counts["memories"] == 1
    assert target.get_memory(memory["id"])["status"] == "confirmed"
    assert target.memory_events(memory["id"])[0]["node_id"] == source.memory_events(memory["id"])[0]["node_id"]
    assert target.list_relations()[0]["id"] == relation["id"]
    assert target.list_entities(limit=10)
    replay = target.import_structured_bundle(bundle)
    assert replay["memories"] == 0
    source.close()
    target.close()
