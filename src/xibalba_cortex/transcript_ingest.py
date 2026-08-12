"""Path C: ingest Claude Code's own session transcript JSONL -- the richest, most complete
source for "entire session including context window and tool calls." Schema verified against
real transcript files on this machine before building this (not guessed):
~/.claude/projects/<project>/<session-uuid>.jsonl.

Unlike Path A (raw API bodies) and Path B (OTLP telemetry), this needs no special env vars --
Claude Code always writes these as part of normal operation, and there's no redaction to work
around: this is Claude Code's own persisted state, not a telemetry export.

What it captures, verified against real transcript structure:
  - `type: "user"` records where `message.content` is a plain string -> a memory, role=user.
  - `type: "assistant"` records: `message.content` is a list of typed blocks --
      - `text`/`thinking` blocks -> a memory, role=assistant (block type recorded in metadata;
        thinking is genuine reasoning trace, not just output, and is worth keeping distinct).
      - `tool_use` blocks -> an otel_event, kind=span, name=f"tool_call.{tool name}",
        span_id=the tool_use block's own id.
  - `type: "user"` records where `message.content` is a list containing `tool_result` blocks
    (Claude Code represents tool results as user-role messages, the standard Anthropic API
    convention) -> an otel_event, kind=span, name="tool_result", span_id AND parent_span_id
    both set to the matching tool_use_id -- a real, unambiguous parent-child span pair, unlike
    Path A/B's request-file-uuid-vs-response-file-request_id mismatch.
  - assistant `message.usage` -> an otel_event, kind=metric, name="context_window.tokens" --
    the direct answer to "context window data": per-turn token composition, not an aggregate.

No truncation cap on tool input/result content, deliberately -- unlike Path A's inherited 60KB
OTel content limit. This is local disk, not a network export; full fidelity is the actual point
of this path. Revisit only if disk usage from it becomes a measured problem, not preemptively.

Incremental, not full-rescan: transcripts are append-only and can grow large, so a per-file
line-offset is tracked in a small state file (`<home>/transcript_ingest_state.json`) --
re-running only processes lines appended since the last run.

Deduplicates against Path A/Path B via the same `GraphStore.find_memory_id_by_content()` --
text this transcript captures that either already stored is reused, not tripled.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .raw_body_ingest import _extract_text
from .redaction import redact as _redact
from .store import GraphStore

_STATE_FILENAME = "transcript_ingest_state.json"


def _load_state(home: Path) -> dict[str, int]:
    state_path = home / _STATE_FILENAME
    if not state_path.is_file():
        return {}
    try:
        return json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(home: Path, state: dict[str, int]) -> None:
    (home / _STATE_FILENAME).write_text(json.dumps(state, sort_keys=True, indent=2))


def _ingest_user_record(
    store: GraphStore, rec: dict[str, Any], session_id: str, prompt_id: str | None
) -> list[dict[str, object]]:
    message = rec.get("message") or {}
    content = message.get("content")
    results: list[dict[str, object]] = []

    if isinstance(content, str):
        if not content.strip():
            return results
        content = _redact(content)
        if store.find_memory_id_by_content(content):
            # Retain the diagnostic counter for compatibility, but do not reuse
            # the prior row: this occurrence still gets its own provenance.
            results.append({"kind": "memory_reused", "role": "user"})
        memory = store.store_memory(
            content,
            source={
                "kind": "runtime_observed",
                "session_id": session_id,
                "role": "user",
                "message_id": rec.get("uuid"),
                "prompt_id": rec.get("promptId"),
                "observed_at": rec.get("timestamp"),
            },
            status="candidate",
            evidence_class="observed_event",
            idempotency_key=f"occurrence:{session_id}:{rec.get('uuid')}:user",
        )
        results.append({"kind": "memory", "id": memory["id"], "role": "user"})
        return results

    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_use_id = block.get("tool_use_id")
            text, _skipped = _extract_text(block.get("content"))
            store.record_otel_batch(session_id, [{
                "kind": "span",
                "name": "tool_result",
                "span_id": tool_use_id,
                "parent_span_id": tool_use_id,
                # Propagated from the most recent user prompt in this transcript, not present
                # on the tool_result block itself -- see ingest_transcript's current_prompt_id
                # tracking. This is what lets the exchange builder attach tool calls to the
                # exchange they actually belong to, matching real OTel prompt.id semantics
                # ("links all events produced while processing a single user prompt").
                "prompt_id": prompt_id,
                # The transcript only records a single instant per record (when this record
                # was written), not a separate call-start/call-end pair -- rec["timestamp"] is
                # the same field already used for memories' observed_at above, so start/end
                # are set equal rather than left null. Without this, every otel_event in the
                # store had no real timestamp at all (only the coarse, ingest-batch-time
                # created_at column), which defeated second-precision compliance search.
                "start_time": rec.get("timestamp"),
                "end_time": rec.get("timestamp"),
                "attributes": {
                    "is_error": block.get("is_error", False),
                    "content": text if text else block.get("content"),
                },
            }])
            results.append({"kind": "otel_event", "name": "tool_result"})
    return results


def _ingest_assistant_record(
    store: GraphStore, rec: dict[str, Any], session_id: str, prompt_id: str | None
) -> list[dict[str, object]]:
    message = rec.get("message") or {}
    content = message.get("content")
    usage = message.get("usage")
    results: list[dict[str, object]] = []

    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type in ("text", "thinking"):
                text = _redact(block.get("text") or block.get("thinking") or "")
                if not text.strip():
                    continue
                if store.find_memory_id_by_content(text):
                    results.append({"kind": "memory_reused", "role": "assistant"})
                memory = store.store_memory(
                    text,
                    source={
                        "kind": "runtime_observed",
                        "session_id": session_id,
                        "role": "assistant",
                        "message_id": rec.get("uuid"),
                        "prompt_id": prompt_id,
                        "observed_at": rec.get("timestamp"),
                        "block_type": block_type,
                    },
                    status="candidate",
                    evidence_class="observed_event",
                    idempotency_key=f"occurrence:{session_id}:{rec.get('uuid')}:{block_type}",
                )
                results.append({"kind": "memory", "id": memory["id"], "role": "assistant"})
            elif block_type == "tool_use":
                store.record_otel_batch(session_id, [{
                    "kind": "span",
                    "name": f"tool_call.{block.get('name')}",
                    "span_id": block.get("id"),
                    "prompt_id": prompt_id,
                    # See the matching comment on the tool_result span above -- same fix,
                    # same reason: rec["timestamp"] was available and simply not passed
                    # through, leaving every tool-call span with no real event time.
                    "start_time": rec.get("timestamp"),
                    "end_time": rec.get("timestamp"),
                    "attributes": {"tool_name": block.get("name"), "input": _redact(block.get("input") or {})},
                }])
                results.append({"kind": "otel_event", "name": "tool_use"})

    if isinstance(usage, dict):
        total = sum(v for v in usage.values() if isinstance(v, int))
        if total > 0:
            store.record_otel_batch(session_id, [{
                "kind": "metric",
                "name": "context_window.tokens",
                "value": total,
                "prompt_id": prompt_id,
                "start_time": rec.get("timestamp"),
                "end_time": rec.get("timestamp"),
                "attributes": usage,
            }])
            results.append({"kind": "otel_event", "name": "context_window.tokens"})
    return results


def _recover_prompt_ids_before(lines: list[str], resume_from_line: int) -> dict[str, str]:
    """Recover the last-known prompt_id per session from already-processed lines, so a
    resumed poll (resume_from_line > 0) correctly continues attributing tool calls to the
    right prompt instead of losing that context at the resume boundary. Scans forward through
    the already-processed prefix once -- cheap relative to re-ingesting, and only run once
    per call, not per line of the new batch.
    """
    current: dict[str, str] = {}
    for line in lines[:resume_from_line]:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "user":
            continue
        message = rec.get("message") or {}
        if isinstance(message.get("content"), str) and rec.get("promptId"):
            session_id = rec.get("sessionId")
            if session_id:
                current[session_id] = rec["promptId"]
    return current


def ingest_transcript(store: GraphStore, transcript_path: Path, *, resume_from_line: int = 0) -> dict[str, object]:
    """Process one transcript file starting at `resume_from_line`. Pure function over an
    explicit offset -- state persistence is the caller's job (see `run` below), so this stays
    directly testable without touching disk for state.
    """
    lines = transcript_path.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines = lines[resume_from_line:]
    current_prompt_id_by_session = _recover_prompt_ids_before(lines, resume_from_line)

    memories = 0
    reused = 0
    otel_events = 0
    skipped_records = 0
    malformed = 0

    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue

        session_id = rec.get("sessionId")
        rec_type = rec.get("type")
        if not session_id or rec_type not in ("user", "assistant"):
            skipped_records += 1
            continue

        store.start_session(session_id, retention_tier="verbatim")
        message = rec.get("message") or {}
        if rec_type == "user" and isinstance(message.get("content"), str) and rec.get("promptId"):
            current_prompt_id_by_session[session_id] = rec["promptId"]
        prompt_id = current_prompt_id_by_session.get(session_id)
        if rec_type == "user":
            results = _ingest_user_record(store, rec, session_id, prompt_id)
        else:
            results = _ingest_assistant_record(store, rec, session_id, prompt_id)

        for result in results:
            if result["kind"] == "memory":
                memories += 1
            elif result["kind"] == "memory_reused":
                reused += 1
            elif result["kind"] == "otel_event":
                otel_events += 1

    return {
        "lines_processed": len(new_lines),
        "resume_from_line": resume_from_line,
        "new_resume_line": len(lines),
        "memories_created": memories,
        "memories_reused": reused,
        "otel_events_created": otel_events,
        "skipped_records": skipped_records,
        "malformed_lines": malformed,
    }


def run(store: GraphStore, home: Path, transcript_path: Path) -> dict[str, object]:
    """Stateful wrapper: reads/writes the resume offset for `transcript_path` in
    `<home>/transcript_ingest_state.json` so repeated calls (e.g. polling an in-progress
    session) only process newly appended lines.
    """
    state = _load_state(home)
    key = str(transcript_path.resolve())
    resume_from = state.get(key, 0)
    result = ingest_transcript(store, transcript_path, resume_from_line=resume_from)
    state[key] = result["new_resume_line"]
    _save_state(home, state)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", required=True, type=Path, help="Path to a Claude Code session transcript JSONL")
    parser.add_argument("--home", required=True, type=Path, help="xibalba-cortex profile home")
    args = parser.parse_args()

    store = GraphStore(args.home)
    try:
        result = run(store, args.home, args.transcript)
        print(json.dumps(result, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
