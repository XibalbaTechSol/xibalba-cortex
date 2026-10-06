import json
import subprocess
import sys

import pytest

from xibalba_cortex.observer_capture import drain, enqueue, normalize
from xibalba_cortex.observer_install import configure
from xibalba_cortex.store import GraphStore
from xibalba_cortex.telemetry_outbox import TelemetryOutbox


def test_identical_prompts_are_distinct_occurrences():
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "again"}
    first = normalize("claude", payload)
    second = normalize("claude", payload)
    assert first["event_id"] != second["event_id"]
    assert first["timestamp_source"] == "callback_received"


def test_redaction_is_applied_before_queue_and_store(tmp_path):
    event = normalize("claude", {"hook_event_name": "PostToolUse", "session_id": "s",
                      "tool_use_id": "tool1", "tool_response": {"password": "SUPER_SECRET",
                      "text": "Bearer abcdefghijklmnop"}}, mode="redacted")
    enqueue(tmp_path, event)
    assert b"SUPER_SECRET" not in (tmp_path / "observer-outbox.sqlite3").read_bytes()
    assert drain(tmp_path) == {"acked": 1, "failed": 0}
    store = GraphStore(tmp_path)
    try:
        events = store.session_otel_events("s")
        assert "SUPER_SECRET" not in json.dumps(events)
        assert "abcdefghijklmnop" not in json.dumps(events)
        assert events[0]["attributes"]["content"]["state"] == "redacted"
    finally:
        store.close()


def test_metadata_mode_never_retains_content():
    event = normalize("claude", {"hook_event_name": "UserPromptSubmit", "session_id": "s",
                                "prompt": "PATIENT_RECORD"})
    assert "PATIENT_RECORD" not in json.dumps(event)
    assert event["content"]["state"] == "omitted_by_policy"


def test_large_content_has_visible_omission():
    event = normalize("claude", {"hook_event_name": "UserPromptSubmit", "session_id": "s",
                                "prompt": "x" * 7000}, mode="redacted")
    assert event["content"]["state"] == "omitted_size_limit"
    assert "value" not in event["content"]


def test_tool_retry_is_idempotent_and_preserves_first_callback_time(tmp_path):
    payload = {"hook_event_name": "PreToolUse", "session_id": "s", "tool_use_id": "t"}
    first = normalize("claude", payload)
    assert not enqueue(tmp_path, first)["duplicate"]
    assert enqueue(tmp_path, normalize("claude", payload))["duplicate"]
    drain(tmp_path)
    # Simulate persistence completed but queue ACK was lost; lease recovery must dedupe.
    queue = TelemetryOutbox(tmp_path / "observer-outbox.sqlite3")
    queue.connection.execute("UPDATE outbox_deliveries SET status='in_flight', lease_until=0")
    queue.close()
    assert drain(tmp_path)["acked"] == 1
    store = GraphStore(tmp_path)
    try:
        rows = store.session_otel_events("s")
        assert len(rows) == 1
        assert rows[0]["start_time"] == first["observed_at_utc"]
    finally:
        store.close()


def test_conflicting_same_tool_event_is_rejected(tmp_path):
    payload = {"hook_event_name": "PostToolUse", "session_id": "s", "tool_use_id": "t", "tool_response": "one"}
    enqueue(tmp_path, normalize("claude", payload))
    with pytest.raises(ValueError, match="conflicting"):
        enqueue(tmp_path, normalize("claude", {**payload, "tool_response": "two"}))


def test_codex_lifecycle_pairing_and_source_time(tmp_path):
    for method in ("item/started", "item/completed"):
        event = normalize("codex", {"method": method, "observed_at_utc": "2026-10-06T11:00:00Z",
                         "params": {"threadId": "s", "turnId": "turn1", "item": {
                             "id": "tool1", "type": "commandExecution", "command": "echo hello",
                             "status": "completed" if method.endswith("completed") else "inProgress"}}}, mode="redacted")
        enqueue(tmp_path, event)
    assert drain(tmp_path)["acked"] == 2
    store = GraphStore(tmp_path)
    try:
        rows = store.session_otel_events("s")
        assert {e["span_id"] for e in rows} == {"tool1"}
        assert {e["attributes"]["event_type"] for e in rows} == {"item/started", "item/completed"}
        assert all(e["attributes"]["timestamp_source"] == "source" for e in rows)
    finally:
        store.close()


