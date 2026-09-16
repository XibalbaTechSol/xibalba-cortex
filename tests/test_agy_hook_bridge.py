import json
import os
import subprocess
import sys

from xibalba_cortex.agy_hook_bridge import normalize
from xibalba_cortex.store import GraphStore


def test_native_command_bridge_persists_and_deduplicates(tmp_path):
    payload = {"conversationId": "native-command-canary", "stepIdx": 0,
               "toolCall": {"name": "view_file", "args": {"secret": "private-input"}},
               "error": "private-error"}
    env = {**os.environ, "XIBALBA_CORTEX_HOME": str(tmp_path), "XIBALBA_AGENT_ID": "agy"}
    for _ in range(2):
        result = subprocess.run([sys.executable, "-m", "xibalba_cortex.agy_hook_bridge", "PostToolUse"],
                                input=json.dumps(payload), text=True, capture_output=True, env=env)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {}
        assert "private" not in result.stderr
    store = GraphStore(tmp_path)
    try:
        events = store.session_otel_events("native-command-canary")
        assert len(events) == 1
        assert events[0]["attributes"]["tool_outcome"] == "error"
        assert events[0]["attributes"]["invocation_id"] == "step:0"
        assert "private" not in str(events)
    finally:
        store.close()


def test_native_zero_invocation_is_preserved():
    event = normalize("PreInvocation", {"conversationId": "session", "invocationNum": 0})
    assert event["turn_id"] == "0"
    assert event["event_id"] == "invocationNum:0"
