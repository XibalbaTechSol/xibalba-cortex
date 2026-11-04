"""Unit tests for the expanded cortex CLI commands (login, status, logout, setup, connect)."""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from xibalba_cortex import connect
from xibalba_cortex.cloud_client import DeviceAuthStore, DeviceCredentials


class _MockCloudHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path == "/api/managed/device/pair/request":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "device_code": "dev-123",
                "user_code": "CLI-PAIR",
                "verification_uri": "https://cortex.mock/#pair?code=CLI-PAIR",
                "expires_in": 300,
                "interval": 1,
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/managed/device/pair/dev-123/status"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "approved",
                "token": "paired-token-999",
                "tenant_id": "tenant-cli-test",
            }).encode("utf-8"))
        elif self.path == "/api/managed/me":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "account": {"email": "agent-user@example.com", "approval_status": "approved"},
                "counts": {"memories": 42, "sessions": 5},
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def test_cortex_connect_legacy_command(tmp_path: Path, capsys):
    ret = connect.main(["connect", "--profile", str(tmp_path), "--agent", "testagent", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["schema_version"] == "xibalba.cortex_connect.v1"
    assert data["agent"] == "testagent"
    assert "did:integrity:" in data["did"]


def test_cortex_login_and_status_and_logout(tmp_path: Path, capsys):
    mock_server = http.server.HTTPServer(("127.0.0.1", 0), _MockCloudHandler)
    mock_port = mock_server.server_port
    cloud_url = f"http://127.0.0.1:{mock_port}"
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()

    try:
        # 1. Login flow
        ret = connect.main([
            "login",
            "--cloud", cloud_url,
            "--profile", str(tmp_path),
            "--agent", "testagent",
            "--no-browser",
            "--timeout", "10",
        ])
        assert ret == 0
        captured = capsys.readouterr()
        assert "AGENT SUCCESSFULLY PAIRED" in captured.out
        assert "tenant-cli-test" in captured.out

        # Verify auth file saved
        creds = DeviceAuthStore.load(tmp_path)
        assert creds is not None
        assert creds.token == "paired-token-999"

        # 2. Status flow
        ret_status = connect.main(["status", "--profile", str(tmp_path)])
        assert ret_status == 0
        captured_status = capsys.readouterr()
        assert "PAIRED" in captured_status.out
        assert "agent-user@example.com" in captured_status.out
        assert "42" in captured_status.out

        # 3. Logout flow
        ret_logout = connect.main(["logout", "--profile", str(tmp_path)])
        assert ret_logout == 0
        assert DeviceAuthStore.load(tmp_path) is None

        # 4. Status after logout
        ret_status_after = connect.main(["status", "--profile", str(tmp_path)])
        assert ret_status_after == 0
        captured_after = capsys.readouterr()
        assert "NOT PAIRED" in captured_after.out
    finally:
        mock_server.shutdown()
        mock_server.server_close()


def test_cortex_setup_harness(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # Claude desktop config
    ret_claude = connect.main(["setup", "claude", "--cloud", "https://cloud.test", "--profile", str(tmp_path)])
    assert ret_claude == 0
    claude_cfg = tmp_path / ".config" / "Claude" / "claude_desktop_config.json"
    assert claude_cfg.is_file()
    cfg_data = json.loads(claude_cfg.read_text())
    assert cfg_data["mcpServers"]["cortex"]["command"] == "xibalba-cortex"
    assert cfg_data["mcpServers"]["cortex"]["args"] == ["--cloud", "https://cloud.test"]

    # Cursor config
    ret_cursor = connect.main(["setup", "cursor", "--cloud", "https://cloud.test", "--profile", str(tmp_path)])
    assert ret_cursor == 0
    cursor_cfg = tmp_path / ".cursor" / "mcp.json"
    assert cursor_cfg.is_file()
    cursor_data = json.loads(cursor_cfg.read_text())
    assert cursor_data["mcpServers"]["cortex"]["command"] == "xibalba-cortex"

    # Antigravity (agy) config
    ret_agy = connect.main(["setup", "agy", "--cloud", "https://cloud.test", "--profile", str(tmp_path)])
    assert ret_agy == 0
    agy_cfg = tmp_path / ".gemini" / "antigravity-cli" / "mcp.json"
    assert agy_cfg.is_file()
    agy_data = json.loads(agy_cfg.read_text())
    assert agy_data["mcpServers"]["cortex"]["command"] == "xibalba-cortex"
    assert agy_data["mcpServers"]["cortex"]["args"] == ["--cloud", "https://cloud.test"]
