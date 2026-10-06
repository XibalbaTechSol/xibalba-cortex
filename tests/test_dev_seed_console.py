"""The console's developer fixture must keep producing what the viewer's documentation says it does.

scripts/ is not a package, so the script is loaded by path. Each test seeds a fresh scratch profile.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from xibalba_cortex.store import GraphStore

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev_seed_console.py"


@pytest.fixture(scope="module")
def seed():
    spec = importlib.util.spec_from_file_location("dev_seed_console", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_scenarios_produce_the_documented_data(seed, tmp_path):
    home = tmp_path / "profile"
    seed.main(["--home", str(home)])
    store = GraphStore(home)
    try:
        sessions = {s["external_session_id"] for s in store.list_sessions(limit=50)}
        assert {"sess-7f3a1c", "sess-05fa36", "sess-w1"} <= sessions
        # backdated history, not "everything happened a second ago"
        oldest = min(m["created_at"] for m in store.list_memories(limit=200, statuses=("active", "confirmed", "disputed")))
        assert datetime.strptime(oldest, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) < datetime.now(timezone.utc).replace(hour=0, minute=0)
        # the review queue came through the real task path, and one proposal is for a memory with no agent
        proposals = store.list_extraction_proposals(status="proposed")
        assert {p["task_type"] for p in proposals} == {"extract_entities", "extract_relations", "detect_contradictions"}
        assert len(store.list_para_classifications(status="proposed")) == 1
        # the agent workspace sees only its own memories and session, never the primary scenario's
        # nor the agent-less memory behind the hidden proposal
        scoped = store.graph_payload(limit=500, agent_id="agent-demo")
        labels = " | ".join(n["label"] for n in scoped["nodes"] if n["type"] == "memory")
        assert "relay" in labels and "Madison" not in labels and "Merkle roots are domain-separated" not in labels
        assert {n["id"] for n in scoped["nodes"] if n["type"] == "session"} == {"session:sess-w1"}
    finally:
        store.close()


def test_agent_scenario_alone_is_small_and_has_one_open_session(seed, tmp_path):
    home = tmp_path / "agent-only"
    seed.main(["--home", str(home), "--scenario", "agent"])
    store = GraphStore(home)
    try:
        assert {s["external_session_id"] for s in store.list_sessions(limit=50)} == {"sess-w1"}
        assert sum(1 for n in store.graph_payload()["nodes"] if n["type"] == "exchange") == 5
        # the agent's private relation chain is walkable, and only inside that workspace
        walked = store.neighbors("relay", max_depth=3, agent_id=store.storage_agent_id("agent-demo"))["edges"]
        assert [(e["subject"], e["object"]) for e in walked] == [("relay", "failed submission"), ("failed submission", "spool"), ("spool", "reconnect")]
    finally:
        store.close()


def test_agent_scenario_records_runtime_telemetry_the_sessions_page_reads(seed, tmp_path):
    home = tmp_path / "telemetry"
    seed.main(["--home", str(home), "--scenario", "agent"])
    store = GraphStore(home)
    try:
        assert len(store.session_otel_events("sess-w1")) == 4
        intents = store.kernel_bridge_intents("sess-w1")
        assert {i["invocation_id"] for i in intents} == {"inv-1", "inv-2"}
        invocations = {i["invocation_id"]: i["runtime_status"] for i in store.invocation_correlations(limit=10)}
        assert invocations == {"inv-1": "complete", "inv-2": "awaiting_outcome"}
    finally:
        store.close()


def test_refuses_an_existing_profile_and_the_default_profile(seed, tmp_path):
    home = tmp_path / "profile"
    seed.main(["--home", str(home), "--scenario", "agent"])
    with pytest.raises(SystemExit):
        seed.main(["--home", str(home)])  # would overwrite
    seed.main(["--home", str(home), "--scenario", "agent", "--reset"])  # explicit reset is allowed
    with pytest.raises(SystemExit):
        seed.main(["--home", str(Path.home() / ".hermes" / "xibalba-cortex")])
