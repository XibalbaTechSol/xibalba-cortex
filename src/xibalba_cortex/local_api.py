"""A local HTTP API for browser-based tooling (e.g. the graph viewer in viewer/).

MCP is stdio-only -- a browser can't call it directly. This mirrors otlp_receiver.py's stdlib
http.server.ThreadingHTTPServer pattern (no new framework dependency) rather than introducing
Flask/FastAPI for a small local operator UI. It is localhost-bound and intentionally omits
destructive operations such as restore or hard purge.

Every route is a thin wrapper around one public GraphStore method -- all the actual query logic
(graph_payload, memory_entity_relations, counts, etc.) lives in store.py where it's unit-tested
independent of HTTP, the same division server.py already uses for its MCP tools.

Routes:
  GET /healthz                         -> process/store liveness
  GET /readyz                         -> full integrity and backup readiness (503 when not ready)
  GET /api/stats                          -> GraphStore.counts()
  GET /api/status                         -> GraphStore.status()
  GET /api/integrity-links?limit=          -> GraphStore.integrity_links_status()
  GET /api/sessions?limit=                 -> GraphStore.list_sessions()
  GET /api/search?q=&limit=                -> GraphStore.search() (lexical-only; no embedding
                                               model runs in a browser, so query_vector is never
                                               supplied here -- vector search stays MCP/tool-side)
  GET /api/memory/{id}                     -> GraphStore.get_memory()
  GET /api/memory/{id}/events              -> GraphStore.memory_events()
  GET /api/memory/{id}/otel                -> GraphStore.memory_otel_events()
  GET /api/memory/{id}/attachments         -> GraphStore.list_attachments()
  GET /api/memory/{id}/contradictions      -> GraphStore.contradictions()
  GET /api/memory/{id}/similar?limit=      -> GraphStore.similar_memories()
  GET /api/memory/{id}/neighbors           -> GraphStore.memory_entity_relations()
  GET /api/entity/{name}/neighbors?max_depth= -> GraphStore.neighbors()
  GET /api/entity/path?from=&to=&max_depth=   -> GraphStore.find_path()
  GET /api/session/{id}/exchanges          -> GraphStore.session_exchanges()
  GET /api/session/{id}/otel               -> GraphStore.session_otel_events()
  GET /api/session/{id}/merkle-root        -> GraphStore.session_merkle_root()
  GET /api/session/{id}/merkle-proof?index= -> GraphStore.session_merkle_evidence()
  GET /api/inference/manifest              -> MEMORY_INFERENCE_SUBAGENT_MANIFEST
  GET /api/inference/tasks?status=&limit=  -> GraphStore.list_inference_tasks()
  GET /api/extraction-proposals?status=&task_id=&source_memory_id=&limit= -> GraphStore.list_extraction_proposals()
  GET /api/retrieval/trace/{id}            -> GraphStore.get_retrieval_trace()
  GET /api/retrieval/trace/{id}/evidence?rank= -> GraphStore.retrieval_trace_evidence()
  GET /api/projections/{id}/checkpoints?limit= -> GraphStore.list_projection_checkpoints()
  GET /api/projections/{id}/checkpoints/latest -> GraphStore.get_latest_projection_checkpoint()
  GET /api/embedding/models                -> GraphStore.list_embedding_models()
  POST /api/exchanges/model                -> GraphStore.record_model_exchange()
  POST /api/memory/propositions            -> GraphStore.store_memory()
  POST /api/memory/link-entities           -> GraphStore.link_entities()
  POST /api/memory/contradictions          -> GraphStore.mark_contradiction()
  POST /api/memory/{id}/supersede          -> GraphStore.supersede_memory()
  POST /api/inference/tasks                -> GraphStore.request_inference_task()
  POST /api/inference/tasks/{id}/claim     -> GraphStore.claim_inference_task()
  POST /api/inference/tasks/{id}/complete  -> GraphStore.complete_inference_task()
  POST /api/extraction-proposals/{id}/decision -> GraphStore.decide_extraction_proposal()
  POST /api/retrieval/hybrid               -> GraphStore.hybrid_retrieve()
  POST /api/projections/{id}/checkpoint    -> GraphStore.create_projection_checkpoint()
  POST /api/projections/{id}/reconcile     -> GraphStore.reconcile_projection_checkpoint()
  POST /api/projections/{id}/rebuild       -> GraphStore.rebuild_projection_checkpoint()
  GET /api/graph?limit=&similarity_threshold= -> GraphStore.graph_payload()
  GET /api/session/{id}/kernel-intents     -> GraphStore.kernel_bridge_intents()
  GET /api/invocations?limit=              -> GraphStore.invocation_correlations()
  POST /api/kernel-bridge/self-test        -> _run_kernel_bridge_self_test() (Guided System Test;
                                               optional {"session_id": ...} also records both cases
                                               as real pre/post_tool_call otel events so
                                               GraphStore.kernel_bridge_intents() -- and the
                                               dashboard's Kernel Intent page -- has real data to show)
  POST /api/otel/batch                     -> GraphStore.record_otel_batch() (browser-reachable write path)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .providers import InferenceTaskContract
from .store import MEMORY_INFERENCE_SUBAGENT_MANIFEST, GraphStore

logger = logging.getLogger("xibalba_cortex.local_api")
_MAX_JSON_BODY_BYTES = 512 * 1024

# Guided System Test wizard (integrity-dashboard's Developer page): a one-click kernel-bridge
# check that doesn't require a live Claude session with XIBALBA_KERNEL_BRIDGE_ENABLED=1 set.
# Same test recipient/values as claude_adapter.py's opt-in pre_tool_call path and
# contracts/script/SubmitKernelBridgeUserOp.s.sol's own case selection -- a matched case
# (well within both the kernel's and adapter's budgets) and a kernel-exceeding case (proves
# real denial, since the registered adapter itself has a known gap -- see kernel_bridge.py's
# module docstring -- and would otherwise always ALLOW).
_SELF_TEST_RECIPIENT = "0x" + "0" * 38 + "ff"
_SELF_TEST_MATCHED_VALUE_WEI = int(0.1 * 10**18)
_SELF_TEST_KERNEL_EXCEEDING_VALUE_WEI = int(1.5 * 10**18)


def _record_kernel_bridge_intent(
    store: GraphStore, *, session_id: str, tool_call_id: str, tool_name: str, decision: dict[str, object]
) -> None:
    # Same (pre_tool_call, post_tool_call) otel-event shape claude_adapter.py's real,
    # opt-in XIBALBA_KERNEL_BRIDGE_ENABLED hook path writes -- see runtime_bridge_contract.py's
    # RuntimeEvent.to_record() and GraphStore.kernel_bridge_intents(), which joins the two by
    # metadata.tool_call_id. Without this, the self-test route (unlike the real hook path) never
    # gave the Kernel Intent page (/kernel-intent) anything to show -- the wizard's "Kernel /
    # adapter bridge" step and the intent-vs-outcome page looked related but were entirely
    # disconnected. This makes the wizard's real, already-verified on-chain result the page's
    # data source too, instead of requiring a live hook-driven session to ever populate it.
    store.start_session(session_id, retention_tier="verbatim")
    success = bool(decision.get("success"))
    store.record_otel_batch(
        session_id,
        [
            {
                "kind": "log",
                "name": "xibalba.runtime.event",
                "span_id": tool_name,
                "attributes": {
                    "tool_name": tool_name,
                    "tool_input_hash": None,
                    "intent_rationale": f"Guided System Test self-test: {tool_name}",
                    "tool_outcome": "success" if success else "blocked",
                    "metadata": {
                        "hook": "pre_tool_call",
                        "tool_call_id": tool_call_id,
                        "policy_reason": "kernel-bridge self-test",
                        "kernel_decision": decision,
                    },
                },
            },
            {
                "kind": "log",
                "name": "xibalba.runtime.event",
                "span_id": tool_name,
                "attributes": {
                    "tool_name": tool_name,
                    "tool_outcome": "success" if success else "blocked",
                    "metadata": {
                        "hook": "post_tool_call",
                        "tool_call_id": tool_call_id,
                        "result": decision.get("user_op_hash"),
                        "duration_ms": None,
                    },
                },
            },
        ],
    )


def _run_kernel_bridge_self_test(store: GraphStore, *, session_id: str | None) -> dict[str, object]:
    from .kernel_bridge import submit_kernel_intent

    try:
        matched = submit_kernel_intent(recipient=_SELF_TEST_RECIPIENT, value_wei=_SELF_TEST_MATCHED_VALUE_WEI)
        kernel_exceeding = submit_kernel_intent(
            recipient=_SELF_TEST_RECIPIENT, value_wei=_SELF_TEST_KERNEL_EXCEEDING_VALUE_WEI
        )
    except Exception as exc:  # noqa: BLE001 -- surfaced as a clean test-failure result, not a 500
        return {"ok": False, "error": str(exc)}

    matched_dict = matched.to_dict()
    kernel_exceeding_dict = kernel_exceeding.to_dict()

    if session_id:
        _record_kernel_bridge_intent(
            store,
            session_id=session_id,
            tool_call_id=f"kernel-bridge-self-test-matched-{matched_dict['user_op_hash']}",
            tool_name="kernel_bridge_self_test_matched",
            decision=matched_dict,
        )
        _record_kernel_bridge_intent(
            store,
            session_id=session_id,
            tool_call_id=f"kernel-bridge-self-test-kernel-exceeding-{kernel_exceeding_dict['user_op_hash']}",
            tool_name="kernel_bridge_self_test_kernel_exceeding",
            decision=kernel_exceeding_dict,
        )

    return {
        "ok": True,
        "matched": matched_dict,
        "kernel_exceeding": kernel_exceeding_dict,
        "passed": matched.success is True and kernel_exceeding.success is False,
    }


def _make_handler(store: GraphStore, *, allowed_origin: str):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802 -- CORS preflight
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def _read_json_body(self) -> dict[str, object]:
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                raise ValueError("invalid Content-Length")
            if length <= 0:
                return {}
            if length > _MAX_JSON_BODY_BYTES:
                raise ValueError("request body too large")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON body: {exc.msg}") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming convention
            parsed = urlparse(self.path)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            parts = [p for p in parsed.path.split("/") if p]

            try:
                if parts == ["healthz"]:
                    self._send_json(200, {"schema_version": "xibalba.health.v1", "status": "ok", "profile_id": store.profile_id})
                elif parts == ["readyz"]:
                    status = store.status()
                    ready = status["integrity_check"] == "ok" and status["foreign_keys"] is True and status["fts5"] is True and status["backup_ready"] is True
                    self._send_json(200 if ready else 503, {"schema_version": "xibalba.readiness.v1", "ready": ready, "profile_id": store.profile_id, "checks": {"integrity_check": status["integrity_check"], "foreign_keys": status["foreign_keys"], "fts5": status["fts5"], "backup_ready": status["backup_ready"]}})
                elif parts == ["api", "stats"]:
                    self._send_json(200, store.counts())
                elif parts == ["api", "status"]:
                    self._send_json(200, store.status(fast=True))
                elif parts == ["api", "integrity-links"]:
                    limit = int(params.get("limit", 50))
                    self._send_json(200, store.integrity_links_status(limit=limit))
                elif parts == ["api", "sessions"]:
                    limit = int(params.get("limit", 100))
                    self._send_json(200, store.list_sessions(limit=limit))
                elif parts == ["api", "invocations"]:
                    limit = int(params.get("limit", 100))
                    self._send_json(200, store.invocation_correlations(limit=limit))
                elif parts == ["api", "search"]:
                    query = params.get("q", "")
                    limit = int(params.get("limit", 10))
                    self._send_json(200, store.search(query, limit=limit))
                elif parts == ["api", "graph"]:
                    limit = int(params.get("limit", 500))
                    threshold = float(params.get("similarity_threshold", 0.75))
                    self._send_json(200, store.graph_payload(limit=limit, similarity_threshold=threshold))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "entity" and parts[3] == "neighbors":
                    max_depth = int(params.get("max_depth", 1))
                    self._send_json(200, store.neighbors(unquote(parts[2]), max_depth=max_depth))
                elif parts == ["api", "entity", "path"]:
                    max_depth = int(params.get("max_depth", 3))
                    self._send_json(200, store.find_path(params.get("from", ""), params.get("to", ""), max_depth=max_depth))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "exchanges":
                    self._send_json(200, store.session_exchanges(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "otel":
                    self._send_json(200, store.session_otel_events(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "merkle-root":
                    self._send_json(200, store.session_merkle_root(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "merkle-proof":
                    self._send_json(200, store.session_merkle_evidence(parts[2], exchange_index=int(params.get("index", "0"))))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "session" and parts[3] == "kernel-intents":
                    self._send_json(200, store.kernel_bridge_intents(parts[2]))
                elif parts == ["api", "inference", "manifest"]:
                    self._send_json(200, MEMORY_INFERENCE_SUBAGENT_MANIFEST)
                elif parts == ["api", "inference", "tasks"]:
                    status = params.get("status", "pending")
                    limit = int(params.get("limit", 50))
                    self._send_json(200, store.list_inference_tasks(status=status, limit=limit))
                elif parts == ["api", "para", "classifications"]:
                    status = params.get("status", "proposed")
                    limit = int(params.get("limit", 50))
                    self._send_json(200, store.list_para_classifications(status=status, limit=limit))
                elif parts == ["api", "extraction-proposals"]:
                    status = params.get("status", "proposed")
                    limit = int(params.get("limit", 50))
                    task_id = params.get("task_id")
                    source_memory_id = params.get("source_memory_id")
                    self._send_json(200, store.list_extraction_proposals(status=status, task_id=task_id, source_memory_id=source_memory_id, limit=limit))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "retrieval" and parts[2] == "trace":
                    self._send_json(200, store.get_retrieval_trace(parts[3]))
                elif len(parts) == 5 and parts[0] == "api" and parts[1] == "retrieval" and parts[2] == "trace" and parts[4] == "evidence":
                    rank = int(params.get("rank", 1))
                    self._send_json(200, store.retrieval_trace_evidence(parts[3], rank=rank))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "projections" and parts[3] == "checkpoints":
                    limit = int(params.get("limit", 50))
                    self._send_json(200, store.list_projection_checkpoints(parts[2], limit=limit))
                elif len(parts) == 5 and parts[0] == "api" and parts[1] == "projections" and parts[3] == "checkpoints" and parts[4] == "latest":
                    latest = store.get_latest_projection_checkpoint(parts[2])
                    if latest is None:
                        self._send_json(404, {"error": "no checkpoint exists for this projection yet"})
                    else:
                        self._send_json(200, latest)
                elif parts == ["api", "embedding", "models"]:
                    self._send_json(200, store.list_embedding_models())
                elif len(parts) == 3 and parts[0] == "api" and parts[1] == "memory" and parts[2]:
                    self._send_json(200, store.get_memory(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "similar":
                    limit = int(params.get("limit", 10))
                    self._send_json(200, store.similar_memories(parts[2], limit=limit))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "neighbors":
                    self._send_json(200, store.memory_entity_relations(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "events":
                    self._send_json(200, store.memory_events(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "otel":
                    self._send_json(200, store.memory_otel_events(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "attachments":
                    self._send_json(200, store.list_attachments(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "attachment" and parts[3] == "file":
                    attachment = store.get_attachment(parts[2])
                    if not attachment:
                        self._send_json(404, {"error": "attachment not found"})
                    else:
                        locator = attachment["storage_locator"]
                        file_path = locator[7:] if locator.startswith("file://") else locator
                        import os
                        if not os.path.exists(file_path):
                            self._send_json(404, {"error": f"file not found at {file_path}"})
                        else:
                            self.send_response(200)
                            self.send_header("Content-Type", attachment.get("media_type") or "application/octet-stream")
                            self.send_header("Content-Length", str(os.path.getsize(file_path)))
                            self.end_headers()
                            with open(file_path, "rb") as f:
                                self.wfile.write(f.read())
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "contradictions":
                    self._send_json(200, store.contradictions(parts[2]))
                else:
                    self._send_json(404, {"error": "not found"})
            except KeyError:
                self._send_json(404, {"error": "not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception:
                logger.exception("local_api request failed: %s", self.path)
                self._send_json(500, {"error": "internal error"})

        def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler's naming convention
            parsed = urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]

            try:
                payload = self._read_json_body()
                if len(parts) == 5 and parts[0] == "api" and parts[1] == "session" and parts[3] == "exchanges" and parts[4] == "build":
                    from .exchange_builder import build_session_exchanges
                    self._send_json(200, build_session_exchanges(store, parts[2]))
                elif parts == ["api", "otel", "batch"]:
                    # Browser-reachable write path for record_otel_batch (~/.claude/plans/
                    # velvet-giggling-quill.md's cross-system test log) -- previously only
                    # callable in-process via runtime_controller.ingest_event; the dashboard
                    # needs its own POST route since it isn't an MCP client. Same
                    # idempotent start_session-then-insert pattern ingest_event already uses,
                    # since otel_events.session_id has a NOT NULL FK to sessions.
                    session_id = str(payload.get("session_id") or "")
                    events = payload.get("events")
                    if not session_id:
                        raise ValueError("session_id is required")
                    if not isinstance(events, list):
                        raise ValueError("events must be a list")
                    store.start_session(session_id, retention_tier="digest")
                    self._send_json(200, store.record_otel_batch(session_id, events))
                elif parts == ["api", "exchanges", "model"]:
                    self._send_json(
                        200,
                        store.record_model_exchange(
                            str(payload.get("external_session_id") or ""),
                            user_prompt=str(payload.get("user_prompt") or ""),
                            model_response=str(payload.get("model_response") or ""),
                            context=list(payload.get("context") or []),
                            runtime=payload.get("runtime") if isinstance(payload.get("runtime"), str) else None,
                            agent_id=payload.get("agent_id") if isinstance(payload.get("agent_id"), str) else None,
                            prompt_id=payload.get("prompt_id") if isinstance(payload.get("prompt_id"), str) else None,
                            prompt_time=payload.get("prompt_time") if isinstance(payload.get("prompt_time"), str) else None,
                            response_time=payload.get("response_time") if isinstance(payload.get("response_time"), str) else None,
                            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
                            idempotency_key=payload.get("idempotency_key")
                            if isinstance(payload.get("idempotency_key"), str)
                            else None,
                        ),
                    )
                elif parts == ["api", "inference", "tasks"]:
                    input_payload = payload.get("input_payload")
                    if not isinstance(input_payload, dict):
                        raise ValueError("input_payload must be an object")
                    contract_raw = payload.get("contract")
                    contract = None
                    if contract_raw is not None:
                        if not isinstance(contract_raw, dict):
                            raise ValueError("contract must be an object")
                        contract = InferenceTaskContract(
                            schema_version=str(contract_raw.get("schema_version", "xibalba.inference.task.v1")),
                            evidence_scope=tuple(str(item) for item in contract_raw.get("evidence_scope", [])),
                            input_snapshot_hash=contract_raw.get("input_snapshot_hash") if isinstance(contract_raw.get("input_snapshot_hash"), str) else None,
                            output_schema=str(contract_raw.get("output_schema", "xibalba.inference.output.v1")),
                            promotion_policy=str(contract_raw.get("promotion_policy", "review_required")),
                            worker_runtime=contract_raw.get("worker_runtime") if isinstance(contract_raw.get("worker_runtime"), str) else None,
                        )
                    self._send_json(
                        200,
                        store.request_inference_task(
                            str(payload.get("task_type") or ""),
                            subject_type=str(payload.get("subject_type") or ""),
                            subject_id=str(payload.get("subject_id") or ""),
                            input_payload=input_payload,
                            requested_by=payload.get("requested_by")
                            if isinstance(payload.get("requested_by"), str)
                            else None,
                            idempotency_key=payload.get("idempotency_key")
                            if isinstance(payload.get("idempotency_key"), str)
                            else None,
                            contract=contract,
                        ),
                    )
                elif parts == ["api", "memory", "propositions"]:
                    source = payload.get("source")
                    if source is not None and not isinstance(source, dict):
                        raise ValueError("source must be an object")
                    self._send_json(
                        200,
                        store.store_memory(
                            str(payload.get("content") or ""),
                            source=source
                            if isinstance(source, dict)
                            else {"kind": "inference_output", "locator": "xibalba://viewer/inference"},
                            status=str(payload.get("status") or "candidate"),
                            evidence_class=str(payload.get("evidence_class") or "extracted_proposition"),
                            idempotency_key=payload.get("idempotency_key")
                            if isinstance(payload.get("idempotency_key"), str)
                            else None,
                        ),
                    )
                elif parts == ["api", "memory", "link-entities"]:
                    self._send_json(
                        200,
                        store.link_entities(
                            str(payload.get("subject") or ""),
                            str(payload.get("predicate") or ""),
                            str(payload.get("object") or ""),
                            evidence_memory_id=str(payload.get("evidence_memory_id") or ""),
                            confidence=float(payload.get("confidence", 1.0)),
                        ),
                    )
                elif parts == ["api", "memory", "contradictions"]:
                    self._send_json(
                        200,
                        store.mark_contradiction(
                            str(payload.get("memory_id_a") or ""),
                            str(payload.get("memory_id_b") or ""),
                            str(payload.get("reason") or ""),
                        ),
                    )
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "memory" and parts[3] == "supersede":
                    source = payload.get("source")
                    if source is not None and not isinstance(source, dict):
                        raise ValueError("source must be an object")
                    self._send_json(
                        200,
                        store.supersede_memory(
                            parts[2],
                            str(payload.get("new_content") or ""),
                            source=source
                            if isinstance(source, dict)
                            else {"kind": "inference_output", "locator": "xibalba://viewer/supersede"},
                            status=str(payload.get("status") or "confirmed"),
                            evidence_class=str(payload.get("evidence_class") or "extracted_proposition"),
                            idempotency_key=payload.get("idempotency_key")
                            if isinstance(payload.get("idempotency_key"), str)
                            else None,
                        ),
                    )
                elif len(parts) == 5 and parts[:3] == ["api", "para", "classifications"] and parts[4] == "decision":
                    decision = str(payload.get("decision") or "")
                    note = payload.get("note") if isinstance(payload.get("note"), str) else None
                    self._send_json(200, store.accept_para_classification(parts[3], decision=decision, note=note))
                elif len(parts) == 4 and parts[:2] == ["api", "extraction-proposals"] and parts[3] == "decision":
                    decision = str(payload.get("decision") or "")
                    note = payload.get("note") if isinstance(payload.get("note"), str) else None
                    decided_by = payload.get("decided_by") if isinstance(payload.get("decided_by"), str) else None
                    self._send_json(200, store.decide_extraction_proposal(parts[2], decision=decision, decided_by=decided_by, note=note))
                elif parts == ["api", "retrieval", "hybrid"]:
                    query_vector = payload.get("query_vector")
                    if query_vector is not None and not isinstance(query_vector, list):
                        raise ValueError("query_vector must be a list")
                    filters = payload.get("filters")
                    if filters is not None and not isinstance(filters, dict):
                        raise ValueError("filters must be an object")
                    self._send_json(
                        200,
                        store.hybrid_retrieve(
                            str(payload.get("query") or ""),
                            query_vector=[float(v) for v in query_vector] if query_vector is not None else None,
                            limit=int(payload.get("limit", 10)),
                            temporal_at=payload.get("temporal_at") if isinstance(payload.get("temporal_at"), str) else None,
                            filters=filters,
                            max_per_source=payload.get("max_per_source") if isinstance(payload.get("max_per_source"), int) else None,
                            max_total_chars=payload.get("max_total_chars") if isinstance(payload.get("max_total_chars"), int) else None,
                        ),
                    )
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "projections" and parts[3] == "checkpoint":
                    metadata = payload.get("metadata")
                    if metadata is not None and not isinstance(metadata, dict):
                        raise ValueError("metadata must be an object")
                    self._send_json(200, store.create_projection_checkpoint(parts[2], metadata=metadata))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "projections" and parts[3] == "reconcile":
                    self._send_json(200, store.reconcile_projection_checkpoint(parts[2]))
                elif len(parts) == 4 and parts[0] == "api" and parts[1] == "projections" and parts[3] == "rebuild":
                    self._send_json(200, store.rebuild_projection_checkpoint(parts[2]))
                elif len(parts) == 5 and parts[:3] == ["api", "inference", "tasks"] and parts[4] == "claim":
                    self._send_json(
                        200,
                        store.claim_inference_task(
                            parts[3],
                            claimed_by=payload.get("claimed_by")
                            if isinstance(payload.get("claimed_by"), str)
                            else None,
                        ),
                    )
                elif parts == ["api", "kernel-bridge", "self-test"]:
                    session_id = payload.get("session_id")
                    self._send_json(
                        200,
                        _run_kernel_bridge_self_test(
                            store, session_id=session_id if isinstance(session_id, str) and session_id else None
                        ),
                    )
                elif len(parts) == 5 and parts[:3] == ["api", "inference", "tasks"] and parts[4] == "complete":
                    output_payload = payload.get("output_payload")
                    if output_payload is not None and not isinstance(output_payload, dict):
                        raise ValueError("output_payload must be an object")
                    self._send_json(
                        200,
                        store.complete_inference_task(
                            parts[3],
                            output_payload=output_payload,
                            error=payload.get("error") if isinstance(payload.get("error"), str) else None,
                            claimed_by=payload.get("claimed_by") if isinstance(payload.get("claimed_by"), str) else None,
                            claim_token=payload.get("claim_token") if isinstance(payload.get("claim_token"), str) else None,
                        ),
                    )
                else:
                    self._send_json(404, {"error": "not found"})
            except KeyError:
                self._send_json(404, {"error": "not found"})
            except (sqlite3.IntegrityError, TypeError, ValueError) as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception:
                logger.exception("local_api request failed: %s", self.path)
                self._send_json(500, {"error": "internal error"})

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            logger.debug(format, *args)

    return Handler


def serve(store: GraphStore, *, host: str = "localhost", port: int = 8420, allowed_origin: str = "*") -> None:
    server = ThreadingHTTPServer((host, port), _make_handler(store, allowed_origin=allowed_origin))
    logger.info("local_api listening on http://%s:%d (local operator API)", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, help="xibalba-cortex profile home")
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
