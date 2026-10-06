#!/usr/bin/env python3
"""Developer fixture for the Cortex console: a scratch profile with realistic, backdated data.

This is a fixture for looking at and testing the viewer (`viewer/`), not part of the product. It
fills a NEW scratch profile through the real GraphStore API -- store_memory, supersede_memory,
link_entities, mark_contradiction, record_model_exchange, forget_memory, and the inference-task
request -> claim -> complete path the workers use -- so every response the viewer shows is genuine
store output. The one thing done in SQL is backdating timestamps, because the store stamps rows
with "now" and a timeline needs history.

Two scenarios, in one store, so both views of the console have something to show:

  primary  eight sessions of memories with no agent, backdated over ~9 days, a supersession, a
           contradiction, a forgotten memory, entities and relations, and exchanges. This is what the
           unscoped "Primary profile (read only)" view shows.
  agent    a writable agent workspace (agent "agent-demo", pseudonymised by the store like any
           agent): one open session with five exchanges, two competing memories, and a review queue
           (entity, relation and contradiction proposals plus a PARA classification) produced via
           the real task path. One proposal belongs to a memory with NO agent, so the console's
           workspace scoping has something to hide.

Safety: it refuses to touch an existing profile (it will not default to ~/.hermes/xibalba-cortex),
and --reset only deletes the SQLite files it would have created.

Usage (from the repo root, with the project's environment):

    uv run python scripts/dev_seed_console.py --home /tmp/cortex-dev
    uv run python -m xibalba_cortex.local_api --home /tmp/cortex-dev          # API on :8420
    cd viewer && CORTEX_HOME=/tmp/cortex-dev npm run dev                        # viewer on :5190

`npm run dev` issues the local-development operator token on first boot, so there is nothing else
to set up. Open the viewer, press "Connect to local Cortex", and pick the agent-demo scope for
the writable workspace (or leave it on the primary profile for the read-only view).
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xibalba_cortex.store import GraphStore

DB_NAME = "graph-memory.sqlite3"
AGENT = "agent-demo"
NOW = datetime.now(timezone.utc).replace(microsecond=0)

# (entity, predicate, entity) triples are what each memory is "evidence" for.
SESSIONS = [
    ("sess-7f3a1c", 9.2, [
        ("Merkle roots are domain-separated per store, so a caller can verify a subset of the graph without the whole chain.", "explicit_memory", "confirmed", "extracted_proposition", [("store.py", "computes", "domain Merkle root")]),
        ("store.py computes one root per domain label; memory_session_merkle_root exposes the session domain to MCP callers.", "explicit_memory", "confirmed", "extracted_proposition", [("memory_session_merkle_root", "exposes", "session domain")]),
        ("Domain separation was frozen for v1 on 2026-08-12; changing a domain label is a spec-surface change, not a refactor.", "direct_user", "confirmed", "policy", []),
        ("Why did memory_hybrid_retrieve rank the store.py note above the spec section?", "direct_user", "active", "observed_event", []),
        ("Lexical and graph signals both placed it first; the vector signal ranked it fourth. RRF carried the agreement.", "direct_model_response", "active", "inference", [("RRF fusion", "combines", "lexical signal")]),
        ("Open question: whether per-device roots should nest under the session domain or stand as their own.", "direct_model_response", "candidate", "inference", []),
    ]),
    ("sess-2b90e4", 7.9, [
        ("xibalba-shield consumes integrity-sdk as a one-way dependency, the same way any third-party agent runtime would.", "imported_document", "confirmed", "extracted_proposition", [("xibalba-shield", "depends_on", "integrity-sdk")]),
        ("AIS is computed in exactly one place, integrity-oracle/scoring-core.", "imported_document", "confirmed", "policy", [("AIS", "computed_by", "integrity-oracle")]),
        ("The middleware forwards the commitment; scoring happens elsewhere.", "imported_document", "active", "extracted_proposition", [("AIS", "computed_by", "bcc_middleware")]),
        ("BCC commitment shape is frozen; Shield must call build_bcc_commitment and nothing else.", "explicit_memory", "confirmed", "policy", [("integrity_exporter", "calls", "build_bcc_commitment")]),
        ("Shield's router runs ActionBroker.contain() first, then the two best-effort export paths.", "explicit_memory", "confirmed", "observed_event", [("ActionBroker", "runs_before", "export paths")]),
    ]),
    ("sess-c41d77", 6.1, [
        ("Entity extraction runs through an isolated Hermes worker profile and produces proposals that require explicit review.", "explicit_memory", "confirmed", "policy", [("extraction worker", "runs_under", "Hermes worker profile")]),
        ("Do not wire extraction output directly into the store; go through the proposal and review lifecycle.", "direct_user", "confirmed", "declared_intent", []),
        ("memory_claim_inference_task then memory_complete_inference_task is the only path from a worker to the graph.", "explicit_memory", "confirmed", "extracted_proposition", [("memory_claim_inference_task", "precedes", "memory_complete_inference_task")]),
        ("Hybrid retrieval combines lexical, vector, graph and temporal signals via Reciprocal Rank Fusion.", "explicit_memory", "confirmed", "extracted_proposition", [("hybrid retrieval", "uses", "RRF fusion")]),
        ("memory_retrieval_trace exposes which signals contributed to a given result.", "explicit_memory", "active", "extracted_proposition", [("memory_retrieval_trace", "explains", "hybrid retrieval")]),
        ("A weekly digest of unreviewed proposals would reduce the review backlog.", "direct_model_response", "candidate", "inference", []),
        ("Storage defaults to ~/.hermes/xibalba-cortex, a local SQLite file.", "imported_document", "active", "observed_event", [("Xibalba Cortex", "stores_in", "SQLite")]),
    ]),
    ("sess-90ab02", 4.8, [
        ("The viewer opens on an authenticated operations overview.", "imported_document", "active", "observed_event", []),
        ("The 3D graph is an interactive overview, not a full-store renderer.", "explicit_memory", "confirmed", "policy", [("graph view", "samples", "memory store")]),
        ("Recall, memory inspection, session Timeline and Integrity continue to query complete API projections.", "explicit_memory", "confirmed", "extracted_proposition", []),
    ]),
    ("sess-1e6f58", 3.0, [
        ("The chain rail should window the graph by time.", "direct_user", "confirmed", "declared_intent", [("chain rail", "windows", "graph view")]),
        ("Selection, facets and the time window survive a lens switch.", "direct_user", "confirmed", "declared_intent", [("lens switch", "preserves", "selection")]),
        ("Every window carries a registration cross at each corner.", "direct_user", "confirmed", "declared_intent", [("window", "carries", "registration cross")]),
        ("Interactive labels are sentence case; upper case is for eyebrows and tags only.", "direct_user", "confirmed", "policy", []),
        ("Shield's dark palette drifted from the mock in commit 7e36a2d.", "direct_model_response", "active", "observed_event", [("Shield", "drifted_from", "Industry mock")]),
        ("The accent is derived in OKLCH at equal lightness and chroma.", "direct_model_response", "confirmed", "extracted_proposition", [("Cortex accent", "derived_from", "Shield accent")]),
    ]),
    ("sess-4d2c93", 1.6, [
        ("Contradictions are surfaced, never auto-resolved.", "explicit_memory", "confirmed", "policy", [("contradiction", "requires", "human review")]),
        ("Roots are computed once per store, not per domain.", "imported_document", "disputed", "extracted_proposition", []),
        ("Domain labels are free-form strings.", "imported_document", "disputed", "extracted_proposition", []),
        ("A forgotten memory keeps its content hash and issues a deletion receipt.", "explicit_memory", "confirmed", "policy", [("forget", "issues", "deletion receipt")]),
        ("Temporary scratch note that should not survive.", "direct_user", "confirmed", "observed_event", []),
    ]),
    ("sess-05fa36", 0.2, [
        ("The Timeline lens shows one lane per session.", "direct_user", "active", "declared_intent", [("Timeline lens", "shows", "session lane")]),
        ("Anchored sessions carry a ring on their mark.", "direct_user", "active", "declared_intent", []),
    ]),
]


TOPICS = ["retrieval ranking", "chain verification", "the review queue", "entity extraction", "the timeline lens", "contradiction handling"]
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def seed_primary(store: GraphStore) -> tuple[dict[str, datetime], dict[str, list[str]]]:
    rng = random.Random(7)
    ids_by_session: dict[str, list[str]] = {}
    stamps: dict[str, datetime] = {}
    forgotten = None
    for ext, days_ago, rows in SESSIONS:
        store.start_session(ext, retention_tier="verbatim")
        start = NOW - timedelta(days=days_ago, hours=rng.randint(0, 5))
        ids_by_session[ext] = []
        for i, (content, kind, status, evidence, triples) in enumerate(rows):
            when = start + timedelta(minutes=7 * i + rng.randint(0, 5))
            src = {"kind": kind, "locator": f"xibalba://dev/{ext}/{i}", "session_id": ext}
            if i % 3 != 2:  # an agent that stamps observed_at; the rest rely on the store's created_at
                src["observed_at"] = when.strftime(STAMP)
            mem = store.store_memory(content, source=src, status=status, evidence_class=evidence, idempotency_key=f"dev:{ext}:{i}")
            ids_by_session[ext].append(mem["id"])
            stamps[mem["id"]] = when
            for s, p, o in triples:
                store.link_entities(s, p, o, evidence_memory_id=mem["id"])
            if "Temporary scratch note" in content:
                forgotten = mem["id"]

    # a real supersession and a real contradiction, through the store's own methods
    first = ids_by_session["sess-4d2c93"][1]
    succ = store.supersede_memory(
        first,
        "Roots are computed once per domain label; a store holds several roots.",
        source={"kind": "explicit_memory", "locator": "xibalba://dev/sess-4d2c93/supersede", "session_id": "sess-4d2c93"},
        status="confirmed",
        evidence_class="extracted_proposition",
        idempotency_key="dev:supersede",
    )
    stamps[succ["id"]] = NOW - timedelta(days=1.5)
    store.mark_contradiction(ids_by_session["sess-7f3a1c"][0], ids_by_session["sess-4d2c93"][2], "Domain labels are fixed by the spec, not free-form.")
    if forgotten:
        store.forget_memory(forgotten)

    for si, (ext, _days, _rows) in enumerate(SESSIONS):
        ids = ids_by_session[ext]
        t0 = min(stamps[i] for i in ids)
        for k in range(3 + (si % 3)):
            topic = TOPICS[(si + k) % len(TOPICS)]
            when = t0 + timedelta(minutes=11 * k + 3)
            ctx = [{"memory_id": ids[(k + j) % len(ids)], "contribution_id": f"c{k}{j}", "context_kind": "retrieved_memory", "relevance": round(0.95 - 0.1 * j, 2)} for j in range(2)]
            store.record_model_exchange(
                ext,
                user_prompt=f"[{ext}] What does the store currently say about {topic}?",
                model_response=f"[{ext}] Here is what the retrieved memories say about {topic}, with their sources.",
                context=ctx,
                runtime="dev-seed",
                prompt_id=f"{ext}-turn-{k + 1}",
                prompt_time=when.strftime(STAMP),
                response_time=(when + timedelta(seconds=5)).strftime(STAMP),
                idempotency_key=f"dev:ex:{ext}:{k}",
            )
    for ext in ("sess-7f3a1c", "sess-2b90e4", "sess-c41d77", "sess-90ab02", "sess-1e6f58", "sess-4d2c93"):
        store.end_session(ext)
    return stamps, ids_by_session


def backdate_primary(home: Path, stamps: dict[str, datetime], ids_by_session: dict[str, list[str]]) -> None:
    """The store stamps 'now'; move the primary scenario's rows into the past. SQL, deliberately:
    there is no API for writing history, and this only ever touches the scratch profile."""
    fmt = "%Y-%m-%d %H:%M:%S"
    con = sqlite3.connect(str(home / DB_NAME))
    for mid, when in stamps.items():
        con.execute("update memories set created_at=? where id=?", (when.strftime(fmt), mid))
        con.execute("update memory_events set created_at=? where memory_id=?", (when.strftime(fmt), mid))
    for ext, ids in ids_by_session.items():
        lo = min(stamps[i] for i in ids)
        hi = max(stamps[i] for i in ids)
        # the newest session stays open, as a live one would
        ended = None if ext == "sess-05fa36" else (hi + timedelta(minutes=9)).strftime(fmt)
        con.execute("update sessions set started_at=?, ended_at=? where external_session_id=?", (lo.strftime(fmt), ended, ext))
    con.commit()
    con.close()


def _run(store: GraphStore, task_type: str, memory: dict, output: dict, provider_id: str | None = None) -> None:
    """request -> claim -> complete, exactly as a worker does it."""
    task = store.request_inference_task(task_type, subject_type="memory", subject_id=memory["id"], input_payload={"source_content_hash": memory["content_hash"]})
    claimed = store.claim_inference_task(task["id"], claimed_by="dev-worker", provider_id=provider_id)
    store.complete_inference_task(task["id"], claimed_by="dev-worker", claim_token=claimed["claim_token"], output_payload=output)


def seed_agent(store: GraphStore) -> None:
    src = lambda locator, session=None: {"kind": "explicit_memory", "agent_id": AGENT, "locator": locator, **({"session_id": session} if session else {})}
    store.start_session("sess-w1", retention_tier="verbatim", agent_id=AGENT)
    a = store.store_memory("The relay retries a failed submission three times before spooling it.", source=src("dev://agent/relay-retry", "sess-w1"), status="confirmed", evidence_class="observed_event", idempotency_key="dev:w:1")
    store.store_memory("The relay never retries; failed submissions are dropped.", source=src("dev://agent/relay-drop", "sess-w1"), status="active", evidence_class="observed_event", idempotency_key="dev:w:2")
    store.store_memory("Spooled submissions are replayed in order on reconnect.", source=src("dev://agent/relay-replay", "sess-w1"), status="confirmed", evidence_class="observed_event", idempotency_key="dev:w:3")
    for k in range(5):
        store.record_model_exchange(
            "sess-w1", user_prompt=f"turn {k} question", model_response=f"turn {k} answer",
            context=[{"memory_id": a["id"], "contribution_id": f"c{k}", "context_kind": "retrieved_memory", "relevance": 0.9}],
            runtime="dev-seed", prompt_id=f"w1-{k}", idempotency_key=f"dev:w:ex:{k}",
        )

    # runtime telemetry through the real batch path: one complete tool invocation with a kernel
    # decision (so kernel intents and the invocations list have a correlated triple), one that is
    # still awaiting its outcome, and one metric
    def tool_event(invocation: str, call: str, hook: str, **attrs: object) -> dict[str, object]:
        base = {"invocation_id": invocation, "runtime": "dev-seed", "tool_name": "write_file", "agent_id": AGENT,
                "metadata": {"hook": hook, "tool_call_id": call, **attrs.pop("metadata", {})}}
        return {"kind": "span", "name": f"tool.{hook}", "trace_id": "trace-dev-1", "attributes": {**base, **attrs}}

    store.record_otel_batch("sess-w1", [
        tool_event("inv-1", "call-1", "pre_tool_call", intent_rationale="Persist the retry policy note", tool_input_hash="sha256:" + "a1" * 32,
                   metadata={"kernel_decision": {"verdict": "allow", "matched_case": "within_budget"}, "policy_reason": "within budget"}),
        tool_event("inv-1", "call-1", "post_tool_call", tool_outcome="success", metadata={"duration_ms": 42, "result": "ok"}),
        tool_event("inv-2", "call-2", "pre_tool_call", intent_rationale="Delete the spool", tool_input_hash="sha256:" + "b2" * 32,
                   metadata={"kernel_decision": {"verdict": "deny", "matched_case": "destructive"}, "policy_reason": "destructive action"}),
        {"kind": "metric", "name": "relay.retry_count", "value": 3, "unit": "1", "attributes": {"agent_id": AGENT}},
    ])

    # the review queue, through the real task path
    m1 = store.store_memory("Xibalba Solutions LLC operates Xibalba Shield from Texas.", source=src("dev://agent/review-1"), status="active", evidence_class="observed_event", idempotency_key="dev:r:1")
    m2 = store.store_memory("Xibalba Shield ships in Q3.", source=src("dev://agent/review-2"), status="active", evidence_class="observed_event", idempotency_key="dev:r:2")
    m3 = store.store_memory("Xibalba Shield ships in Q1.", source=src("dev://agent/review-3"), status="active", evidence_class="observed_event", idempotency_key="dev:r:3")
    _run(store, "extract_entities", m1, {"schema_version": "xibalba.entities.v1", "input_snapshot_hash": m1["content_hash"], "entities": [
        {"name": "Xibalba Solutions LLC", "entity_type": "organization", "evidence_quote": "Xibalba Solutions LLC", "confidence": 0.9},
        {"name": "Texas", "entity_type": "location", "evidence_quote": "Texas", "confidence": 0.8}]})
    _run(store, "extract_relations", m1, {"schema_version": "xibalba.relations.v1", "input_snapshot_hash": m1["content_hash"], "relations": [
        {"subject": "Xibalba Solutions LLC", "predicate": "operates", "object": "Xibalba Shield", "evidence_quote": "Xibalba Solutions LLC operates Xibalba Shield", "confidence": 0.9}]})
    _run(store, "detect_contradictions", m2, {"schema_version": "xibalba.contradictions.v1", "input_snapshot_hash": m2["content_hash"], "contradictions": [
        {"contradicting_memory_id": m3["id"], "reason": "conflicting ship dates", "confidence": 0.9}]})
    # a memory with NO agent: its proposal belongs to a different workspace and must stay hidden from this one
    other = store.store_memory("Quarterly offsite is in Madison.", source={"kind": "explicit_memory", "locator": "dev://other/offsite"}, status="active", idempotency_key="dev:r:other")
    _run(store, "extract_entities", other, {"schema_version": "xibalba.entities.v1", "input_snapshot_hash": other["content_hash"], "entities": [
        {"name": "Madison", "entity_type": "location", "evidence_quote": "Madison", "confidence": 0.7}]})
    for task in store.list_inference_tasks(status="pending", task_type="classify_para", limit=500):
        if task["subject_id"] == m1["id"]:
            claimed = store.claim_inference_task(task["id"], claimed_by="dev-worker", provider_id="hermes")
            store.complete_inference_task(task["id"], claimed_by="dev-worker", claim_token=claimed["claim_token"], output_payload={
                "category": "area", "confidence": 0.72, "rationale": "Describes an ongoing operating responsibility, not a deliverable.",
                "signals": ["ongoing", "ownership"], "alternatives": ["resource"], "source_memory_id": m1["id"], "source_content_hash": m1["content_hash"]})


def prepare_home(home: Path, reset: bool) -> None:
    default = Path.home() / ".hermes" / "xibalba-cortex"
    if home.resolve() == default.resolve():
        sys.exit(f"refusing to seed the default profile {default}; pass a scratch directory")
    existing = sorted(home.glob(f"{DB_NAME}*")) if home.exists() else []
    if existing and not reset:
        sys.exit(f"{home} already holds a profile ({existing[0].name}); pass --reset to replace it, or choose a new directory")
    for path in existing:
        path.unlink()
    home.mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Seed a scratch Cortex profile for the console (developer fixture).")
    parser.add_argument("--home", required=True, type=Path, help="scratch profile directory to create")
    parser.add_argument("--scenario", choices=("primary", "agent", "both"), default="both")
    parser.add_argument("--reset", action="store_true", help="replace an existing profile's SQLite files in --home")
    args = parser.parse_args(argv)

    prepare_home(args.home, args.reset)
    store = GraphStore(args.home)
    stamps: dict[str, datetime] = {}
    ids_by_session: dict[str, list[str]] = {}
    try:
        if args.scenario in ("primary", "both"):
            stamps, ids_by_session = seed_primary(store)
        if args.scenario in ("agent", "both"):
            seed_agent(store)
    finally:
        store.close()
    if stamps:
        backdate_primary(args.home, stamps, ids_by_session)
    print(f"seeded scenario={args.scenario} into {args.home} ({len(stamps)} backdated primary memories)")


if __name__ == "__main__":
    main()
