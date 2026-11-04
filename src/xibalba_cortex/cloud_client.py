"""Client for Cortex Cloud Managed Memory and Device Pairing (RFC 8628 + Loopback)."""
from __future__ import annotations

import hashlib
import http.server
import json
import logging
import os
import platform
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from integrity_sdk.did import key_store_for_profile, load_or_create_did, write_did_file

log = logging.getLogger("xibalba_cortex.cloud_client")

DEFAULT_CLOUD_URL = os.environ.get("CORTEX_CLOUD_URL", os.environ.get("CORTEX_MANAGED_URL", "https://cortex-managed-pilot.onrender.com"))


def get_default_profile_root() -> Path:
    override = os.environ.get("XIBALBA_CORTEX_HOME")
    if override:
        return Path(override).expanduser().resolve()
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        return (Path(hermes_home) / "xibalba-cortex").expanduser().resolve()
    return (Path.home() / ".hermes" / "xibalba-cortex").expanduser().resolve()


def get_auth_file_path(profile_root: Path | None = None) -> Path:
    root = profile_root or get_default_profile_root()
    return root / "device_auth.json"


@dataclass
class DeviceCredentials:
    token: str
    cloud_url: str
    tenant_id: str | None = None
    agent_did: str | None = None
    agent_name: str = "default"
    device_id: str | None = None
    device_name: str | None = None
    paired_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "cloud_url": self.cloud_url,
            "tenant_id": self.tenant_id,
            "agent_did": self.agent_did,
            "agent_name": self.agent_name,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "paired_at": self.paired_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceCredentials:
        return cls(
            token=str(data["token"]),
            cloud_url=str(data.get("cloud_url", DEFAULT_CLOUD_URL)),
            tenant_id=data.get("tenant_id"),
            agent_did=data.get("agent_did"),
            agent_name=str(data.get("agent_name", "default")),
            device_id=data.get("device_id"),
            device_name=data.get("device_name"),
            paired_at=data.get("paired_at"),
        )


class DeviceAuthStore:
    """Manages secure persistence of device credentials."""

    @staticmethod
    def load(profile_root: Path | None = None, *, ignore_env: bool = False) -> DeviceCredentials | None:
        if profile_root is not None:
            path = get_auth_file_path(profile_root)
            if path.is_file():
                try:
                    content = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(content, dict) and content.get("token"):
                        return DeviceCredentials.from_dict(content)
                except Exception as exc:
                    log.warning("Failed to load device auth file %s: %s", path, exc)
            return None

        # When profile_root is None: check default profile path first
        default_path = get_auth_file_path(get_default_profile_root())
        if default_path.is_file():
            try:
                content = json.loads(default_path.read_text(encoding="utf-8"))
                if isinstance(content, dict) and content.get("token"):
                    return DeviceCredentials.from_dict(content)
            except Exception as exc:
                log.warning("Failed to load default auth file %s: %s", default_path, exc)

        # Fallback to CORTEX_API_KEY
        if not ignore_env:
            env_token = os.environ.get("CORTEX_API_KEY")
            cloud_url = os.environ.get("CORTEX_CLOUD_URL", DEFAULT_CLOUD_URL)
            if env_token and env_token.strip():
                return DeviceCredentials(
                    token=env_token.strip(),
                    cloud_url=cloud_url,
                    agent_name=os.environ.get("XIBALBA_AGENT_NAME", "default"),
                    device_id=platform.node(),
                )

        # Fallback to ~/.cortex/auth.json
        fallback = Path.home() / ".cortex" / "auth.json"
        if fallback.is_file():
            try:
                content = json.loads(fallback.read_text(encoding="utf-8"))
                if isinstance(content, dict) and content.get("token"):
                    return DeviceCredentials.from_dict(content)
            except Exception as exc:
                log.warning("Failed to load ~/.cortex/auth.json: %s", exc)

        return None

    @staticmethod
    def save(credentials: DeviceCredentials, profile_root: Path | None = None) -> Path:
        root = profile_root or get_default_profile_root()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)

        path = get_auth_file_path(root)
        temp_path = path.with_suffix(".tmp")
        payload = credentials.to_dict()
        if not payload.get("paired_at"):
            payload["paired_at"] = datetime.now(timezone.utc).isoformat()

        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(temp_path, 0o600)
        temp_path.replace(path)
        os.chmod(path, 0o600)

        # Also link or update ~/.cortex/auth.json for convenience if default profile
        if profile_root is None:
            try:
                cortex_dir = Path.home() / ".cortex"
                cortex_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(cortex_dir, 0o700)
                cortex_auth = cortex_dir / "auth.json"
                cortex_auth.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                os.chmod(cortex_auth, 0o600)
            except Exception:
                pass

        return path

    @staticmethod
    def clear(profile_root: Path | None = None) -> bool:
        cleared = False
        path = get_auth_file_path(profile_root)
        if path.is_file():
            try:
                path.unlink()
                cleared = True
            except OSError:
                pass
        fallback = Path.home() / ".cortex" / "auth.json"
        if fallback.is_file():
            try:
                fallback.unlink()
                cleared = True
            except OSError:
                pass
        return cleared


