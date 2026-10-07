#!/usr/bin/env python3
"""Generate viewer/COVERAGE.md: what the backend offers and where the console exposes it.

The question this answers is "what is hidden?". It has two halves:

  * every HTTP route local_api.py documents, and the console surface that calls it;
  * every MCP tool server.py registers, and either the surface that covers the same capability
    or the reason it is deliberately not a console feature.

The CLASSIFICATION below is hand-maintained judgment (a script cannot decide that a worker's
claim/complete protocol should not be a button). What the script enforces is completeness: a new
MCP tool or documented route that is not classified here fails `--check`, so nothing becomes
hidden by omission. tests/test_ui_coverage.py runs --check in CI.

    python scripts/ui_coverage.py --write    # regenerate viewer/COVERAGE.md
    python scripts/ui_coverage.py --check    # exit 1 if the file is stale or anything is unclassified
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "viewer" / "COVERAGE.md"

# --- HTTP routes -> console surface ----------------------------------------------------------------------
# Keys are "METHOD /path" exactly as local_api.py's module docstring writes them, with ?query removed.
# Routes the handler serves but the docstring omits are listed in UNDOCUMENTED_ROUTES below.
ROUTES: dict[str, str] = {
    "GET /metrics": "Operations → metrics",
    "GET /healthz": "Settings → Developer (liveness)",
    "GET /readyz": "Operations → full readiness check",
    "GET /api/stats": "Facet rail counts",
    "GET /api/status": "Status bar, Operations",
    "GET /api/operations": "Operations",
    "GET /api/integrity-links": "Integrity → Links",
    "GET /api/sessions": "Timeline / Sessions",
    "GET /api/session/{id}/replay": "Sessions → Replay",
    "GET /api/search": "Recall → Lexical",
    "GET /api/memory/{id}": "Inspector",
    "GET /api/memory/{id}/events": "Inspector → Chain",
    "GET /api/memory/{id}/verify-chain": "Inspector → Chain → Verify this history",
    "GET /api/memory/{id}/provenance": "Inspector → Provenance → Export",
    "GET /api/memory/{id}/otel": "Inspector → Telemetry",
    "GET /api/memory/{id}/attachments": "Inspector → Files (with download)",
    "GET /api/memory/{id}/contradictions": "Inspector → Contradictions",
    "GET /api/memory/{id}/similar": "Inspector → Neighbors",
    "GET /api/memory/{id}/neighbors": "Inspector → Neighbors",
    "GET /api/entity/{name}/neighbors": "Entities",
    "GET /api/entity/path": "Entities → Path",
    "GET /api/session/{id}/exchanges": "Sessions → Exchanges",
    "GET /api/session/{id}/verify-chain": "Integrity → Sessions (server recomputation)",
    "GET /api/session/{id}/memories": "Sessions → Memories",
    "GET /api/session/{id}/otel-summary": "Sessions → Telemetry summary",
    "GET /api/session/{id}/otel": "Sessions → Telemetry",
    "GET /api/session/{id}/merkle-root": "Inspector, Integrity",
    "GET /api/session/{id}/merkle-proof": "Integrity → Sessions (verified in the browser)",
    "GET /api/session/{id}/decision-trace": "Sessions → Decision trace",
    "GET /api/session/{id}/decision-trace.html": "Sessions → Decision trace (opens the server's audit view)",
    "GET /api/inference/manifest": "Settings → Inference → Worker contract",
    "GET /api/inference/tasks": "Review (which task produced a proposal)",
    "GET /api/extraction-proposals": "Review",
    "GET /api/retrieval/trace/{id}": "Recall → per-channel ranks",
    "GET /api/retrieval/trace/{id}/evidence": "Recall → Inclusion proof (verified in the browser)",
    "GET /api/projections/{id}/checkpoints": "Integrity → Checkpoints",
    "GET /api/projections/{id}/checkpoints/latest": "not called: the checkpoint history already contains the latest",
    "GET /api/embedding/models": "Settings → Embeddings",
    "POST /api/exchanges/model": "Sessions → Record exchange",
    "POST /api/memory/propositions": "Memories → New memory",
    "POST /api/memory/link-entities": "Inspector → Link entities",
    "POST /api/memory/contradictions": "Inspector → Contradiction",
    "POST /api/memory/{id}/supersede": "Inspector → Supersede",
    "POST /api/memory/{id}/forget": "Inspector → Forget",
    "POST /api/memory/{id}/extract-structural": "Inspector → Request extraction → structural entities",
    "POST /api/inference/tasks": "Inspector → Request extraction",
    "POST /api/inference/tasks/{id}/claim": "NOT A CONSOLE FEATURE: worker protocol (a person should not impersonate the worker)",
    "POST /api/inference/tasks/{id}/complete": "NOT A CONSOLE FEATURE: worker protocol (a person should not impersonate the worker)",
    "POST /api/extraction-proposals/{id}/decision": "Review → Accept / Reject",
    "POST /api/retrieval/hybrid": "Recall → Hybrid",
    "POST /api/context/assemble": "Recall → Context",
    "POST /api/projections/{id}/checkpoint": "Integrity → Checkpoints → New checkpoint",
    "POST /api/projections/{id}/reconcile": "Integrity → Checkpoints → Reconcile",
    "POST /api/projections/{id}/rebuild": "Integrity → Checkpoints → Rebuild (confirmed)",
    "GET /api/graph": "Graph and Timeline lenses",
    "GET /api/session/{id}/kernel-intents": "Sessions → Kernel intents",
    "GET /api/invocations": "Sessions → Invocations",
    "POST /api/kernel-bridge/self-test": "Settings → Developer → Kernel bridge self-test",
    "POST /api/otel/batch": "NOT A CONSOLE FEATURE: machine telemetry ingest (agents and the OTLP receiver)",
}

# Served by local_api.py but missing from its module docstring (the docstring is not the source of truth).
UNDOCUMENTED_ROUTES: dict[str, str] = {
    "GET /api/agents": "Scope picker, Agents",
    "GET /api/agent-devices": "Agents → device pairing",
    "POST /api/agent-devices": "Agents → Pair a device / Rename / Detach / Revoke",
    "GET /api/memories": "Memories",
    "GET /api/sessions/page": "Sessions",
    "GET /api/settings/inference": "Settings → Inference",
    "POST /api/settings/inference": "Settings → Inference → Save",
    "GET /api/para/classifications": "Review → PARA",
    "POST /api/para/classifications/{id}/decision": "Review → PARA → Accept / Reject",
    "GET /api/attachment/{id}/file": "Inspector → Files → Download",
    "POST /api/session/{id}/exchanges/build": "Sessions → Build from telemetry",
    "GET /api/auth/me": "Settings → Account",
    "GET /api/auth/sessions": "Settings → Account → Sessions",
    "POST /api/auth/sessions/revoke": "Settings → Account → Revoke",
    "GET /api/auth/events": "Settings → Account → Security events",
    "POST /api/auth/password": "Settings → Account → Change password",
    "GET /api/auth/csrf": "api.ts (sent automatically on cookie-session writes)",
    "POST /api/auth/login": "Sign-in",
    "POST /api/auth/signup": "Sign-in → Create account",
    "POST /api/auth/logout": "Rail / top bar → Sign out",
    "POST /api/auth/password-reset/request": "Sign-in → Forgot password (not yet built)",
    "POST /api/auth/password-reset/confirm": "Sign-in → Reset password (not yet built)",
    "POST /api/auth/admin/approve": "not yet built: account approval for operators",
}

# --- MCP tools -> console surface or reason ----------------------------------------------------------------
# status: "console" = a console surface covers the capability, "machine" = a protocol for workers or
# agent harnesses that should not be a button, "withheld" = deliberately not exposed to a browser
# (takes a server path, is outward-facing, or needs an upload route that does not exist yet).
TOOLS: dict[str, tuple[str, str]] = {
    "memory_remember": ("console", "Memories → New memory"),
    "memory_supersede": ("console", "Inspector → Supersede"),
    "memory_contradict": ("console", "Inspector → Contradiction"),
    "memory_forget": ("console", "Inspector → Forget"),
    "memory_link_entities": ("console", "Inspector → Link entities"),
    "memory_get": ("console", "Inspector"),
    "memory_events": ("console", "Inspector → Chain"),
    "memory_otel_events": ("console", "Inspector → Telemetry"),
    "memory_contradictions": ("console", "Inspector → Contradictions"),
    "memory_similar": ("console", "Inspector → Neighbors"),
    "memory_neighbors": ("console", "Inspector → Neighbors"),
    "memory_list_attachments": ("console", "Inspector → Files"),
    "memory_verify_chain": ("console", "Inspector → Chain → Verify this history"),
    "memory_export_provenance": ("console", "Inspector → Provenance → Export (one memory; the bulk export is not offered)"),
    "memory_find_path": ("console", "Entities → Path"),
    "memory_hybrid_retrieve": ("console", "Recall → Hybrid"),
    "memory_recall": ("console", "Recall"),
    "memory_context_assemble": ("console", "Recall → Context"),
    "memory_retrieval_trace": ("console", "Recall → per-channel ranks"),
    "memory_retrieval_trace_evidence": ("console", "Recall → Inclusion proof"),
    "memory_list_extraction_proposals": ("console", "Review"),
    "memory_decide_extraction_proposal": ("console", "Review → Accept / Reject"),
    "memory_request_inference": ("console", "Inspector → Request extraction"),
    "memory_extract_structural_entities": ("console", "Inspector → Request extraction → structural entities"),
    "memory_inference_tasks": ("console", "Review (which task produced a proposal)"),
    "memory_inference_subagent_manifest": ("console", "Settings → Inference → Worker contract"),
    "memory_embedding_models": ("console", "Settings → Embeddings"),
    "memory_embedding_coverage": ("console", "Operations, Settings → Embeddings"),
    "memory_status": ("console", "Status bar, Operations"),
    "memory_session_get": ("console", "Sessions"),
    "memory_session_exchanges": ("console", "Sessions → Exchanges"),
    "memory_session_replay": ("console", "Sessions → Replay"),
    "memory_session_memories": ("console", "Sessions → Memories"),
    "memory_session_otel_summary": ("console", "Sessions → Telemetry summary"),
    "memory_session_merkle_root": ("console", "Inspector, Integrity"),
    "memory_verify_exchange_chain": ("console", "Integrity → Sessions"),
    "memory_build_session_exchanges": ("console", "Sessions → Build from telemetry"),
    "memory_record_model_exchange": ("console", "Sessions → Record exchange"),
    "memory_claim_inference_task": ("machine", "Worker protocol: claiming a task is what the extraction worker does, not a person"),
    "memory_complete_inference_task": ("machine", "Worker protocol: completing a task submits the worker's output"),
    "memory_evidence_bundle": ("machine", "Worker-side: the bounded evidence a claimed task may read"),
    "memory_embed": ("machine", "Embedding worker writes vectors; a browser has no embedding model"),
    "memory_record_otel_batch": ("machine", "Telemetry ingest for agents and the OTLP receiver (POST /api/otel/batch exists; there is no UI producer)"),
    "memory_ingest_agent_turn": ("machine", "Agent harness ingest"),
    "memory_ingest_connector_event": ("machine", "Connector ingest"),
    "memory_start_self_extraction": ("machine", "An agent extracting from its own context"),
    "memory_session_start": ("machine", "Harness lifecycle; a session begins when its first exchange is recorded"),
    "memory_session_end": ("machine", "Harness lifecycle; no HTTP route exists to end a session"),
    "memory_attach": ("withheld", "Takes a file path on the server's disk; a browser upload route does not exist yet"),
    "memory_backup": ("withheld", "Takes a destination path on the server's disk"),
    "memory_backup_reconcile": ("withheld", "Takes a backup path on the server's disk"),
    "memory_vault_inspect": ("withheld", "Takes a vault directory path on the server's disk"),
    "memory_verify_integrity_link": ("withheld", "Takes a dag_home path on the server's disk; the link states are listed under Integrity → Links"),
    "memory_anchor_session_root": ("withheld", "Outward-facing: publishes a session root to the oracle. Needs an explicit, confirmed action"),
}
RUNTIME_REASON = (
    "machine",
    "Agent-harness hook. The runtime controller lives in the MCP server process, so an HTTP process would report its own empty registry as if it were the real state",
)


def documented_routes() -> list[str]:
    """`METHOD /path` for every route in local_api.py's module docstring, query strings removed."""
    source = (ROOT / "src" / "xibalba_cortex" / "local_api.py").read_text()
    block = source.split("Routes:", 1)[1].split('"""', 1)[0]
    return [f"{m} {p.split('?')[0]}" for m, p in re.findall(r"^\s+(GET|POST) (/\S+)", block, re.M)]


