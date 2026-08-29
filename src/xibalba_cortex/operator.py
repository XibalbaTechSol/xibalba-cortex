"""Operator CLI for local graph-memory administration."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from .config import load_config
from .providers import provider_manifest
from .ingest_tokens import list_tokens
from .server import _default_home, _identity_mode
from .store import GraphStore


def _memory_available_bytes() -> int | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024
    return None


def readiness(home: Path, *, min_disk_bytes: int = 2 * 1024**3, min_memory_bytes: int = 256 * 1024**2) -> dict[str, Any]:
    home.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(home)
    memory_available = _memory_available_bytes()
    checks = {
        "disk": {
            "ok": usage.free >= min_disk_bytes,
            "free_bytes": usage.free,
            "minimum_bytes": min_disk_bytes,
        },
        "memory": {
            "ok": memory_available is None or memory_available >= min_memory_bytes,
            "available_bytes": memory_available,
            "minimum_bytes": min_memory_bytes,
            "mode": "warn",
        },
    }
    return {
        "home": str(home),
        "ready": checks["disk"]["ok"],
        "checks": checks,
    }


def _open_store(home: Path) -> GraphStore:
    config = load_config(home=home)
    if config.storage.backend != "sqlite":
        raise RuntimeError(
            f"storage backend {config.storage.backend!r} is configured but no production adapter is installed; refusing SQLite fallback"
        )
    return GraphStore(home, profile_id=config.profile_id, identity_mode=_identity_mode(), features=config.features.as_dict())


def evaluation_smoke() -> dict[str, Any]:
    """Run a deterministic, isolated contract smoke gate for the local memory substrate."""
    with tempfile.TemporaryDirectory(prefix="xibalba-cortex-eval-") as directory:
        store = GraphStore(Path(directory))
        first = store.store_memory("The project uses an append-only evidence ledger.", source={"kind": "evaluation"}, status="confirmed")
        second = store.store_memory("The project preserves source lineage for every fact.", source={"kind": "evaluation"}, status="confirmed")
        retrieval = store.hybrid_retrieve("source lineage", limit=5)
        context = store.assemble_context("source lineage", limit=5, max_total_chars=4000)
        historical = store.store_memory("The project used a legacy memory path.", source={"kind": "evaluation", "observed_at": "2020-01-01T00:00:00Z"}, status="confirmed")
        current = store.supersede_memory(historical["id"], "The project uses the current memory path.", source={"kind": "evaluation"})
        conflict = store.store_memory("The project has a conflicting memory path.", source={"kind": "evaluation"}, status="confirmed")
        store.mark_contradiction(current["id"], conflict["id"], "evaluation contradiction")
        to_forget = store.store_memory("The project temporary test note.", source={"kind": "evaluation"}, status="confirmed")
        forgotten = store.forget_memory(to_forget["id"])
        export = store.export_memory_bundle(memory_ids=[first["id"], second["id"]])
        checks = {
            "lexical_recall": any(item["id"] == second["id"] for item in retrieval["results"]),
            "context_schema": context["schema_version"] == "xibalba.context_block.v1",
            "provenance_present": all("provenance" in item for bucket in ("current_facts", "historical_facts", "summaries", "observations") for item in context[bucket]),
            "export_commitment": bool(export["root_hash"]) and export["schema_version"] == "xibalba.provenance_export.v1",
            "temporal_update": store.get_memory(historical["id"])["status"] == "superseded" and current["supersedes_id"] == historical["id"],
            "contradiction_preserved": conflict["id"] in {item["id"] for item in store.contradictions(current["id"])},
            "deletion_receipt": forgotten["status"] == "forgotten" and forgotten["deletion_receipt"]["receipt_hash"].startswith("sha256:"),
        }
        store.close()
    return {"schema_version": "xibalba.evaluation_smoke.v1", "dataset": "synthetic-contract-smoke-v1", "checks": checks, "passed": all(checks.values()), "pilot_ready": False, "disclaimer": "Synthetic local contract smoke only; not a memory-quality benchmark or production pilot evidence."}

def production_readiness(home: Path) -> dict[str, Any]:
    config = load_config(home=home)
    tokens = list_tokens(home)
    active_tokens = sum(1 for row in tokens if not row["revoked_at"])
    checks = {
        "inference_reliability": {"state": "local_only", "evidence": "queue leases, retries, dead-letter metadata, and scoped evidence tests"},
        "storage_boundary": {"state": "ready" if config.storage.backend == "sqlite" else "blocked", "backend": config.storage.backend},
        "authorization_tenancy": {"state": "local_only" if active_tokens else "blocked", "active_tokens": active_tokens},
        "semantic_retrieval": {"state": "local_only", "provider": config.embeddings.provider, "vector_enabled": config.retrieval.vector},
        "connectors": {"state": "local_only", "enabled": config.features.connectors},
        "governance": {"state": "local_only", "enabled": config.features.governance, "provenance_export": True},
        "operations": {"state": "local_only", "backup_ready": False, "evidence": "operator backup and restore verification exists; HA/PITR is not demonstrated"},
        "evaluation": {"state": "blocked", "evidence": "benchmark datasets and failure-injection thresholds are not complete"},
    }
    return {"schema_version": "xibalba.production_readiness.v1", "ready": all(item["state"] == "ready" for item in checks.values()), "home": str(home), "checks": checks, "disclaimer": "Local readiness only; not deployment, SLA, or external compliance evidence."}

def run_command(args: argparse.Namespace) -> dict[str, Any]:
    home = Path(args.home) if args.home else _default_home()
    if args.command == "config":
        config = load_config(home=home)
        return config.redacted_dict()
    if args.command == "doctor":
        config = load_config(home=home)
        manifest = provider_manifest()
        return {
            "home": str(home),
            "mode": config.mode,
            "storage_backend": config.storage.backend,
            "canonical_store": manifest["canonical_store"],
            "inference_provider": config.inference.provider,
            "embedding_provider": config.embeddings.provider,
            "retrieval_provider": manifest["retrieval"],
            "remote_projections": manifest["remote_projections"],
            "features": config.features.as_dict(),
            "retrieval_channels": {
                "lexical": config.retrieval.lexical,
                "vector": config.retrieval.vector,
                "graph": config.retrieval.graph,
            },
        }
    if args.command == "evaluation-smoke":
        return evaluation_smoke()
    if args.command == "production-readiness":
        return production_readiness(home)
    if args.command == "readiness":
        return readiness(
            home,
            min_disk_bytes=args.min_disk_bytes,
            min_memory_bytes=args.min_memory_bytes,
        )

    store = _open_store(home)
    try:
        if args.command == "status":
            return store.status()
        if args.command == "backup":
            return store.backup(args.destination)
        if args.command == "restore":
            return store.restore(args.source)
        if args.command == "verify-memory":
            return store.verify_chain(args.memory_id)
        if args.command == "verify-integrity-link":
            return store.verify_integrity_link(
                args.memory_id,
                node_id=args.node_id,
                dag_home=args.dag_home,
                agent_id=args.agent_id,
            )
        if args.command == "verify-session":
            return store.verify_exchange_chain(args.session_id)
        if args.command == "integrity-links":
            return store.integrity_links_status(limit=args.limit)
        if args.command == "requeue-expired":
            return store.requeue_expired_inference_tasks(limit=args.limit, max_attempts=args.max_attempts)
        if args.command == "retention-sweep":
            try:
                policy = json.loads(args.max_age_days)
            except json.JSONDecodeError as exc:
                raise ValueError("--max-age-days must be a JSON object such as {\"digest\":30}") from exc
            return store.retention_sweep(max_age_days=policy, apply=args.apply, limit=args.limit)
    finally:
        store.close()
    raise ValueError(f"unknown command: {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=os.environ.get("XIBALBA_CORTEX_HOME"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("production-readiness", help="Report production gate status.")
    subparsers.add_parser("evaluation-smoke", help="Run the isolated deterministic contract smoke gate.")

    readiness_parser = subparsers.add_parser("readiness", help="Check local disk/memory startup readiness.")
    readiness_parser.add_argument("--min-disk-bytes", type=int, default=2 * 1024**3)
    readiness_parser.add_argument("--min-memory-bytes", type=int, default=256 * 1024**2)

    config_parser = subparsers.add_parser("config", help="Show effective configuration.")
    config_parser.add_argument("show", nargs="?", default="show")

    subparsers.add_parser("doctor", help="Show provider and local-mode diagnostics.")

    subparsers.add_parser("status", help="Show SQLite store health.")

    backup_parser = subparsers.add_parser("backup", help="Write a verified SQLite online backup.")
    backup_parser.add_argument("destination")

    restore_parser = subparsers.add_parser("restore", help="Restore the live SQLite store from a verified backup.")
    restore_parser.add_argument("source")

    verify_memory_parser = subparsers.add_parser("verify-memory", help="Verify one memory event hash chain.")
    verify_memory_parser.add_argument("memory_id")

    verify_integrity_parser = subparsers.add_parser(
        "verify-integrity-link",
        help="Verify one memory against a cited Integrity Memory DAG node.",
    )
    verify_integrity_parser.add_argument("memory_id")
    verify_integrity_parser.add_argument("--node-id")
    verify_integrity_parser.add_argument("--dag-home")
    verify_integrity_parser.add_argument("--agent-id")

    verify_session_parser = subparsers.add_parser("verify-session", help="Verify one session exchange chain.")
    verify_session_parser.add_argument("session_id")

    integrity_parser = subparsers.add_parser("integrity-links", help="Show Integrity DAG link states.")
    integrity_parser.add_argument("--limit", type=int, default=50)
    recovery_parser = subparsers.add_parser("requeue-expired", help="Recover expired inference-task leases.")
    recovery_parser.add_argument("--limit", type=int, default=50)
    recovery_parser.add_argument("--max-attempts", type=int, default=3)
    retention_parser = subparsers.add_parser("retention-sweep", help="Plan or apply bounded session retention expiry.")
    retention_parser.add_argument("--max-age-days", required=True, help="JSON policy, e.g. {\"digest\":30,\"synopsis\":90}")
    retention_parser.add_argument("--apply", action="store_true", help="Apply forgetting; default is a dry run.")
    retention_parser.add_argument("--limit", type=int, default=500)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    print(json.dumps(run_command(args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