class _LoopbackCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Handles the browser redirect callback on 127.0.0.1:<port>/callback."""

    server: _LoopbackServer  # Type annotation

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress logging to keep stdio clean
        pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        params = urllib.parse.parse_qs(parsed.query)
        token = params.get("token", [None])[0]
        tenant_id = params.get("tenant_id", [None])[0]
        agent_did = params.get("agent_did", [None])[0]

        if token:
            self.server.result = {
                "token": token,
                "tenant_id": tenant_id,
                "agent_did": agent_did,
            }
            self.server.done_event.set()

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Agent Authorized — Cortex</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f3f4f6; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
    .card { background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 40px; text-align: center; max-width: 440px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
    .icon { font-size: 48px; color: #10b981; margin-bottom: 16px; }
    h1 { font-size: 22px; margin: 0 0 10px 0; font-weight: 600; }
    p { color: #9ca3af; font-size: 14px; line-height: 1.5; margin: 0 0 20px 0; }
    .code { font-family: monospace; background: #1f2937; padding: 4px 8px; border-radius: 4px; color: #60a5fa; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✓</div>
    <h1>Agent Authorized</h1>
    <p>Your agent is now securely connected to <strong>Cortex Cloud</strong>.</p>
    <p>You can close this window and return to your agent harness.</p>
  </div>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization missing token</h1>")


class _LoopbackServer(http.server.HTTPServer):
    def __init__(self, server_address: tuple[str, int]):
        super().__init__(server_address, _LoopbackCallbackHandler)
        self.result: dict[str, Any] | None = None
        self.done_event = threading.Event()


class DevicePairingFlow:
    """Orchestrates browser authorization and token polling for agent onboarding."""

    def __init__(
        self,
        cloud_url: str = DEFAULT_CLOUD_URL,
        profile_root: Path | None = None,
        agent_name: str = "default",
        harness: str = "mcp",
    ):
        self.cloud_url = cloud_url.rstrip("/")
        self.profile_root = profile_root or get_default_profile_root()
        self.agent_name = agent_name
        self.harness = harness
        self.device_id = platform.node() or "device-" + hashlib.sha256(str(self.profile_root).encode()).hexdigest()[:12]
        self.device_name = platform.node() or "Local Device"

    def ensure_agent_did(self) -> str:
        """Loads or creates a persistent Ed25519 DID for this agent."""
        self.profile_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        did, keypair, _ = load_or_create_did(
            self.agent_name, did_home_root=key_store_for_profile(self.profile_root)
        )
        write_did_file(
            self.profile_root,
            did=did,
            public_key=keypair.public_bytes(),
            agent_id=self.agent_name,
            harness=self.harness,
            profile=self.profile_root.name,
        )
        return did

    def request_pairing(self, callback_url: str | None = None) -> dict[str, Any]:
        """Calls /api/managed/device/pair/request on Cortex Cloud."""
        agent_did = self.ensure_agent_did()
        url = f"{self.cloud_url}/api/managed/device/pair/request"
        payload = {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "agent_did": agent_did,
            "agent_name": self.agent_name,
            "callback_url": callback_url,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                res["agent_did"] = agent_did
                return res
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Pairing request failed ({exc.code}): {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Could not reach Cortex Cloud at {self.cloud_url}: {exc}") from exc

    def poll_status(self, device_code: str) -> dict[str, Any]:
        """Polls /api/managed/device/pair/{code}/status."""
        url = f"{self.cloud_url}/api/managed/device/pair/{urllib.parse.quote(device_code)}/status"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return {"status": "error", "code": exc.code}
        except Exception:
            return {"status": "network_error"}

    def run_pairing(
        self,
        *,
        open_browser: bool = True,
        on_instructions: Any | None = None,
        timeout_seconds: int = 600,
    ) -> DeviceCredentials:
        """Executes full hybrid pairing: loopback listener + RFC 8628 polling fallback."""
        # 1. Start ephemeral loopback server
        loopback_server: _LoopbackServer | None = None
        callback_url: str | None = None
        try:
            loopback_server = _LoopbackServer(("127.0.0.1", 0))
            port = loopback_server.server_port
            callback_url = f"http://127.0.0.1:{port}/callback"
            server_thread = threading.Thread(target=loopback_server.serve_forever, daemon=True)
            server_thread.start()
        except Exception as exc:
            log.warning("Could not start local loopback listener: %s (polling only)", exc)

        # 2. Request pairing code from Cortex Cloud
        req = self.request_pairing(callback_url=callback_url)
        device_code = req["device_code"]
        user_code = req["user_code"]
        agent_did = req["agent_did"]

        # Build verification URL
        verification_uri = req.get("verification_uri") or f"{self.cloud_url}/#pair?code={user_code}"
        if callback_url and "callback=" not in verification_uri:
            sep = "&" if "?" in verification_uri else "?"
            verification_uri += f"{sep}callback={urllib.parse.quote(callback_url)}"

        # 3. Notify user / caller
        instructions = {
            "user_code": user_code,
            "verification_uri": verification_uri,
            "agent_did": agent_did,
            "device_name": self.device_name,
            "expires_in": req.get("expires_in", 900),
        }
        if on_instructions:
            on_instructions(instructions)
        else:
            # Output to stderr to preserve stdio for JSON-RPC
            sys.stderr.write(
                f"\n[Cortex] Device pairing required:\n"
                f"  Open in browser: {verification_uri}\n"
                f"  Verification Code: {user_code}\n"
                f"  Agent DID: {agent_did}\n\n"
            )
            sys.stderr.flush()

        # 4. Open browser if requested and possible
        if open_browser:
            try:
                webbrowser.open(verification_uri)
            except Exception:
                pass

        # 5. Wait for loopback or poll status
        start_time = time.time()
        poll_interval = req.get("interval", 2)
        token: str | None = None
        tenant_id: str | None = None

        try:
            while time.time() - start_time < timeout_seconds:
                # Check loopback result
                if loopback_server and loopback_server.done_event.is_set():
                    res = loopback_server.result
                    if res and res.get("token"):
                        token = res["token"]
                        tenant_id = res.get("tenant_id")
                        break

                # Poll cloud
                status_res = self.poll_status(device_code)
                status = status_res.get("status")
                if status == "approved":
                    token = status_res["token"]
                    tenant_id = status_res.get("tenant_id")
                    break
                elif status in ("expired", "rejected"):
                    raise RuntimeError(f"Pairing request was {status}")

                time.sleep(poll_interval)
        finally:
            if loopback_server:
                loopback_server.shutdown()
                loopback_server.server_close()

        if not token:
            raise TimeoutError("Device pairing timed out awaiting authorization.")

        credentials = DeviceCredentials(
            token=token,
            cloud_url=self.cloud_url,
            tenant_id=tenant_id,
            agent_did=agent_did,
            agent_name=self.agent_name,
            device_id=self.device_id,
            device_name=self.device_name,
            paired_at=datetime.now(timezone.utc).isoformat(),
        )
        DeviceAuthStore.save(credentials, self.profile_root)
        return credentials


class CortexCloudClient:
    """Client for interacting with Cortex Cloud Managed Memory API."""

    def __init__(
        self,
        cloud_url: str = DEFAULT_CLOUD_URL,
        token: str | None = None,
        profile_root: Path | None = None,
    ):
        self.cloud_url = cloud_url.rstrip("/")
        self.profile_root = profile_root or get_default_profile_root()
        self._token = token
        if not self._token:
            creds = DeviceAuthStore.load(self.profile_root)
            if creds:
                self._token = creds.token
                if creds.cloud_url:
                    self.cloud_url = creds.cloud_url.rstrip("/")

    @property
    def is_authenticated(self) -> bool:
        return bool(self._token)

    @property
    def token(self) -> str | None:
        return self._token

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        if not self._token:
            raise PermissionError("Cortex Cloud authentication token is not set. Run pairing first.")
        h = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "xibalba-cortex-client/0.1.0",
        }
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    def store_memory(
        self,
        content: str,
        *,
        source: dict[str, Any] | None = None,
        status: str = "active",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Store a memory directly in Cortex Cloud."""
        if not idempotency_key:
            idempotency_key = "mem-" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:24]

        url = f"{self.cloud_url}/api/managed/memories"
        payload = {
            "content": content,
            "source": source or {"kind": "agent_mcp", "timestamp": datetime.now(timezone.utc).isoformat()},
            "status": status,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(idempotency_key), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Cloud store_memory failed ({exc.code}): {detail}") from exc

    def search_memories(self, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """Search or list memories in Cortex Cloud."""
        query_param = f"?q={urllib.parse.quote(query)}" if query else ""
        url = f"{self.cloud_url}/api/managed/memories{query_param}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("memories", [])
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Cloud search_memories failed ({exc.code}): {detail}") from exc

    def get_graph(self) -> dict[str, Any]:
        """Retrieve the tenant knowledge graph from Cortex Cloud."""
        url = f"{self.cloud_url}/api/managed/graph"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Cloud get_graph failed ({exc.code}): {detail}") from exc

    def get_timeline(self) -> dict[str, Any]:
        """Retrieve the tenant memory timeline from Cortex Cloud."""
        url = f"{self.cloud_url}/api/managed/timeline"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Cloud get_timeline failed ({exc.code}): {detail}") from exc

    def me(self) -> dict[str, Any]:
        """Get profile and usage info."""
        url = f"{self.cloud_url}/api/managed/me"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Cloud me call failed ({exc.code}): {detail}") from exc
