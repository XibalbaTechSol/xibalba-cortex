"""Operational status the console reports: agent runtimes, background workers, ingest connectors.

Every function here is a READ over data the store already records. None of them starts, stops or
drives anything: a person watching the console must not be able to impersonate a worker (the claim and
complete protocol stays a machine protocol) or push events into a connector. They report; the
console links from each row to the Graph or Timeline filtered to that source.

What can honestly be said, and what cannot -- decisions, not accidents:

  * Runtimes. A runtime (claude, codex, hermes, ...) is known from what it left behind: the
    ``runtime`` field on memory sources and on tool-call telemetry. Counts are what was recorded, not
    a health check; a runtime that has not written lately is "quiet", not "down".
  * Workers. There is no heartbeat table (the v1 store schema is frozen, and a heartbeat would be a
    schema change). A worker's state is derived from the work it leaves in the queue: tasks claimed
    under a live lease, tasks finished, tasks failed, tasks waiting. A worker with nothing to do
    leaves nothing, so "no recent activity" with an empty queue is "idle", and with a waiting queue is
    "backlog" (nothing is picking the work up) -- different states, shown as such. ``not seen`` is
    never reported as ``idle``.
  * Connectors. The manifest says what each entry point is; the evidence is the sources it wrote.
    Only the connectors whose output is distinguishable in the store get per-connector counts; the
    rest are reported without a count rather than with a made-up one.

These take a read-only sqlite connection (GraphStore._read_connection) and plain data, so they are
unit-tested with fixtures and cannot write.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

# A claimed task whose lease is past is "stalled": its worker died or hung without releasing it.
# Waiting work with no activity for this long means nothing is servicing the queue.
BACKLOG_AFTER = timedelta(minutes=15)
RECENT = timedelta(hours=24)

# Which queue each worker family services. Mirrors inference_loop.process_inference_cycle.
WORKER_FAMILIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "extraction": ("Entity and relation extraction", ("extract_entities", "extract_relations", "extract_propositions")),
    "metadata": ("Memory metadata", ("extract_memory_metadata",)),
    "para": ("PARA classification", ("classify_para",)),
    "contradiction": ("Contradiction detection", ("detect_contradictions",)),
    "summary": ("Session summaries", ("summarize_session",)),
    "consolidation": ("Consolidation and duplicates", ("consolidate_memories", "find_duplicates")),
}


def parse_time(value: object) -> datetime | None:
    """SQLite stamps 'YYYY-MM-DD HH:MM:SS' (UTC); leases and some rows carry ISO-8601 with an offset."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _latest(*values: object) -> datetime | None:
    stamps = [t for t in (parse_time(v) for v in values) if t]
    return max(stamps) if stamps else None


# --- runtimes ----------------------------------------------------------------------------------------------

