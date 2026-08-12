import json

from xibalba_cortex.raw_body_ingest import UNATTRIBUTED_SESSION_ID, scan_once
from xibalba_cortex.store import GraphStore


def _write(path, body):
    path.write_text(json.dumps(body))


def test_request_file_ingests_only_the_last_message_not_full_history(tmp_path):
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    store = GraphStore(tmp_path / "graph")

    _write(watch_dir / "req-1.request.json", {
        "model": "claude-sonnet-5",
        "messages": [
            {"role": "user", "content": "What's 2+2?"},
            {"role": "assistant", "content": [{"type": "text", "text": "4"}]},
            {"role": "user", "content": [{"type": "text", "text": "Now fix the CSS bug."}]},
        ],
    })

    results = scan_once(store, watch_dir)
    assert len(results) == 1
    assert results[0]["status"] == "ingested"

    memory = store.get_memory(results[0]["memory_id"])
    assert memory["content"] == "Now fix the CSS bug."  # last message only, not "What's 2+2?"
    assert memory["source"]["message_id"] == "req-1"
    assert memory["source"]["session_id"] == UNATTRIBUTED_SESSION_ID
    assert memory["source"]["role"] == "user"
    store.close()


def test_response_file_ingests_text_and_reports_skipped_non_text_blocks(tmp_path):
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    store = GraphStore(tmp_path / "graph")

    _write(watch_dir / "req-anthropic-id-2.response.json", {
        "id": "msg_abc", "type": "message", "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me check that file."},
            {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "x.py"}},
        ],
    })

    results = scan_once(store, watch_dir)
    assert len(results) == 1
    assert results[0]["skipped_blocks"] == ["tool_use"]

    memory = store.get_memory(results[0]["memory_id"])
    assert memory["content"] == "Let me check that file."
    assert memory["source"]["message_id"] == "req-anthropic-id-2"
    assert memory["source"]["role"] == "assistant"
    store.close()


def test_rescanning_the_same_files_is_idempotent(tmp_path):
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    store = GraphStore(tmp_path / "graph")
    _write(watch_dir / "req-1.request.json", {
        "messages": [{"role": "user", "content": "hello"}]
    })

    first = scan_once(store, watch_dir)
    second = scan_once(store, watch_dir)
    assert first[0]["memory_id"] == second[0]["memory_id"]

    # And no duplicate memory got created -- idempotency_key dedup returns the same row,
    # not a second one. (Ingested content defaults to status=candidate, per the security
    # invariant that automatic/untrusted content shouldn't auto-confirm into default recall
    # -- so this isn't visible via search(), which only returns active/confirmed.)
    events = store.memory_events(first[0]["memory_id"])
    assert [e["event_type"] for e in events] == ["create"]  # exactly one create, not two
    store.close()


def test_request_with_no_messages_array_reports_error_not_silent_skip(tmp_path):
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    store = GraphStore(tmp_path / "graph")
    _write(watch_dir / "req-1.request.json", {"model": "claude-sonnet-5"})  # malformed: no messages

    results = scan_once(store, watch_dir)
    assert results[0]["status"] == "error"
    assert "no messages" in results[0]["error"]
    store.close()


def test_unreadable_json_reports_error_not_a_crash(tmp_path):
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    store = GraphStore(tmp_path / "graph")
    (watch_dir / "req-1.request.json").write_text("not valid json{{{")

    results = scan_once(store, watch_dir)
    assert results[0]["status"] == "error"
    assert "unreadable" in results[0]["error"]
    store.close()


def test_response_with_no_text_blocks_is_skipped_not_ingested_as_empty(tmp_path):
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    store = GraphStore(tmp_path / "graph")
    _write(watch_dir / "req-1.response.json", {
        "id": "msg_abc", "role": "assistant",
        "content": [{"type": "tool_use", "id": "tu_1", "name": "Read", "input": {}}],
    })

    results = scan_once(store, watch_dir)
    assert results[0]["status"] == "skipped"
    assert store.search("Read") == []
    store.close()


def test_reuses_existing_memory_when_content_already_captured_by_otlp_receiver(tmp_path):
    """Symmetric with otlp_receiver's dedup test: if the OTLP receiver (Path B) already
    stored this exact text with real attribution, Path A must reuse it, not create a worse-
    attributed duplicate under the unattributed session.
    """
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    store = GraphStore(tmp_path / "graph")

    store.start_session("real-session", retention_tier="verbatim")
    already_attributed = store.store_memory(
        "fix the login page css",
        source={"kind": "direct_user", "session_id": "real-session", "prompt_id": "p1"},
        status="candidate",
        evidence_class="observed_event",
    )

    _write(watch_dir / "uuid-1.request.json", {
        "messages": [{"role": "user", "content": "fix the login page css"}]
    })
    results = scan_once(store, watch_dir)

    assert results[0]["status"] == "reused"
    assert results[0]["memory_id"] == already_attributed["id"]
    # The already-attributed memory's real session was not overwritten with the unattributed one.
    assert store.get_memory(already_attributed["id"])["source"]["session_id"] == "real-session"
    store.close()
