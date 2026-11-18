"""HTTP API for the SuperCortex engine, shaped like Supermemory Local's.

Same paths and payloads as the subset super-cortex's `SupermemoryClient` uses, so pointing
SUPERMEMORY_URL at this server swaps engines with no client change, and the retrieval eval can
run identical requests against both.

Differences, all deliberate:
- `limit` is honoured up to 100 (the client never sent it to Supermemory, which capped at 10).
- `searchMode` also accepts `lexical` and `vector` (single-channel ablations for the eval).
- `searchMode: "memories"` searches learned memories; each hit lists the quotes behind it.
- `searchMode: "combined"` ranks memories and chunks together; each hit says which `kind` it is.
- Retention is a per-namespace policy (GET/PUT /ns/{ns}/policy; presets audit, standard,
  research; see policy.py). Kept versions are served at GET /ns/{ns}/document/{id}/versions.
- Learned memories are written by the dreaming worker, which is OFF unless SUPER_CORTEX_DREAMING=on,
  or by an agent session using its own model: POST /ns/{ns}/extraction/claim, then
  POST /extraction/claims/{id}/submit (or /release). See session_extraction.py.
"""

from __future__ import annotations

import hmac
import os
import re
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .profile import DYNAMIC_LIMIT, build_profile
from .search import combined_search, hybrid_search, memory_search
from .session_extraction import DEFAULT_LEASE_SECONDS, claim, release, submit
from .store import EngineStore

_NAMESPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def create_app(store: EngineStore, api_key: str | None = None, allow_anonymous: bool = False) -> Starlette:
    key = api_key if api_key is not None else os.getenv("SUPER_CORTEX_ENGINE_API_KEY", "")
    if not key and not allow_anonymous:
        raise RuntimeError("SUPER_CORTEX_ENGINE_API_KEY is required (or allow_anonymous=True for local tests)")

    def authorised(request: Request) -> bool:
        if not key:
            return True
        header = request.headers.get("authorization", "")
        return header.startswith("Bearer ") and hmac.compare_digest(header[7:].strip(), key)

    def guard(handler):
        async def wrapped(request: Request) -> JSONResponse:
            if not authorised(request):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            ns = request.path_params.get("ns")
            if ns is not None and not _NAMESPACE.match(ns):
                return JSONResponse({"error": "invalid namespace"}, status_code=400)
            try:
                return await handler(request)
            except PermissionError as exc:
                return JSONResponse({"error": str(exc)}, status_code=409)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)

        return wrapped

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except Exception as exc:
            raise ValueError("request body must be JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "engine": "supercortex", "embedding_model": store.embedder.model_key,
                             "vector_backend": store.vector_backend, "dreaming": dreaming_state})

    async def namespaces(request: Request) -> JSONResponse:
        return JSONResponse({"namespaces": [{"namespace": n} for n in store.list_namespaces()]})

    async def add_document(request: Request) -> JSONResponse:
        data = await body(request)
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content is required")
        result = store.upsert_document(request.path_params["ns"], content, data.get("id"), data.get("metadata"),
                                       **_task_options(data))
        return JSONResponse(result, status_code=201 if result["status"] == "created" else 200)

    async def add_batch(request: Request) -> JSONResponse:
        data = await body(request)
        docs = data.get("documents")
        if not isinstance(docs, list) or not docs:
            raise ValueError("documents must be a non-empty list")
        if len(docs) > 100:
            raise ValueError("at most 100 documents per batch")
        ns = request.path_params["ns"]
        options = _task_options(data)
        results = []
        for d in docs:
            if not isinstance(d, dict) or not isinstance(d.get("content"), str):
                raise ValueError("each document needs string content")
            results.append(store.upsert_document(ns, d["content"], d.get("id"), d.get("metadata"),
                                                 **{**options, **_task_options(d)}))
        return JSONResponse({"results": results})

    async def get_document(request: Request) -> JSONResponse:
        doc = store.get_document(request.path_params["ns"], request.path_params["doc_id"])
        if doc is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(doc)

    async def delete_documents(request: Request) -> JSONResponse:
        data = await body(request)
        ids = data.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError("ids must be a list of strings")
        return JSONResponse({"deleted": store.delete_documents(request.path_params["ns"], ids)})

    async def search(request: Request) -> JSONResponse:
        data = await body(request)
        query = data.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query is required")
        mode = str(data.get("searchMode") or "")
        if not mode:
            mode = "memories" if store.get_policy(request.path_params["ns"]).default_search == "memories" else "hybrid"
        include = data.get("include") or {}
        if mode == "memories":
            return JSONResponse(memory_search(
                store, request.path_params["ns"], query,
                limit=int(data.get("limit", 10)), threshold=float(data.get("threshold", 0.3)),
                include_documents=bool(include.get("documents")) if isinstance(include, dict) else False,
                include_candidates=bool(data.get("includeCandidates")),
            ))
        if mode == "combined":
            return JSONResponse(combined_search(
                store, request.path_params["ns"], query,
                limit=int(data.get("limit", 10)), threshold=float(data.get("threshold", 0.3)),
                include_documents=bool(include.get("documents")) if isinstance(include, dict) else False,
            ))
        if mode == "chunks":
            mode = "hybrid"
        result = hybrid_search(
            store,
            request.path_params["ns"],
            query,
            limit=int(data.get("limit", 10)),
            threshold=float(data.get("threshold", 0.3)),
            mode=mode,
            metadata_filter=data.get("filter") if isinstance(data.get("filter"), dict) else None,
            include_documents=bool(include.get("documents")) if isinstance(include, dict) else False,
        )
        return JSONResponse(result)

    async def list_documents(request: Request) -> JSONResponse:
        data = await body(request)
        return JSONResponse(store.list_documents(request.path_params["ns"], int(data.get("page", 1)),
                                                 int(data.get("limit", 10))))

    async def list_memories(request: Request) -> JSONResponse:
        # Supermemory pages list endpoints through the query string; accept both for convenience.
        data = await body(request) if await request.body() else {}
        page = int(request.query_params.get("page", data.get("page", 1)))
        limit = int(request.query_params.get("limit", data.get("limit", 10)))
        status = data.get("status", "latest")
        if status not in (None, "latest", "superseded", "candidate", "forgotten"):
            raise ValueError("status must be latest, superseded, candidate, forgotten or null")
        return JSONResponse(store.list_memories(request.path_params["ns"], status, page, limit))

    async def profile(request: Request) -> JSONResponse:
        data = await body(request) if await request.body() else {}
        buckets = data.get("buckets")
        if buckets is not None and (not isinstance(buckets, list) or not all(isinstance(b, str) for b in buckets)):
            raise ValueError("buckets must be a list of strings")
        result = build_profile(store, request.path_params["ns"], buckets,
                               int(data.get("limit", DYNAMIC_LIMIT)))
        ignored = sorted(k for k in data if k not in {"buckets", "limit"})
        if ignored:
            result["ignored"] = ignored  # e.g. Supermemory's `filter`: accepted, not applied
        return JSONResponse(result)

    async def get_memory(request: Request) -> JSONResponse:
        found = store.get_memories([request.path_params["memory_id"]]).get(request.path_params["memory_id"])
        if found is None or found["namespace"] != request.path_params["ns"]:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(found)

    async def get_policy(request: Request) -> JSONResponse:
        return JSONResponse(store.get_policy(request.path_params["ns"]).as_dict())

    async def put_policy(request: Request) -> JSONResponse:
        data = await body(request)
        overrides = data.get("settings") or {}
        if not isinstance(overrides, dict):
            raise ValueError("settings must be an object")
        return JSONResponse(store.set_policy(request.path_params["ns"], str(data.get("preset", "")), overrides).as_dict())

    async def document_versions(request: Request) -> JSONResponse:
        versions = store.document_versions(request.path_params["ns"], request.path_params["doc_id"])
        if not versions:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse({"documentId": request.path_params["doc_id"], "versions": versions})

    async def extraction_claim(request: Request) -> JSONResponse:
        data = await body(request) if await request.body() else {}
        lease = max(60.0, min(float(data.get("leaseSeconds", DEFAULT_LEASE_SECONDS)), 3600.0))
        return JSONResponse(claim(store, request.path_params["ns"], int(data.get("limit", 5)), lease))

    async def extraction_submit(request: Request) -> JSONResponse:
        data = await body(request)
        return JSONResponse(submit(store, request.path_params["claim_id"], str(data.get("model") or ""),
                                   documents=data.get("documents"), proposals=data.get("proposals")))

    async def extraction_release(request: Request) -> JSONResponse:
        return JSONResponse(release(store, request.path_params["claim_id"]))

    dreaming_state: dict[str, Any] = {"enabled": False}
    if os.getenv("SUPER_CORTEX_DREAMING", "off").lower() == "on":
        dreaming_state.update(_start_dreaming(store))

    return Starlette(routes=[
        Route("/healthz", healthz, methods=["GET"]),
        Route("/namespaces", guard(namespaces), methods=["GET"]),
        Route("/ns/{ns}/document", guard(add_document), methods=["POST"]),
        Route("/ns/{ns}/document", guard(delete_documents), methods=["DELETE"]),
        Route("/ns/{ns}/document/batch", guard(add_batch), methods=["POST"]),
        Route("/ns/{ns}/document/{doc_id}/versions", guard(document_versions), methods=["GET"]),
        Route("/ns/{ns}/policy", guard(get_policy), methods=["GET"]),
        Route("/ns/{ns}/policy", guard(put_policy), methods=["PUT"]),
        Route("/ns/{ns}/document/{doc_id}", guard(get_document), methods=["GET"]),
        Route("/ns/{ns}/search", guard(search), methods=["POST"]),
        Route("/ns/{ns}/list/documents", guard(list_documents), methods=["POST"]),
        Route("/ns/{ns}/list/memories", guard(list_memories), methods=["POST"]),
        Route("/ns/{ns}/memory/{memory_id}", guard(get_memory), methods=["GET"]),
        Route("/ns/{ns}/profile", guard(profile), methods=["POST"]),
        Route("/ns/{ns}/extraction/claim", guard(extraction_claim), methods=["POST"]),
        Route("/extraction/claims/{claim_id}/submit", guard(extraction_submit), methods=["POST"]),
        Route("/extraction/claims/{claim_id}/release", guard(extraction_release), methods=["POST"]),
    ])


