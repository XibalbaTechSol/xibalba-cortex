"""Provision isolated Cortex tenant profiles for controlled pilots."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

import yaml

from .ingest_tokens import issue_token
from .store import GraphStore

_TENANT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def provision_tenant(root: str | Path, tenant_id: str, *, label: str = "pilot-operator", ttl_hours: int = 720, max_memories: int | None = None) -> dict[str, object]:
    """Create one isolated profile home and return its one-time bootstrap credential."""
    if not _TENANT_ID.fullmatch(tenant_id):
        raise ValueError("tenant_id must be 1-63 lowercase letters, digits, or hyphens")
    if ttl_hours < 1:
        raise ValueError("ttl_hours must be positive")
    if max_memories is not None and max_memories < 1:
        raise ValueError("max_memories must be positive or None")
    tenant_root = Path(root).expanduser().resolve() / tenant_id
    tenant_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        tenant_root.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise FileExistsError(f"tenant profile already exists: {tenant_root}") from exc
    config = {"profile_id": tenant_id, "mode": "local", "storage": {"backend": "sqlite", "home": str(tenant_root)}, "quotas": {"max_memories": max_memories}}
    try:
        config_path = tenant_root / "config.yaml"
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))
        config_path.chmod(0o600)
        store = GraphStore(tenant_root, profile_id=tenant_id, quotas={"max_memories": max_memories})
        store.close()
        token = issue_token(tenant_root, label, profile_id=tenant_id, roles=("operator",), scopes=("memory:read", "memory:write", "memory:delete", "proposal:decide"), ttl_hours=ttl_hours)
        (tenant_root / "ingest_tokens.sqlite3").chmod(0o600)
    except Exception:
        shutil.rmtree(tenant_root)
        raise
    return {"schema_version": "xibalba.tenant_onboarding.v1", "tenant_id": tenant_id, "home": str(tenant_root), "profile_id": tenant_id, "token": token, "token_label": label, "ttl_hours": ttl_hours, "max_memories": max_memories, "disclaimer": "Local isolated-profile provisioning evidence; not hosted SaaS deployment or external pilot proof."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="parent directory for isolated tenant profiles")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--label", default="pilot-operator")
    parser.add_argument("--ttl-hours", type=int, default=720)
    parser.add_argument("--max-memories", type=int, default=None)
    args = parser.parse_args()
    result = provision_tenant(args.root, args.tenant_id, label=args.label, ttl_hours=args.ttl_hours, max_memories=args.max_memories)
    print(json.dumps(result, indent=2))
    print("WARNING: token is shown once; move it to the tenant secret store now.")


if __name__ == "__main__":
    main()
