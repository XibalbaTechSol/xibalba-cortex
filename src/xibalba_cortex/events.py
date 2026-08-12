"""Portable append-only event and Merkle primitives.

This module is deliberately independent of SQLite.  The store may persist these
records, while another implementation can replay and verify the same vectors.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from .canonical import CANONICAL_JSON_V1, canonical_json_bytes, sha256_prefixed

EVENT_SCHEMA_V1 = "xibalba.memory.event.v1"
EVIDENCE_CLASSES = frozenset(
    {"declared_intent", "observed_event", "extracted_proposition", "inference", "summary", "policy"}
)
VERIFICATION_DIMENSIONS = frozenset(
    {"content", "source", "signature", "lineage", "authorization", "completeness"}
)


@dataclass(frozen=True)
class Event:
    sequence: int
    event_type: str
    subject_id: str
    payload: Mapping[str, Any]
    previous_hash: str | None = None
    evidence_class: str = "observed_event"

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.evidence_class not in EVIDENCE_CLASSES:
            raise ValueError(f"invalid evidence class: {self.evidence_class}")

    def envelope(self) -> dict[str, Any]:
        return {
            "schema": EVENT_SCHEMA_V1,
            "canonicalization": CANONICAL_JSON_V1,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "subject_id": self.subject_id,
            "payload": dict(self.payload),
            "previous_hash": self.previous_hash,
            "evidence_class": self.evidence_class,
        }

    def digest(self) -> str:
        return sha256_prefixed(canonical_json_bytes(self.envelope()))


def append_event(
    events: Iterable[Event],
    event_type: str,
    subject_id: str,
    payload: Mapping[str, Any],
    *,
    evidence_class: str = "observed_event",
) -> Event:
    prior = list(events)
    previous = prior[-1].digest() if prior else None
    return Event(len(prior), event_type, subject_id, dict(payload), previous, evidence_class)


def verify_events(events: Iterable[Event]) -> dict[str, Any]:
    expected_sequence = 0
    previous: str | None = None
    for event in events:
        if event.sequence != expected_sequence or event.previous_hash != previous:
            return {"valid": False, "sequence": expected_sequence, "reason": "ordering_or_parent"}
        previous = event.digest()
        expected_sequence += 1
    return {"valid": True, "length": expected_sequence, "head": previous}


def ingest_signed_bcc(
    envelope: Mapping[str, Any],
    verify_signature: Callable[[Mapping[str, Any]], bool],
) -> dict[str, Any]:
    """Validate a signed BCC envelope without accepting or persisting private keys."""
    required = {"agent_id", "nonce", "timestamp", "signature"}
    missing = sorted(required - envelope.keys())
    if missing:
        raise ValueError(f"missing BCC fields: {', '.join(missing)}")
    if not isinstance(envelope["nonce"], int) or envelope["nonce"] < 0:
        raise ValueError("BCC nonce must be a non-negative integer")
    if not envelope["signature"] or not verify_signature(envelope):
        raise ValueError("invalid BCC signature")
    return {
        "event_type": "bcc_ingested",
        "agent_id": envelope["agent_id"],
        "nonce": envelope["nonce"],
        "signature": envelope["signature"],
        "payload": dict(envelope),
        "private_key_stored": False,
    }


def merkle_parent(left: str, right: str) -> str:
    ordered = sorted((left.removeprefix("sha256:"), right.removeprefix("sha256:")))
    left_bytes = bytes.fromhex(ordered[0])
    right_bytes = bytes.fromhex(ordered[1])
    return hashlib.sha256(left_bytes + right_bytes).hexdigest()


def merkle_root(leaves: Iterable[str]) -> str | None:
    level = [leaf.removeprefix("sha256:") for leaf in leaves]
    if not level:
        return None
    while len(level) > 1:
        level = [merkle_parent(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)] + (
            [level[-1]] if len(level) % 2 else []
        )
    return "sha256:" + level[0]


def merkle_proof(leaves: list[str], index: int) -> dict[str, Any]:
    if not 0 <= index < len(leaves):
        raise IndexError(index)
    level = [leaf.removeprefix("sha256:") for leaf in leaves]
    proof: list[dict[str, str]] = []
    position = index
    while len(level) > 1:
        sibling = position - 1 if position % 2 else position + 1
        if sibling < len(level):
            proof.append({"hash": level[sibling]})
        level = [merkle_parent(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)] + (
            [level[-1]] if len(level) % 2 else []
        )
        position //= 2
    return {"leaf": leaves[index], "index": index, "siblings": proof, "root": "sha256:" + level[0]}


def verify_merkle_proof(proof: Mapping[str, Any]) -> bool:
    current = str(proof["leaf"]).removeprefix("sha256:")
    for sibling in proof["siblings"]:
        current = merkle_parent(current, sibling["hash"])
    return "sha256:" + current == proof["root"]
