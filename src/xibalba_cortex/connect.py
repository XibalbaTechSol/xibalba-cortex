"""Provision a Cortex DID and print MCP and SDK connection snippets."""
from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path
from textwrap import dedent
from typing import Any
from integrity_sdk.did import key_store_for_profile, load_or_create_did, write_did_file
_AGENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
def _default_profile() -> Path:
    return Path(os.environ.get("XIBALBA_CORTEX_HOME", "~/.hermes/xibalba-cortex")).expanduser()
def redeem_enrollment_code(*, code: str, api_url: str, did: str, keypair: Any, device_id: str) -> dict[str, Any]:
    """Bind this DID to the workspace that issued `code`.

    The signature is made here, locally, from the keypair that already exists on this
    machine. The private key never leaves it: the request carries the DID, the *public*
    key, and a signature over the code. The server recomputes the DID fingerprint from
    that public key and refuses if it does not match the DID being claimed, so a stolen
    code cannot be used to bind an identity the caller does not hold the key for.
    """
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
    if not _AGENT_RE.fullmatch(agent): raise ValueError("agent must contain 1-128 letters, digits, dots, underscores, or hyphens")
    if not harness.strip() or len(harness) > 80: raise ValueError("harness must contain 1-80 characters")
    if not mcp_url.startswith(("http://", "https://")): raise ValueError("mcp_url must be an http(s) URL")
    if not api_url.startswith(("http://", "https://")): raise ValueError("api_url must be an http(s) URL")
    profile_root.mkdir(parents=True, exist_ok=True, mode=0o700); os.chmod(profile_root, 0o700)
    did, keypair, _ = load_or_create_did(agent, did_home_root=key_store_for_profile(profile_root))
    did_file = write_did_file(profile_root, did=did, public_key=keypair.public_bytes(), agent_id=agent, harness=harness, profile=profile_root.name)
    # Identity is the validated DID-file/key pair. Do not emit XIBALBA_AGENT_ID:
    # that variable is an explicit override and could bypass pair validation.
    env = {"XIBALBA_CORTEX_HOME": str(profile_root), "INTEGRITY_PROFILE_ROOT": str(profile_root)}
    enrollment: dict[str, Any] | None = None
    if code:
        # Redeemed after the DID exists, because the signature requires its key, and before
        # the snippets are printed, so a refused enrollment does not look like a success.
        enrollment = redeem_enrollment_code(code=code, api_url=api_url, did=did,
                                            keypair=keypair, device_id=profile_root.name)
    return {"schema_version":"xibalba.cortex_connect.v1","did":did,"agent":agent,"harness":harness,"profile":str(profile_root),"did_file":str(did_file),"mcp_url":mcp_url.rstrip("/"),"api_url":api_url.rstrip("/"),"environment":env,"enrollment":enrollment,
      "mcp_stdio":{"mcpServers":{"cortex":{"command":"xibalba-cortex","args":["--transport","stdio"],"env":env}}},
        "mcp_remote":{"url":mcp_url.rstrip("/"),"headers":{"Authorization":"Bearer " + chr(36) + "{CORTEX_API_KEY}"}},
      "sdk_snippet":dedent(f'''
import os
from integrity_sdk import integrity
agent = integrity.init(agent_id={agent!r}, harness={harness!r}, identity="persistent")
# The same DID is used by MCP and the SDK: {did}
agent.start_session("session-1")
agent.prompt("example prompt")
agent.response("example response")
agent.export_cortex(base_url={api_url.rstrip('/')!r}, bearer_token=os.environ["CORTEX_API_KEY"], session_id="session-1")
''').strip(),
      "next":["Create a workspace key bound to this DID in the managed Cortex workspace.","Store it as CORTEX_API_KEY; never put it in source control.","Run cortex_connection_status or one SDK export canary, then recall it."],"registration":"DID provisioned locally; no Oracle or on-chain registration was performed."}
def _print_human(result: dict[str, Any]) -> None:
    print(f"DID:          {result['did']}\nProfile:      {result['profile']}\nPublic file:  {result['did_file']}")
    print("\nMCP stdio configuration:\n" + json.dumps(result["mcp_stdio"], indent=2))
    print("\nMCP remote configuration:\n" + json.dumps(result["mcp_remote"], indent=2))
    print("\nSDK snippet:\n" + result["sdk_snippet"])
    print("\nNext steps:"); [print(f"- {item}") for item in result["next"]]
    print("\n" + result["registration"])
def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(prog="cortex",description=__doc__); sub=parser.add_subparsers(dest="command")
    command=sub.add_parser("connect",help="create or reuse a DID and print connection snippets")
    command.add_argument("--profile",type=Path,default=_default_profile()); command.add_argument("--agent",default="default"); command.add_argument("--harness",default="custom"); command.add_argument("--mcp-url",default="http://127.0.0.1:8421/mcp"); command.add_argument("--api-url",default="http://127.0.0.1:8421"); command.add_argument("--json",action="store_true")
    command.add_argument("--code",default=None,help="single-use enrollment code from the console; binds this DID to that workspace")
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] != "connect":
        raw.insert(0, "connect")
    args=parser.parse_args(raw)
    if args.command is None: parser.print_help(); return 2
    try: result=connect(profile=args.profile,agent=args.agent,harness=args.harness,mcp_url=args.mcp_url,api_url=args.api_url,code=args.code)
    except (OSError,ValueError,RuntimeError) as exc: parser.exit(2,f"cortex connect: {exc}\\n")
    if args.json: print(json.dumps(result,indent=2))
    else: _print_human(result)
    return 0
if __name__ == "__main__": raise SystemExit(main())
