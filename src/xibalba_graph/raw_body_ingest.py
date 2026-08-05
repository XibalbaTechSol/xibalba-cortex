"""Ingest raw Anthropic Messages API request/response bodies Claude Code writes to disk.

Path A of the "collect raw LLM input/output" plan (Path B is the OTLP log receiver for
claude_code.user_prompt/assistant_response, correlated -- not built here).

Enable on the Claude Code side with:

    CLAUDE_CODE_ENABLE_TELEMETRY=1
    OTEL_LOG_RAW_API_BODIES=file:<dir>

Per Claude Code's own docs (code.claude.com/docs/en/monitoring-usage), this writes:
    <dir>/<uuid>.request.json          -- untruncated Anthropic Messages API request body
    <dir>/<request_id>.response.json   -- untruncated Anthropic Messages API response body

with NO wrapper metadata in the files themselves -- no session_id, no prompt_id, no
timestamp, and critically no way to pair a request file to its response file from the files
or filenames alone (they use different identifier schemes: a fresh uuid for requests, the
Anthropic API's own request_id for responses). That pairing lives only in the OTLP event
stream's attributes (client_request_id / request_id), which Path B will provide.

What this module does honestly, standalone, without Path B:
  - Captures every request/response body's actual text content as a memory -- the direct
    answer to "get the raw input and raw output text."
  - Preserves the file-derived identifier (the uuid or request_id) as the memory's
    `message_id`, so that when Path B lands, its events (which carry both identifiers) can
    retroactively join request memories to response memories and to a real session_id.
  - Does NOT claim to know which session, or which response answers which request. Every
    ingested memory's `session_id` is a fixed synthetic session
    ("raw-capture-unattributed") until Path B supplies the real one -- explicit, not
    silently guessed.

Idempotent by construction: `idempotency_key` is derived from the file path, so re-scanning
already-ingested files (e.g. on every poll) is a no-op, not a duplicate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .store import GraphStore

UNATTRIBUTED_SESSION_ID = "raw-capture-unattributed"


def _extract_text(content: Any) -> tuple[str, list[str]]:
    """Anthropic Messages API content is either a plain string or a list of typed blocks
    (text/tool_use/tool_result/thinking/...). Concatenate text blocks; note the kinds of any
    non-text blocks seen rather than silently dropping them -- honest about what's not
    captured, not a silent gap.
    """
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return "", []
    texts: list[str] = []
    skipped_kinds: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
        elif block_type:
            skipped_kinds.append(block_type)
    return "\n".join(texts), skipped_kinds


def _ingest_request_file(store: GraphStore, path: Path) -> dict[str, object] | None:
    """The request body carries the FULL conversation history (Claude Code's docs: "Bodies
    include the entire conversation history"), not just the new turn -- so the honest unit to
    capture is the last message in the array, which is the new user input for this turn.
    Earlier messages in the same array were already ingested as their own turn's last message
    in a prior request file.
    """
    try:
        body = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"file": str(path), "status": "error", "error": f"unreadable: {exc}"}

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return {"file": str(path), "status": "error", "error": "no messages array in request body"}
    last = messages[-1]
    text, skipped = _extract_text(last.get("content"))
    if not text.strip():
        return {"file": str(path), "status": "skipped", "reason": "no text content in last message"}

    uuid_stem = path.stem.removesuffix(".request")
    memory = store.store_memory(
        text,
        source={
            "kind": "direct_user",
            "locator": str(path),
            "role": last.get("role", "user"),
            "session_id": UNATTRIBUTED_SESSION_ID,
            "message_id": uuid_stem,
        },
        status="candidate",
        evidence_class="observed_event",
        idempotency_key="raw-body:" + hashlib.sha256(str(path).encode()).hexdigest(),
    )
    return {"file": str(path), "status": "ingested", "memory_id": memory["id"], "skipped_blocks": skipped}


def _ingest_response_file(store: GraphStore, path: Path) -> dict[str, object] | None:
    try:
        body = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"file": str(path), "status": "error", "error": f"unreadable: {exc}"}

    content = body.get("content")
    text, skipped = _extract_text(content)
    if not text.strip():
        return {"file": str(path), "status": "skipped", "reason": "no text content in response body"}

    request_id_stem = path.stem.removesuffix(".response")
    memory = store.store_memory(
        text,
        source={
            "kind": "direct_user",
            "locator": str(path),
            "role": body.get("role", "assistant"),
            "session_id": UNATTRIBUTED_SESSION_ID,
            "message_id": request_id_stem,
        },
        status="candidate",
        evidence_class="observed_event",
        idempotency_key="raw-body:" + hashlib.sha256(str(path).encode()).hexdigest(),
    )
    return {"file": str(path), "status": "ingested", "memory_id": memory["id"], "skipped_blocks": skipped}


def scan_once(store: GraphStore, watch_dir: Path) -> list[dict[str, object]]:
    """Ingest every *.request.json / *.response.json currently in watch_dir. Idempotent --
    safe to call repeatedly on the same directory (e.g. from a poll loop).
    """
    store.start_session(UNATTRIBUTED_SESSION_ID, retention_tier="verbatim")
    results = []
    for path in sorted(watch_dir.glob("*.request.json")):
        result = _ingest_request_file(store, path)
        if result:
            results.append(result)
    for path in sorted(watch_dir.glob("*.response.json")):
        result = _ingest_response_file(store, path)
        if result:
            results.append(result)
    return results


def watch(store: GraphStore, watch_dir: Path, *, poll_interval: float = 2.0) -> None:
    """Poll watch_dir forever, ingesting new files as they appear. No filesystem event API
    dependency (inotify etc.) -- a directory Claude Code writes to occasionally does not
    justify that complexity; a 2-second poll is cheap and simple.
    """
    while True:
        scan_once(store, watch_dir)
        time.sleep(poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, type=Path, help="Directory Claude Code writes raw bodies to (matches OTEL_LOG_RAW_API_BODIES=file:<dir>)")
    parser.add_argument("--home", required=True, type=Path, help="xibalba-graph-memory profile home")
    parser.add_argument("--once", action="store_true", help="Scan once and exit, instead of polling forever")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    args = parser.parse_args()

    store = GraphStore(args.home)
    try:
        if args.once:
            for result in scan_once(store, args.dir):
                print(json.dumps(result))
        else:
            watch(store, args.dir, poll_interval=args.poll_interval)
    finally:
        store.close()


if __name__ == "__main__":
    main()
