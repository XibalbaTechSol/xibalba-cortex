"""Provision a Cortex DID, manage cloud authentication, and configure agent harnesses."""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

from integrity_sdk.did import key_store_for_profile, load_or_create_did, write_did_file

from .cloud_client import (
    DEFAULT_CLOUD_URL,
    CortexCloudClient,
    DeviceAuthStore,
    DeviceCredentials,
    DevicePairingFlow,
)

_AGENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _default_profile() -> Path:
    return Path(os.environ.get("XIBALBA_CORTEX_HOME", "~/.hermes/xibalba-cortex")).expanduser().resolve()


def redeem_enrollment_code(*, code: str, api_url: str, did: str, keypair: Any, device_id: str) -> dict[str, Any]:
    """Bind this DID to the workspace that issued `code`."""
    from base64 import b64encode
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    payload = json.dumps({
        "code": code,
        "did": did,
        "device_id": device_id,
        "public_key": b64encode(keypair.public_bytes()).decode(),
        "signature": b64encode(keypair.sign(code.encode())).decode(),
    }).encode()
    request = Request(f"{api_url.rstrip('/')}/api/enrollment/redeem", data=payload,
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 -- scheme validated by caller
            return dict(json.loads(response.read().decode()))
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            message = str(json.loads(detail).get("error") or detail)
        except ValueError:
            message = detail
        raise RuntimeError(f"enrollment refused: {message}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"could not reach {api_url} to redeem the enrollment code: {exc}") from exc


def connect(*, profile: str | Path, agent: str, harness: str, mcp_url: str, api_url: str, code: str | None = None) -> dict[str, Any]:
    profile_root = Path(profile).expanduser().resolve()
    if not _AGENT_RE.fullmatch(agent):
        raise ValueError("agent must contain 1-128 letters, digits, dots, underscores, or hyphens")
    if not harness.strip() or len(harness) > 80:
        raise ValueError("harness must contain 1-80 characters")
    if not mcp_url.startswith(("http://", "https://")):
        raise ValueError("mcp_url must be an http(s) URL")
    if not api_url.startswith(("http://", "https://")):
        raise ValueError("api_url must be an http(s) URL")

    profile_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(profile_root, 0o700)
    did, keypair, _ = load_or_create_did(agent, did_home_root=key_store_for_profile(profile_root))
    did_file = write_did_file(profile_root, did=did, public_key=keypair.public_bytes(), agent_id=agent, harness=harness, profile=profile_root.name)

    env = {"XIBALBA_CORTEX_HOME": str(profile_root), "INTEGRITY_PROFILE_ROOT": str(profile_root)}
    enrollment: dict[str, Any] | None = None
    if code:
        enrollment = redeem_enrollment_code(code=code, api_url=api_url, did=did,
                                            keypair=keypair, device_id=profile_root.name)
    return {
        "schema_version": "xibalba.cortex_connect.v1",
        "did": did,
        "agent": agent,
        "harness": harness,
        "profile": str(profile_root),
        "did_file": str(did_file),
        "mcp_url": mcp_url.rstrip("/"),
        "api_url": api_url.rstrip("/"),
        "environment": env,
        "enrollment": enrollment,
        "mcp_stdio": {"mcpServers": {"cortex": {"command": "xibalba-cortex", "args": ["--transport", "stdio"], "env": env}}},
        "mcp_remote": {"url": mcp_url.rstrip("/"), "headers": {"Authorization": "Bearer " + chr(36) + "{CORTEX_API_KEY}"}},
        "sdk_snippet": dedent(f'''
import os
from integrity_sdk import integrity
agent = integrity.init(agent_id={agent!r}, harness={harness!r}, identity="persistent")
# The same DID is used by MCP and the SDK: {did}
agent.start_session("session-1")
agent.prompt("example prompt")
agent.response("example response")
agent.export_cortex(base_url={api_url.rstrip('/')!r}, bearer_token=os.environ["CORTEX_API_KEY"], session_id="session-1")
''').strip(),
        "next": [
            "Log in to Cortex Cloud using 'cortex login' or create a workspace key in the console.",
            "Store it as CORTEX_API_KEY; never put it in source control.",
            "Run 'cortex setup claude' or 'cortex setup cursor' to add Cortex to your harness.",
        ],
        "registration": "DID provisioned locally; no Oracle or on-chain registration was performed.",
    }


def _print_human(result: dict[str, Any]) -> None:
    print(f"DID:          {result['did']}\nProfile:      {result['profile']}\nPublic file:  {result['did_file']}")
    print("\nMCP stdio configuration:\n" + json.dumps(result["mcp_stdio"], indent=2))
    print("\nMCP remote configuration:\n" + json.dumps(result["mcp_remote"], indent=2))
    print("\nSDK snippet:\n" + result["sdk_snippet"])
    print("\nNext steps:")
    for item in result["next"]:
        print(f"- {item}")
    print("\n" + result["registration"])


def login_flow(
    *,
    cloud_url: str = DEFAULT_CLOUD_URL,
    profile: Path | None = None,
    agent: str = "default",
    harness: str = "custom",
    no_browser: bool = False,
    timeout: int = 600,
) -> int:
    profile_root = profile or _default_profile()
    flow = DevicePairingFlow(
        cloud_url=cloud_url,
        profile_root=profile_root,
        agent_name=agent,
        harness=harness,
    )

    print("=" * 64)
    print("  XIBALBA CORTEX — AGENT CLOUD ONBOARDING")
    print("=" * 64)
    print(f"Agent name:  {agent}")
    print(f"Profile:     {profile_root}")
    print(f"Cloud URL:   {cloud_url}")
    print("Initiating device pairing session...")

    def _on_instructions(inst: dict[str, Any]):
        print("\n" + "-" * 64)
        print("  DEVICE AUTHORIZATION REQUIRED")
        print("-" * 64)
        print(f"Verification link:  {inst['verification_uri']}")
        print(f"User code:          {inst['user_code']}")
        print(f"Agent DID:          {inst['agent_did']}")
        print("-" * 64)
        if not no_browser:
            print("Opening browser for authorization...")
        print("Waiting for you to sign in and click 'Authorize Agent'...")

    try:
        creds = flow.run_pairing(
            open_browser=not no_browser,
            on_instructions=_on_instructions,
            timeout_seconds=timeout,
        )
        print("\n" + "=" * 64)
        print("  ✓ AGENT SUCCESSFULLY PAIRED WITH CORTEX CLOUD")
        print("=" * 64)
        print(f"Workspace / Tenant: {creds.tenant_id}")
        print(f"Agent DID:          {creds.agent_did}")
        print(f"Device Name:        {creds.device_name}")
        print(f"Credentials saved:  ~/.cortex/auth.json")
        print("=" * 64)
        print("\nTo connect this agent to Claude Desktop or Cursor:")
        print("  cortex setup claude")
        print("  cortex setup cursor\n")
        return 0
    except Exception as exc:
        print(f"\nLogin failed: {exc}", file=sys.stderr)
        return 1


def status_flow(*, profile: Path | None = None) -> int:
    profile_root = profile or _default_profile()
    creds = DeviceAuthStore.load(profile_root)
    print("=" * 64)
    print("  CORTEX DEVICE & AGENT STATUS")
    print("=" * 64)
    print(f"Profile directory: {profile_root}")
    if not creds:
        print("Status: NOT PAIRED (run 'cortex login' to connect to Cortex Cloud)")
        print("=" * 64)
        return 0

    print("Status:           PAIRED")
    print(f"Cloud URL:        {creds.cloud_url}")
    print(f"Tenant / Profile: {creds.tenant_id or 'unknown'}")
    print(f"Agent DID:        {creds.agent_did or 'unknown'}")
    print(f"Agent Name:       {creds.agent_name}")
    print(f"Device Name:      {creds.device_name or platform.node()}")
    print(f"Paired At:        {creds.paired_at or 'unknown'}")

    client = CortexCloudClient(cloud_url=creds.cloud_url, token=creds.token, profile_root=profile_root)
    try:
        me_info = client.me()
        account = me_info.get("account", {})
        counts = me_info.get("counts", {})
        print("-" * 64)
        print(f"Account Email:    {account.get('email', 'N/A')}")
        print(f"Approval Status:  {account.get('approval_status', 'N/A')}")
        print(f"Stored Memories:  {counts.get('memories', 0)}")
        print(f"Active Sessions:  {counts.get('sessions', 0)}")
    except Exception as exc:
        print(f"Cloud check:      Unreachable or session expired ({exc})")

    print("=" * 64)
    return 0


def logout_flow(*, profile: Path | None = None) -> int:
    profile_root = profile or _default_profile()
    cleared = DeviceAuthStore.clear(profile_root)
    if cleared:
        print("✓ Paired device credentials removed.")
    else:
        print("No paired device credentials found.")
    return 0


def setup_harness(
    harness: str = "claude",
    cloud_url: str = DEFAULT_CLOUD_URL,
    profile_root: Path | None = None,
) -> int:
    target = harness.lower().strip()
    profile = profile_root or _default_profile()
    creds = DeviceAuthStore.load(profile)
    active_cloud_url = (creds.cloud_url if creds else None) or cloud_url

    configured = []

    if target in ("claude", "all"):
        system = platform.system()
        if system == "Darwin":
            config_path = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        elif system == "Windows":
            appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
            config_path = Path(appdata) / "Claude" / "claude_desktop_config.json"
        else:
            config_path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

        config_path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if config_path.is_file():
            try:
                existing = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}

        mcp_servers = existing.setdefault("mcpServers", {})
        mcp_servers["cortex"] = {
            "command": "xibalba-cortex",
            "args": ["--cloud", active_cloud_url],
        }
        config_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        configured.append(("Claude Desktop", config_path))

    if target in ("cursor", "all"):
        config_path = Path.home() / ".cursor" / "mcp.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if config_path.is_file():
            try:
                existing = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}

        mcp_servers = existing.setdefault("mcpServers", {})
        mcp_servers["cortex"] = {
            "command": "xibalba-cortex",
            "args": ["--cloud", active_cloud_url],
        }
        config_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        configured.append(("Cursor", config_path))

    if target in ("agy", "antigravity", "all"):
        agy_mcp_path = Path.home() / ".gemini" / "antigravity-cli" / "mcp.json"
        agy_mcp_path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if agy_mcp_path.is_file():
            try:
                existing = json.loads(agy_mcp_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}

        mcp_servers = existing.setdefault("mcpServers", {})
        mcp_servers["cortex"] = {
            "command": "xibalba-cortex",
            "args": ["--cloud", active_cloud_url],
            "env": {
                "XIBALBA_CORTEX_HOME": str(profile),
            },
        }
        agy_mcp_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        configured.append(("Antigravity (agy)", agy_mcp_path))

    if not configured:
        print(f"Unknown harness '{harness}'. Choose 'claude', 'cursor', 'agy', or 'all'.", file=sys.stderr)
        return 1

    print("=" * 64)
    print("  ✓ CORTEX MCP HARNESS CONFIGURATION UPDATED")
    print("=" * 64)
    for name, p in configured:
        print(f"- {name}: {p}")
    print("\nRestart your harness application to activate Cortex memory.")
    print("=" * 64)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cortex", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    # cortex login
    login_cmd = sub.add_parser("login", help="authenticate this agent/device with Cortex Cloud in browser")
    login_cmd.add_argument("--cloud", default=DEFAULT_CLOUD_URL, help="Cortex Cloud endpoint")
    login_cmd.add_argument("--profile", type=Path, default=_default_profile(), help="Cortex home/profile directory")
    login_cmd.add_argument("--agent", default="default", help="agent identity label")
    login_cmd.add_argument("--harness", default="custom", help="harness name")
    login_cmd.add_argument("--no-browser", action="store_true", help="do not open browser automatically")
    login_cmd.add_argument("--timeout", type=int, default=600, help="timeout in seconds")

    # cortex status
    status_cmd = sub.add_parser("status", help="check paired status, DID, and workspace info")
    status_cmd.add_argument("--profile", type=Path, default=_default_profile(), help="Cortex profile directory")

    # cortex logout
    logout_cmd = sub.add_parser("logout", help="remove paired device credentials")
    logout_cmd.add_argument("--profile", type=Path, default=_default_profile(), help="Cortex profile directory")

    # cortex setup
    setup_cmd = sub.add_parser("setup", help="configure MCP in Claude Desktop, Cursor, agy, etc.")
    setup_cmd.add_argument("harness", nargs="?", default="claude", choices=["claude", "cursor", "agy", "all"])
    setup_cmd.add_argument("--cloud", default=DEFAULT_CLOUD_URL, help="Cortex Cloud endpoint")
    setup_cmd.add_argument("--profile", type=Path, default=_default_profile())

    # cortex connect (legacy & backward-compatible)
    command = sub.add_parser("connect", help="create or reuse a DID and print connection snippets")
    command.add_argument("--profile", type=Path, default=_default_profile())
    command.add_argument("--agent", default="default")
    command.add_argument("--harness", default="custom")
    command.add_argument("--mcp-url", default="http://127.0.0.1:8421/mcp")
    command.add_argument("--api-url", default="http://127.0.0.1:8421")
    command.add_argument("--json", action="store_true")
    command.add_argument("--code", default=None, help="single-use enrollment code from the console")

    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        parser.print_help()
        return 0

    known_subcommands = {"login", "status", "logout", "setup", "connect", "-h", "--help"}
    if raw[0] not in known_subcommands and not raw[0].startswith("-"):
        raw.insert(0, "connect")
    elif raw[0].startswith("-") and raw[0] not in ("-h", "--help"):
        raw.insert(0, "connect")

    args = parser.parse_args(raw)
    if args.command is None:
        parser.print_help()
        return 2

    if args.command == "login":
        return login_flow(
            cloud_url=args.cloud,
            profile=args.profile,
            agent=args.agent,
            harness=args.harness,
            no_browser=args.no_browser,
            timeout=args.timeout,
        )
    elif args.command == "status":
        return status_flow(profile=args.profile)
    elif args.command == "logout":
        return logout_flow(profile=args.profile)
    elif args.command == "setup":
        return setup_harness(
            harness=args.harness,
            cloud_url=args.cloud,
            profile_root=args.profile,
        )
    elif args.command == "connect":
        try:
            result = connect(
                profile=args.profile,
                agent=args.agent,
                harness=args.harness,
                mcp_url=args.mcp_url,
                api_url=args.api_url,
                code=args.code,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            parser.exit(2, f"cortex connect: {exc}\n")
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            _print_human(result)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
