"""Optional OTLP/gRPC receiver using the official generated OpenTelemetry services."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from google.protobuf.json_format import MessageToDict

from .otel_core import ingest_metric_records, parse_otlp_metrics_json
from .otlp_receiver import ingest_gen_ai_spans, ingest_log_records, parse_otlp_logs_json, parse_otlp_spans_json
from .config import load_config
from .store import GraphStore


def _dict(message: Any) -> dict[str, Any]:
    return MessageToDict(message, preserving_proto_field_name=False)


def _services(store: GraphStore):
    try:
        import grpc
        from opentelemetry.proto.collector.logs.v1 import logs_service_pb2, logs_service_pb2_grpc
        from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2, metrics_service_pb2_grpc
        from opentelemetry.proto.collector.trace.v1 import trace_service_pb2, trace_service_pb2_grpc
    except ImportError as exc:
        raise RuntimeError("OTLP/gRPC requires the optional 'otel' dependency group") from exc

    class Traces(trace_service_pb2_grpc.TraceServiceServicer):
        def Export(self, request, context):  # noqa: N802
            ingest_gen_ai_spans(store, parse_otlp_spans_json(_dict(request)))
            return trace_service_pb2.ExportTraceServiceResponse()

    class Metrics(metrics_service_pb2_grpc.MetricsServiceServicer):
        def Export(self, request, context):  # noqa: N802
            ingest_metric_records(store, parse_otlp_metrics_json(_dict(request)))
            return metrics_service_pb2.ExportMetricsServiceResponse()

    class Logs(logs_service_pb2_grpc.LogsServiceServicer):
        def Export(self, request, context):  # noqa: N802
            ingest_log_records(store, parse_otlp_logs_json(_dict(request)))
            return logs_service_pb2.ExportLogsServiceResponse()

    return grpc, Traces(), Metrics(), Logs(), trace_service_pb2_grpc, metrics_service_pb2_grpc, logs_service_pb2_grpc


def serve_grpc(store: GraphStore, *, host: str = "localhost", port: int = 4317,
               max_workers: int = 8) -> None:
    """Serve OTLP traces, metrics, and logs over the standard gRPC port."""
    grpc, traces, metrics, logs, trace_rpc, metric_rpc, log_rpc = _services(store)
    server = grpc.server(ThreadPoolExecutor(max_workers=max_workers))
    trace_rpc.add_TraceServiceServicer_to_server(traces, server)
    metric_rpc.add_MetricsServiceServicer_to_server(metrics, server)
    log_rpc.add_LogsServiceServicer_to_server(logs, server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    try:
        server.wait_for_termination()
    finally:
        server.stop(grace=5)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Serve OTLP traces, metrics, and logs over gRPC")
    parser.add_argument("--home", required=True, help="xibalba-cortex profile home")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4317)
    args = parser.parse_args()
    config = load_config(home=args.home)
    store = GraphStore(config.storage.home, profile_id=config.profile_id, quotas=config.quotas.as_dict())
    try:
        serve_grpc(store, host=args.host, port=args.port)
    finally:
        store.close()


__all__ = ["main", "serve_grpc"]


if __name__ == "__main__":
    main()
