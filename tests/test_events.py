from xibalba_cortex.events import (
    Event,
    append_event,
    ingest_signed_bcc,
    merkle_proof,
    merkle_root,
    verify_events,
    verify_merkle_proof,
)


def test_event_replay_is_ordered_and_tamper_evident():
    events = [append_event([], "intent", "memory-1", {"action": "remember"}, evidence_class="declared_intent")]
    events.append(append_event(events, "outcome", "memory-1", {"ok": True}))
    assert verify_events(events)["valid"] is True
    events[1] = Event(1, "outcome", "memory-1", {"ok": False}, events[0].digest())
    assert verify_events(events)["valid"] is True
    events[1] = Event(1, "outcome", "memory-1", {"ok": False}, "sha256:forged")
    assert verify_events(events)["valid"] is False


def test_bcc_ingestion_requires_signature_and_never_stores_private_key():
    envelope = {"agent_id": "did:example:agent", "nonce": 3, "timestamp": 1, "signature": "0xabc"}
    result = ingest_signed_bcc(envelope, lambda value: value["signature"] == "0xabc")
    assert result["private_key_stored"] is False


def test_merkle_odd_leaf_promotion_and_inclusion_proof():
    leaves = [f"sha256:{i:064x}" for i in range(3)]
    proof = merkle_proof(leaves, 2)
    assert proof["root"] == merkle_root(leaves)
    assert verify_merkle_proof(proof)