def _task_options(data: dict[str, Any]) -> dict[str, str]:
    options: dict[str, str] = {}
    if "taskType" in data:
        options["task_type"] = str(data["taskType"])
    if "dreaming" in data:
        options["dreaming"] = str(data["dreaming"])
    return options


def _start_dreaming(store: EngineStore) -> dict[str, Any]:
    """Background worker: poll the queue every SUPER_CORTEX_DREAM_INTERVAL seconds (default 300)."""
    import threading

    from .dreaming import GeminiExtractor, run_dreaming

    extractor = GeminiExtractor()
    interval = float(os.getenv("SUPER_CORTEX_DREAM_INTERVAL", "300"))
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            try:
                run_dreaming(store, extractor, max_requests=int(os.getenv("SUPER_CORTEX_DREAM_MAX_REQUESTS_PER_PASS", "30")),
                             stop=stop)
            except Exception:  # noqa: BLE001 - the worker must not take the API down
                import logging

                logging.getLogger(__name__).exception("dreaming pass failed")
            stop.wait(interval)

    threading.Thread(target=loop, name="supercortex-dreaming", daemon=True).start()
    return {"enabled": True, "model": extractor.model, "interval_s": interval}


def main() -> None:
    import uvicorn

    from .embedder import default_embedder

    path = os.getenv("SUPER_CORTEX_ENGINE_DB", os.path.expanduser("~/.super-cortex/engine.db"))
    store = EngineStore(path, default_embedder())
    host = os.getenv("SUPER_CORTEX_ENGINE_HOST", "127.0.0.1")
    port = int(os.getenv("SUPER_CORTEX_ENGINE_PORT", "6768"))
    uvicorn.run(create_app(store), host=host, port=port)
