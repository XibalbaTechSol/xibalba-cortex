"""Preview, apply, or roll back a Cortex to Supabase Auth identity mapping batch.

The mapping manifest is JSON: {"links":[{"auth_user_id":"...","legacy_account_id":"..."}]}.
Set CORTEX_MANAGED_DATABASE_URL to the server-side Postgres DSN.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .managed.config import ManagedConfig
from .managed.control import ManagedControl
from .managed.storage import SupabaseManagedDbFactory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply", "rollback"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--batch", required=True)
    args = parser.parse_args(argv)
    dsn = os.environ.get("CORTEX_MANAGED_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("CORTEX_MANAGED_DATABASE_URL must be set")
    service = ManagedControl(
        ManagedConfig(home=Path(os.environ.get("CORTEX_MANAGED_HOME", "/data/cortex-managed")),
                      storage_backend="supabase", identity_backend="sqlite_compat"),
        db_factory=SupabaseManagedDbFactory(dsn), bootstrap_schema=False)
    if args.action == "rollback":
        result = {"batch_id": args.batch, "rolled_back": service.rollback_auth_subject_batch(args.batch)}
    else:
        if args.manifest is None:
            parser.error("--manifest is required for preview/apply")
        manifest = json.loads(args.manifest.read_text())
        links = manifest.get("links")
        if not isinstance(links, list):
            parser.error("manifest must contain a links array")
        result = service.migrate_auth_subjects(links, batch_id=args.batch, apply=args.action == "apply")
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
