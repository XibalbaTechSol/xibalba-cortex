import inspect
import subprocess
import sys
import uuid

import pytest

from xibalba_cortex.agy_adapter import AgyWrapperShim
from xibalba_cortex.claude_adapter import ClaudeAdapter
from xibalba_cortex.codex_probe import CodexAdapter, CodexLauncher, CodexLauncherProbe
from xibalba_cortex.cursor_adapter import CursorAdapter
from xibalba_cortex.gemini_adapter import GeminiCliAdapter
from xibalba_cortex.openai_compatible_adapter import OpenAICompatibleAdapter
from xibalba_cortex.runtime_bridge_contract import (
    AGY_ADAPTER,
    CLAUDE_ADAPTER,
    CODEX_ADAPTER,
    CURSOR_ADAPTER,
    GEMINI_ADAPTER,
    OPENAI_COMPATIBLE_ADAPTER,
    RuntimeEvent,
)
from xibalba_cortex.runtime_controller import XibalbaRuntimeController
from xibalba_cortex.store import GraphStore


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
    attrs = events[0]["attributes"]
    assert attrs["traceparent"] is None
    assert attrs["agent_id"] is None
    assert attrs["intent_rationale"] is None
    assert attrs["token_usage"] is None


def test_controller_auto_anchors_when_session_closes(controller, monkeypatch):
    ctl, store = controller
    ctl.auto_anchor_on_session_end = True
    ctl.open_session("claude", session_id="anchor-session")
    monkeypatch.setattr(
        store,
        "anchor_session_root",
        lambda session_id: {"anchored": True, "session_id": session_id},
    )

    result = ctl.close_session("claude", session_id="anchor-session")

    assert result["closed"] is True
    assert result["anchor"] == {"anchored": True, "session_id": "anchor-session"}


def test_controller_reports_anchor_failure_without_failing_session_close(controller, monkeypatch):
    ctl, store = controller
    ctl.auto_anchor_on_session_end = True
    ctl.open_session("claude", session_id="anchor-failure")

    def fail_anchor(session_id):
        raise RuntimeError("anchor endpoint unavailable")

    monkeypatch.setattr(store, "anchor_session_root", fail_anchor)
    result = ctl.close_session("claude", session_id="anchor-failure")

    assert result["closed"] is True
    assert result["anchor"]["anchored"] is False
    assert result["anchor"]["error"] == "anchor endpoint unavailable"
    assert store.get_session("anchor-failure")["ended_at"] is not None


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
    denied = adapter.pre_tool_call(
        session_id="session-2",
        turn_id="turn-2",
        tool_name="memory_recall",
        tool_call_id="tool-denied",
    )
    assert denied["allowed"] is False
    allowed = adapter.pre_tool_call(
        session_id="session-2",
        turn_id="turn-2",
        tool_name="memory_recall",
        tool_call_id="tool-1",
        tool_input_hash="sha256:abc",
        intent_rationale="Check stored context.",
    )
    assert allowed["allowed"] is True
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
    tool_event = next(
        event for event in telemetry
        if event["attributes"].get("metadata", {}).get("hook") == "post_tool_call"
    )
    assert tool_event["attributes"]["tool_name"] == "memory_recall"
    assert tool_event["attributes"]["intent_rationale"] == "Check stored context."
    pre_tool_events = [
        event for event in telemetry
        if event["attributes"].get("metadata", {}).get("hook") == "pre_tool_call"
    ]
    assert [event["attributes"]["tool_outcome"] for event in pre_tool_events] == ["blocked", "success"]


def test_claude_adapter_propagates_supplied_invocation_id_across_pre_and_post(controller):
    ctl, store = controller
    adapter = ClaudeAdapter(ctl)
    invocation_id = "ca5e6c31-d095-4d84-a404-d0ff2f0d3dbf"

    pre = adapter.pre_tool_call(
        session_id="session-supplied-invocation",
        tool_name="memory_recall",
        tool_call_id="tool-supplied",
        invocation_id=invocation_id,
        tool_input_hash="sha256:abc",
        intent_rationale="Read evidence-backed context.",
    )
    post = adapter.post_tool_call(
        session_id="session-supplied-invocation",
        tool_name="memory_recall",
        tool_call_id="tool-supplied",
        invocation_id=invocation_id,
        status="ok",
        result={"ok": True},
    )

    assert pre["invocation_id"] == invocation_id
    assert post["invocation_id"] == invocation_id
    events = store.session_otel_events("session-supplied-invocation")
    assert [event["attributes"]["invocation_id"] for event in events] == [
        invocation_id,
        invocation_id,
    ]


