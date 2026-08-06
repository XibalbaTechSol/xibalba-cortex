"""Finalize runtime sessions into graph memory and Hermes state.db.

The finalizer is deliberately a process boundary: runtime hooks and stale-session
scanners only enqueue this command. It is safe to run repeatedly for the same
session because transcript and summary memories use content-derived idempotency
keys, while Hermes message imports use deterministic platform message identifiers.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .store import GraphStore
from .transcript_ingest import run as ingest_claude

DEFAULT_HOME = Path(os.environ.get("XIBALBA_GRAPH_MEMORY_HOME", "~/.hermes/xibalba-graph-memory")).expanduser()
HERMES_AGENT_ROOT = Path(os.environ.get("HERMES_AGENT_ROOT", "~/.hermes/hermes-agent")).expanduser()

_SECRET_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(secret|password|token|private[_ -]?key)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED]"),
    (re.compile(r"\b(?:0x)?[0-9a-fA-F]{64}\b"), "[REDACTED]"),
)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        for pattern, replacement in _SECRET_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {str(key): redact(item) for key, item in value.items()}
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(redact(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for part in (_text(item) for item in value) if part)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), (str, list)):
            return _text(value["content"])
    return ""


def _load_hermes_db():
    root = HERMES_AGENT_ROOT
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from hermes_state import SessionDB  # type: ignore
    return SessionDB


def _hermes_messages(session_id: str) -> list[dict[str, Any]]:
    try:
        SessionDB = _load_hermes_db()
        db = SessionDB()
        try:
            return [redact(message) for message in db.get_messages(session_id, include_inactive=True)]
        finally:
            db.close()
    except Exception:
        return []


def _parse_jsonl(path: Path, runtime: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if not path.is_file():
        return messages
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = record.get("payload") or record
        role = None
        content = ""
        if runtime == "codex":
            if record.get("type") == "response_item" and payload.get("type") == "message":
                role, content = payload.get("role"), _text(payload.get("content"))
            elif record.get("type") == "event_msg":
                event_type = payload.get("type")
                if event_type == "user_message":
                    role, content = "user", payload.get("message", "")
                elif event_type == "agent_message":
                    role, content = "assistant", payload.get("message", "")
        elif runtime == "agy":
            batch = (record.get("$set") or {}).get("messages")
            if isinstance(batch, list):
                for index, item in enumerate(batch):
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("type")
                    item_role = "user" if item_type == "user" else "assistant" if item_type in {"gemini", "assistant"} else None
                    item_content = _text(item.get("content"))
                    if item_role and item_content.strip():
                        messages.append({
                            "role": item_role,
                            "content": redact(item_content),
                            "platform_message_id": f"{runtime}:{path.name}:{line_number}:{index}",
                            "timestamp": item.get("timestamp") or record.get("lastUpdated"),
                        })
                continue
            if record.get("type") == "user":
                role, content = "user", _text(record.get("content"))
            elif record.get("type") in {"gemini", "assistant"}:
                role, content = "assistant", _text(record.get("content"))
        else:
            role, content = record.get("role"), _text(record.get("content"))
        if role in {"user", "assistant", "developer", "tool"} and content.strip():
            messages.append({
                "role": role,
                "content": redact(content),
                "platform_message_id": f"{runtime}:{path.name}:{line_number}",
                "timestamp": record.get("timestamp"),
            })
    return messages


def _hermes_session_upsert(session_id: str, runtime: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Create an actual Hermes session for non-Hermes runtimes and append messages once."""
    SessionDB = _load_hermes_db()
    db = SessionDB()
    try:
        try:
            existing_session = db.get_session(session_id)
        except Exception:
            existing_session = None
        if existing_session:
            created = False
        else:
            db.create_session(session_id, f"xibalba-{runtime}")
            created = True
        existing = {row.get("platform_message_id") for row in db.get_messages(session_id, include_inactive=True)}
        appended = 0
        for message in messages:
            platform_id = message["platform_message_id"]
            if platform_id in existing:
                continue
            db.append_message(
                session_id,
                message["role"],
                content=message["content"],
                platform_message_id=platform_id,
                observed=True,
                timestamp=message.get("timestamp"),
            )
            appended += 1
        return {"created": created, "messages_appended": appended, "messages_seen": len(messages)}
    finally:
        db.close()


