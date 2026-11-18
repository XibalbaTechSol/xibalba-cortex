"""Hybrid retrieval: keyword (BM25) and vector channels fused by Reciprocal Rank Fusion.

Ported from the old Cortex `hybrid_retrieve` (RRF, k=60): ordering comes from fused ranks, so
neither BM25's unbounded scores nor cosine's compressed range has to be calibrated against the
other. Each result still reports its real cosine similarity, so callers see the score behind
the rank and the relevance threshold has a meaning.
"""

from __future__ import annotations

import time
from typing import Any

from .store import EngineStore

RRF_K = 60
SEARCH_MODES = ("hybrid", "lexical", "vector")
MEMORY_STATUSES = ("latest",)


def hybrid_search(
    store: EngineStore,
    namespace: str,
    query: str,
    *,
    limit: int = 10,
    threshold: float = 0.3,
    mode: str = "hybrid",
    metadata_filter: dict[str, Any] | None = None,
    include_documents: bool = False,
) -> dict[str, Any]:
    if mode not in SEARCH_MODES:
        raise ValueError(f"mode must be one of {SEARCH_MODES}")
    started = time.perf_counter()
    limit = max(1, min(int(limit), 100))
    pool = max(limit * 4, 40)

    query_vector = store.embedder.embed([query])[0]
    lexical = store.lexical_ranked(namespace, query, pool) if mode in ("hybrid", "lexical") else []
    vector_hits = store.vector_ranked(namespace, query_vector, pool) if mode in ("hybrid", "vector") else []

    scores: dict[str, float] = {}
    channels: dict[str, dict[str, int]] = {"lexical": {}, "vector": {}}
    for rank, chunk_id in enumerate(lexical, 1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        channels["lexical"][chunk_id] = rank
    for rank, (chunk_id, _) in enumerate(vector_hits, 1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        channels["vector"][chunk_id] = rank

    similarity = dict(vector_hits)
    missing = [cid for cid in scores if cid not in similarity]
    similarity.update(store.similarities(missing, query_vector))

    ranked = sorted(scores, key=lambda cid: (-scores[cid], cid))
    hits = store.chunks(ranked)
    doc_cache: dict[str, dict[str, Any] | None] = {}

    results: list[dict[str, Any]] = []
    for chunk_id in ranked:
        hit = hits.get(chunk_id)
        if hit is None:
            continue
        sim = similarity.get(chunk_id, 0.0)
        # A keyword match is kept even below the cosine threshold: an exact identifier or rare
        # term is strong evidence that a small embedding model may not capture.
        if sim < threshold and chunk_id not in channels["lexical"]:
            continue
        if hit.doc_id not in doc_cache:
            doc_cache[hit.doc_id] = store.get_document(namespace, hit.doc_id)
            if doc_cache[hit.doc_id] is not None:
                doc_cache[hit.doc_id]["version"] = store.current_version(namespace, hit.doc_id)
        doc = doc_cache[hit.doc_id]
        if doc is None:
            continue
        if metadata_filter and any(doc["metadata"].get(k) != v for k, v in metadata_filter.items()):
            continue
        item: dict[str, Any] = {
            "id": chunk_id,
            "chunk": hit.content,
            "documentId": hit.doc_id,
            "similarity": sim,
            "score": scores[chunk_id],
            "signals": [name for name in ("lexical", "vector") if chunk_id in channels[name]],
            "metadata": doc["metadata"],
            "isLatest": True,
            "isInference": False,
            # A chunk is synthesised from the document (split + embedded): metadata, not the record.
            "dataClass": "metadata",
            "derivedFrom": [{"documentId": hit.doc_id, "documentVersion": doc.get("version")}],
            "generator": {"process": "chunking", "embeddingModel": store.embedder.model_key},
        }
        if include_documents:
            item["included"] = {"document": {"id": doc["id"], "title": doc["content"][:80]}}
        results.append(item)
        if len(results) >= limit:
            break

    return {
        "results": results,
        "searchTime": round((time.perf_counter() - started) * 1000, 2),
        "engine": {"mode": mode, "rrf_k": RRF_K, "embedding_model": store.embedder.model_key,
                   "vector_backend": store.vector_backend, "threshold": threshold},
    }


def memory_search(
    store: EngineStore,
    namespace: str,
    query: str,
    *,
    limit: int = 10,
    threshold: float = 0.3,
    include_documents: bool = False,
    include_candidates: bool = False,
) -> dict[str, Any]:
    """Search learned memories (keyword + vector, RRF). Only `latest` memories unless asked.

    Each result carries its evidence: `sources` lists every document and quote behind it, and
    `documentId` / `included.document` name the first, so clients that anchor provenance on the
    source document (super-cortex's `hybrid_retrieve`, the eval harness) work unchanged.
    """
    started = time.perf_counter()
    limit = max(1, min(int(limit), 100))
    pool = max(limit * 4, 40)
    statuses = ("latest", "candidate") if include_candidates else MEMORY_STATUSES
    query_vector = store.embedder.embed([query])[0]
    lexical = store.memory_lexical_ranked(namespace, query, pool, statuses)
    vector_hits = store.memory_vector_ranked(namespace, query_vector, pool, statuses)

    scores: dict[str, float] = {}
    lexical_rank: dict[str, int] = {}
    for rank, memory_id in enumerate(lexical, 1):
        scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (RRF_K + rank)
        lexical_rank[memory_id] = rank
    for rank, (memory_id, _) in enumerate(vector_hits, 1):
        scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (RRF_K + rank)
    similarity = dict(vector_hits)
    similarity.update(store.memory_similarities([m for m in scores if m not in similarity], query_vector))

    ranked = sorted(scores, key=lambda mid: (-scores[mid], mid))
    found = store.get_memories(ranked[: pool])
    results: list[dict[str, Any]] = []
    for memory_id in ranked:
        memory = found.get(memory_id)
        if memory is None or not memory["sources"]:
            continue
        sim = similarity.get(memory_id, 0.0)
        if sim < threshold and memory_id not in lexical_rank:
            continue
        first = memory["sources"][0]
        item: dict[str, Any] = {
            "id": memory_id,
            "memory": memory["memory"],
            "similarity": sim,
            "score": scores[memory_id],
            "isLatest": memory["isLatest"],
            "isInference": memory["isInference"],
            "confidence": memory["confidence"],
            "supersedes": memory["supersedes"],
            "documentId": first["documentId"],
            "sources": memory["sources"],
            "updatedAt": memory["updatedAt"],
            "dataClass": "metadata",
            "derivedFrom": memory["derivedFrom"],
            "generator": memory["generator"],
        }
        if include_documents:
            item["included"] = {"document": {"id": first["documentId"]}}
        results.append(item)
        if len(results) >= limit:
            break
    return {
        "results": results,
        "searchTime": round((time.perf_counter() - started) * 1000, 2),
        "engine": {"mode": "memories", "rrf_k": RRF_K, "embedding_model": store.embedder.model_key,
                   "statuses": list(statuses), "threshold": threshold},
    }


def combined_search(
    store: EngineStore,
    namespace: str,
    query: str,
    *,
    limit: int = 10,
    threshold: float = 0.3,
    include_documents: bool = False,
) -> dict[str, Any]:
    """Learned memories and document chunks in one ranking (RRF over the two result lists).

    A memory answers "what is known"; a chunk answers "what was said". Fusing by rank, not score,
    means neither list's similarity scale has to be calibrated against the other. Every item
    keeps its `kind` and its provenance, so callers can still tell a distilled fact from a quote.
    """
    started = time.perf_counter()
    limit = max(1, min(int(limit), 100))
    pool = max(limit * 2, 20)
    memories = memory_search(store, namespace, query, limit=pool, threshold=threshold,
                             include_documents=include_documents)["results"]
    chunks = hybrid_search(store, namespace, query, limit=pool, threshold=threshold,
                           include_documents=include_documents)["results"]
    fused: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}
    for kind, results in (("memory", memories), ("chunk", chunks)):
        for rank, item in enumerate(results, 1):
            key = f"{kind}:{item['id']}"
            fused[key] = fused.get(key, 0.0) + 1.0 / (RRF_K + rank)
            items[key] = {**item, "kind": kind}
    ranked = sorted(fused, key=lambda k: (-fused[k], k))[:limit]
    return {
        "results": [{**items[k], "score": fused[k]} for k in ranked],
        "searchTime": round((time.perf_counter() - started) * 1000, 2),
        "engine": {"mode": "combined", "rrf_k": RRF_K, "embedding_model": store.embedder.model_key},
    }