def runtime_overview(conn: sqlite3.Connection, invocations: Sequence[Mapping[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """One row per runtime seen in memory sources or in tool-call telemetry, busiest first.

    ``invocations`` is GraphStore.invocation_correlations() (the recent, correlated tool calls): its
    ``pre_tool.kernel_decision.verdict`` is the policy decision (allow / deny / ask) and its
    ``post_tool.outcome`` is how the call ended.
    """
    now = now or datetime.now(timezone.utc)
    rows: dict[str, dict[str, Any]] = {}

    def row(name: str) -> dict[str, Any]:
        return rows.setdefault(name, {
            "runtime": name, "sessions": set(), "memories": 0, "first_seen": None, "last_seen": None,
            "invocations": 0, "decisions": Counter(), "outcomes": Counter(), "denied": [],
        })

    for r in conn.execute(
        "SELECT json_extract(metadata_json, '$.runtime') AS runtime, session_id, COUNT(*) AS n, MIN(created_at) AS first, MAX(created_at) AS last "
        "FROM sources WHERE json_extract(metadata_json, '$.runtime') IS NOT NULL GROUP BY runtime, session_id"
    ):
        item = row(str(r["runtime"]))
        if r["session_id"]:
            item["sessions"].add(r["session_id"])
        item["memories"] += int(r["n"])
        item["first_seen"] = min(filter(None, [item["first_seen"], parse_time(r["first"])]), default=None)
        item["last_seen"] = _latest(item["last_seen"], r["last"])

    for inv in invocations:
        name = inv.get("runtime")
        if not name:
            continue
        item = row(str(name))
        item["invocations"] += 1
        if inv.get("session_id"):
            item["sessions"].add(inv["session_id"])
        stamp = parse_time(inv.get("last_seen_at"))
        item["last_seen"] = _latest(item["last_seen"], inv.get("last_seen_at"))
        first = parse_time(inv.get("first_seen_at"))
        item["first_seen"] = min(filter(None, [item["first_seen"], first]), default=None)
        decision = ((inv.get("pre_tool") or {}).get("kernel_decision") or {})
        verdict = str(decision.get("verdict") or "").lower()
        if verdict:
            item["decisions"][verdict if verdict in {"allow", "deny", "ask"} else "other"] += 1
        if verdict in {"deny", "ask"}:
            item["denied"].append({
                "invocation_id": inv.get("invocation_id"), "session_id": inv.get("session_id"), "tool_name": inv.get("tool_name"),
                "verdict": verdict, "reason": (inv.get("pre_tool") or {}).get("policy_reason"), "at": _iso(stamp),
            })
        outcome = (inv.get("post_tool") or {}).get("outcome")
        if outcome:
            item["outcomes"]["success" if outcome == "success" else "error" if outcome in {"error", "failure", "failed"} else "other"] += 1

    out = []
    for item in rows.values():
        last = item["last_seen"]
        out.append({
            "runtime": item["runtime"],
            "sessions": len(item["sessions"]),
            "memories": item["memories"],
            "invocations": item["invocations"],
            "decisions": {k: item["decisions"].get(k, 0) for k in ("allow", "deny", "ask", "other")},
            "outcomes": {k: item["outcomes"].get(k, 0) for k in ("success", "error", "other")},
            "first_seen_at": _iso(item["first_seen"]),
            "last_seen_at": _iso(last),
            # "quiet", not "down": the store only knows when a runtime last wrote
            "activity": "recent" if last and now - last <= RECENT else "quiet",
            "interventions": sorted(item["denied"], key=lambda d: d["at"] or "", reverse=True)[:20],
        })
    out.sort(key=lambda r: (r["activity"] != "recent", -(r["memories"] + r["invocations"]), r["runtime"]))
    return out


# --- workers -----------------------------------------------------------------------------------------------

def worker_status(conn: sqlite3.Connection, embedding: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Derived state for each background worker family, from the queue and the embeddings it fills."""
    now = now or datetime.now(timezone.utc)
    by_type: dict[str, dict[str, Any]] = defaultdict(lambda: {"pending": 0, "claimed": 0, "completed": 0, "failed": 0, "cancelled": 0, "live": 0, "stalled": 0, "recent_completed": 0, "recent_failed": 0, "oldest_pending": None, "last_activity": None, "owners": set()})
    for r in conn.execute("SELECT task_type, status, claim_owner, lease_expires_at, created_at, updated_at FROM memory_inference_tasks"):
        t = by_type[r["task_type"]]
        status = r["status"]
        t[status] += 1
        updated = parse_time(r["updated_at"])
        if status == "pending":
            created = parse_time(r["created_at"])
            if created and (t["oldest_pending"] is None or created < t["oldest_pending"]):
                t["oldest_pending"] = created
        else:
            t["last_activity"] = _latest(t["last_activity"], r["updated_at"])
        if status == "claimed":
            lease = parse_time(r["lease_expires_at"])
            t["live" if lease and lease > now else "stalled"] += 1
            if r["claim_owner"]:
                t["owners"].add(str(r["claim_owner"]))
        if updated and now - updated <= RECENT:
            if status == "completed":
                t["recent_completed"] += 1
            elif status == "failed":
                t["recent_failed"] += 1

    workers = []
    for key, (label, types) in WORKER_FAMILIES.items():
        fam = [by_type[t] for t in types if t in by_type]
        pending = sum(f["pending"] for f in fam)
        live = sum(f["live"] for f in fam)
        stalled = sum(f["stalled"] for f in fam)
        completed = sum(f["recent_completed"] for f in fam)
        failed = sum(f["recent_failed"] for f in fam)
        last = _latest(*[f["last_activity"] for f in fam])
        oldest = min((f["oldest_pending"] for f in fam if f["oldest_pending"]), default=None)
        quiet_for = (now - last) if last else None
        if live:
            state = "working"
        elif stalled:
            state = "stalled"
        elif failed and failed >= max(1, completed):
            state = "failing"
        elif pending and (last is None or (quiet_for is not None and quiet_for > BACKLOG_AFTER)):
            state = "backlog"
        elif pending:
            state = "draining"
        elif last is None and not fam:
            state = "no work seen"
        else:
            state = "idle"
        workers.append({
            "id": key, "label": label, "state": state, "task_types": list(types),
            "pending": pending, "in_flight": live, "stalled_leases": stalled,
            "completed_24h": completed, "failed_24h": failed,
            "last_activity_at": _iso(last), "oldest_pending_at": _iso(oldest),
            "claimed_by": sorted(set().union(*[f["owners"] for f in fam])) if fam else [],
        })

    last_embedded = conn.execute("SELECT MAX(created_at) FROM embeddings_meta").fetchone()[0]
    missing = int(embedding.get("missing", 0)) + int(embedding.get("stale", 0))
    failed_embeddings = int(embedding.get("failed", 0))
    embed_last = parse_time(last_embedded)
    if failed_embeddings and failed_embeddings >= missing:
        e_state = "failing"
    elif missing and (embed_last is None or now - embed_last > BACKLOG_AFTER):
        e_state = "backlog"
    elif missing:
        e_state = "draining"
    else:
        e_state = "idle" if embed_last else "no work seen"
    workers.append({
        "id": "embedding", "label": "Embedding backfill", "state": e_state, "task_types": [],
        "pending": missing, "in_flight": 0, "stalled_leases": 0, "completed_24h": None, "failed_24h": failed_embeddings,
        "last_activity_at": _iso(embed_last), "oldest_pending_at": None, "claimed_by": [],
        "coverage": {"eligible": embedding.get("eligible"), "current": embedding.get("current"), "missing": embedding.get("missing"), "stale": embedding.get("stale"), "failed": embedding.get("failed"), "model": (embedding.get("model") or {}).get("model_id")},
    })
    return {
        "as_of": _iso(now),
        "workers": workers,
        "basis": "Derived from the work each worker leaves in the store. There is no heartbeat: a worker with nothing to do leaves no trace, so an empty queue reads as idle, and a waiting queue with no recent activity reads as backlog.",
    }


# --- connectors --------------------------------------------------------------------------------------------

# Source kinds whose output identifies one connector. The others (transcripts, hermes sessions, codex,
# otel) write ordinary direct_* sources that are not distinguishable by connector, so they get no count.
_CONNECTOR_SOURCE_KINDS = {"webhook": "connector_event", "integrity_wiki": "imported_document"}


def connector_status(conn: sqlite3.Connection, manifest: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Each declared connector, with evidence where the store can attribute it, plus the ingest overall."""
    kind_rows = conn.execute("SELECT kind, COUNT(*) AS n, MAX(created_at) AS last FROM sources GROUP BY kind ORDER BY n DESC").fetchall()
    kinds = {r["kind"]: {"memories": int(r["n"]), "last_at": _iso(parse_time(r["last"]))} for r in kind_rows}
    connectors = []
    for name, entry in manifest.items():
        source_kind = _CONNECTOR_SOURCE_KINDS.get(name)
        evidence = kinds.get(source_kind, {"memories": 0, "last_at": None}) if source_kind else None
        connectors.append({
            "name": name, "entrypoint": entry.get("entrypoint"), "state": entry.get("state"), "idempotency": entry.get("idempotency"),
            "source_kind": source_kind, "evidence": evidence,
        })
    webhook = conn.execute(
        "SELECT json_extract(metadata_json, '$.connector') AS connector, COUNT(*) AS n, MAX(created_at) AS last FROM sources "
        "WHERE kind = 'connector_event' AND json_extract(metadata_json, '$.connector') IS NOT NULL GROUP BY connector ORDER BY n DESC"
    ).fetchall()
    telemetry = [dict(r) for r in conn.execute("SELECT provider, accepted, duplicates, rejected, last_error, last_seen_at FROM telemetry_health ORDER BY provider")]
    return {
        "connectors": connectors,
        "webhook_senders": [{"connector": r["connector"], "events": int(r["n"]), "last_at": _iso(parse_time(r["last"]))} for r in webhook],
        "ingest_by_source_kind": [{"kind": k, **v} for k, v in kinds.items()],
        "provider_telemetry": telemetry,
        "basis": "What each connector's entry point is, and what the store recorded from it. This reports ingest; it does not start or drive it.",
    }
