"""Namespace profile: what is known about a namespace at a glance (Supermemory `/profile` shape).

- `dynamic`: the most recent current memories, newest first, each prefixed with its date the way
  Supermemory does ("[2026-11-18] ..."), so agents reading the profile see recency. The date is when
  the newest attached source was recorded (`metadata.recordCreatedAt` or `metadata.createdAt`, if
  it is a date; else when the document arrived), never when extraction ran: a backfill extracts
  old records today, and dating them today would make stale facts look fresh.
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


_DATE = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*"
# A client-supplied record time counts only if it looks like a date; anything else falls back to
# when the engine received the document, so free text in metadata cannot reorder the profile.
_SOURCE_TIME = f"""CASE
    WHEN json_extract(d.metadata_json, '$.recordCreatedAt') GLOB '{_DATE}' THEN json_extract(d.metadata_json, '$.recordCreatedAt')
    WHEN json_extract(d.metadata_json, '$.createdAt') GLOB '{_DATE}' THEN json_extract(d.metadata_json, '$.createdAt')
    ELSE d.created_at END"""


def _observed(store: EngineStore, namespace: str, limit: int) -> list[tuple[str, str]]:
    """Current memories newest-first by their newest attached source's record time."""
    with store._lock:
        rows = store._conn.execute(
            f"""SELECT m.id, COALESCE(MAX({_SOURCE_TIME}), m.created_at) AS observed
                FROM memories m
                LEFT JOIN memory_sources s ON s.memory_id = m.id AND s.detached_at IS NULL
                LEFT JOIN documents d ON d.namespace = s.namespace AND d.id = s.doc_id
                WHERE m.namespace = ? AND m.status = 'latest'
                GROUP BY m.id ORDER BY observed DESC, m.id LIMIT ?""",
            (namespace, limit)).fetchall()
    return [(r["id"], r["observed"]) for r in rows]


def _items(store: EngineStore, ids: list[str], observed: dict[str, str] | None = None) -> list[dict[str, Any]]:
    found = store.get_memories(ids)
    out = []
    for memory_id in ids:
        m = found.get(memory_id)
        if m is None:
            continue
        item = {"id": m["id"], "memory": m["memory"], "kind": m["kind"], "isInference": m["isInference"],
                "updatedAt": m["updatedAt"], "dataClass": m["dataClass"], "derivedFrom": m["derivedFrom"],
                "generator": m["generator"]}
        if observed is not None:
            item["observedAt"] = observed[memory_id]
            item["memory"] = f"[{observed[memory_id][:10]}] {m['memory']}"
        out.append(item)
    return out


def build_profile(store: EngineStore, namespace: str, buckets: list[str] | None = None,
                  dynamic_limit: int = DYNAMIC_LIMIT) -> dict[str, Any]:
    names = [str(b).strip().lower() for b in (buckets or DEFAULT_BUCKETS) if str(b).strip()]
    bucket_items = {name: _items(store, _ids(store, namespace, BUCKET_KINDS[name], BUCKET_LIMIT))
                    if name in BUCKET_KINDS else [] for name in names}
    dated = _observed(store, namespace, max(1, min(dynamic_limit, 500)))
    result: dict[str, Any] = {
        "profile": {
            "static": _items(store, _ids(store, namespace, STATIC_KINDS, BUCKET_LIMIT)),
            "dynamic": _items(store, [i for i, _ in dated], dict(dated)),
            "buckets": bucket_items,
        },
    }
    unsupported = [n for n in names if n not in BUCKET_KINDS]
    if unsupported:
        result["unsupportedBuckets"] = unsupported
    return result
