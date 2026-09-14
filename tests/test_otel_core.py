from pathlib import Path

from xibalba_cortex.otel_core import (
    OtlpExporterConfig,
    build_otlp_exporters,
    canonical_gen_ai_attributes,
    token_usage_metric_events,
)
from xibalba_cortex.otlp_grpc_receiver import _services
from xibalba_cortex.store import GraphStore


def test_canonical_gen_ai_attributes_preserve_legacy_and_standard_names():
    attrs = canonical_gen_ai_attributes({
        "provider": "openai", "model": "gpt-test", "prompt_tokens": 4,
        "completion_tokens": 3, "cache_write_tokens": 2,
    })
    assert attrs["provider"] == "openai"
    assert attrs["gen_ai.provider.name"] == "openai"
    assert attrs["gen_ai.request.model"] == "gpt-test"
    assert attrs["gen_ai.usage.input_tokens"] == 4
    assert attrs["gen_ai.usage.output_tokens"] == 3
    assert attrs["gen_ai.usage.cache_creation.input_tokens"] == 2


def test_token_usage_emits_standard_histogram_datapoints():
    events = token_usage_metric_events(
        session_id="s1", provider="openai",
        usage={"input_tokens": 4, "output_tokens": 3, "reasoning_tokens": 2},
        trace_id="t1", span_id="s1",
    )
    assert [event["attributes"]["gen_ai.token.type"] for event in events] == [
        "input", "output", "reasoning"
    ]
    assert all(event["name"] == "gen_ai.client.token.usage" for event in events)
    assert all(event["attributes"]["otel.metric.type"] == "histogram" for event in events)


def test_official_otlp_exporters_construct_for_http_and_grpc():
    for protocol in ("http/protobuf", "grpc"):
        exporters = build_otlp_exporters(OtlpExporterConfig("http://collector:4318", protocol=protocol))
        assert set(exporters) == {"traces", "metrics", "logs"}


def test_grpc_metric_service_uses_same_collector_path(tmp_path):
    from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2

    store = GraphStore(Path(tmp_path) / "graph")
    try:
        _, _, metrics, _, *_ = _services(store)
        request = metrics_service_pb2.ExportMetricsServiceRequest()
        resource_metrics = request.resource_metrics.add()
        attribute = resource_metrics.resource.attributes.add()
        attribute.key = "session.id"
        attribute.value.string_value = "grpc-session"
        metric = resource_metrics.scope_metrics.add().metrics.add()
        metric.name = "gen_ai.client.token.usage"
        metric.sum.data_points.add().as_int = 9
        metrics.Export(request, None)
        assert store.session_otel_events("grpc-session")[0]["value"] == 9.0
    finally:
        store.close()
