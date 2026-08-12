import pytest

from xibalba_cortex.store import GraphStore


def test_ingest_agent_turn_captures_prompt_response_and_tool_calls(tmp_path):
    store = GraphStore(tmp_path / "graph")

    result = store.ingest_agent_turn(
        "sess-cloud-1",
        runtime="perplexity-computer",
        prompt="What is the capital of France?",
        response="The capital of France is Paris.",
        tool_calls=[
            {
                "name": "web_search",
                "attributes": {"query": "capital of France"},
                "start_time": "2026-08-12T10:00:00.000Z",
                "end_time": "2026-08-12T10:00:01.000Z",
            }
        ],
        agent_id="agent-comet-1",
        prompt_id="turn-1",
        metadata={"source_app": "comet"},
        idempotency_key="sess-cloud-1:turn-1",
    )

    assert result["prompt_memory"]["content"] == "What is the capital of France?"
    assert result["response_memory"]["content"] == "The capital of France is Paris."
    assert result["prompt_memory"]["source"]["metadata"]["runtime"] == "perplexity-computer"
    assert len(result["tool_call_otel_event_ids"]) == 1

    exchange = result["exchange"]
    assert exchange["tool_calls"][0]["name"] == "tool_call.web_search"
    assert exchange["tool_calls"][0]["start_time"] == "2026-08-12T10:00:00.000Z"
    assert exchange["tool_calls"][0]["attributes"] == {"query": "capital of France"}

    assert store.verify_exchange_chain("sess-cloud-1")["valid"] is True
    store.close()


def test_ingest_agent_turn_with_no_tool_calls_still_builds_a_valid_exchange(tmp_path):
    store = GraphStore(tmp_path / "graph")

    result = store.ingest_agent_turn(
        "sess-cloud-2",
        runtime="antigravity-cli",
        prompt="Ping",
        response="Pong",
    )

    assert result["tool_call_otel_event_ids"] == []
    assert result["exchange"]["tool_calls"] == []
    assert store.verify_exchange_chain("sess-cloud-2")["valid"] is True
    store.close()


def test_ingest_agent_turn_supports_multiple_tool_calls_in_one_turn(tmp_path):
    store = GraphStore(tmp_path / "graph")

    result = store.ingest_agent_turn(
        "sess-cloud-3",
        runtime="codex",
        prompt="Look up the weather and convert to Celsius.",
        response="It's 20C.",
        tool_calls=[
            {"name": "weather_lookup", "attributes": {"city": "Paris"}},
            {"name": "unit_convert", "attributes": {"from": "F", "to": "C"}},
        ],
    )

    assert len(result["tool_call_otel_event_ids"]) == 2
    names = {tc["name"] for tc in result["exchange"]["tool_calls"]}
    assert names == {"tool_call.weather_lookup", "tool_call.unit_convert"}
    store.close()


def test_ingest_agent_turn_redacts_secrets_in_prompt_response_and_tool_attributes(tmp_path):
    store = GraphStore(tmp_path / "graph")

    result = store.ingest_agent_turn(
        "sess-cloud-4",
        runtime="test-harness",
        prompt="My api_key: sk-abcdefghijklmnop, please store it",
        response="Noted, but I won't repeat secret=hunter2",
        tool_calls=[{"name": "save_credential", "attributes": {"value": "bearer abc123secretvalue"}}],
    )

    assert "sk-abcdefghijklmnop" not in result["prompt_memory"]["content"]
    assert "[REDACTED]" in result["prompt_memory"]["content"]
    assert "hunter2" not in result["response_memory"]["content"]
    assert "[REDACTED]" in result["response_memory"]["content"]
    tool_call_attrs = result["exchange"]["tool_calls"][0]["attributes"]
    assert "abc123secretvalue" not in str(tool_call_attrs)
    store.close()


def test_ingest_agent_turn_accepts_a_brand_new_runtime_name_with_no_code_change(tmp_path):
    """The whole point: no allowlist. A runtime name nobody has seen before must just work."""
    store = GraphStore(tmp_path / "graph")

    result = store.ingest_agent_turn(
        "sess-cloud-5",
        runtime="some-future-cloud-agent-2027",
        prompt="hello",
        response="hi",
    )

    assert result["prompt_memory"]["source"]["metadata"]["runtime"] == "some-future-cloud-agent-2027"
    store.close()


def test_ingest_agent_turn_is_idempotent_under_the_same_key(tmp_path):
    store = GraphStore(tmp_path / "graph")

    first = store.ingest_agent_turn(
        "sess-cloud-6", runtime="codex", prompt="hi", response="hello",
        idempotency_key="sess-cloud-6:turn-1",
    )
    second = store.ingest_agent_turn(
        "sess-cloud-6", runtime="codex", prompt="hi", response="hello",
        idempotency_key="sess-cloud-6:turn-1",
    )

    assert first["prompt_memory"]["id"] == second["prompt_memory"]["id"]
    assert first["response_memory"]["id"] == second["response_memory"]["id"]
    store.close()
