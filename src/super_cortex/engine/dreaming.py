"""Dreaming: turn ingested documents into learned memories, with evidence.

Supermemory's "memory" task type has an LLM read each document and write atomic facts. This
module does the same, with one rule Supermemory does not state: a memory is stored only if the
model quotes the passage it came from and that quote is found verbatim (whitespace- and
case-insensitive) in the document it cites. A proposal without locatable evidence is dropped and
counted, so the ungrounded rate is measurable rather than hidden.

The worker is off by default. It runs only when explicitly started (`super-cortex engine dream`,
or SUPER_CORTEX_DREAMING=on for the server), and it spends from a daily request budget keyed to
Gemini's quota day (midnight Pacific). The free tier is per Google project, not per key, so other
processes on the same project draw from the same budget.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .store import EngineStore

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash-lite"
MERGE_SIMILARITY = 0.92      # a new memory this close to an existing one adds evidence instead
MIN_CONFIDENCE = 0.6         # below this a memory is stored as a candidate, not served
MIN_INFERENCE_CONFIDENCE = 0.8
MAX_QUOTE_CHARS = 300
MAX_DOC_CHARS = 4000

_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|ghp_[A-Za-z0-9]{20,}|xox[abp]-[A-Za-z0-9-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b0x[0-9a-fA-F]{64}\b|(?i:(api[_-]?key|secret|password|token)\s*[:=]\s*\S{8,}))"
)

SYSTEM_PROMPT = """You maintain a long-term memory for an AI agent. You read documents and write
memories: short, atomic, self-contained facts worth knowing later.

Rules:
- One fact per memory. Resolve pronouns and vague references using the document ("the service" ->
  its name). Keep names, numbers, dates and identifiers exactly as written.
- Keep durable information: decisions, preferences, configurations, states, outcomes, causes,
  commitments, and who/what/where. Skip greetings, filler, and step-by-step narration.
- Every memory must cite one document (its D-number) and a quote copied character-for-character
  from that document (at most 300 characters) that supports it. No quote, no memory.
- Set "inference": true only when the memory is a conclusion the document implies but does not
  state; it still needs a supporting quote.
- If a memory replaces or contradicts an existing memory listed below, set "updates" to that
  memory's M-number. Otherwise null. Do not restate an existing memory unchanged.
