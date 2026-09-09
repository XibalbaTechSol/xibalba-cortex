"""Build a session's Merkle-chained exchange sequence from whatever memories/otel_events
already exist for it -- path-agnostic: works identically whether the underlying data came
from raw_body_ingest (Path A), otlp_receiver (Path B), transcript_ingest (Path C), or a
combination, since all three converge on the same memories/otel_events tables and dedupe
against each other already (GraphStore.find_memory_id_by_content).

An "exchange" is one prompt and everything that followed it before the next prompt: the
response text/thinking memories, plus any otel_events (tool calls, context-window metrics)
correlated to that turn via prompt_id or an explicit memory_id link. Grouping is by role
(source.role == "user" starts a new exchange; "assistant" memories accumulate into the
current one) -- session summary memories (evidence_class="summary", written by end_session)
are deliberately excluded, since they're a session-level artifact, not a turn.
"""
from __future__ import annotations

from .store import GraphStore


def build_session_exchanges(store: GraphStore, external_session_id: str) -> dict[str, object]:
    """Build the derived exchange view once and return explicit duplicate or empty outcomes."""
    session = store.get_session(external_session_id)
    external_session_id = str(session["external_session_id"])
    existing_exchanges = store.session_exchanges(external_session_id)
    if existing_exchanges:
        return {
            "session_id": external_session_id,
            "exchanges_built": 0,
            "exchange_ids": [],
            "status": "unchanged",
            "deduplicated": True,
            "reason": "session_exchanges_already_exist",
        }
    memories = [
        m for m in store.session_memories(external_session_id)
        if m["evidence_class"] != "summary"
    ]
    otel_events = store.session_otel_events(external_session_id)
    if not memories and not otel_events:
        return {
            "session_id": external_session_id,
            "exchanges_built": 0,
            "exchange_ids": [],
            "status": "empty",
            "deduplicated": False,
            "reason": "no_non_summary_memories_or_otel_events",
        }

    # Group otel_events for fast lookup: by prompt_id (weak link) and by memory_id (strong link).
    events_by_prompt_id: dict[str, list[dict]] = {}
    events_by_memory_id: dict[str, list[dict]] = {}
    for event in otel_events:
        if event["prompt_id"]:
            events_by_prompt_id.setdefault(event["prompt_id"], []).append(event)
        if event["memory_id"]:
            events_by_memory_id.setdefault(event["memory_id"], []).append(event)

    def _linked_events(memory: dict[str, object]) -> list[dict]:
        found = {}
        for event in events_by_memory_id.get(memory["id"], []):
            found[event["id"]] = event
        prompt_id = memory["source"].get("prompt_id")
        if prompt_id:
            for event in events_by_prompt_id.get(prompt_id, []):
                found[event["id"]] = event
        return list(found.values())

    exchanges_built = []
    current_prompt: dict[str, object] | None = None
    current_responses: list[dict[str, object]] = []
    current_events: dict[str, dict] = {}
    seen_prompt_ids = set()

    def _flush():
        if current_prompt is None and not current_responses and not current_events:
            return
        prompt_ids = [current_prompt["id"]] if current_prompt else []
        response_ids = [m["id"] for m in current_responses]
        tool_call_ids = list(current_events.keys())
        prompt_time = current_prompt["source"]["observed_at"] if current_prompt else None
        response_time = current_responses[-1]["source"]["observed_at"] if current_responses else None
        pid = current_prompt["source"].get("prompt_id") if current_prompt else None
        if pid:
            seen_prompt_ids.add(pid)
        exchange = store.record_exchange(
            external_session_id,
            prompt_memory_ids=prompt_ids,
            response_memory_ids=response_ids,
            tool_call_otel_event_ids=tool_call_ids,
            prompt_id=pid,
            prompt_time=prompt_time,
            response_time=response_time,
        )
        exchanges_built.append(exchange["id"])

    for memory in memories:
        role = memory["source"].get("role")
        if role == "user":
            _flush()
            current_prompt = memory
            current_responses = []
            current_events = {}
            for event in _linked_events(memory):
                current_events[event["id"]] = event
        else:
            current_responses.append(memory)
            for event in _linked_events(memory):
                current_events[event["id"]] = event
    _flush()

    unseen_prompt_ids = set(events_by_prompt_id.keys()) - seen_prompt_ids - {None}
    if unseen_prompt_ids:
        def earliest_event(pid):
            return min(e["created_at"] for e in events_by_prompt_id[pid])
        
        for pid in sorted(unseen_prompt_ids, key=earliest_event):
            events = events_by_prompt_id[pid]
            exchange = store.record_exchange(
                external_session_id,
                prompt_memory_ids=[],
                response_memory_ids=[],
                tool_call_otel_event_ids=[e["id"] for e in events],
                prompt_id=pid,
                prompt_time=None,
                response_time=None,
            )
            exchanges_built.append(exchange["id"])

    return {
        "session_id": external_session_id,
        "exchanges_built": len(exchanges_built),
        "exchange_ids": exchanges_built,
        "status": "built",
        "deduplicated": False,
        "reason": None,
    }
