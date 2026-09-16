from xibalba_cortex.openclaw_adapter import OpenClawAdapter
from xibalba_cortex.runtime_bridge_contract import OPENCLAW_ADAPTER
from xibalba_cortex.runtime_controller import XibalbaRuntimeController
from xibalba_cortex.store import GraphStore


def test_openclaw_typed_hooks_normalize_tool_and_agent_events(tmp_path):
    store = GraphStore(tmp_path / "graph")
    adapter = OpenClawAdapter(XibalbaRuntimeController(store))
    adapter.ingest_hook("session_start", {"sessionId": "s1", "agentId": "main"})
    adapter.ingest_hook("before_tool_call", {
        "sessionId": "s1", "turnId": "t1", "toolCallId": "c1", "toolName": "exec",
        "params": {"command": "secret"},
    })
    adapter.ingest_hook("after_tool_call", {
        "sessionId": "s1", "turnId": "t1", "toolCallId": "c1", "toolName": "exec",
        "result": "ok", "status": "success", "durationMs": 12,
    })
    events = store.session_otel_events("s1")
    assert [e["attributes"]["metadata"]["hook"] for e in events] == [
        "before_tool_call", "after_tool_call"
    ]
    assert events[0]["attributes"]["tool_input_hash"]
    assert "secret" not in str(events[0]["attributes"])
    assert events[1]["attributes"]["tool_outcome"] == "success"
    assert OPENCLAW_ADAPTER.status == "implemented"
    store.close()


def test_openclaw_subagent_and_message_events_preserve_correlation(tmp_path):
    store = GraphStore(tmp_path / "graph")
    adapter = OpenClawAdapter(XibalbaRuntimeController(store))
    adapter.ingest_hook("session_start", {"session_id": "s1"})
    adapter.ingest_hook("subagent_spawned", {
        "sessionId": "s1", "runId": "run1", "childSessionKey": "child1",
        "resolvedModel": "model-x",
    })
    adapter.ingest_hook("message_sent", {
        "sessionId": "s1", "runId": "run1", "message": "done",
    })
    events = store.session_otel_events("s1")
    assert events[0]["attributes"]["metadata"]["child_session_key"] == "child1"
    assert events[1]["attributes"]["assistant_response"] == "done"
    store.close()