def test_codex_reasoning_and_unknown_events_are_excluded():
    assert normalize("codex", {"method": "item/reasoning/textDelta", "params": {"delta": "secret"}}) is None
    assert normalize("codex", {"method": "item/completed", "params": {"threadId": "s", "item": {"type": "reasoning", "content": "secret"}}}) is None
    assert normalize("codex", {"method": "auth/token", "params": {"token": "secret"}}) is None


def test_codex_deltas_are_distinct_and_approval_is_observation_only():
    payload = {"method": "item/agentMessage/delta", "params": {"threadId": "s", "itemId": "i", "delta": "hi"}}
    assert normalize("codex", payload)["event_id"] != normalize("codex", payload)["event_id"]
    approval = normalize("codex", {"id": 10, "method": "item/commandExecution/requestApproval",
                         "params": {"threadId": "s", "turnId": "t", "itemId": "i"}})
    assert "decision" not in approval and "result" not in approval


@pytest.mark.parametrize("payload", [{"session_id": ""}, {"session_id": "s", "observed_at_utc": "2026-10-06T11:00:00"}])
def test_invalid_identity_or_timestamp_rejected(payload):
    with pytest.raises(ValueError):
        normalize("claude", {"hook_event_name": "SessionStart", **payload})


def test_install_preserves_existing_hooks_and_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    original = {"permissions": {"allow": ["Read"]}, "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "existing-check"}]}]}}
    settings.write_text(json.dumps(original))
    assert configure(settings, home=tmp_path / "profile")
    assert not configure(settings, home=tmp_path / "profile")
    data = json.loads(settings.read_text())
    assert data["hooks"]["PreToolUse"][0] == original["hooks"]["PreToolUse"][0]
    assert configure(settings, home=tmp_path / "profile", uninstall=True)
    assert json.loads(settings.read_text()) == original


def test_installed_command_real_subprocess_enqueues_without_stdout(tmp_path):
    settings = tmp_path / "settings.json"
    home = tmp_path / "profile with spaces"
    configure(settings, home=home, mode="redacted")
    command = json.loads(settings.read_text())["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    result = subprocess.run(command, shell=True, input=json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "hello"}), text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert drain(home)["acked"] == 1


def test_failed_hook_never_blocks_or_outputs_context(tmp_path):
    result = subprocess.run([sys.executable, "-m", "xibalba_cortex.observer_capture", "claude-hook", "--home", str(tmp_path)], input='{"password": "SECRET", bad}', text=True, capture_output=True, timeout=10)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "SECRET" not in result.stderr


def test_unavailable_store_keeps_queue_for_recovery(tmp_path):
    enqueue(tmp_path, normalize("claude", {"hook_event_name": "SessionStart", "session_id": "s"}))
    db = tmp_path / "graph-memory.sqlite3"
    db.mkdir()
    with pytest.raises(Exception):
        drain(tmp_path)
    db.rmdir()
    assert drain(tmp_path)["acked"] == 1


def test_two_profiles_do_not_share_events(tmp_path):
    for profile in (tmp_path / "a", tmp_path / "b"):
        enqueue(profile, normalize("claude", {"hook_event_name": "SessionStart", "session_id": profile.name}))
        drain(profile)
    store = GraphStore(tmp_path / "a")
    try:
        with pytest.raises(KeyError):
            store.get_session("b")
    finally:
        store.close()


def test_codex_copied_stream_real_subprocess(tmp_path):
    messages = [
        {"method": "turn/started", "params": {"threadId": "s", "turn": {"id": "t", "status": "inProgress"}}},
        {"method": "item/completed", "params": {"threadId": "s", "turnId": "t", "item": {"id": "i", "type": "agentMessage", "text": "done"}}},
        {"method": "turn/completed", "params": {"threadId": "s", "turn": {"id": "t", "status": "interrupted"}}},
    ]
    result = subprocess.run([sys.executable, "-m", "xibalba_cortex.observer_capture", "codex-stream", "--home", str(tmp_path), "--mode", "redacted"], input="\n".join(json.dumps(m) for m in messages) + "\n", text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert drain(tmp_path)["acked"] == 3
    store = GraphStore(tmp_path)
    try:
        rows = store.session_otel_events("s")
        assert rows[-1]["attributes"]["metadata"]["status"] == "interrupted"
        assert rows[1]["attributes"]["content"]["value"]["text"] == "done"
    finally:
        store.close()


def test_codex_oversized_frame_does_not_corrupt_next_frame(tmp_path):
    oversized = json.dumps({"method": "item/agentMessage/delta", "params": {"threadId": "s", "delta": "x" * (1024 * 1024)}})
    valid = json.dumps({"method": "thread/started", "params": {"thread": {"id": "s"}}})
    result = subprocess.run([sys.executable, "-m", "xibalba_cortex.observer_capture", "codex-stream", "--home", str(tmp_path)], input=oversized + "\n" + valid + "\n", text=True, capture_output=True, timeout=10)
    assert result.returncode == 1
    assert result.stdout == ""
    assert drain(tmp_path)["acked"] == 1


def test_installer_refuses_malformed_settings_and_symlinks(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"hooks": []}')
    with pytest.raises(ValueError):
        configure(settings, home=tmp_path)
    assert settings.read_text() == '{"hooks": []}'
    link = tmp_path / "linked-settings.json"
    link.symlink_to(settings)
    with pytest.raises(ValueError, match="symlink"):
        configure(link, home=tmp_path)


def test_codex_native_installer_and_stop_contract(tmp_path):
    settings = tmp_path / "hooks.json"
    original = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo '{}'"}]}]}, "custom": True}
    settings.write_text(json.dumps(original))
    assert configure(settings, home=tmp_path / "profile", runtime="codex", mode="redacted")
    assert not configure(settings, home=tmp_path / "profile", runtime="codex", mode="redacted")
    installed = json.loads(settings.read_text())
    assert "PostToolUseFailure" not in installed["hooks"]
    for event in ("SessionEnd", "Interrupt"):
        assert installed["hooks"][event][-1]["hooks"][0]["timeout"] == 3
    command = installed["hooks"]["Stop"][-1]["hooks"][0]["command"]
    result = subprocess.run(command, shell=True, input=json.dumps({"hook_event_name": "Stop", "session_id": "s", "turn_id": "t", "last_assistant_message": "finished"}), text=True, capture_output=True, timeout=10)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}
    assert drain(tmp_path / "profile")["acked"] == 1
    store = GraphStore(tmp_path / "profile")
    try:
        event = store.session_otel_events("s")[0]["attributes"]
        assert event["turn_id"] == "t"
        assert event["metadata"]["capture_surface"] == "native_hook"
        assert event["content"]["value"]["last_assistant_message"] == "finished"
    finally:
        store.close()
    assert configure(settings, home=tmp_path / "profile", runtime="codex", uninstall=True)
    assert json.loads(settings.read_text()) == original


def test_codex_native_failure_is_nonblocking_empty_json(tmp_path):
    result = subprocess.run([sys.executable, "-m", "xibalba_cortex.observer_capture", "codex-hook", "--home", str(tmp_path)], input='{"password":"SECRET",broken}', text=True, capture_output=True, timeout=10)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}
    assert "SECRET" not in result.stderr


def test_codex_native_tool_pair_and_runtime_identity():
    payload = {"hook_event_name": "PreToolUse", "session_id": "s", "turn_id": "t", "tool_use_id": "i", "tool_name": "Bash"}
    pre = normalize("codex", payload)
    post = normalize("codex", {**payload, "hook_event_name": "PostToolUse"})
    assert pre["tool_call_id"] == post["tool_call_id"] == "i"
    assert pre["event_id"] != post["event_id"]
    assert pre["event_id"] != normalize("claude", payload)["event_id"]
    assert normalize("codex", {**payload, "hook_event_name": "PostToolUseFailure"}) is None
