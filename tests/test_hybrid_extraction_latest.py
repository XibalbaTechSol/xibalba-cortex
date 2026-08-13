from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from xibalba_cortex.events import domain_merkle_root
from xibalba_cortex.hermes_worker import process_extraction_tasks, validate_extraction_result
from xibalba_cortex.projection_reconcile import compare_roots, reconcile_projection
from xibalba_cortex.store import GraphStore


def test_hybrid_retrieval_persists_trace_with_provenance_and_root(tmp_path: Path):
    store = GraphStore(tmp_path / "graph")
    first = store.store_memory("Cortex uses Hermes for controlled extraction.", source={"kind": "test", "observed_at": "2026-08-13T10:00:00Z"}, status="confirmed")
    second = store.store_memory("The viewer displays retrieval provenance.", source={"kind": "test", "observed_at": "2026-08-14T10:00:00Z"}, status="confirmed")
    result = store.hybrid_retrieve("Hermes extraction", limit=5)
    assert result["results"]
    assert {"lexical", "vector", "graph", "temporal"}.issubset(result["signals"])
    trace = store.get_retrieval_trace(result["trace_id"])
    assert trace["root_hash"].startswith("sha256:")
    assert trace["results"][0]["memory_id"] in {first["id"], second["id"]}
    assert trace["results"][0]["provenance"]["content_hash"].startswith("sha256:")


def test_merkle_root_comparison_and_projection_reconciliation():
    left = {"root_profile": "xibalba.projection_checkpoint.v1", "leaf_hashes": ["sha256:" + "1" * 64]}
    left["root_hash"] = domain_merkle_root(left["leaf_hashes"], domain="projection_checkpoint")
    right = {"root_profile": "xibalba.projection_checkpoint.v1", "leaf_hashes": ["sha256:" + "1" * 64, "sha256:" + "2" * 64]}
    right["root_hash"] = domain_merkle_root(right["leaf_hashes"], domain="projection_checkpoint")
    comparison = compare_roots(left, right)
    assert comparison["equal"] is False
    assert comparison["missing_on_left"] == ["sha256:" + "2" * 64]
    reconciliation = reconcile_projection(left, right)
    assert reconciliation["action"] == "rebuild_projection"
    assert reconciliation["canonical"] == "left"


def test_hermes_extraction_vertical_slice_claims_validates_and_completes(tmp_path: Path):
    store = GraphStore(tmp_path / "graph")
    memory = store.store_memory(
        "Xibalba Cortex uses Hermes to extract entities from bounded evidence.",
        source={"kind": "test"}, status="confirmed",
    )
    task = store.request_inference_task(
        "extract_entities", subject_type="memory", subject_id=memory["id"],
        input_payload={"source_content_hash": memory["content_hash"]}, idempotency_key="extract-e2e",
    )

    def runner(prompt: str) -> str:
        assert "Xibalba Cortex" in prompt
        return json.dumps({
            "schema_version": "xibalba.entities.v1",
            "input_snapshot_hash": memory["content_hash"],
            "entities": [{"name": "Hermes", "entity_type": "software", "evidence_quote": "uses Hermes", "confidence": 0.95}],
        })

    result = process_extraction_tasks(store, runner=runner, worker_id="hermes-test")
    assert result == {"processed": 1, "completed": 1, "failed": 0}
    completed = store.get_inference_task(task["id"])
    assert completed["status"] == "completed"
    assert completed["output"]["entities"][0]["name"] == "Hermes"


def test_extraction_result_rejects_wrong_snapshot_hash():
    with pytest.raises(ValueError, match="input_snapshot_hash"):
        validate_extraction_result({"schema_version": "xibalba.entities.v1", "input_snapshot_hash": "sha256:" + "0" * 64, "entities": []}, expected_hash="sha256:" + "1" * 64, kind="entities")
