"""Session extraction: let the calling agent's own model do the extraction.

An agent session (Claude Code, Codex, agy, Hermes, ...) already pays for a capable model. Instead
of the engine calling Gemini, the session claims a batch of pending documents, runs the same
extractor prompt on its own model, and submits the result:

    claim(store, ns)          -> documents (D1..Dn), related memories (M1..Mn), prompt, schema
    submit(store, claim_id, model=..., documents=[...])   -> stats

Nothing about acceptance changes. Submissions go through `apply_proposals`, the function the
Gemini worker uses: a memory is kept only if its quote appears in the claimed document, secrets
are rejected, near-duplicates merge, and certainty labels set the stored confidence. So the engine
never has to trust the session model, only the quotes it can check.

Claims lease their documents (default 15 minutes) so the worker and other sessions skip them. A
namespace whose policy says `dreaming: off` is never handed out.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .dreaming import (
    RELATED_SIMILARITY,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    DreamStats,
    apply_proposals,
    build_prompt,
    flatten_response,
    related_memories,
)
from .store import EngineStore

DEFAULT_LEASE_SECONDS = 900
MAX_CLAIM_DOCUMENTS = 10
_MODEL = re.compile(r"[^A-Za-z0-9_.:@/-]+")

SUBMIT_INSTRUCTIONS = (
    "Run the instructions on the prompt with your own model, then submit with "
    "memory_extraction_submit: either `documents` shaped like responseSchema "
    "({\"documents\": [{\"doc\": \"D1\", \"memories\": [...]}]}) or a flat `proposals` list where each "
    "memory carries its own \"doc\". Quotes must be copied from the document; anything else is "
    "rejected as ungrounded. Release the claim instead if you will not finish it."
)


class ClaimError(PermissionError):
    """The claim is unknown, already submitted, or expired. Maps to HTTP 409."""


def claim(store: EngineStore, namespace: str, limit: int = 5, lease_seconds: float = DEFAULT_LEASE_SECONDS,
          related_similarity: float = RELATED_SIMILARITY) -> dict[str, Any]:
    limit = max(1, min(int(limit), MAX_CLAIM_DOCUMENTS))
    claim_id = f"clm_{uuid.uuid4().hex}"
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
    candidates = store.pending_documents(limit=limit, namespace=namespace)
    leased = set(store.lease_documents(namespace, [d["id"] for d in candidates], claim_id, lease_seconds))
    documents = [d for d in candidates if d["id"] in leased]
    if not documents:
        return {"claimId": None, "namespace": namespace, "documents": [], "related": [],
                "message": "nothing pending in this namespace (or extraction is off for it)"}
    related = related_memories(store, namespace, documents, min_similarity=related_similarity)
    store.save_claim(claim_id, namespace, [d["id"] for d in documents], [m["id"] for m in related], expires_at)
    return {
        "claimId": claim_id,
        "namespace": namespace,
        "expiresAt": expires_at,
        "instructions": SYSTEM_PROMPT,
        "prompt": build_prompt(documents, related),
        "responseSchema": RESPONSE_SCHEMA,
        "submit": SUBMIT_INSTRUCTIONS,
        "documents": [{"label": f"D{i}", "id": d["id"]} for i, d in enumerate(documents, 1)],
        "related": [{"label": f"M{i}", "id": m["id"], "memory": m["memory"]} for i, m in enumerate(related, 1)],
    }


def _live_claim(store: EngineStore, claim_id: str) -> dict[str, Any]:
    found = store.get_claim(claim_id)
    if found is None:
        raise ClaimError("unknown or already submitted claim")
    if found["expires_at"] <= datetime.now(timezone.utc).isoformat():
        store.delete_claim(claim_id)
        raise ClaimError("claim expired; its documents are back in the queue, claim again")
    return found


def submit(store: EngineStore, claim_id: str, model: str, documents: list[dict[str, Any]] | None = None,
           proposals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    found = _live_claim(store, claim_id)
    namespace = found["namespace"]
    if documents is not None:
        if not isinstance(documents, list):
            raise ValueError("documents must be a list")
        proposals = flatten_response({"documents": documents})
    proposals = proposals or []
    if not isinstance(proposals, list) or not all(isinstance(p, dict) for p in proposals):
        raise ValueError("proposals must be a list of objects")

    # Re-read what is still ours: a document edited since the claim lost its lease and is skipped.
    # Labels follow the claim's order, so a skipped document leaves its D-number unused, not shifted.
    held = {d["id"]: d for d in store.leased_documents(namespace, found["doc_ids"], claim_id)}
    labelled = {f"D{i}": held[doc_id] for i, doc_id in enumerate(found["doc_ids"], 1) if doc_id in held}
    related_by_id = store.get_memories(found["related_ids"])
    still_related = [(f"M{i}", related_by_id[mid]) for i, mid in enumerate(found["related_ids"], 1)
                     if mid in related_by_id and related_by_id[mid]["namespace"] == namespace]

    # apply_proposals labels D1..Dn and M1..Mn by position; renumber to what still exists, so a
    # dropped document or memory can never make a label point at a different one.
    doc_remap = {old: f"D{new}" for new, old in enumerate(labelled, 1)}
    mem_remap = {old: f"M{new}" for new, (old, _) in enumerate(still_related, 1)}
    usable = [{**p, "doc": doc_remap.get(str(p.get("doc", "")).strip(), ""),
               "updates": mem_remap.get(str(p.get("updates") or "").strip())} for p in proposals]

    stats = DreamStats()
    label = "session:" + (_MODEL.sub("-", str(model or "unknown")).strip("-")[:80] or "unknown")
    docs = list(labelled.values())
    apply_proposals(store, namespace, docs, [m for _, m in still_related], usable, label, stats)
    if docs:
        store.mark_dreamed(namespace, [d["id"] for d in docs])
    store.delete_claim(claim_id)
    stats.documents = len(docs)
    return {**stats.as_dict(), "extractor": label, "skipped": len(found["doc_ids"]) - len(docs)}


def release(store: EngineStore, claim_id: str) -> dict[str, Any]:
    found = store.get_claim(claim_id)
    if found is None:
        raise ClaimError("unknown or already submitted claim")
    store.release_lease(found["namespace"], found["doc_ids"], claim_id)
    store.delete_claim(claim_id)
    return {"released": len(found["doc_ids"])}
