from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from .events import merkle_root


def _validate_checkpoint(value: Mapping[str, Any]) -> tuple[str, list[str]]:
    profile = value.get("root_profile")
    if profile != "xibalba.projection_checkpoint.v1":
        raise ValueError("root_profile must be xibalba.projection_checkpoint.v1")
    leaves = list(value.get("leaf_hashes") or [])
    if any(not isinstance(leaf, str) or not leaf.startswith("sha256:") for leaf in leaves):
        raise ValueError("leaf_hashes must contain sha256 hashes")
    expected = merkle_root(leaves)
    if value.get("root_hash") != expected:
        raise ValueError("root_hash does not match ordered leaf_hashes")
    return str(value["root_hash"]), leaves


def compare_roots(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    left_root, left_leaves = _validate_checkpoint(left)
    right_root, right_leaves = _validate_checkpoint(right)
    left_counts, right_counts = Counter(left_leaves), Counter(right_leaves)
    missing = list((right_counts - left_counts).elements())
    extra = list((left_counts - right_counts).elements())
    return {
        "equal": left_root == right_root and left_leaves == right_leaves,
        "left_root": left_root,
        "right_root": right_root,
        "missing_on_left": missing,
        "missing_on_right": extra,
        "reordered": not missing and not extra and left_leaves != right_leaves,
        "root_profile": "xibalba.projection_checkpoint.v1",
    }


def reconcile_projection(canonical: Mapping[str, Any], projection: Mapping[str, Any]) -> dict[str, Any]:
    comparison = compare_roots(canonical, projection)
    return {
        **comparison,
        "canonical": "left",
        "projection": "right",
        "action": "noop" if comparison["equal"] else "rebuild_projection",
    }
