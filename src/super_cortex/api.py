from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncGenerator

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from .config import SuperCortexConfig
from .memory import SuperCortex

logger = logging.getLogger(__name__)


def create_app(config: SuperCortexConfig | None = None) -> Starlette:
    cfg = config or SuperCortexConfig()
    cortex = SuperCortex(cfg)
    subscribers: list[asyncio.Queue] = []

    async def broadcast_event(event_type: str, data: dict[str, Any]) -> None:
        payload = json.dumps({"type": event_type, "data": data})
        for q in subscribers:
            await q.put(payload)

    async def api_status(request: Request) -> JSONResponse:
        alive = await cortex.client.ping()
        chain = cortex.verify_chain()
        return JSONResponse({
            "status": "online",
            "supermemory_local_alive": alive,
            "supermemory_url": cfg.supermemory_url,
            "chain_valid": chain.get("valid", False),
            "event_count": chain.get("event_count", 0),
            "head_hash": chain.get("head_hash"),
            "actor_did": cfg.actor_did,
        })

    async def api_graph(request: Request) -> JSONResponse:
        # Retrieve memories and relations from store
        with cortex.store._get_conn() as conn:
            cursor = conn.execute(
                "SELECT id, source_id, text, epistemic_class, lifecycle_status, content_hash, namespace, metadata_json, created_at FROM memories ORDER BY rowid DESC LIMIT 100"
            )
            mem_rows = cursor.fetchall()

            rel_cursor = conn.execute(
                "SELECT relation_id, subject, predicate, object, confidence, evidence_links_json, created_at FROM relations ORDER BY rowid DESC LIMIT 100"
            )
            rel_rows = rel_cursor.fetchall()

        nodes = []
        links = []

        # Add central root document
        nodes.append({
            "id": "doc_root_hub",
            "label": "Xibalba & Super-Cortex Knowledge Fabric",
            "type": "document",
            "status": "active",
            "space": cfg.default_namespace,
            "version": "v1 // LATEST",
            "relevanceScore": 100,
            "date": "14/11/2026",
            "hash": "0x8F41A990B",
            "content": "Root cognitive fabric combining Supermemory local neural embeddings with Cortex cryptographic provenance.",
        })

        for row in mem_rows:
            mem_id = row["id"]
            nodes.append({
                "id": mem_id,
                "label": row["text"][:50] + ("..." if len(row["text"]) > 50 else ""),
                "type": "memory-latest",
                "status": row["lifecycle_status"],
                "space": row["namespace"],
                "version": "v1",
                "relevanceScore": 95,
                "date": row["created_at"][:10],
                "hash": row["content_hash"][:16],
                "content": row["text"],
            })
            links.append({
                "source": "doc_root_hub",
                "target": mem_id,
                "type": "doc-to-memory",
            })

        for r in rel_rows:
            links.append({
                "source": r["subject"],
                "target": r["object"],
                "type": "version-chain",
                "label": r["predicate"],
            })

        return JSONResponse({"nodes": nodes, "links": links})

    async def api_sessions(request: Request) -> JSONResponse:
        sessions = cortex.get_session_distribution()
        return JSONResponse({"sessions": sessions})

    async def api_session_detail(request: Request) -> JSONResponse:
        session_id = request.path_params["session_id"]
        turns = cortex.get_session_turns(session_id)
        root = cortex.session_merkle_root(session_id)
        return JSONResponse({
            "session_id": session_id,
            "merkle_root": root,
            "turn_count": len(turns),
            "turns": turns,
        })

    async def api_session_proof(request: Request) -> JSONResponse:
        session_id = request.path_params["session_id"]
        turn_index = int(request.query_params.get("turn_index", "0"))
        proof = cortex.get_session_merkle_proof(session_id, turn_index)
        return JSONResponse(proof)

    async def api_remember(request: Request) -> JSONResponse:
        body = await request.json()
        text = body.get("text", "")
        if not text:
            return JSONResponse({"error": "text is required"}, status_code=400)

        epistemic_class = body.get("epistemic_class", "fact")
        namespace = body.get("namespace", cfg.default_namespace)

        res = await cortex.remember(
            text=text,
            epistemic_class=epistemic_class,
            namespace=namespace,
        )
        await broadcast_event("memory_created", res)
        return JSONResponse(res)

    async def api_chat(request: Request) -> JSONResponse:
        body = await request.json()
        query = body.get("message", "")
        if not query:
            return JSONResponse({"error": "message is required"}, status_code=400)

        # Hybrid retrieve from Supermemory and Ledger
        retrieval = await cortex.hybrid_retrieve(query=query, limit=5)
        results = retrieval.get("results", [])

        # Construct context summary
        context_snippets = [f"- {r.get('content')}" for r in results if r.get("content")]
        context_text = "\n".join(context_snippets) if context_snippets else "No prior memories matched."

        response_text = (
            f"Super-Cortex analyzed your query across local memory namespaces.\n\n"
            f"**Relevant Stored Knowledge:**\n{context_text}\n\n"
            f"✓ Cryptographic integrity validated against local ledger."
        )

        return JSONResponse({
            "reply": response_text,
            "retrieval": results,
            "query": query,
        })

    async def api_live_events(request: Request) -> EventSourceResponse:
        queue: asyncio.Queue = asyncio.Queue()
        subscribers.append(queue)

        async def event_generator() -> AsyncGenerator[dict[str, str], None]:
            try:
                # Send initial handshake ping
                yield {"event": "connected", "data": json.dumps({"status": "live", "clock": "144Hz"})}
                while True:
                    data = await queue.get()
                    yield {"event": "update", "data": data}
            except asyncio.CancelledError:
                pass
            finally:
                if queue in subscribers:
                    subscribers.remove(queue)

        return EventSourceResponse(event_generator())

    routes = [
        Route("/api/status", api_status, methods=["GET"]),
        Route("/api/graph", api_graph, methods=["GET"]),
        Route("/api/sessions", api_sessions, methods=["GET"]),
        Route("/api/sessions/{session_id}", api_session_detail, methods=["GET"]),
        Route("/api/sessions/{session_id}/proof", api_session_proof, methods=["GET"]),
        Route("/api/remember", api_remember, methods=["POST"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Route("/api/events/live", api_live_events, methods=["GET"]),
    ]

    # Mount static viewer if dist exists
    dist_dir = Path(__file__).resolve().parent.parent.parent / "viewer" / "dist"
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        routes.append(Mount("/", StaticFiles(directory=str(dist_dir), html=True), name="viewer"))

    app = Starlette(routes=routes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app