def test_claude_adapter_derives_matching_uuid5_from_session_and_tool_call(controller):
    ctl, store = controller
    adapter = ClaudeAdapter(ctl)
    namespace = uuid.UUID("9f7df4b9-8538-4c58-9044-b34d56454f13")
    expected = str(uuid.uuid5(namespace, "claude:session-derived-invocation:tool-derived"))

    pre = adapter.pre_tool_call(
        session_id="session-derived-invocation",
        tool_name="memory_recall",
        tool_call_id="tool-derived",
        tool_input_hash="sha256:def",
        intent_rationale="Read the same context deterministically.",
    )
    post = adapter.post_tool_call(
        session_id="session-derived-invocation",
        tool_name="memory_recall",
        tool_call_id="tool-derived",
        status="ok",
    )

    assert pre["invocation_id"] == expected
    assert post["invocation_id"] == expected
    assert uuid.UUID(expected).version == 5
    events = store.session_otel_events("session-derived-invocation")
    assert {event["attributes"]["invocation_id"] for event in events} == {expected}


def test_kernel_bridge_intents_prefers_invocation_id_and_labels_legacy_fallback(controller):
    ctl, store = controller
    session_id = "session-kernel-correlation"
    ctl.open_session("claude", session_id=session_id)

    def ingest(*, hook, invocation_id=None, tool_call_id, outcome, kernel=False, result=None):
        metadata = {"hook": hook, "tool_call_id": tool_call_id, "result": result}
        if kernel:
            metadata["kernel_decision"] = {"success": True}
        ctl.ingest_event(RuntimeEvent(
            runtime="claude",
            session_id=session_id,
            invocation_id=invocation_id,
            tool_name="memory_recall",
            tool_outcome=outcome,
            intent_rationale="Inspect context.",
            tool_input_hash="sha256:123",
            metadata=metadata,
        ))

    invocation_id = "1236e53f-c982-40bd-b252-5b140aa38af5"
    ingest(
        hook="pre_tool_call", invocation_id=invocation_id,
        tool_call_id="reused-tool-id", outcome="success", kernel=True,
    )
    # A reused legacy tool-call ID must not correlate when its invocation UUID differs.
    ingest(
        hook="post_tool_call", invocation_id="7ebbed12-44ad-4018-a66b-e4c6946bff41",
        tool_call_id="reused-tool-id", outcome="error", result={"wrong": True},
    )
    ingest(
        hook="post_tool_call", invocation_id=invocation_id,
        tool_call_id="different-tool-id", outcome="success", result={"matched": True},
    )
    ingest(
        hook="pre_tool_call", tool_call_id="legacy-tool-id",
        outcome="success", kernel=True,
    )
    ingest(
        hook="post_tool_call", tool_call_id="legacy-tool-id",
        outcome="success", result={"legacy": True},
    )

    intents = store.kernel_bridge_intents(session_id)
    by_mode = {intent["correlation_mode"]: intent for intent in intents}

    current = by_mode["invocation_id"]
    assert current["invocation_id"] == invocation_id
    assert current["tool_call_id"] == "reused-tool-id"
    assert current["actual_outcome"]["result"] == {"matched": True}

    legacy = by_mode["legacy_tool_call_id"]
    assert legacy["invocation_id"] is None
    assert legacy["tool_call_id"] == "legacy-tool-id"
    assert legacy["actual_outcome"]["result"] == {"legacy": True}


