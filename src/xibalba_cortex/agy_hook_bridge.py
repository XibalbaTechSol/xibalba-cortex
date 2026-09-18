"""Native Agy command-hook bridge; stdout is exclusively the hook response."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .agy_adapter import AgyNativeHookAdapter
from .runtime_controller import XibalbaRuntimeController
from .store import GraphStore


def normalize(hook: str, payload: dict) -> dict:
    if hook not in {"PreInvocation", "PostInvocation", "PostToolUse", "Stop"}:
        raise ValueError("unsupported observation hook")
    session = payload.get("conversationId")
    if not isinstance(session, str) or not session:
        raise ValueError("missing conversationId")
    tool = payload.get("toolCall") or {}
    # Use the profile-bound DID supplied by the installed hook. A short harness
    # label is not an authenticated identity and would split attribution from
    # the local Cortex API's DID-bound profile.
    agent_id = os.environ.get("XIBALBA_AGENT_ID", "").strip()
    if not agent_id.startswith("did:integrity:"):
        raise ValueError("missing or invalid profile DID")
    event = {"session_id": session, "agent_id": agent_id}
    for counter in ("stepIdx", "invocationNum", "executionNum"):
        if counter in payload:
            event["event_id"] = f"{counter}:{payload[counter]}"
            break
    if "invocationNum" in payload:
        event["turn_id"] = str(payload["invocationNum"])
    if "stepIdx" in payload:
        event["invocation_id"] = f"step:{payload['stepIdx']}"
    if hook == "PostToolUse":
        event.update(tool_name=tool.get("name"), tool_input=tool.get("args"),
                     status="error" if payload.get("error") else "success")
    return event


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise ValueError("expected hook name")
        hook = sys.argv[1]
        raw = sys.stdin.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("payload too large")
        payload = json.loads(raw)
        event = normalize(hook, payload)
        # Installed command pins the profile so an inherited Hermes profile cannot redirect it.
        home = Path(os.environ["XIBALBA_CORTEX_HOME"])
        store = GraphStore(home)
        try:
            ctl = XibalbaRuntimeController(store, auto_anchor_on_session_end=False)
            result = AgyNativeHookAdapter(ctl, provenance={"source": "agy.command_hook"}).ingest_hook(hook, event)
            # Stop ends an execution attempt, not the resumable conversation.
            # Session finalization belongs to the explicit session-end path.
        finally:
            store.close()
        print(json.dumps({"bridge": "agy", "hook": hook, "recorded": result["recorded"]}), file=sys.stderr)
        print(json.dumps({"decision": "stop"} if hook == "Stop" else {}))
        return 0
    except Exception as exc:
        # Do not echo raw payloads, exceptions, tool arguments, or credentials.
        print(f"agy hook delivery failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
