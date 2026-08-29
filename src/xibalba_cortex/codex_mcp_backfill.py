"""Backfill Codex session JSONL into xibalba-cortex through the MCP tool surface.

Codex already persists rich local session records under ~/.codex/sessions. This collector
replays those records through memory_ingest_agent_turn, so backfill exercises the same MCP
boundary as live harness capture instead of writing to GraphStore directly.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


DEFAULT_CODEX_SESSIONS = Path("~/.codex/sessions").expanduser()
DEFAULT_CORTEX_HOME = Path(os.environ.get("XIBALBA_CORTEX_HOME", "~/.hermes/xibalba-cortex")).expanduser()
DEFAULT_SERVER_COMMAND = (
    shutil.which("xibalba-cortex")
    or str(Path(__file__).resolve().parents[2] / ".venv" / "bin" / "xibalba-cortex")
)


@dataclass
class CodexTurn:
    session_id: str
    turn_id: str
    prompt: str = ""
    response_parts: list[str] = field(default_factory=list)
    prompt_time: str | None = None
    response_time: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def response(self) -> str:
        return "\n\n".join(part for part in self.response_parts if part.strip())

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return list(self.tool_calls_by_id.values())


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(parts)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), (str, list)):
            return _text(value["content"])
    return ""


def _jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _turn_id_from_payload(payload: dict[str, Any], fallback: str) -> str:
    passthrough = payload.get("internal_chat_message_metadata_passthrough")
    if isinstance(passthrough, dict) and isinstance(passthrough.get("turn_id"), str):
        return passthrough["turn_id"]
    if isinstance(payload.get("turn_id"), str):
        return payload["turn_id"]
    return fallback


def _session_id_from_path(path: Path) -> str:
    return path.stem.replace("rollout-", "codex-")


def parse_codex_session(path: Path) -> list[CodexTurn]:
    session_id = _session_id_from_path(path)
    session_meta: dict[str, Any] = {}
    turns: dict[str, CodexTurn] = {}
    ordered_turn_ids: list[str] = []
    current_turn_id = "unknown"

    def get_turn(turn_id: str) -> CodexTurn:
        nonlocal session_id
        if turn_id not in turns:
            turns[turn_id] = CodexTurn(
                session_id=session_id,
                turn_id=turn_id,
                metadata={"transcript_path": str(path), **session_meta},
            )
            ordered_turn_ids.append(turn_id)
        return turns[turn_id]

    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        timestamp = rec.get("timestamp")
        rec_type = rec.get("type")
        payload = rec.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if rec_type == "session_meta":
            meta_payload = payload
            session_id = meta_payload.get("id") or meta_payload.get("session_id") or session_id
            session_meta = {
                key: meta_payload.get(key)
                for key in ("cwd", "originator", "cli_version", "source", "thread_source", "model_provider")
                if meta_payload.get(key) is not None
            }
            for turn in turns.values():
                turn.session_id = session_id
                turn.metadata.update(session_meta)
            continue

        if rec_type == "turn_context":
            current_turn_id = payload.get("turn_id") or current_turn_id
            turn = get_turn(current_turn_id)
            for key in ("cwd", "model", "approval_policy"):
                if payload.get(key) is not None:
                    turn.metadata[key] = payload[key]
            continue

        if rec_type == "event_msg" and payload.get("type") == "user_message":
            turn_id = _turn_id_from_payload(payload, current_turn_id)
            turn = get_turn(turn_id)
            turn.prompt = payload.get("message") or ""
            turn.prompt_time = timestamp
            turn.metadata["prompt_line"] = line_number
            continue

        if rec_type != "response_item":
            continue

        item_type = payload.get("type")
        turn_id = _turn_id_from_payload(payload, current_turn_id)
        turn = get_turn(turn_id)

        if item_type == "message" and payload.get("role") == "assistant":
            text = _text(payload.get("content"))
            if text.strip():
                turn.response_parts.append(text)
                turn.response_time = timestamp
            continue

        if item_type in {"function_call", "custom_tool_call"}:
            call_id = payload.get("call_id") or payload.get("id") or f"{turn_id}:call:{line_number}"
            name = payload.get("name") or payload.get("tool_name") or item_type
            attributes = {
                "codex_item_type": item_type,
                "codex_item_id": payload.get("id"),
                "arguments": _jsonish(payload.get("arguments") or payload.get("input")),
                "line_number": line_number,
            }
            turn.tool_calls_by_id[call_id] = {
                "name": name,
                "span_id": call_id,
                "start_time": timestamp,
                "end_time": timestamp,
                "attributes": attributes,
            }
            continue

        if item_type in {"function_call_output", "custom_tool_call_output"}:
            call_id = payload.get("call_id") or payload.get("id") or f"{turn_id}:output:{line_number}"
            tool_call = turn.tool_calls_by_id.setdefault(
                call_id,
                {
                    "name": item_type,
                    "span_id": call_id,
                    "start_time": timestamp,
                    "attributes": {"codex_item_type": item_type},
                },
            )
            tool_call["end_time"] = timestamp
            attrs = tool_call.setdefault("attributes", {})
            attrs["output"] = payload.get("output")
            attrs["output_line_number"] = line_number

    return [
        turn for turn_id in ordered_turn_ids
        if (turn := turns[turn_id]).prompt.strip() and turn.response.strip()
    ]


def discover_session_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(root.glob("**/*.jsonl"))


async def ingest_turns_via_mcp(
    turns: list[CodexTurn],
    *,
    server_command: str = DEFAULT_SERVER_COMMAND,
    cortex_home: Path = DEFAULT_CORTEX_HOME,
    dry_run: bool = False,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "turns_seen": len(turns),
        "turns_ingested": 0,
        "turns_skipped_existing": 0,
        "tool_calls_seen": sum(len(turn.tool_calls) for turn in turns),
        "sessions": sorted({turn.session_id for turn in turns}),
    }
    if dry_run or not turns:
        return summary

    env = {
        **os.environ,
        "XIBALBA_CORTEX_HOME": str(cortex_home),
        "XIBALBA_CORTEX_RETENTION_TIER": os.environ.get("XIBALBA_CORTEX_RETENTION_TIER", "verbatim"),
        "XIBALBA_CORTEX_IDENTITY_MODE": os.environ.get("XIBALBA_CORTEX_IDENTITY_MODE", "full"),
        "XIBALBA_AGENT_ID": os.environ.get("XIBALBA_AGENT_ID", "codex.backfill"),
    }
    params = StdioServerParameters(command=server_command, env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            existing_prompt_ids: dict[str, set[str]] = {}
            for session_id in summary["sessions"]:
                result = await session.call_tool(
                    "memory_session_exchanges", {"external_session_id": session_id}
                )
                if getattr(result, "is_error", False):
                    existing_prompt_ids[session_id] = set()
                    continue
                exchanges = result.structured_content or {}
                if isinstance(exchanges, dict):
                    rows = exchanges.get("result") or []
                else:
                    rows = exchanges
                existing_prompt_ids[session_id] = {
                    row["prompt_id"] for row in rows
                    if isinstance(row, dict) and isinstance(row.get("prompt_id"), str)
                }
            for turn in turns:
                if turn.turn_id in existing_prompt_ids.get(turn.session_id, set()):
                    summary["turns_skipped_existing"] += 1
                    continue
                result = await session.call_tool(
                    "memory_ingest_agent_turn",
                    {
                        "external_session_id": turn.session_id,
                        "runtime": "codex",
                        "prompt": turn.prompt,
                        "response": turn.response,
                        "tool_calls": turn.tool_calls,
                        "agent_id": "codex",
                        "prompt_id": turn.turn_id,
                        "prompt_time": turn.prompt_time,
                        "response_time": turn.response_time,
                        "metadata": turn.metadata,
                        "idempotency_key": f"codex-jsonl:{turn.session_id}:{turn.turn_id}",
                    },
                )
                if getattr(result, "is_error", False):
                    raise RuntimeError(f"memory_ingest_agent_turn failed for {turn.session_id}/{turn.turn_id}: {result.content}")
                summary["turns_ingested"] += 1
    return summary


async def collect_once(args: argparse.Namespace) -> dict[str, Any]:
    files = discover_session_files(args.sessions)
    if args.limit_files:
        files = files[:args.limit_files]
    turns: list[CodexTurn] = []
    malformed_files = 0
    for path in files:
        try:
            turns.extend(parse_codex_session(path))
        except OSError:
            malformed_files += 1
    if args.limit_turns:
        turns = turns[:args.limit_turns]
    summary = await ingest_turns_via_mcp(
        turns,
        server_command=args.server_command,
        cortex_home=args.home,
        dry_run=args.dry_run,
    )
    summary["files_seen"] = len(files)
    summary["malformed_files"] = malformed_files
    return summary


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.watch:
        return await collect_once(args)

    iterations = 0
    last_summary: dict[str, Any] = {}
    while True:
        iterations += 1
        last_summary = await collect_once(args)
        print(json.dumps({"iteration": iterations, **last_summary}, sort_keys=True), flush=True)
        if args.max_iterations and iterations >= args.max_iterations:
            return {"iterations": iterations, "last_summary": last_summary}
        await asyncio.sleep(args.poll_interval)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, default=DEFAULT_CODEX_SESSIONS, help="Codex JSONL file or sessions directory")
    parser.add_argument("--home", type=Path, default=DEFAULT_CORTEX_HOME, help="xibalba-cortex home used by the MCP server")
    parser.add_argument("--server-command", default=DEFAULT_SERVER_COMMAND, help="xibalba-cortex MCP stdio command")
    parser.add_argument("--dry-run", action="store_true", help="Parse and summarize without writing through MCP")
    parser.add_argument("--watch", action="store_true", help="Poll Codex sessions continuously and ingest only new turns")
    parser.add_argument("--poll-interval", type=float, default=15.0, help="Seconds between --watch scans")
    parser.add_argument("--max-iterations", type=int, default=0, help="Stop --watch after N scans; 0 means forever")
    parser.add_argument("--limit-files", type=int, default=0, help="Only process the first N session files")
    parser.add_argument("--limit-turns", type=int, default=0, help="Only ingest the first N reconstructed turns")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
