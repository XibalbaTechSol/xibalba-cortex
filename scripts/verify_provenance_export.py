#!/usr/bin/env python3
"""Independently verify a Cortex provenance-export bundle's Merkle commitment.

Deliberately has ZERO dependency on the xibalba_cortex package -- only the
Python standard library. This is the whole point: Gate 6 of Cortex's
production readiness plan requires a verification procedure "usable by
someone outside this repo's own operator tooling," so an external auditor or
a tenant can confirm a bundle's root_hash really commits to its memories
without installing this repo or trusting its internals. See
docs/operations/provenance-export-verification.md for the full documented
algorithm this reimplements from scratch.

Usage:
    python3 verify_provenance_export.py bundle.json
    python3 verify_provenance_export.py < bundle.json

Exit code 0 if the bundle's root_hash is verified, 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys

DOMAIN_TAG = b"xibalba.provenance_export.v1"
EXPECTED_SCHEMA_VERSION = "xibalba.provenance_export.v1"


def canonical_json(value: object) -> str:
    """Must byte-for-byte match GraphStore._canonical_json (store.py)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def leaf_hash_for_memory(memory: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(memory).encode()).hexdigest()


def _hex(hash_with_prefix: str) -> bytes:
    return bytes.fromhex(hash_with_prefix.removeprefix("sha256:"))


def domain_leaf(index: int, payload_hash: str) -> str:
    digest = hashlib.sha256(
        DOMAIN_TAG + b"\x00leaf\x00" + index.to_bytes(8, "big") + _hex(payload_hash)
    ).hexdigest()
    return "sha256:" + digest


def merkle_parent(left: str, right: str) -> str:
    ordered = sorted((left.removeprefix("sha256:"), right.removeprefix("sha256:")))
    return hashlib.sha256(bytes.fromhex(ordered[0]) + bytes.fromhex(ordered[1])).hexdigest()


def merkle_root(leaves: list[str]) -> str | None:
    level = [leaf.removeprefix("sha256:") for leaf in leaves]
    if not level:
        return None
    while len(level) > 1:
        level = [merkle_parent(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)] + (
            [level[-1]] if len(level) % 2 else []
        )
    return "sha256:" + level[0]


def wrap_domain_root(inner_root: str) -> str:
    digest = hashlib.sha256(DOMAIN_TAG + b"\x00root\x00" + _hex(inner_root)).hexdigest()
    return "sha256:" + digest


def verify_bundle(bundle: dict) -> tuple[bool, list[str]]:
    """Returns (verified, problems). problems is empty iff verified is True."""
    problems: list[str] = []

    schema_version = bundle.get("schema_version")
    if schema_version != EXPECTED_SCHEMA_VERSION:
        problems.append(f"unexpected schema_version {schema_version!r}, expected {EXPECTED_SCHEMA_VERSION!r}")
        return False, problems

    memories = bundle.get("memories")
    claimed_leaf_hashes = bundle.get("leaf_hashes")
    claimed_root_hash = bundle.get("root_hash")
    if not isinstance(memories, list) or not isinstance(claimed_leaf_hashes, list):
        problems.append("bundle must contain list fields 'memories' and 'leaf_hashes'")
        return False, problems
    if len(memories) != len(claimed_leaf_hashes):
        problems.append(f"memories count ({len(memories)}) does not match leaf_hashes count ({len(claimed_leaf_hashes)})")
        return False, problems

    recomputed_leaf_hashes: list[str] = []
    for index, memory in enumerate(memories):
        recomputed = leaf_hash_for_memory(memory)
        recomputed_leaf_hashes.append(recomputed)
        claimed = claimed_leaf_hashes[index]
        if recomputed != claimed:
            problems.append(
                f"leaf {index} (memory_id={memory.get('id', '?')!r}): recomputed leaf hash {recomputed} "
                f"does not match bundle's claimed leaf hash {claimed} -- this memory's content does not "
                f"match what the bundle claims was committed"
            )

    if problems:
        return False, problems

    domain_leaves = [domain_leaf(index, payload_hash) for index, payload_hash in enumerate(recomputed_leaf_hashes)]
    inner_root = merkle_root(domain_leaves)
    recomputed_root_hash = wrap_domain_root(inner_root) if inner_root is not None else None

    if recomputed_root_hash != claimed_root_hash:
        problems.append(
            f"recomputed root_hash {recomputed_root_hash} does not match bundle's claimed root_hash "
            f"{claimed_root_hash} -- every individual memory hashed correctly, but the commitment "
            f"over the whole set does not, meaning the bundle was reordered, truncated, or the "
            f"root_hash field itself was tampered with"
        )
        return False, problems

    return True, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bundle_path", nargs="?", help="path to a provenance-export bundle JSON file; reads stdin if omitted")
    args = parser.parse_args()

    raw = sys.stdin.read() if args.bundle_path is None else open(args.bundle_path, encoding="utf-8").read()
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"FAIL: input is not valid JSON: {exc}", file=sys.stderr)
        return 1

    verified, problems = verify_bundle(bundle)
    if verified:
        print(f"VERIFIED: root_hash {bundle['root_hash']} independently confirmed over {len(bundle['memories'])} memories")
        return 0
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
