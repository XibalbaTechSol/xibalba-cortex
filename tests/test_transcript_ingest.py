import json

from xibalba_graph.store import GraphStore
from xibalba_graph.transcript_ingest import ingest_transcript, run

# Matches the REAL schema verified against actual Claude Code transcript files on disk
# (see the commit message / session log for the structural inspection this was built from),
# not a guessed shape.
_RECORDS = [
    {"type": "user", "sessionId": "sess-xyz", "uuid": "u1", "promptId": "prompt-1",
     "timestamp": "2026-08-05T10:00:00Z", "message": {"role": "user", "content": "Fix the login page CSS bug."}},
    {"type": "assistant", "sessionId": "sess-xyz", "uuid": "a1", "parentUuid": "u1",
     "message": {"role": "assistant", "usage": {"input_tokens": 1200, "output_tokens": 5, "cache_read_input_tokens": 300},
                 "content": [{"type": "thinking", "thinking": "I should check the CSS file first."}]}},
    {"type": "assistant", "sessionId": "sess-xyz", "uuid": "a2", "parentUuid": "a1",
     "message": {"role": "assistant", "usage": {"input_tokens": 50, "output_tokens": 20},
                 "content": [
                     {"type": "text", "text": "Let me look at the file."},
                     {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"file_path": "login.css"}},
                 ]}},
    {"type": "user", "sessionId": "sess-xyz", "uuid": "u2", "parentUuid": "a2",
     "message": {"role": "user", "content": [
         {"type": "tool_result", "tool_use_id": "tool-1", "is_error": False,
          "content": [{"type": "text", "text": ".login { display: flex; }"}]},
     ]}},
    {"type": "assistant", "sessionId": "sess-xyz", "uuid": "a3", "parentUuid": "u2",
     "message": {"role": "assistant", "usage": {"input_tokens": 80, "output_tokens": 30},
                 "content": [{"type": "text", "text": "Found it -- the flex alignment was wrong."}]}},
]


def _write_transcript(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records))


def test_ingest_captures_user_and_assistant_text_and_thinking_as_memories(tmp_path):
    store = GraphStore(tmp_path / "graph")
    transcript = tmp_path / "s.jsonl"
    _write_transcript(transcript, _RECORDS)

    result = ingest_transcript(store, transcript)
    assert result["memories_created"] == 4  # user turn + thinking + text + text
    assert result["otel_events_created"] == 5  # tool_use + tool_result + 3x context_window.tokens

    memories = store.session_memories("sess-xyz")
    roles_and_content = [(m["source"]["role"], m["content"]) for m in memories]
    assert ("user", "Fix the login page CSS bug.") in roles_and_content
    assert ("assistant", "I should check the CSS file first.") in roles_and_content
    assert ("assistant", "Found it -- the flex alignment was wrong.") in roles_and_content

    thinking_memory = next(m for m in memories if m["content"] == "I should check the CSS file first.")
    assert thinking_memory["source"]["metadata"]["block_type"] == "thinking"
    store.close()


def test_ingest_links_tool_use_and_tool_result_via_shared_span_id(tmp_path):
    store = GraphStore(tmp_path / "graph")
    transcript = tmp_path / "s.jsonl"
    _write_transcript(transcript, _RECORDS)
    ingest_transcript(store, transcript)

    rows = store._connection.execute(
        "SELECT name, span_id, parent_span_id FROM otel_events "
        "WHERE session_id = 'sess-xyz' AND kind = 'span' ORDER BY rowid"
    ).fetchall()
    tool_call = next(r for r in rows if r["name"] == "tool_call.Read")
    tool_result = next(r for r in rows if r["name"] == "tool_result")
    assert tool_call["span_id"] == "tool-1"
    assert tool_result["span_id"] == "tool-1"
    assert tool_result["parent_span_id"] == "tool-1"
    store.close()


def test_ingest_captures_per_turn_context_window_token_usage(tmp_path):
    store = GraphStore(tmp_path / "graph")
    transcript = tmp_path / "s.jsonl"
    _write_transcript(transcript, _RECORDS)
    ingest_transcript(store, transcript)

    summary = store.session_otel_summary("sess-xyz")
    assert summary["metric_totals"]["context_window.tokens"]["count"] == 3
    # 1200+5+300 + 50+20 + 80+30 = 1685
    assert summary["metric_totals"]["context_window.tokens"]["total"] == 1685.0
    store.close()


def test_ingest_preserves_session_occurrence_when_content_exists_elsewhere(tmp_path):
    store = GraphStore(tmp_path / "graph")
    store.start_session("other-session", retention_tier="verbatim")
    already_there = store.store_memory(
        "Fix the login page CSS bug.",
        source={"kind": "direct_user", "session_id": "other-session"},
        status="confirmed",
    )

    transcript = tmp_path / "s.jsonl"
    _write_transcript(transcript, _RECORDS)
    result = ingest_transcript(store, transcript)

    assert result["memories_reused"] == 1
    assert result["memories_created"] == 4
    # The existing content remains in its original session, while this
    # transcript receives a distinct occurrence with its own provenance.
    assert store.get_memory(already_there["id"])["source"]["session_id"] == "other-session"
    assert len(store.session_memories("sess-xyz")) == 4
    store.close()


def test_run_is_incremental_across_calls_via_persisted_state(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    store = GraphStore(home / "graph")
    transcript = tmp_path / "s.jsonl"
    _write_transcript(transcript, _RECORDS)

    first = run(store, home, transcript)
    assert first["lines_processed"] == len(_RECORDS)

    second = run(store, home, transcript)
    assert second["lines_processed"] == 0  # nothing new since last run

    with transcript.open("a") as f:
        f.write("\n" + json.dumps({
            "type": "user", "sessionId": "sess-xyz", "uuid": "u3",
            "message": {"role": "user", "content": "Thanks, that fixed it."},
        }))
    third = run(store, home, transcript)
    assert third["lines_processed"] == 1
    assert third["memories_created"] == 1
    store.close()


def test_ingest_skips_malformed_lines_without_crashing(tmp_path):
    store = GraphStore(tmp_path / "graph")
    transcript = tmp_path / "s.jsonl"
    transcript.write_text("not valid json{{{\n" + json.dumps(_RECORDS[0]))

    result = ingest_transcript(store, transcript)
    assert result["malformed_lines"] == 1
    assert result["memories_created"] == 1  # the valid line still processed
    store.close()


def test_ingest_skips_non_conversation_record_types(tmp_path):
    store = GraphStore(tmp_path / "graph")
    transcript = tmp_path / "s.jsonl"
    _write_transcript(transcript, [
        {"type": "mode", "sessionId": "sess-xyz", "mode": "default"},
        {"type": "system", "sessionId": "sess-xyz", "subtype": "init"},
        _RECORDS[0],
    ])

    result = ingest_transcript(store, transcript)
    assert result["skipped_records"] == 2
    assert result["memories_created"] == 1
    store.close()
