import json

from xibalba_graph.exchange_builder import build_session_exchanges
from xibalba_graph.store import GraphStore
from xibalba_graph.transcript_ingest import ingest_transcript

# Same schema verified against real transcript files, same records used to validate the
# prompt_id propagation fix that makes tool-call linkage actually work.
_RECORDS = [
    {"type": "user", "sessionId": "sess-xyz", "uuid": "u1", "promptId": "prompt-1",
     "timestamp": "2026-08-05T10:00:00Z", "message": {"role": "user", "content": "Fix the login page CSS bug."}},
    {"type": "assistant", "sessionId": "sess-xyz", "uuid": "a1", "parentUuid": "u1",
     "message": {"role": "assistant", "usage": {"input_tokens": 1200, "output_tokens": 5},
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
    {"type": "user", "sessionId": "sess-xyz", "uuid": "u3", "promptId": "prompt-2",
     "timestamp": "2026-08-05T10:05:00Z", "message": {"role": "user", "content": "Great, add a test for it."}},
    {"type": "assistant", "sessionId": "sess-xyz", "uuid": "a4", "parentUuid": "u3",
     "message": {"role": "assistant", "usage": {"input_tokens": 40, "output_tokens": 15},
                 "content": [{"type": "text", "text": "Added a regression test."}]}},
]


def test_build_session_exchanges_groups_by_prompt_and_links_tool_calls(tmp_path):
    store = GraphStore(tmp_path / "graph")
    transcript = tmp_path / "s.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in _RECORDS))
    ingest_transcript(store, transcript)

    result = build_session_exchanges(store, "sess-xyz")
    assert result["exchanges_built"] == 2

    exchanges = store.session_exchanges("sess-xyz")
    assert len(exchanges) == 2

    first, second = exchanges
    assert first["sequence_number"] == 0
    assert first["prompt_id"] == "prompt-1"
    assert first["prompt_memories"][0]["content"] == "Fix the login page CSS bug."
    # thinking + 2 text blocks, all grouped into the same exchange's responses
    assert len(first["response_memories"]) == 3
    response_block_types = {m["source"]["metadata"].get("block_type", "text") for m in first["response_memories"]}
    assert response_block_types == {"thinking", "text"}

    # tool_call, tool_result, and all 3 context_window.tokens metrics for this turn linked
    tool_call_names = {t["name"] for t in first["tool_calls"]}
    assert tool_call_names == {"tool_call.Read", "tool_result", "context_window.tokens"}
    assert sum(1 for t in first["tool_calls"] if t["name"] == "context_window.tokens") == 3

    assert second["sequence_number"] == 1
    assert second["prompt_id"] == "prompt-2"
    assert second["prompt_memories"][0]["content"] == "Great, add a test for it."
    assert len(second["response_memories"]) == 1


def test_build_session_exchanges_produces_a_verifiable_chain(tmp_path):
    store = GraphStore(tmp_path / "graph")
    transcript = tmp_path / "s.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in _RECORDS))
    ingest_transcript(store, transcript)
    build_session_exchanges(store, "sess-xyz")

    result = store.verify_exchange_chain("sess-xyz")
    assert result["valid"] is True
    assert result["length"] == 2


def test_build_session_exchanges_excludes_session_summary_memories(tmp_path):
    store = GraphStore(tmp_path / "graph")
    store.start_session("s1", retention_tier="digest")
    store.store_memory(
        "User wants the login page fixed.",
        source={"kind": "direct_user", "session_id": "s1", "role": "user"},
        status="confirmed", evidence_class="declared_intent",
    )
    store.store_memory(
        "Fixed the CSS bug.",
        source={"kind": "direct_user", "session_id": "s1", "role": "assistant"},
        status="confirmed", evidence_class="observed_event",
    )
    store.end_session("s1", summary_content="Session complete: fixed login CSS.")

    result = build_session_exchanges(store, "s1")
    exchanges = store.session_exchanges("s1")
    assert len(exchanges) == 1
    # the summary memory (evidence_class=summary) must not appear as a response in any exchange
    all_response_content = [m["content"] for e in exchanges for m in e["response_memories"]]
    assert "Session complete: fixed login CSS." not in all_response_content
