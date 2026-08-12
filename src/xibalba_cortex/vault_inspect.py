"""Read-only inspection of the real Integrity Protocol TrustVault.

Independent of integrity-sdk (not a dependency of this project) -- parses the same
leaves.jsonl/anchors.jsonl format documented in
INTEGRITY-LATEST/integrity-sdk/integrity_sdk/vault.py, and recomputes each leaf's
domain-separated Keccak hash rather than trusting the stored leaf_hash field, so a
tampered-with-but-consistent-looking JSON Lines file is still caught.

This does NOT verify memories. See spec/xibalba-cortex-v1.md section 6.3 and
docs/operations/resource-readiness.md's 2026-08-05 correction: a memory's content_hash has no
matching leaf_hash in this vault, because leaf_hash commits to (kind, task_id, commit_sha,
test_result_hash, timestamp) -- development-process evidence, not arbitrary content. This module
exists to inspect that real evidence for its own sake, never as a stand-in for memory
verification.
"""
from __future__ import annotations

import json
from pathlib import Path

from eth_hash.auto import keccak

_SUPPORTED_LEAF_KINDS = {"commit"}


def _leaf_preimage(
    kind: str, task_id: str, commit_sha: str, test_result_hash: str, timestamp: int
) -> bytes:
    if kind not in _SUPPORTED_LEAF_KINDS:
        raise ValueError(
            f"unsupported leaf kind: {kind!r} (only {_SUPPORTED_LEAF_KINDS} defined in the real "
            "vault format as of this writing)"
        )
    preimage = "|".join(
        ["integrity.vault.commit.v1", task_id, commit_sha, test_result_hash, str(timestamp)]
    )
    return preimage.encode("utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def inspect_leaf(leaf_hash: str, vault_dir: str | Path) -> dict[str, object]:
    """Check whether `leaf_hash` (0x-prefixed hex) is present in, and anchored by, a real vault.

    Read-only: never writes to the vault, never used as this system's own hot index. `vault_dir`
    is the per-agent directory (`~/.integrity/vault/<agent_id>/` in the real vault's own layout).
    """
    vault_dir = Path(vault_dir).expanduser()

    try:
        leaves = _read_jsonl(vault_dir / "leaves.jsonl")
    except (OSError, json.JSONDecodeError) as exc:
        return {"found": False, "anchored": False, "error": f"could not read leaves.jsonl: {exc}"}

    matched_index: int | None = None
    matched_leaf: dict[str, object] | None = None
    recomputed_hash_matches: bool | None = None
    for index, leaf in enumerate(leaves):
        if leaf.get("leaf_hash") == leaf_hash:
            matched_index = index
            matched_leaf = leaf
            try:
                preimage = _leaf_preimage(
                    str(leaf["kind"]),
                    str(leaf["task_id"]),
                    str(leaf["commit_sha"]),
                    str(leaf["test_result_hash"]),
                    int(leaf["timestamp"]),
                )
                recomputed_hash_matches = ("0x" + keccak(preimage).hex()) == leaf_hash
            except (KeyError, ValueError):
                recomputed_hash_matches = False
            break

    if matched_leaf is None or matched_index is None:
        return {"found": False, "anchored": False, "leaf": None, "anchor": None}

    try:
        anchors = _read_jsonl(vault_dir / "anchors.jsonl")
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "found": True,
            "anchored": False,
            "leaf": matched_leaf,
            "recomputed_hash_matches": recomputed_hash_matches,
            "anchor": None,
            "error": f"could not read anchors.jsonl: {exc}",
        }

    covering_anchor = next(
        (a for a in anchors if int(a.get("leaves_through", 0)) > matched_index), None
    )
    return {
        "found": True,
        "anchored": covering_anchor is not None,
        "leaf": matched_leaf,
        "recomputed_hash_matches": recomputed_hash_matches,
        "anchor": covering_anchor,
    }
