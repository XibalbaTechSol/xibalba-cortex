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

from .store import MEMORY_KINDS, EngineStore

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.5-flash-lite"
MERGE_SIMILARITY = 0.92      # a new memory this close to an existing one adds evidence instead
MIN_CONFIDENCE = 0.6         # below this a memory is stored as a candidate, not served
MIN_INFERENCE_CONFIDENCE = 0.8
# Models give uncalibrated probabilities (Gemini said 1.0 for all 352 eval memories), so the
# extractor picks a label and the engine maps it to a stored score.
CERTAINTY_SCORES = {"certain": 0.95, "likely": 0.75, "uncertain": 0.4}
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
  commitments, identifiers (PR numbers, versions, paths, ports), and who/what/where.
- Many documents are an agent's progress notes. Narration still contains facts: record the
  outcomes, states, findings and decisions it reports. Skip only greetings and filler.
- Be thorough: most documents yield 1 to 4 memories; a document with nothing durable yields none.
- Every memory must cite one document (its D-number) and a quote copied character-for-character
  from that document (at most 300 characters) that supports it. Quote the words as they read;
  Markdown symbols may be dropped. No quote, no memory.
- Set "inference": true only when the memory is a conclusion the document implies but does not
  state; it still needs a supporting quote.
- Existing memories are listed only so you can mark replacements. If a memory replaces or
  contradicts one, set "updates" to its M-number; otherwise null. They are never a reason to
  skip a new fact, and only an exact restatement of one should be left out.
- Return one entry per document, in order D1..Dn, each with its own list of memories. Read every
  document; an entry may have an empty list only if that document has nothing durable.
- "kind" says what the memory is: "preference" (what someone likes, wants or habitually does),
  "rule" (a standing instruction, policy or constraint), "goal" (an intended future outcome or
  plan), "decision" (a choice that was made), "event" (something that happened at a point in
  time), or "fact" (any other state of the world). Choose the most specific that fits.
- "certainty": "certain" when the quote states the memory outright and nothing suggests it has
  changed; "likely" when it is stated but hedged, partial, or may be out of date; "uncertain"
  when it is speculative ("might", "probably", an untested idea). Do not default to "certain".
- Never write credentials, keys, tokens or passwords into a memory.
- If nothing is worth keeping, return each document's entry with an empty "memories" list."""

_MEMORY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "memory": {"type": "STRING"},
        "quote": {"type": "STRING"},
        "certainty": {"type": "STRING", "enum": list(CERTAINTY_SCORES)},
        "inference": {"type": "BOOLEAN"},
        "kind": {"type": "STRING", "enum": list(MEMORY_KINDS)},
        "updates": {"type": "STRING", "nullable": True},
    },
    "required": ["memory", "quote", "certainty", "inference", "kind"],
}
# One entry per document: batching otherwise lets the model skim and silently skip documents
# (measured: 6-doc batches yielded under half the memories of single-document requests).
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "documents": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"doc": {"type": "STRING"}, "memories": {"type": "ARRAY", "items": _MEMORY_SCHEMA}},
                "required": ["doc", "memories"],
            },
        }
    },
    "required": ["documents"],
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
            return flatten_response(json.loads(text))
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ValueError(f"unparseable extraction response: {exc}") from exc


def flatten_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-document entries -> flat proposals, each tagged with its document's D-number."""
    out: list[dict[str, Any]] = []
    for entry in data.get("documents", []) or []:
        for memory in entry.get("memories", []) or []:
            out.append({**memory, "doc": str(entry.get("doc", ""))})
    return out


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


# bge-small scores even unrelated agent notes around 0.70 (median), so 0.8 is where "related" starts.
# Model-specific: override with SUPER_CORTEX_DREAM_RELATED_SIMILARITY for another embedder.
RELATED_SIMILARITY = float(os.getenv("SUPER_CORTEX_DREAM_RELATED_SIMILARITY", "0.8"))


def related_memories(store: EngineStore, namespace: str, documents: list[dict[str, Any]], per_doc: int = 3,
                     cap: int = 12, min_similarity: float = RELATED_SIMILARITY) -> list[dict[str, Any]]:
    """Existing latest memories close to these documents: the only ones the model may mark as updated.

    Kept short and close on purpose: a long list of loosely related memories made the model treat
    new facts as already known (measured: 30 shown halved the memories proposed).
    """
    ids: list[str] = []
    vectors = store.embedder.embed([d["content"][:MAX_DOC_CHARS] for d in documents])
    for vector in vectors:
        for memory_id, sim in store.memory_vector_ranked(namespace, vector, per_doc):
            if sim >= min_similarity:
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
        label = str(proposal.get("certainty") or "").strip().lower()
        if label in CERTAINTY_SCORES:
            confidence = CERTAINTY_SCORES[label]
        else:  # a numeric confidence from an older or non-Gemini extractor
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
            kind=str(proposal.get("kind") or "fact"),
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
    docs_per_request: int = 3,      # measured: 3/request kept 85% of 1/request's yield at a third of the requests
    max_chars_per_request: int = 9000,
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
            # Lease the batch so a session claiming meanwhile cannot extract the same documents.
            holder = f"worker:{extractor.model}"
            leased = set(store.lease_documents(namespace, [d["id"] for d in batch], holder, 600))
            batch = [d for d in batch if d["id"] in leased]
            if not batch:
                continue
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
                        store.release_lease(namespace, doc_ids, holder)
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
                store.release_lease(namespace, doc_ids, holder)
    if not stats.stopped:
        stats.stopped = "stop requested" if stop and stop.is_set() else "request cap reached"
    return stats
