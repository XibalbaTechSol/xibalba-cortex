import subprocess
import sys

import pytest

from xibalba_graph.agy_adapter import AgyWrapperShim
from xibalba_graph.claude_adapter import ClaudeAdapter
from xibalba_graph.codex_probe import CodexLauncherProbe
from xibalba_graph.runtime_bridge_contract import CLAUDE_ADAPTER, AGY_ADAPTER, CODEX_ADAPTER, RuntimeEvent
from xibalba_graph.runtime_controller import XibalbaRuntimeController
from xibalba_graph.store import GraphStore


@pytest.fixture
def controller(tmp_path):
    store = GraphStore(tmp_path / "graph")
    ctl = XibalbaRuntimeController(store)
    yield ctl, store
    store.close()


def test_controller_facade_registers_binds_and_records_events(controller):
    ctl, store = controller
    registration = ctl.register_runtime(CLAUDE_ADAPTER, provenance={"source": "test"})
    assert registration["registered"] is True
    assert registration["runtime"] == "claude"

    bound = ctl.bind_identity(
        "claude",
        session_id="session-1",
        agent_id="did:integrity:abc",
        provenance={"source": "test"},
    )
    assert bound["bound"] is True

    opened = ctl.open_session("claude", session_id="session-1", traceparent="00-abc-01")
    assert opened["opened"] is True

    memory = ctl.write_memory(
        "Xibalba controller memo.",
        source={"kind": "direct_user", "session_id": "session-1", "prompt_id": "turn-1"},
        status="confirmed",
    )
    assert store.get_memory(memory["id"])["content"] == "Xibalba controller memo."

    decision = ctl.evaluate_policy(
        runtime="claude",
        session_id="session-1",
        tool_name="memory_remember",
        tool_input_hash="sha256:deadbeef",
    )
    assert decision["allowed"] is False

    event = RuntimeEvent(runtime="claude", session_id="session-1", turn_id="turn-1", tool_name="memory_recall")
    ingest = ctl.ingest_event(event)
    assert ingest["recorded"] == 1
    events = store.session_otel_events("session-1")
    assert events[0]["name"] == "xibalba.runtime.event"


def test_claude_adapter_routes_hooks_through_controller(controller):
    ctl, store = controller
    adapter = ClaudeAdapter(ctl)

    adapter.on_session_start(session_id="session-2", traceparent="00-xyz-01", agent_id="did:integrity:def")
    adapter.post_llm_call(
        session_id="session-2",
        turn_id="turn-2",
        user_message="Explain the bridge.",
        assistant_response="Hermes MCP is necessary but insufficient.",
        intent_rationale="Describe the architecture boundary.",
    )
    adapter.post_tool_call(
        session_id="session-2",
        turn_id="turn-2",
        tool_name="memory_recall",
        tool_call_id="tool-1",
        status="ok",
        result={"ok": True},
        intent_rationale="Check stored context.",
    )
    adapter.on_session_end(session_id="session-2", summary="done")

    memories = store.session_memories("session-2")
    assert {m["content"] for m in memories} >= {
        "Explain the bridge.",
        "Hermes MCP is necessary but insufficient.",
        "done",
    }
    telemetry = store.session_otel_events("session-2")
    names = [event["name"] for event in telemetry]
    assert "xibalba.runtime.event" in names


def test_agy_wrapper_is_lifecycle_only_but_records_observations(controller):
    ctl, store = controller
    shim = AgyWrapperShim(ctl)

    shim.start(session_id="agy-1", command="agy run", cwd="/tmp/work")
    shim.record_observation(session_id="agy-1", note="wrapper observed a completed command")
    shim.end(session_id="agy-1", exit_code=0, summary="finished")

    session = store.get_session("agy-1")
    assert session["ended_at"] is not None
    telemetry = store.session_otel_events("agy-1")
    assert [event["name"] for event in telemetry] == [
        "xibalba.runtime.event",
        "xibalba.runtime.event",
        "xibalba.runtime.event",
    ]


def test_codex_probe_reports_absence_and_discovery(monkeypatch):
    probe = CodexLauncherProbe()
    monkeypatch.setattr("xibalba_graph.codex_probe.shutil.which", lambda candidate: None)
    absent = probe.discover()
    assert absent.surface_kind == "absent"
    assert absent.executable is None

    monkeypatch.setattr("xibalba_graph.codex_probe.shutil.which", lambda candidate: "/usr/local/bin/codex")

    class Completed:
        stdout = "codex 1.2.3"
        stderr = ""

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: Completed(),
    )
    discovered = probe.discover()
    assert discovered.executable == "codex"
    assert discovered.surface_kind == "cli"
    assert discovered.version == "codex 1.2.3"