def mcp_tools() -> list[str]:
    source = (ROOT / "src" / "xibalba_cortex" / "server.py").read_text()
    return re.findall(r"\n@server\.tool\([^)]*\)\n(?:@[^\n]*\n)*(?:async )?def (\w+)", source)


def problems() -> list[str]:
    out: list[str] = []
    for route in documented_routes():
        if route not in ROUTES:
            out.append(f"route not classified: {route}")
    for route in ROUTES:
        if route not in documented_routes():
            out.append(f"classified route is not in local_api.py's docstring (renamed or removed?): {route}")
    tools = mcp_tools()
    for tool in tools:
        if tool.startswith("runtime_"):
            continue
        if tool not in TOOLS:
            out.append(f"MCP tool not classified: {tool}")
    for tool in TOOLS:
        if tool not in tools:
            out.append(f"classified MCP tool no longer exists: {tool}")
    return out


def render() -> str:
    tools = mcp_tools()
    runtime = [t for t in tools if t.startswith("runtime_")]
    classified = {t: TOOLS[t] for t in tools if not t.startswith("runtime_")}
    counts = {s: sum(1 for st, _ in classified.values() if st == s) for s in ("console", "machine", "withheld")}
    lines = [
        "# What the console exposes",
        "",
        "Generated by `scripts/ui_coverage.py` — do not edit by hand. `tests/test_ui_coverage.py` fails when a new MCP tool",
        "or documented route is not classified, so nothing becomes hidden by omission.",
        "",
        "## Summary",
        "",
        f"- **{len(documented_routes())} documented HTTP routes** and {len(UNDOCUMENTED_ROUTES)} more the handler serves but its docstring omits.",
        f"- **{len(tools)} MCP tools**: {counts['console']} have a console surface, {counts['machine'] + len(runtime)} are machine protocols"
        f" ({len(runtime)} of them `runtime_*` harness hooks), {counts['withheld']} are deliberately withheld from a browser.",
        "",
        "Statuses: **console** = a surface covers it. **machine** = a protocol for workers or agent harnesses; a person should not be",
        "able to drive it from a button. **withheld** = would hand a browser a server filesystem path, or is outward-facing, or needs a",
        "route that does not exist yet.",
        "",
        "## HTTP routes",
        "",
        "| Route | Console surface |",
        "|---|---|",
    ]
    for route in documented_routes():
        lines.append(f"| `{route}` | {ROUTES[route]} |")
    lines += ["", "### Served but not in the docstring", "", "| Route | Console surface |", "|---|---|"]
    for route, surface in UNDOCUMENTED_ROUTES.items():
        lines.append(f"| `{route}` | {surface} |")
    lines += ["", "## MCP tools", "", "| Tool | Status | Console surface or reason |", "|---|---|---|"]
    for tool in tools:
        if tool.startswith("runtime_"):
            continue
        status, text = classified[tool]
        lines.append(f"| `{tool}` | {status} | {text} |")
    lines += [
        "",
        f"### `runtime_*` ({len(runtime)} tools)",
        "",
        f"{RUNTIME_REASON[1]}.",
        "",
        "`" + "`, `".join(runtime) + "`",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    issues = problems()
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    text = render()
    if args.write:
        OUTPUT.write_text(text)
        print(f"wrote {OUTPUT.relative_to(ROOT)}")
        return 0
    if not OUTPUT.exists() or OUTPUT.read_text() != text:
        print(f"{OUTPUT.relative_to(ROOT)} is stale; run: python scripts/ui_coverage.py --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