def _hermes_end(session_id: str, reason: str) -> None:
    try:
        SessionDB = _load_hermes_db()
        db = SessionDB()
        try:
            if db.get_session(session_id):
                db.end_session(session_id, reason)
        finally:
            db.close()
    except Exception:
        # Graph-memory finalization remains authoritative for retry and records
        # this gap through the returned Hermes result rather than fabricating it.
        return


def finalize(*, session_id: str, runtime: str, transcript_path: Path | None = None,
              reason: str = "explicit_end", source_home: Path = DEFAULT_HOME) -> dict[str, Any]:
    source_home.mkdir(parents=True, exist_ok=True)
    store = GraphStore(source_home)
    try:
        store.start_session(session_id, retention_tier="verbatim")
        if runtime == "hermes":
            messages = _hermes_messages(session_id)
            hermes_result = {"existing": True, "messages_seen": len(messages)}
        else:
            messages = _parse_jsonl(transcript_path, runtime) if transcript_path else []
            hermes_result = _hermes_session_upsert(session_id, runtime, messages)
        _hermes_end(session_id, reason)

        if runtime == "claude" and transcript_path and transcript_path.is_file():
            ingest_result = ingest_claude(store, source_home, transcript_path)
            raw = transcript_path.read_text(encoding="utf-8", errors="replace")
        else:
            ingest_result = {"messages_seen": len(messages)}
            raw = "\n".join(canonical_json(message) for message in messages)
        raw = redact(raw)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if runtime == "agy":
            completeness = {"status": "incomplete", "reasons": ["agy_no_authoritative_transcript_surface"]}
        elif not transcript_path and runtime != "hermes":
            completeness = {"status": "incomplete", "reasons": ["runtime_transcript_not_found"]}
        else:
            completeness = {"status": "partial", "reasons": ["source_stability_not_verified"]}
        if runtime == "hermes":
            completeness = {"status": "partial", "reasons": ["hook_watermark_not_verified"]}
        artifact = store.store_memory(
            raw or f"No transcript content was available; finalization reason: {reason}",
            source={
                "kind": "runtime_transcript",
                "locator": str(transcript_path) if transcript_path else f"hermes://session/{session_id}",
                "session_id": session_id,
                "role": "session",
                "runtime": runtime,
                "reason": reason,
                "content_hash": digest,
            },
            status="candidate",
            evidence_class="observed_event",
            idempotency_key=f"session-transcript:{session_id}:{digest}",
        )
        summary = canonical_json({
            "session_id": session_id,
            "runtime": runtime,
            "reason": reason,
            "transcript_hash": digest,
            "transcript_memory_id": artifact["id"],
            "ingest": ingest_result,
            "hermes": hermes_result,
            "completeness": completeness,
        })
        ended = store.end_session(
            session_id,
            summary_content=summary,
            source={"kind": "session_finalization", "session_id": session_id, "runtime": runtime, "reason": reason},
            idempotency_key=f"session-summary:{session_id}:{digest}",
            summary_status="candidate",
        )
        marker = Path("/home/xibalba/.hermes/xibalba-runtime-sessions") / f"{runtime}.json"
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
        return {"session": ended, "transcript_memory_id": artifact["id"], "transcript_hash": digest,
                "ingest": ingest_result, "hermes": hermes_result, "completeness": completeness}
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--runtime", choices=("claude", "codex", "agy", "hermes"), required=True)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--reason", default="explicit_end")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    args = parser.parse_args()
    print(json.dumps(finalize(session_id=args.session_id, runtime=args.runtime,
                              transcript_path=args.transcript, reason=args.reason,
                              source_home=args.home), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
