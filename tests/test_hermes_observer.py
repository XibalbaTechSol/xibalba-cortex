from xibalba_graph.hermes_observer import HermesObserverAdapter
from xibalba_graph.store import GraphStore


def _adapter(tmp_path):
    store = GraphStore(tmp_path / "graph")
    return store, HermesObserverAdapter(store)


def test_session_start_and_end_round_trip(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.on_session_start(session_id="s1")
    session = store.get_session("s1")
    assert session["ended_at"] is None

    adapter.on_session_end(session_id="s1", completed=True, reason="task finished")
    session = store.get_session("s1")
    assert session["ended_at"] is not None
    summary = store.get_memory(session["summary_memory_id"])
    assert summary["content"] == "Session ended: task finished"
    store.close()


def test_session_end_for_unknown_session_is_a_noop_not_a_crash(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.on_session_end(session_id="never-started")  # must not raise
    store.close()


def test_post_llm_call_stores_prompt_and_response_with_shared_prompt_id(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.post_llm_call(
        session_id="s1", turn_id="turn-1",
        user_message="What's 2+2?", assistant_response="4",
    )
    memories = store.session_memories("s1")
    assert {m["content"] for m in memories} == {"What's 2+2?", "4"}
    for m in memories:
        assert m["source"]["prompt_id"] == "turn-1"
    store.close()


def test_post_llm_call_dedupes_against_content_already_captured_elsewhere(tmp_path):
    store, adapter = _adapter(tmp_path)
    store.start_session("other-session", retention_tier="verbatim")
    existing = store.store_memory(
        "fix the login page css",
        source={"kind": "direct_user", "session_id": "other-session", "prompt_id": "p1"},
        status="candidate",
        evidence_class="observed_event",
    )

    adapter.post_llm_call(
        session_id="s1", turn_id="turn-1",
        user_message="fix the login page css", assistant_response="Done.",
    )

    # The existing memory's original attribution must not be overwritten.
    assert store.get_memory(existing["id"])["source"]["session_id"] == "other-session"
    # And s1 must not have created a second, worse-attributed copy of the same text.
    s1_contents = {m["content"] for m in store.session_memories("s1")}
    assert "fix the login page css" not in s1_contents
    assert "Done." in s1_contents
    store.close()


def test_post_llm_call_ignores_non_string_or_blank_messages(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.post_llm_call(session_id="s1", turn_id="turn-1", user_message=None, assistant_response="   ")
    assert store.session_memories("s1") == []
    store.close()


def test_post_api_request_records_otel_log_event(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.post_api_request(
        session_id="s1", turn_id="turn-1", api_request_id="req-1",
        model="claude-sonnet-5", provider="anthropic", api_duration=1.23,
        usage={"input_tokens": 50, "output_tokens": 120}, finish_reason="stop",
    )
    events = store.session_otel_events("s1")
    assert len(events) == 1
    assert events[0]["kind"] == "log"
    assert events[0]["name"] == "hermes.api_request"
    assert events[0]["prompt_id"] == "turn-1"
    assert events[0]["attributes"]["model"] == "claude-sonnet-5"
    store.close()


def test_api_request_error_records_otel_log_event(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.api_request_error(
        session_id="s1", turn_id="turn-1", api_request_id="req-1",
        error={"message": "rate limited"}, status_code=429, retryable=True,
    )
    events = store.session_otel_events("s1")
    assert events[0]["name"] == "hermes.api_request_error"
    assert events[0]["attributes"]["status_code"] == 429
    store.close()


def test_post_tool_call_records_span_event_parented_to_turn(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.post_tool_call(
        session_id="s1", tool_name="Read", tool_call_id="tool-1", turn_id="turn-1",
        result="file contents", duration_ms=42.0, status="ok",
    )
    events = store.session_otel_events("s1")
    assert events[0]["kind"] == "span"
    assert events[0]["name"] == "tool_call.Read"
    assert events[0]["span_id"] == "tool-1"
    assert events[0]["parent_span_id"] == "turn-1"
    store.close()


def test_post_approval_response_records_security_relevant_decision(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.post_approval_response(
        session_id="s1", command="rm -rf /tmp/x", description="cleanup", choice="approved",
    )
    events = store.session_otel_events("s1")
    assert events[0]["name"] == "hermes.approval"
    assert events[0]["attributes"]["choice"] == "approved"
    store.close()


def test_subagent_lifecycle_recorded_on_parent_session(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.on_session_start(session_id="parent")
    adapter.subagent_start(
        parent_session_id="parent", child_session_id="child-1", child_subagent_id="sub-1",
        child_role="Explore", child_goal="find files",
    )
    adapter.subagent_stop(
        parent_session_id="parent", child_session_id="child-1", child_subagent_id="sub-1",
        status="ok", child_summary="found 3 files", duration_ms=500.0,
    )
    events = store.session_otel_events("parent")
    names = [e["name"] for e in events]
    assert names == ["hermes.subagent_start", "hermes.subagent_stop"]
    assert events[0]["attributes"]["child_session_id"] == "child-1"
    store.close()


def test_hooks_without_session_id_are_noops(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.post_llm_call(session_id=None, turn_id="t1", user_message="hi", assistant_response="hi")
    adapter.post_api_request(session_id=None)
    adapter.post_tool_call(session_id=None)
    adapter.post_approval_response(session_id=None)
    adapter.subagent_start(parent_session_id=None)
    adapter.subagent_stop(parent_session_id=None)
    row_count = store._connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert row_count == 0
    store.close()


def test_unknown_kwargs_are_tolerated_for_forward_compatibility(tmp_path):
    store, adapter = _adapter(tmp_path)
    adapter.post_llm_call(
        session_id="s1", turn_id="turn-1", user_message="hi", assistant_response="hi there",
        some_future_field="new in a later Hermes release",
    )
    assert len(store.session_memories("s1")) == 2
    store.close()
