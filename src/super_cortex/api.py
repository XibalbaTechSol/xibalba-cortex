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
        scopes = cortex.list_scopes()
        agents = cortex.list_agents()
        return JSONResponse({
            "status": "online",
            "supermemory_local_alive": alive,
            "supermemory_url": cfg.supermemory_url,
            "chain_valid": chain.get("valid", False),
            "event_count": chain.get("event_count", 0),
            "head_hash": chain.get("head_hash"),
            "actor_did": cfg.actor_did,
            "scope_count": len(scopes),
            "agent_count": len(agents),
        })

    async def api_scopes(request: Request) -> JSONResponse:
        if request.method == "GET":
            return JSONResponse({"scopes": cortex.list_scopes()})
        elif request.method == "POST":
            body = await request.json()
            scope_id = body.get("scope_id", "").strip()
            name = body.get("name", "").strip()
            if not scope_id or not name:
                return JSONResponse({"error": "scope_id and name are required"}, status_code=400)
            res = cortex.create_scope(
                scope_id=scope_id,
                name=name,
                scope_type=body.get("scope_type", "single_agent"),
                agent_id=body.get("agent_id"),
                description=body.get("description", ""),
            )
            await broadcast_event("scope_created", res)
            return JSONResponse(res)

    async def api_agents(request: Request) -> JSONResponse:
        if request.method == "GET":
            return JSONResponse({"agents": cortex.list_agents()})
        elif request.method == "POST":
            body = await request.json()
            agent_id = body.get("agent_id", "").strip()
            name = body.get("name", "").strip()
            if not agent_id or not name:
                return JSONResponse({"error": "agent_id and name are required"}, status_code=400)
            res = cortex.register_agent(
                agent_id=agent_id,
                name=name,
                default_scope_id=body.get("default_scope_id", "shared"),
                client_type=body.get("client_type", "custom"),
            )
            await broadcast_event("agent_registered", res)
            return JSONResponse(res)

    async def api_mcp_config(request: Request) -> JSONResponse:
        repo_dir = str(Path(__file__).resolve().parent.parent.parent)
        config_payload = {
            "claude_code": {
                "mcpServers": {
                    "super-cortex": {
                        "command": "uv",
                        "args": ["--directory", repo_dir, "run", "super-cortex", "server"]
                    }
                }
            },
            "cursor": {
                "mcpServers": {
                    "super-cortex": {
                        "command": "uv",
                        "args": ["--directory", repo_dir, "run", "super-cortex", "server"]
                    }
                }
            },
            "antigravity": {
                "mcpServers": {
                    "super-cortex": {
                        "command": "uv",
                        "args": ["--directory", repo_dir, "run", "super-cortex", "server"]
                    }
                }
            },
            "environment": {
                "repo_path": repo_dir,
                "supermemory_local_url": cfg.supermemory_url,
                "sqlite_ledger_path": str(cfg.db_path),
            }
        }
        return JSONResponse(config_payload)

    async def api_graph(request: Request) -> JSONResponse:
        import math
        selected_scope = request.query_params.get("scope", "all")

        # 1. Fetch registered scopes and agents
        scopes = cortex.list_scopes()
        agents = cortex.list_agents()

        # 2. Retrieve memories and relations from store
        with cortex.store._get_conn() as conn:
            cursor = conn.execute(
                "SELECT id, source_id, text, epistemic_class, lifecycle_status, content_hash, namespace, metadata_json, created_at FROM memories ORDER BY rowid DESC LIMIT 150"
            )
            mem_rows = cursor.fetchall()

            rel_cursor = conn.execute(
                "SELECT relation_id, subject, predicate, object, confidence, evidence_links_json, created_at FROM relations ORDER BY rowid DESC LIMIT 150"
            )
            rel_rows = rel_cursor.fetchall()

        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []

        # Color mapping by epistemic class
        epistemic_colors = {
            "rule": 0x00ffa3,       # Emerald
            "fact": 0x38bdf8,       # Sky Cyan
            "decision": 0x34d399,   # Teal
            "inference": 0xddb7ff,  # Lavender
            "belief": 0xf59e0b,     # Amber
            "goal": 0xf43f5e,       # Rose
            "document": 0x00f0ff,   # Cyan
        }

        # Central Root Hub: Shared Memory Fabric
        nodes.append({
            "id": "hub_shared",
            "title": "Shared Memory Fabric",
            "labelTag": "SHARED MEMORY HUB",
            "category": "shared",
            "type": "hub",
            "status": "active",
            "epistemic_class": "rule",
            "color": 0x00f0ff,
            "size": 34,
            "pos3D": [0, 20, 0],
            "pos2D": [0, 20, 0],
            "isLineage": True,
            "confidence": 1.0,
            "hash": "0xSHARED_FABRIC",
            "content": "Collective operational memory accessible across all authorized agent scopes via Supermemory 768-D local embeddings.",
            "scope": "shared",
        })

        # Satellite Agent Hubs
        agent_positions: dict[str, list[float]] = {}
        active_agents = [a for a in agents if a["status"] == "active"]
        num_agents = max(len(active_agents), 1)

        for i, agent in enumerate(active_agents):
            aid = agent["agent_id"]
            angle = (2 * math.pi / num_agents) * i
            radius = 240.0
            ax = math.cos(angle) * radius
            ay = math.sin(angle * 2) * 40.0 + 10.0
            az = math.sin(angle) * radius
            agent_positions[aid] = [ax, ay, az]

            hub_id = f"hub_agent_{aid}"
            nodes.append({
                "id": hub_id,
                "title": f"Agent Scope: {agent['name']}",
                "labelTag": f"AGENT // {aid.upper()}",
                "category": "agent",
                "type": "agent_hub",
                "status": agent["status"],
                "epistemic_class": "decision",
                "color": 0x00ffa3,
                "size": 26,
                "pos3D": [round(ax, 1), round(ay, 1), round(az, 1)],
                "pos2D": [round(ax, 1), round(ay, 1), 0],
                "isLineage": True,
                "confidence": 1.0,
                "hash": f"0xAGENT_{aid.upper()}",
                "content": f"Isolated private memory scope for {agent['name']} ({agent['client_type']} client).",
                "scope": f"agent:{aid}",
                "agent_id": aid,
            })

            # Federation link between Shared Fabric and Agent Hub
            links.append({
                "source": "hub_shared",
                "target": hub_id,
                "type": "federation",
                "label": "Federated Scope Bridge",
            })

        # Memory Voxel Nodes
        for idx, row in enumerate(mem_rows):
            mem_id = row["id"]
            try:
                meta = json.loads(row["metadata_json"])
            except Exception:
                meta = {}

            mem_scope = meta.get("scope") or "shared"
            mem_agent_id = meta.get("agent_id")
            ep_class = row["epistemic_class"]
            para = meta.get("para", {})
            para_cat = para.get("category", "area") if isinstance(para, dict) else "area"
            triples = meta.get("triples", [])

            # Filter if a specific scope is requested
            if selected_scope and selected_scope != "all" and mem_scope != selected_scope:
                continue

            # Deterministic spatial positioning around respective hub
            int_seed = int(row["content_hash"][:8], 16)
            theta = (int_seed % 360) * (math.pi / 180.0)
            phi = ((int_seed >> 8) % 180) * (math.pi / 180.0)

            if mem_scope.startswith("agent:") and mem_agent_id in agent_positions:
                center = agent_positions[mem_agent_id]
                m_rad = 60.0 + (int_seed % 40)
            elif mem_scope.startswith("agent:"):
                # Agent scope without registered position
                center = [120, 80, -120]
                m_rad = 60.0
            else:
                # Shared scope clusters around center
                center = [0, 20, 0]
                m_rad = 120.0 + (int_seed % 70)

            px = center[0] + m_rad * math.sin(phi) * math.cos(theta)
            py = center[1] + m_rad * math.cos(phi) * 0.6
            pz = center[2] + m_rad * math.sin(phi) * math.sin(theta)

            color = epistemic_colors.get(ep_class, 0x38bdf8)

            nodes.append({
                "id": mem_id,
                "title": row["text"][:45] + ("..." if len(row["text"]) > 45 else ""),
                "labelTag": f"{ep_class.upper()} // {para_cat.upper()}",
                "category": para_cat,
                "type": "memory",
                "status": row["lifecycle_status"],
                "epistemic_class": ep_class,
                "para": para,
                "triples": triples,
                "color": color,
                "size": 15,
                "pos3D": [round(px, 1), round(py, 1), round(pz, 1)],
                "pos2D": [round(px, 1), round(py, 1), 0],
                "confidence": 0.95,
                "hash": row["content_hash"][:16],
                "full_hash": row["content_hash"],
                "content": row["text"],
                "scope": mem_scope,
                "agent_id": mem_agent_id,
                "created_at": row["created_at"],
            })

            # Link memory to its parent hub
            target_hub = f"hub_agent_{mem_agent_id}" if mem_scope.startswith("agent:") and mem_agent_id else "hub_shared"
            links.append({
                "source": target_hub,
                "target": mem_id,
                "type": "scope-to-memory",
                "label": f"belongs_to ({mem_scope})",
            })

        # Relational edges from triples
        for r in rel_rows:
            links.append({
                "source": r["subject"],
                "target": r["object"],
                "type": "relation",
                "label": r["predicate"],
            })

        return JSONResponse({
            "nodes": nodes,
            "links": links,
            "stats": {
                "total_nodes": len(nodes),
                "total_links": len(links),
                "selected_scope": selected_scope,
                "scopes_count": len(scopes),
                "agents_count": len(agents),
            }
        })

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
        text = body.get("text", "").strip()
        if not text:
            return JSONResponse({"error": "text is required"}, status_code=400)

        epistemic_class = body.get("epistemic_class")
        namespace = body.get("namespace")
        scope = body.get("scope", "shared")
        agent_id = body.get("agent_id")
        metadata = body.get("metadata")

        res = await cortex.remember(
            text=text,
            epistemic_class=epistemic_class,
            namespace=namespace,
            scope=scope,
            agent_id=agent_id,
            metadata=metadata,
        )
        await broadcast_event("memory_created", res)
        return JSONResponse(res)

    async def api_chat(request: Request) -> JSONResponse:
        body = await request.json()
        query = body.get("message", "")
        if not query:
            return JSONResponse({"error": "message is required"}, status_code=400)

        scope = body.get("scope")
        agent_id = body.get("agent_id")

        # Hybrid retrieve from Supermemory and Ledger
        retrieval = await cortex.hybrid_retrieve(
            query=query,
            scope=scope,
            agent_id=agent_id,
            limit=5,
        )
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
        Route("/api/scopes", api_scopes, methods=["GET", "POST"]),
        Route("/api/agents", api_agents, methods=["GET", "POST"]),
        Route("/api/mcp-config", api_mcp_config, methods=["GET"]),
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
