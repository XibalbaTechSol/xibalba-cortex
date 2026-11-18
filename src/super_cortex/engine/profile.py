"""Namespace profile: what is known about a namespace at a glance (Supermemory `/profile` shape).

- `dynamic`: the most recent current memories, newest first, each prefixed with its date the way
  Supermemory does ("[2026-11-18] ..."), so agents reading the profile see recency.
- `static`: standing context that rarely changes: preferences and rules.
- `buckets`: memories of the kinds a bucket names. Unknown bucket names come back empty and are
  listed under `unsupportedBuckets`, not dropped silently.

Buckets select by the `kind` extraction assigns, never by embedding similarity: bge-small cannot
tell a preference from a fact on the same topic. Only `latest` memories appear; superseded,
candidate and forgotten ones never do. Every item keeps its provenance (it is metadata).
"""

from __future__ import annotations

from typing import Any

from .store import EngineStore

BUCKET_KINDS: dict[str, tuple[str, ...]] = {
    "preferences": ("preference",),
    "rules": ("rule",),
    "goals": ("goal",),
    "decisions": ("decision",),
    "events": ("event",),
    "facts": ("fact",),
}
STATIC_KINDS = ("preference", "rule")
DEFAULT_BUCKETS = ("preferences",)
DYNAMIC_LIMIT = 100
BUCKET_LIMIT = 50


def _ids(store: EngineStore, namespace: str, kinds: tuple[str, ...] | None, limit: int) -> list[str]:
    where, args = "namespace = ? AND status = 'latest'", [namespace]
    if kinds:
        where += f" AND kind IN ({','.join('?' for _ in kinds)})"
        args += list(kinds)
    with store._lock:
        return [r["id"] for r in store._conn.execute(
            f"SELECT id FROM memories WHERE {where} ORDER BY created_at DESC, id LIMIT ?", (*args, limit))]


def _items(store: EngineStore, ids: list[str], dated: bool = False) -> list[dict[str, Any]]:
    found = store.get_memories(ids)
    out = []
    for memory_id in ids:
        m = found.get(memory_id)
        if m is None:
            continue
        text = f"[{m['createdAt'][:10]}] {m['memory']}" if dated else m["memory"]
        out.append({"id": m["id"], "memory": text, "kind": m["kind"], "isInference": m["isInference"],
                    "updatedAt": m["updatedAt"], "dataClass": m["dataClass"], "derivedFrom": m["derivedFrom"],
                    "generator": m["generator"]})
    return out


def build_profile(store: EngineStore, namespace: str, buckets: list[str] | None = None,
                  dynamic_limit: int = DYNAMIC_LIMIT) -> dict[str, Any]:
    names = [str(b).strip().lower() for b in (buckets or DEFAULT_BUCKETS) if str(b).strip()]
    bucket_items = {name: _items(store, _ids(store, namespace, BUCKET_KINDS[name], BUCKET_LIMIT))
                    if name in BUCKET_KINDS else [] for name in names}
    result: dict[str, Any] = {
        "profile": {
            "static": _items(store, _ids(store, namespace, STATIC_KINDS, BUCKET_LIMIT)),
            "dynamic": _items(store, _ids(store, namespace, None, max(1, min(dynamic_limit, 500))), dated=True),
            "buckets": bucket_items,
        },
    }
    unsupported = [n for n in names if n not in BUCKET_KINDS]
    if unsupported:
        result["unsupportedBuckets"] = unsupported
    return result
