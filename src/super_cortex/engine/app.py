"""HTTP API for the SuperCortex engine, shaped like Supermemory Local's.

Same paths and payloads as the subset super-cortex's `SupermemoryClient` uses, so pointing
SUPERMEMORY_URL at this server swaps engines with no client change, and the retrieval eval can
run identical requests against both.

Differences, all deliberate:
- `limit` is honoured up to 100 (the client never sent it to Supermemory, which capped at 10).
- `searchMode` also accepts `lexical` and `vector` (single-channel ablations for the eval).
- `searchMode: "memories"` returns no results until learned memories exist (Phase 2).
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

from .search import hybrid_search
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
                             "vector_backend": store.vector_backend})

    async def namespaces(request: Request) -> JSONResponse:
        return JSONResponse({"namespaces": [{"namespace": n} for n in store.list_namespaces()]})

    async def add_document(request: Request) -> JSONResponse:
        data = await body(request)
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content is required")
        result = store.upsert_document(request.path_params["ns"], content, data.get("id"), data.get("metadata"))
        return JSONResponse(result, status_code=201 if result["status"] == "created" else 200)

    async def add_batch(request: Request) -> JSONResponse:
        data = await body(request)
        docs = data.get("documents")
        if not isinstance(docs, list) or not docs:
            raise ValueError("documents must be a non-empty list")
        if len(docs) > 100:
            raise ValueError("at most 100 documents per batch")
        ns = request.path_params["ns"]
        results = [store.upsert_document(ns, d["content"], d.get("id"), d.get("metadata")) for d in docs]
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
        mode = str(data.get("searchMode") or "hybrid")
        if mode == "memories":
            return JSONResponse({"results": [], "searchTime": 0.0,
                                 "notice": "learned memories are not built yet (Phase 2)"})
        if mode == "chunks":
            mode = "hybrid"
        include = data.get("include") or {}
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

    return Starlette(routes=[
        Route("/healthz", healthz, methods=["GET"]),
        Route("/namespaces", guard(namespaces), methods=["GET"]),
        Route("/ns/{ns}/document", guard(add_document), methods=["POST"]),
        Route("/ns/{ns}/document", guard(delete_documents), methods=["DELETE"]),
        Route("/ns/{ns}/document/batch", guard(add_batch), methods=["POST"]),
        Route("/ns/{ns}/document/{doc_id}", guard(get_document), methods=["GET"]),
        Route("/ns/{ns}/search", guard(search), methods=["POST"]),
        Route("/ns/{ns}/list/documents", guard(list_documents), methods=["POST"]),
    ])


def main() -> None:
    import uvicorn

    from .embedder import default_embedder

    path = os.getenv("SUPER_CORTEX_ENGINE_DB", os.path.expanduser("~/.super-cortex/engine.db"))
    store = EngineStore(path, default_embedder())
    host = os.getenv("SUPER_CORTEX_ENGINE_HOST", "127.0.0.1")
    port = int(os.getenv("SUPER_CORTEX_ENGINE_PORT", "6768"))
    uvicorn.run(create_app(store), host=host, port=port)
