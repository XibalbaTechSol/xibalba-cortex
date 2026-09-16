import pytest

from xibalba_cortex.config import load_config
from xibalba_cortex.provider_adapters import (
    CloudRunAdapter,
    MCPAdapter,
    PerplexityAdapter,
    ProviderTelemetryPolicy,
    policy_from_config,
)
from xibalba_cortex.runtime_controller import XibalbaRuntimeController
from xibalba_cortex.store import GraphStore


def _policy(provider="test-provider", *, raw=False):
    return ProviderTelemetryPolicy(provider, consent_granted=True, allow_raw_payloads=raw)


def test_mcp_adapter_binds_did_and_hashes_payloads_by_default(tmp_path):
    store = GraphStore(tmp_path / "graph")
    adapter = MCPAdapter(XibalbaRuntimeController(store), _policy("mcp"))
    adapter.tool_started(session_id="s1", agent_id="did:integrity:test", tool_name="search",
                         arguments={"query": "private text"}, invocation_id="i1")
    adapter.tool_finished(session_id="s1", agent_id="did:integrity:test", tool_name="search",
                          result={"secret": "private text"}, invocation_id="i1")
    events = store.session_otel_events("s1")
    attrs = events[0]["attributes"]
    assert attrs["agent_id"] == "did:integrity:test"
    assert attrs["metadata"]["arguments"]["hash"].startswith("sha256:")
    assert "private text" not in str(attrs)
    store.close()


def test_provider_policy_requires_consent_and_integrity_did(tmp_path):
    store = GraphStore(tmp_path / "graph")
    adapter = MCPAdapter(XibalbaRuntimeController(store), ProviderTelemetryPolicy("mcp", False))
    with pytest.raises(PermissionError):
        adapter.tool_started(session_id="s1", agent_id="did:integrity:test", tool_name="x")
    consented = MCPAdapter(XibalbaRuntimeController(store), _policy("mcp"))
    with pytest.raises(ValueError, match="did:integrity"):
        consented.tool_started(session_id="s1", agent_id="wrong", tool_name="x")
    store.close()


def test_perplexity_adapter_captures_response_usage_and_citations_without_network(tmp_path):
    store = GraphStore(tmp_path / "graph")
    adapter = PerplexityAdapter(
        XibalbaRuntimeController(store), _policy("perplexity"),
        request_fn=lambda endpoint, key, payload: {
            "id": "req-1", "output": "answer", "usage": {
                "prompt_tokens": 3, "completion_tokens": 5, "cache_read_tokens": 2,
                "cache_write_tokens": 1, "reasoning_output_tokens": 4,
                "cost_usd": "0.0125",
            },
            "citations": ["https://example.test/source"],
        },
    )
    response = adapter.run(session_id="s1", agent_id="did:integrity:perplexity",
                           api_key="not-stored", payload={"input": "question"}, turn_id="t1")
    assert response["id"] == "req-1"
    events = store.session_otel_events("s1")
    response_event = next(e for e in events if e["attributes"]["metadata"].get("phase") == "response")
    assert response_event["attributes"]["token_usage"] == {
        "input_tokens": 3, "output_tokens": 5, "cached_input_tokens": 2,
        "cache_read_tokens": 2, "cache_write_tokens": 1,
        "reasoning_tokens": 4, "reasoning_output_tokens": 4,
    }
    assert response_event["attributes"]["metadata"]["usage"]["cost_usd"] == 0.0125
    assert response_event["attributes"]["metadata"]["citations"]["hash"].startswith("sha256:")
    assert any(e["kind"] == "metric" and e["name"] == "gen_ai.client.token.usage" for e in events)
    store.close()


def test_provider_events_are_idempotent_and_health_is_observable(tmp_path):
    store = GraphStore(tmp_path / "graph")
    controller = XibalbaRuntimeController(store)
    adapter = MCPAdapter(controller, _policy("mcp"))
    first = adapter.tool_started(session_id="s1", agent_id="did:integrity:test",
                                 tool_name="search", turn_id="t1")
    second = adapter.tool_started(session_id="s1", agent_id="did:integrity:test",
                                  tool_name="search", turn_id="t1")
    assert first["recorded"] == 1
    assert second["duplicates"] == 1
    health = store.telemetry_health_report()
    assert health == [{"provider": "mcp", "accepted": 1, "duplicates": 1,
                       "rejected": 0, "last_error": None,
                       "last_seen_at": health[0]["last_seen_at"]}]
    store.close()


def test_cloud_run_adapter_records_retries_latency_output_and_usage(tmp_path):
    store = GraphStore(tmp_path / "graph")
    adapter = CloudRunAdapter(XibalbaRuntimeController(store), _policy("perplexity"))
    adapter.ingest(session_id="s1", agent_id="did:integrity:cloud", event_name="run.completed",
                   payload={"status": "completed", "final_output": "done", "retry_count": 2,
                            "latency_ms": 42, "usage": {"total_tokens": 9}, "citations": ["u"]},
                   turn_id="t1")
    event = store.session_otel_events("s1")[-1]["attributes"]
    assert event["tool_outcome"] == "success"
    assert event["metadata"]["retry_count"] == 2
    assert event["metadata"]["latency_ms"] == 42
    assert event["assistant_response"] is None
    store.close()


def test_config_provider_telemetry_is_disabled_by_default_and_explicitly_opted_in(tmp_path):
    config = load_config(home=tmp_path)
    assert config.telemetry.enabled is False
    assert not policy_from_config(config, "perplexity").consent_granted
    (tmp_path / "config.yaml").write_text(
        "telemetry:\n"
        "  enabled: true\n"
        "  consented_providers: [perplexity]\n"
        "  retention_tier: synopsis\n"
        "  allow_raw_payloads: false\n"
    )
    config = load_config(home=tmp_path)
    policy = policy_from_config(config, "perplexity")
    assert policy.consent_granted is True
    assert policy.retention_tier == "synopsis"
    assert policy.allow_raw_payloads is False
