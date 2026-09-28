import threading
import time

import grpc
import pytest
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2, logs_service_pb2_grpc

from xibalba_cortex.ingest_tokens import issue_token
from xibalba_cortex.otlp_grpc_receiver import serve_grpc
from xibalba_cortex.store import GraphStore


def _free_port():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


def _start(store, port):
    thread = threading.Thread(target=serve_grpc, kwargs={"store": store, "port": port}, daemon=True)
    thread.start()
    time.sleep(0.3)


def test_grpc_export_without_a_token_is_rejected(tmp_path):
    store = GraphStore(tmp_path / "graph")
    port = _free_port()
    _start(store, port)

    with grpc.insecure_channel(f"localhost:{port}") as channel:
        stub = logs_service_pb2_grpc.LogsServiceStub(channel)
        with pytest.raises(grpc.RpcError) as excinfo:
            stub.Export(logs_service_pb2.ExportLogsServiceRequest())
        assert excinfo.value.code() == grpc.StatusCode.UNAUTHENTICATED
    store.close()


def test_grpc_export_with_a_reader_only_token_is_rejected(tmp_path):
    store = GraphStore(tmp_path / "graph")
    port = _free_port()
    _start(store, port)
    token = issue_token(store.home, "reader", profile_id=store.profile_id, roles=("reader",), scopes=("memory:read",))

    with grpc.insecure_channel(f"localhost:{port}") as channel:
        stub = logs_service_pb2_grpc.LogsServiceStub(channel)
        with pytest.raises(grpc.RpcError) as excinfo:
            stub.Export(logs_service_pb2.ExportLogsServiceRequest(), metadata=(("authorization", f"Bearer {token}"),))
        assert excinfo.value.code() == grpc.StatusCode.PERMISSION_DENIED
    store.close()


def test_grpc_export_with_a_valid_writer_token_succeeds(tmp_path):
    store = GraphStore(tmp_path / "graph")
    port = _free_port()
    _start(store, port)
    token = issue_token(
        store.home, "writer", profile_id=store.profile_id,
        roles=("writer",), scopes=("memory:read", "memory:write"),
    )

    with grpc.insecure_channel(f"localhost:{port}") as channel:
        stub = logs_service_pb2_grpc.LogsServiceStub(channel)
        response = stub.Export(
            logs_service_pb2.ExportLogsServiceRequest(),
            metadata=(("authorization", f"Bearer {token}"),),
        )
        assert response is not None
    store.close()
