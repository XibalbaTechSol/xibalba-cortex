"""Tests for Cortex Cloud client, DeviceAuthStore, and DevicePairingFlow."""
from __future__ import annotations

import http.server
import json
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from xibalba_cortex.cloud_client import (
    CortexCloudClient,
    DeviceAuthStore,
    DeviceCredentials,
    DevicePairingFlow,
    _LoopbackServer,
)


def test_device_auth_store_save_load_clear(tmp_path: Path):
    creds = DeviceCredentials(
        token="test-cortex-token-12345",
        cloud_url="https://cloud.xibalba.test",
        tenant_id="tenant-alpha",
        agent_did="did:integrity:1234567890abcdef",
        agent_name="pilot-agent",
        device_id="device-mock-1",
        device_name="Mock Laptop",
    )

    saved_path = DeviceAuthStore.save(creds, profile_root=tmp_path)
    assert saved_path.is_file()
    assert (saved_path.stat().st_mode & 0o777) == 0o600

    loaded = DeviceAuthStore.load(profile_root=tmp_path)
    assert loaded is not None
    assert loaded.token == "test-cortex-token-12345"
    assert loaded.cloud_url == "https://cloud.xibalba.test"
    assert loaded.tenant_id == "tenant-alpha"
    assert loaded.agent_did == "did:integrity:1234567890abcdef"
    assert loaded.agent_name == "pilot-agent"

    cleared = DeviceAuthStore.clear(profile_root=tmp_path)
    assert cleared is True
    assert DeviceAuthStore.load(profile_root=tmp_path) is None


def test_loopback_callback_captures_token():
    server = _LoopbackServer(("127.0.0.1", 0))
    port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        url = f"http://127.0.0.1:{port}/callback?token=mock-token-xyz&tenant_id=t-100&agent_did=did:integrity:abc"
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "Agent Authorized" in body

        assert server.done_event.wait(timeout=2)
        assert server.result is not None
        assert server.result["token"] == "mock-token-xyz"
        assert server.result["tenant_id"] == "t-100"
        assert server.result["agent_did"] == "did:integrity:abc"
    finally:
        server.shutdown()
        server.server_close()


class _MockCloudHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

        if self.path == "/api/managed/device/pair/request":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "device_code": "dev-code-999",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://test.cloud/#pair?code=ABCD-EFGH",
                "expires_in": 300,
                "interval": 1,
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        elif self.path == "/api/managed/memories":
            auth = self.headers.get("authorization", "")
            if auth != "Bearer token-ok-123":
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"id": "mem-101", "content": data.get("content")}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        auth = self.headers.get("authorization", "")
        if self.path.startswith("/api/managed/device/pair/dev-code-999/status"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "approved",
                "token": "token-ok-123",
                "tenant_id": "tenant-test",
            }).encode("utf-8"))
        elif self.path.startswith("/api/managed/memories"):
            if auth != "Bearer token-ok-123":
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"memories": [{"id": "mem-101", "content": "hello world"}]}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def test_device_pairing_flow_and_cloud_client(tmp_path: Path):
    mock_server = http.server.HTTPServer(("127.0.0.1", 0), _MockCloudHandler)
    mock_port = mock_server.server_port
    cloud_url = f"http://127.0.0.1:{mock_port}"
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()

    try:
        instructions_received = []

        flow = DevicePairingFlow(
            cloud_url=cloud_url,
            profile_root=tmp_path,
            agent_name="test-agent",
            harness="pytest",
        )
        creds = flow.run_pairing(
            open_browser=False,
            on_instructions=lambda inst: instructions_received.append(inst),
            timeout_seconds=10,
        )

        assert creds.token == "token-ok-123"
        assert creds.tenant_id == "tenant-test"
        assert len(instructions_received) == 1
        assert instructions_received[0]["user_code"] == "ABCD-EFGH"

        # Now test CortexCloudClient using stored credentials
        client = CortexCloudClient(cloud_url=cloud_url, profile_root=tmp_path)
        assert client.is_authenticated

        # Store memory
        stored = client.store_memory("Remember to hydrate.")
        assert stored["id"] == "mem-101"
        assert stored["content"] == "Remember to hydrate."

        # Search memories
        results = client.search_memories("hydrate")
        assert len(results) == 1
        assert results[0]["id"] == "mem-101"
    finally:
        mock_server.shutdown()
        mock_server.server_close()
