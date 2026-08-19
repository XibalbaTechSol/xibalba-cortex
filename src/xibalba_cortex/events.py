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


# Domain-separated, order-committing Merkle construction.
#
# `merkle_root`/`merkle_proof` above have two properties that make them unsuitable for
# cross-domain roots (projection checkpoints, retrieval traces): (1) they hash only the leaf
# values -- nothing about *which kind* of root this is enters the preimage, so a projection
# root and a trace root over an identical leaf set are byte-identical; (2) `merkle_parent`
# sorts its two children before hashing, so the root commits to a *multiset* of leaves, not
# an ordered sequence -- two permutations of the same leaves produce the same root, which
# defeats reorder detection.
#
# The functions below wrap each leaf's hash with a domain tag and its position before handing
# it to the existing (untouched) tree-building primitives. Because the position is baked into
# each leaf's own hash, permuting the input list changes which leaf occupies which position,
# which changes the leaf *set* itself -- so the resulting root differs even though the
# underlying `merkle_parent` still sorts pairs. Nothing above this line changes: existing
# `merkle_root`/`merkle_proof` roots (e.g. session exchange chains) stay verifiable exactly
# as before.
MERKLE_DOMAINS: dict[str, bytes] = {
    "projection_checkpoint": b"xibalba.projection_checkpoint.v1",
    "retrieval_trace": b"xibalba.retrieval_trace.v1",
    "exchange_batch": b"xibalba.exchange_batch.v2",
    # docs/plans/2026-08-18-phase-h5-backup-reconciliation-proposal.md: same canonical
    # (table, columns) sources projection_checkpoint already uses, but a DISTINCT domain
    # tag -- a live-vs-backup-file root must never collide with a live-vs-projection root
    # even when the underlying leaves happen to be identical, or domain separation is void.
    "backup.memories": b"xibalba.backup.memories.v1",
    "backup.entities": b"xibalba.backup.entities.v1",
    "backup.relations": b"xibalba.backup.relations.v1",
}


def _domain_tag(domain: str) -> bytes:
    try:
        return MERKLE_DOMAINS[domain]
    except KeyError:
        raise ValueError(f"unknown Merkle domain: {domain!r}") from None


def domain_leaf(domain: str, index: int, payload_hash: str) -> str:
    """A domain- and position-committed leaf hash for one item's payload hash."""
    tag = _domain_tag(domain)
    digest = hashlib.sha256(
        tag + b"\x00leaf\x00" + index.to_bytes(8, "big") + bytes.fromhex(str(payload_hash).removeprefix("sha256:"))
    ).hexdigest()
    return "sha256:" + digest


def _wrap_domain_root(domain: str, inner_root: str) -> str:
    tag = _domain_tag(domain)
    digest = hashlib.sha256(tag + b"\x00root\x00" + bytes.fromhex(inner_root.removeprefix("sha256:"))).hexdigest()
    return "sha256:" + digest


def domain_merkle_root(payload_hashes: Iterable[str], *, domain: str) -> str | None:
    leaves = [domain_leaf(domain, index, payload_hash) for index, payload_hash in enumerate(payload_hashes)]
    inner = merkle_root(leaves)
    if inner is None:
        return None
    return _wrap_domain_root(domain, inner)


def domain_merkle_proof(payload_hashes: list[str], index: int, *, domain: str) -> dict[str, Any]:
    leaves = [domain_leaf(domain, i, payload_hash) for i, payload_hash in enumerate(payload_hashes)]
    proof = merkle_proof(leaves, index)
    return {
        "domain": domain,
        "index": index,
        "payload_hash": payload_hashes[index],
        "siblings": proof["siblings"],
        "root": _wrap_domain_root(domain, proof["root"]),
    }


def verify_domain_merkle_proof(proof: Mapping[str, Any]) -> bool:
    """Return whether a domain proof is valid; malformed untrusted proofs fail closed."""
    try:
        domain = str(proof["domain"])
        index = int(proof["index"])
        if index < 0:
            return False
        leaf = domain_leaf(domain, index, str(proof["payload_hash"]))
        current = leaf.removeprefix("sha256:")
        siblings = proof["siblings"]
        if not isinstance(siblings, list):
            return False
        for sibling in siblings:
            if not isinstance(sibling, Mapping):
                return False
            current = merkle_parent(current, str(sibling["hash"]))
        return _wrap_domain_root(domain, "sha256:" + current) == proof["root"]
    except (KeyError, TypeError, ValueError, OverflowError, IndexError):
        return False
