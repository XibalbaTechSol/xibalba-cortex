import pytest

from xibalba_cortex.providers import (
    EvidenceScope,
    ExtractedEntity,
    ExtractedRelation,
    InferenceTaskContract,
    NativeHarnessInferenceProvider,
    validate_extraction_output,
)
from xibalba_cortex.store import GraphStore


def test_bounded_evidence_and_typed_extraction_contracts_validate():
    scope = EvidenceScope(subject_ids=("memory:one",), max_items=4, max_bytes=2048, max_depth=1)
    contract = InferenceTaskContract(evidence_limits=scope)
    assert contract.as_dict()["evidence_limits"]["max_bytes"] == 2048

    entity = ExtractedEntity("Hermes", "software", "Hermes worker", 0.9)
    entity.validate()
    relation = ExtractedRelation("Hermes", "executes", "task", "Hermes executes task", 0.8)
    relation.validate()
    result = validate_extraction_output(
        {"schema_version": "xibalba.entities.v1", "input_snapshot_hash": "sha256:" + "c" * 64,
         "entities": [{"name": "Hermes", "entity_type": "software", "evidence_quote": "Hermes worker", "confidence": 0.9}]},
        kind="entities",
    )
    assert result["entities"][0]["name"] == "Hermes"


def test_typed_extraction_rejects_missing_evidence_quote():
    with pytest.raises(ValueError, match="invalid entities item"):
        validate_extraction_output(
            {"schema_version": "xibalba.entities.v1", "input_snapshot_hash": "sha256:" + "c" * 64,
             "entities": [{"name": "Hermes", "entity_type": "software", "evidence_quote": "", "confidence": 0.9}]},
            kind="entities",
        )


def test_inference_task_contract_serializes_explicit_evidence_boundary():
    contract = InferenceTaskContract(
        evidence_scope=("memory:abc", "exchange:def"),
        input_snapshot_hash="sha256:" + "a" * 64,
        output_schema="xibalba.entities.v1",
        promotion_policy="review_required",
        worker_runtime="hermes",
    )

    assert contract.as_dict() == {
        "schema_version": "xibalba.inference.task.v1",
        "evidence_scope": ["memory:abc", "exchange:def"],
        "input_snapshot_hash": "sha256:" + "a" * 64,
        "output_schema": "xibalba.entities.v1",
        "promotion_policy": "review_required",
        "worker_runtime": "hermes",
    }


def test_inference_task_contract_rejects_invalid_snapshot_hash():
    with pytest.raises(ValueError, match="input_snapshot_hash"):
        InferenceTaskContract(input_snapshot_hash="not-a-hash").validate()


def test_inference_task_failure_metadata_is_exposed(tmp_path):
    store = GraphStore(tmp_path / "graph")
    task = store.request_inference_task(
        "extract_entities", subject_type="memory", subject_id="m", input_payload={}
    )
    claimed = store.claim_inference_task(task["id"], claimed_by="worker")
    completed = store.complete_inference_task(
        task["id"], error="timeout", claimed_by="worker", claim_token=claimed["claim_token"]
    )
    assert completed["status"] == "failed"
    assert completed["failure_class"] == "transient"
    assert completed["dead_letter_reason"] is None
    assert completed["retry_after"] is not None
    store.close()


def test_inference_task_exhaustion_records_dead_letter_reason(tmp_path):
    store = GraphStore(tmp_path / "graph")
    task = store.request_inference_task(
        "extract_entities", subject_type="memory", subject_id="m", input_payload={}
    )
    with store._lock:
        store._connection.execute(
            "UPDATE memory_inference_tasks SET status='claimed', claim_owner='w', claim_token='t', lease_expires_at=datetime('now','-1 second'), attempt_count=3 WHERE id=?",
            (task["id"],),
        )
    result = store.requeue_expired_inference_tasks(max_attempts=3)
    assert result["dead_lettered"] == 1
    final = store.get_inference_task(task["id"])
    assert final["dead_letter_reason"]
    store.close()
def test_inference_task_contract_is_persisted_without_breaking_legacy_input(tmp_path):
    store = GraphStore(tmp_path / "graph")
    contract = InferenceTaskContract(
        evidence_scope=("memory:source",),
        input_snapshot_hash="sha256:" + "b" * 64,
        output_schema="xibalba.entities.v1",
        worker_runtime="hermes",
    )
    task = store.request_inference_task(
        "extract_entities",
        subject_type="memory",
        subject_id="memory-1",
        input_payload={"content": "untrusted"},
        contract=contract,
    )

    assert task["input"]["content"] == "untrusted"
    assert task["input"]["_contract"]["evidence_scope"] == ["memory:source"]
    assert task["input"]["_contract"]["input_snapshot_hash"].startswith("sha256:")
    store.close()


def test_legacy_inference_task_gets_default_contract(tmp_path):
    store = GraphStore(tmp_path / "graph")
    task = store.request_inference_task(
        "extract_memory_metadata",
        subject_type="memory",
        subject_id="memory-legacy",
        input_payload={"fields": ["preference"]},
    )

    assert task["input"]["_contract"]["schema_version"] == "xibalba.inference.task.v1"
    assert task["input"]["_contract"]["promotion_policy"] == "review_required"
    store.close()


def test_native_harness_provider_executes_through_injected_runner():
    calls = []

    def runner(command, *, prompt, timeout):
        calls.append((command, prompt, timeout))
        return '{"ok":true}'

    provider = NativeHarnessInferenceProvider(harness="hermes", runner=runner)
    assert provider.infer("extract entities") == '{"ok":true}'
    assert calls[0][0] == ["hermes", "-z", "extract entities"]
    assert calls[0][2] == 120