def test_invocation_correlations_exposes_complete_and_missing_runtime_stages(controller):
    ctl, store = controller
    adapter = ClaudeAdapter(ctl)
    complete_id = "4d00fd31-d868-4f63-8397-f5b916446b29"
    waiting_id = "c27520ce-c02a-488c-a668-124261556b33"

    adapter.pre_tool_call(
        session_id="correlation-ui",
        tool_name="shell",
        tool_input_hash="sha256:complete",
        intent_rationale="Validate the complete correlation path.",
        tool_call_id="call-complete",
        invocation_id=complete_id,
    )
    adapter.post_tool_call(
        session_id="correlation-ui",
        tool_name="shell",
        tool_call_id="call-complete",
        invocation_id=complete_id,
        status="success",
        result="ok",
    )
    adapter.pre_tool_call(
        session_id="correlation-ui",
        tool_name="write_file",
        tool_input_hash="sha256:waiting",
        intent_rationale="Leave one invocation awaiting an outcome.",
        tool_call_id="call-waiting",
        invocation_id=waiting_id,
    )

    rows = {row["invocation_id"]: row for row in store.invocation_correlations()}
    assert rows[complete_id]["runtime_status"] == "complete"
    assert rows[complete_id]["pre_tool"] is not None
    assert rows[complete_id]["post_tool"]["outcome"] == "success"
    assert rows[waiting_id]["runtime_status"] == "awaiting_outcome"
    assert rows[waiting_id]["post_tool"] is None


def test_runtime_adapters_do_not_write_directly_to_graph_store():
    for adapter in (
        ClaudeAdapter,
        AgyWrapperShim,
        CodexAdapter,
        GeminiCliAdapter,
        CursorAdapter,
        OpenAICompatibleAdapter,
    ):
        source = inspect.getsource(adapter)
        assert "GraphStore" not in source
        assert ".store_memory(" not in source
        assert ".record_otel_batch(" not in source


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
    assert not hasattr(shim, "post_tool_call")
    assert not hasattr(shim, "pre_tool_call")
    assert shim.record_observation(session_id="agy-1", note=None) == {
        "recorded": 0,
        "reason": "missing note",
    }
    assert all(
        event["attributes"]["tool_name"].startswith("agy.wrapper.")
        for event in telemetry
    )


def test_codex_probe_reports_absence_and_discovery(monkeypatch):
    probe = CodexLauncherProbe()
    monkeypatch.setattr("xibalba_cortex.codex_probe.shutil.which", lambda candidate: None)
    absent = probe.discover()
    assert absent.surface_kind == "absent"
    assert absent.executable is None

    monkeypatch.setattr("xibalba_cortex.codex_probe.shutil.which", lambda candidate: "/usr/local/bin/codex")

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
    assert discovered.hook_surface == "unknown"
    assert discovered.version == "codex 1.2.3"


def test_codex_launcher_reports_absent_executable_without_fabricating_session(controller, monkeypatch):
    ctl, store = controller
    monkeypatch.setattr("xibalba_cortex.codex_probe.shutil.which", lambda candidate: None)

    result = CodexLauncher(ctl).launch(session_id="codex-absent", args=["--help"])

    assert result["launched"] is False
    assert result["reason"] == "codex executable not found"
    with pytest.raises(KeyError):
        store.get_session("codex-absent")


def test_codex_launcher_opens_session_injects_context_and_records_process_telemetry(controller, monkeypatch):
    ctl, store = controller
    monkeypatch.setattr("xibalba_cortex.codex_probe.shutil.which", lambda candidate: "/usr/local/bin/codex")

    class VersionCompleted:
        stdout = "codex 1.2.3"
        stderr = ""
        returncode = 0

    class LaunchCompleted:
        stdout = "done"
        stderr = ""
        returncode = 0

    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args == ["codex", "--version"]:
            return VersionCompleted()
        assert kwargs["env"]["XIBALBA_RUNTIME"] == "codex"
        assert kwargs["env"]["XIBALBA_SESSION_ID"] == "codex-launch"
        assert kwargs["env"]["XIBALBA_GRAPH_HOOK_SURFACE"] == "unknown"
        assert kwargs["env"]["XIBALBA_AGENT_ID"] == "did:integrity:codex"
        assert kwargs["env"]["TRACEPARENT"] == "00-codex-01"
        return LaunchCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = CodexLauncher(ctl).launch(
        session_id="codex-launch",
        args=["exec", "echo ok"],
        agent_id="did:integrity:codex",
        traceparent="00-codex-01",
        env={"EXTRA": "1"},
        timeout_seconds=5,
    )

    assert result["launched"] is True
    assert result["command"] == ["codex", "exec", "echo ok"]
    assert result["returncode"] == 0
    assert store.get_session("codex-launch")["ended_at"] is not None
    telemetry = store.session_otel_events("codex-launch")
    launch_event = next(
        event for event in telemetry
        if event["attributes"]["tool_name"] == "codex.launcher"
    )
    assert launch_event["attributes"]["tool_outcome"] == "success"
    assert launch_event["attributes"]["metadata"]["hook_surface"] == "unknown"