- "confidence" is your probability (0 to 1) that the memory is correct and still current.
- Never write credentials, keys, tokens or passwords into a memory.
- Return {"memories": []} if nothing is worth keeping."""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "memories": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "memory": {"type": "STRING"},
                    "doc": {"type": "STRING"},
                    "quote": {"type": "STRING"},
                    "confidence": {"type": "NUMBER"},
                    "inference": {"type": "BOOLEAN"},
                    "updates": {"type": "STRING", "nullable": True},
                },
                "required": ["memory", "doc", "quote", "confidence", "inference"],
            },
        }
    },
    "required": ["memories"],
}


class QuotaExhausted(RuntimeError):
    """The provider refused for quota reasons. `per_day` means stop until the quota day rolls."""

    def __init__(self, message: str, per_day: bool, retry_after: float | None):
        super().__init__(message)
        self.per_day = per_day
        self.retry_after = retry_after


class TransientError(RuntimeError):
    """Overloaded or unreachable provider: retry later without charging the documents an attempt."""


class Extractor(Protocol):
    model: str

    def propose(self, documents: list[dict[str, Any]], related: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


def build_prompt(documents: list[dict[str, Any]], related: list[dict[str, Any]]) -> str:
    parts = ["Existing memories (cite as M-number in \"updates\" only if replaced):"]
    parts += [f"M{i}: {m['memory']}" for i, m in enumerate(related, 1)] or ["(none)"]
    parts.append("\nDocuments:")
    for i, doc in enumerate(documents, 1):
        stamp = doc.get("metadata", {}).get("created_at") or doc.get("created_at", "")
        parts.append(f"<D{i} written=\"{stamp}\">\n{doc['content'][:MAX_DOC_CHARS]}\n</D{i}>")
    return "\n".join(parts)


class GeminiExtractor:
    """Gemini `generateContent` with a JSON response schema. Free tier only: no billing is assumed."""

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float = 120.0):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is required for dreaming")
        self.model = model or os.getenv("SUPER_CORTEX_DREAM_MODEL", DEFAULT_MODEL)
        self.timeout = timeout

    def propose(self, documents: list[dict[str, Any]], related: list[dict[str, Any]]) -> list[dict[str, Any]]:
        import httpx

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": build_prompt(documents, related)}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json",
                                 "responseSchema": RESPONSE_SCHEMA, "maxOutputTokens": 8192},
        }
        try:
            response = httpx.post(url, json=payload, headers={"x-goog-api-key": self.api_key}, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise TransientError(f"{type(exc).__name__}") from exc
        if response.status_code == 429:
            raise _quota_error(response)
        if response.status_code >= 500:
            raise TransientError(f"HTTP {response.status_code}")
        if response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
            return list(json.loads(text).get("memories", []))
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ValueError(f"unparseable extraction response: {exc}") from exc


def _quota_error(response: Any) -> QuotaExhausted:
    per_day, retry_after, ids = False, None, []
    try:
        for detail in response.json().get("error", {}).get("details", []):
            for violation in detail.get("violations", []) or []:
                quota_id = str(violation.get("quotaId", ""))
                ids.append(f"{quota_id}={violation.get('quotaValue')}")
                per_day = per_day or "PerDay" in quota_id
            if "retryDelay" in detail:
                retry_after = float(str(detail["retryDelay"]).rstrip("s") or 0)
    except Exception:  # noqa: BLE001 - a malformed 429 body is still a 429
        pass
    log.warning("gemini quota refusal: %s", ", ".join(ids) or "no quota details")
    return QuotaExhausted("; ".join(ids) or "quota exhausted", per_day, retry_after)


@dataclass
class DreamStats:
    requests: int = 0
    documents: int = 0
    proposed: int = 0
    stored: int = 0
    candidates: int = 0
    merged: int = 0
    superseded: int = 0
    ungrounded: int = 0
    rejected_secret: int = 0
    failed_batches: int = 0
    stopped: str = ""
    quota_ids: list[str] = field(default_factory=list)

    @property
    def grounded_rate(self) -> float:
        considered = self.proposed - self.rejected_secret
        return 0.0 if considered <= 0 else (considered - self.ungrounded) / considered

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "grounded_rate": round(self.grounded_rate, 4)}


def related_memories(store: EngineStore, namespace: str, documents: list[dict[str, Any]], per_doc: int = 5,
                     cap: int = 30) -> list[dict[str, Any]]:
    """Existing latest memories near these documents: the only ones the model may mark as updated."""
    ids: list[str] = []
    vectors = store.embedder.embed([d["content"][:MAX_DOC_CHARS] for d in documents])
    for doc, vector in zip(documents, vectors):
        for memory_id in store.memory_lexical_ranked(namespace, doc["content"][:2000], per_doc):
            ids.append(memory_id)
        for memory_id, _ in store.memory_vector_ranked(namespace, vector, per_doc):
            ids.append(memory_id)
    unique = list(dict.fromkeys(ids))[:cap]
    found = store.get_memories(unique)
    return [found[i] for i in unique if i in found and found[i]["namespace"] == namespace]


def apply_proposals(store: EngineStore, namespace: str, documents: list[dict[str, Any]],
                    related: list[dict[str, Any]], proposals: list[dict[str, Any]], extractor_model: str,
                    stats: DreamStats) -> None:
    by_label = {f"D{i}": d for i, d in enumerate(documents, 1)}
    related_by_label = {f"M{i}": m for i, m in enumerate(related, 1)}
    for proposal in proposals:
        stats.proposed += 1
        text = str(proposal.get("memory", "")).strip()
        quote = str(proposal.get("quote", "")).strip()[:MAX_QUOTE_CHARS]
        if not text:
            stats.ungrounded += 1
            continue
        if _SECRET.search(text) or _SECRET.search(quote):
            stats.rejected_secret += 1
            continue
        doc = by_label.get(str(proposal.get("doc", "")).strip())
        chunk_id = store.chunk_for_quote(namespace, doc["id"], quote) if doc and quote else None
        if chunk_id is None:
            stats.ungrounded += 1
            continue
        try:
            confidence = max(0.0, min(1.0, float(proposal.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        is_inference = bool(proposal.get("inference"))
        floor = MIN_INFERENCE_CONFIDENCE if is_inference else MIN_CONFIDENCE
        status = "latest" if confidence >= floor else "candidate"
        target = related_by_label.get(str(proposal.get("updates") or "").strip())
        vector = store.embedder.embed([text])[0]

        if target is None:
            nearest = store.memory_vector_ranked(namespace, vector, 1)
            if nearest and nearest[0][1] >= MERGE_SIMILARITY:
                store.add_memory_source(nearest[0][0], namespace, doc["id"], chunk_id, quote)
                stats.merged += 1
                continue
        store.insert_memory(
            namespace, text, [(doc["id"], chunk_id, quote)], confidence=confidence, status=status,
            extractor=extractor_model, is_inference=is_inference,
            supersedes_id=target["id"] if target else None, vector=vector,
        )
        stats.stored += 1
        if status == "candidate":
            stats.candidates += 1
        if target is not None and status == "latest":
            stats.superseded += 1


def _batches(pending: list[dict[str, Any]], docs_per_request: int, max_chars: int) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for doc in pending:
        length = min(len(doc["content"]), MAX_DOC_CHARS)
        same_ns = not current or current[0]["namespace"] == doc["namespace"]
        if current and (not same_ns or len(current) >= docs_per_request or size + length > max_chars):
            batches.append(current)
            current, size = [], 0
        current.append(doc)
        size += length
    if current:
        batches.append(current)
    return batches


def run_dreaming(
    store: EngineStore,
    extractor: Extractor,
    *,
    max_requests: int,
    daily_budget: int | None = None,
    rpm: float | None = None,
    docs_per_request: int = 6,
    max_chars_per_request: int = 14000,
    max_transient_retries: int = 3,
    stop: threading.Event | None = None,
    sleep=time.sleep,
) -> DreamStats:
    """Dream over pending documents until the queue, `max_requests` or the daily budget runs out."""
    daily_budget = daily_budget if daily_budget is not None else int(os.getenv("SUPER_CORTEX_DREAM_DAILY_BUDGET", "200"))
    rpm = rpm if rpm is not None else float(os.getenv("SUPER_CORTEX_DREAM_RPM", "12"))
    spacing = 60.0 / rpm if rpm > 0 else 0.0
    stats = DreamStats()
    last_call = 0.0
    while stats.requests < max_requests and not (stop and stop.is_set()):
        pending = store.pending_documents(limit=docs_per_request * 20)
        if not pending:
            stats.stopped = stats.stopped or "queue empty"
            break
        for batch in _batches(pending, docs_per_request, max_chars_per_request):
            if stats.requests >= max_requests or (stop and stop.is_set()):
                break
            if store.llm_requests_today(extractor.model) >= daily_budget:
                stats.stopped = "daily budget reached"
                return stats
            namespace = batch[0]["namespace"]
            doc_ids = [d["id"] for d in batch]
            related = related_memories(store, namespace, batch)
            for attempt in range(max_transient_retries + 1):
                wait = spacing - (time.monotonic() - last_call)
                if wait > 0:
                    sleep(wait)
                last_call = time.monotonic()
                store.record_llm_request(extractor.model)
                stats.requests += 1
                try:
                    proposals = extractor.propose(batch, related)
                except QuotaExhausted as exc:
                    stats.quota_ids.append(str(exc))
                    if exc.per_day:
                        stats.stopped = "provider daily quota exhausted"
                        return stats
                    sleep(max(exc.retry_after or 0.0, spacing, 5.0))
                    continue
                except TransientError:
                    sleep(min(60.0, 5.0 * 2 ** attempt))
                    continue
                except ValueError as exc:
                    log.warning("dreaming batch failed: %s", exc)
                    store.record_dream_failure(namespace, doc_ids)
                    stats.failed_batches += 1
                    break
                apply_proposals(store, namespace, batch, related, proposals, extractor.model, stats)
                store.mark_dreamed(namespace, doc_ids)
                stats.documents += len(batch)
                break
            else:
                stats.failed_batches += 1  # transient errors used up; documents stay pending
    if not stats.stopped:
        stats.stopped = "stop requested" if stop and stop.is_set() else "request cap reached"
    return stats
