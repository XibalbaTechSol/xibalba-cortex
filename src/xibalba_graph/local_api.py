"""A local, read-only HTTP API for browser-based tooling (e.g. the graph viewer in viewer/).

MCP is stdio-only -- a browser can't call it directly. This mirrors otlp_receiver.py's stdlib
http.server.ThreadingHTTPServer pattern (no new framework dependency) rather than introducing
Flask/FastAPI for a handful of GET routes. Read-only and localhost-bound: nothing here mutates
the store, and it's not meant to be reachable off the local machine.

Every route is a thin wrapper around one public GraphStore method -- all the actual query logic
(graph_payload, memory_entity_relations, counts, etc.) lives in store.py where it's unit-tested
independent of HTTP, the same division server.py already uses for its MCP tools.

Routes:
  GET /api/stats                          -> GraphStore.counts()
  GET /api/search?q=&limit=                -> GraphStore.search() (lexical-only; no embedding
                                               model runs in a browser, so query_vector is never
                                               supplied here -- vector search stays MCP/tool-side)
  GET /api/memory/{id}                     -> GraphStore.get_memory()
  GET /api/memory/{id}/similar?limit=      -> GraphStore.similar_memories()
  GET /api/memory/{id}/neighbors           -> GraphStore.memory_entity_relations()
  GET /api/graph?limit=&similarity_threshold= -> GraphStore.graph_payload()
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .store import GraphStore

logger = logging.getLogger("xibalba_graph.local_api")


def _make_handler(store: GraphStore, *, allowed_origin: str):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802 -- CORS preflight
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming convention
            parsed = urlparse(self.path)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            parts = [p for p in parsed.path.split("/") if p]

            try:
                if parts == ["api", "stats"]:
                    self._send_json(200, store.counts())
                elif parts == ["api", "search"]:
                    query = params.get("q", "")
                    limit = int(params.get("limit", 10))
                    self._send_json(200, store.search(query, limit=limit))
                elif parts == ["api", "graph"]:
                    limit = int(params.get("limit", 500))
                    threshold = float(params.get("similarity_threshold", 0.75))
                    self._send_json(200, store.graph_payload(limit=limit, similarity_threshold=threshold))
                elif len(parts) == 3 and parts[0] == "api" and parts[1] == "memory" and parts[2]:
                    self._send_json(200, store.get_memory(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "similar":
                    limit = int(params.get("limit", 10))
                    self._send_json(200, store.similar_memories(parts[2], limit=limit))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "neighbors":
                    self._send_json(200, store.memory_entity_relations(parts[2]))
                else:
                    self._send_json(404, {"error": "not found"})
            except KeyError:
                self._send_json(404, {"error": "memory not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception:
                logger.exception("local_api request failed: %s", self.path)
                self._send_json(500, {"error": "internal error"})

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            logger.debug(format, *args)

    return Handler


def serve(store: GraphStore, *, host: str = "localhost", port: int = 8420, allowed_origin: str = "*") -> None:
    server = ThreadingHTTPServer((host, port), _make_handler(store, allowed_origin=allowed_origin))
    logger.info("local_api listening on http://%s:%d (read-only)", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, help="xibalba-graph-memory profile home")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--allowed-origin", default="*", help="CORS origin for the browser viewer")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    store = GraphStore(args.home)
    try:
        serve(store, host=args.host, port=args.port, allowed_origin=args.allowed_origin)
    finally:
        store.close()


if __name__ == "__main__":
    main()
