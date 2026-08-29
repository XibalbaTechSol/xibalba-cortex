"""Operator CLI for local graph-memory administration."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

from .config import load_config
from .providers import provider_manifest
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
    return GraphStore(home, identity_mode=_identity_mode())


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
    finally:
        store.close()
    raise ValueError(f"unknown command: {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", default=os.environ.get("XIBALBA_CORTEX_HOME"))
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    print(json.dumps(run_command(args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