def test_codex_adapter_is_lifecycle_only_and_attaches_probe_discovery(controller, monkeypatch):
    ctl, store = controller
    monkeypatch.setattr("xibalba_cortex.codex_probe.shutil.which", lambda candidate: None)
    adapter = CodexAdapter(ctl)

    started = adapter.start(session_id="codex-adapter-1")
    assert started["opened"] is True
    adapter.record_observation(session_id="codex-adapter-1", note="lifecycle-only observation")
    adapter.end(session_id="codex-adapter-1", summary="finished")

    session = store.get_session("codex-adapter-1")
    assert session["ended_at"] is not None
    telemetry = store.session_otel_events("codex-adapter-1")
    assert [event["name"] for event in telemetry] == ["xibalba.runtime.event"] * 3
    start_event = next(
        event for event in telemetry
        if event["attributes"]["tool_name"] == "codex.adapter.start"
    )
    assert start_event["attributes"]["metadata"]["probe"]["surface_kind"] == "absent"
    assert not hasattr(adapter, "post_tool_call")
    assert not hasattr(adapter, "pre_tool_call")


@pytest.mark.parametrize(
    "adapter_cls,tool_prefix,extra_start_kwargs",
    [
        (GeminiCliAdapter, "gemini.wrapper.", {"command": "gemini chat", "cwd": "/tmp/work"}),
        (CursorAdapter, "cursor.wrapper.", {"workspace": "/tmp/work"}),
        (OpenAICompatibleAdapter, "openai_compatible.wrapper.", {}),
    ],
)
def test_wrapper_style_adapter_is_lifecycle_only_but_records_observations(
    controller, adapter_cls, tool_prefix, extra_start_kwargs,
):
    ctl, store = controller
    shim = adapter_cls(ctl)
    session_id = f"{adapter_cls.__name__}-1"

    shim.start(session_id=session_id, **extra_start_kwargs)
    shim.record_observation(session_id=session_id, note="wrapper observed a completed command")
    shim.end(session_id=session_id, summary="finished")

    session = store.get_session(session_id)
    assert session["ended_at"] is not None
    telemetry = store.session_otel_events(session_id)
    assert [event["name"] for event in telemetry] == ["xibalba.runtime.event"] * 3
    assert not hasattr(shim, "post_tool_call")
    assert not hasattr(shim, "pre_tool_call")
    assert shim.record_observation(session_id=session_id, note=None) == {
        "recorded": 0,
        "reason": "missing note",
    }
    assert all(
        event["attributes"]["tool_name"].startswith(tool_prefix)
        for event in telemetry
    )


@pytest.mark.parametrize(
    "adapter",
    [CLAUDE_ADAPTER, AGY_ADAPTER, CODEX_ADAPTER, GEMINI_ADAPTER, CURSOR_ADAPTER, OPENAI_COMPATIBLE_ADAPTER],
)
def test_every_declared_adapter_registers_and_documents_honest_status(controller, adapter):
    ctl, _store = controller
    registration = ctl.register_runtime(adapter, provenance={"source": "test"})
    assert registration["registered"] is True
    assert registration["runtime"] == adapter.runtime
    if adapter.status != "implemented":
        assert adapter.limitations, f"{adapter.runtime} is not implemented but declares no limitations"
