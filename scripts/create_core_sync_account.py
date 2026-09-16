#!/usr/bin/env python3
"""Create and explicitly bind a Cortex account, then enable CORE sync.

This script deliberately requires the operator to provide the controller. It
never selects a controller from an email address, wallet inventory, or a
transaction sender. The controller must already appear in CORE's agent
directory; the directory may still be non-finalized, in which case the timer
will run but the sync worker will fail closed.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.request import Request, urlopen

from xibalba_cortex.accounts import (
    active_account_by_email,
    create_account,
    set_account_controller,
    verify_account_password,
)


ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
PLACEHOLDER_MARKERS = ("example.invalid", "replace-", "REPLACE_", "0x0000000000000000000000000000000000000000")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("XIBALBA_CORE_ORACLE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--home", default=os.environ.get("XIBALBA_CORTEX_HOME", str(Path.home() / ".hermes/xibalba-cortex")))
    parser.add_argument("--config-dir", default=os.environ.get("XIBALBA_CORTEX_CONFIG_DIR", str(Path.home() / ".config/xibalba-cortex")))
    parser.add_argument("--email", help="Account email; prompted when omitted")
    parser.add_argument("--display-name", help="Account display name; prompted when omitted")
    parser.add_argument("--controller", help="Already-registered EVM controller; prompted when omitted")
    parser.add_argument("--force-config", action="store_true", help="Replace an existing non-placeholder sync config")
    return parser.parse_args()


def fetch_snapshot(endpoint: str) -> dict[str, object]:
    request = Request(endpoint.rstrip("/") + "/v1/agents/snapshot", headers={"Accept": "application/json"})
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict) or not isinstance(payload.get("agents"), list):
        raise RuntimeError("CORE returned an invalid agent snapshot")
    return payload


def config_is_safe_to_replace(path: Path) -> bool:
    if not path.exists():
        return True
    text = path.read_text(encoding="utf-8")
    return any(marker in text for marker in PLACEHOLDER_MARKERS)


def write_sync_config(path: Path, *, endpoint: str, home: Path, account_id: str, controller: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"XIBALBA_CORE_ORACLE_URL={endpoint}\n"
        f"XIBALBA_CORTEX_HOME={home}\n"
        f"XIBALBA_CORTEX_ACCOUNT_ID={account_id}\n"
        f"XIBALBA_CORTEX_CONTROLLER={controller.lower()}\n"
    )
    old_umask = os.umask(0o077)
    try:
        path.write_text(content, encoding="utf-8")
    finally:
        os.umask(old_umask)
    path.chmod(0o600)


def install_timer(repo_root: Path) -> None:
    unit_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name in ("xibalba-cortex-core-sync.service", "xibalba-cortex-core-sync.timer"):
        source = repo_root / "packaging/systemd" / name
        if not source.is_file():
            raise RuntimeError(f"missing systemd unit: {source}")
        shutil.copy2(source, unit_dir / name)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "xibalba-cortex-core-sync.timer"], check=True)


def main() -> int:
    args = parse_args()
    home = Path(args.home).expanduser()
    config_path = Path(args.config_dir).expanduser() / "core-sync.env"

    email = args.email or input("Cortex account email: ").strip()
    existing = active_account_by_email(home, email=email)
    display_name = args.display_name or (input("Cortex display name: ").strip() if existing is None else str(existing["display_name"]))
    controller = (args.controller or input("Registered controller address (0x...): ").strip()).lower()
    if not ADDRESS_RE.fullmatch(controller):
        raise SystemExit("ERROR: controller must be a 20-byte EVM address")
    if config_path.exists() and not config_is_safe_to_replace(config_path) and not args.force_config:
        raise SystemExit(f"ERROR: refusing to replace non-placeholder config: {config_path} (use --force-config only after review)")

    try:
        snapshot = fetch_snapshot(args.endpoint)
    except Exception as exc:
        raise SystemExit(f"ERROR: could not read CORE snapshot: {exc}") from exc
    snapshot_controllers = {
        str(row.get("controller", "")).lower()
        for row in snapshot["agents"]
        if isinstance(row, dict)
    }
    if controller not in snapshot_controllers:
        raise SystemExit("ERROR: controller is not present in the current CORE agent snapshot; refusing to bind it")
    if snapshot.get("finalized") is not True:
        print("WARNING: CORE snapshot is not finalized; sync will remain fail-closed.", file=sys.stderr)

    password = getpass.getpass("Cortex account password: ")
    if not password:
        raise SystemExit("ERROR: password must not be empty")

    if existing is None:
        account = create_account(home, email=email, password=password, display_name=display_name)
        account_id = str(account["id"])
        created = True
    else:
        if not verify_account_password(home, email=email, password=password):
            raise SystemExit("ERROR: existing Cortex account password was not accepted")
        account_id = str(existing["id"])
        created = False
        print(f"Using existing Cortex account {account_id} ({existing['display_name']}).")
        previous_controller = str(existing.get("controller_address") or "").lower()
        if previous_controller and previous_controller != controller:
            raise SystemExit(
                f"ERROR: existing account is already bound to {previous_controller}; refusing to replace it"
            )
    if not set_account_controller(home, account_id=account_id, controller_address=controller):
        raise SystemExit("ERROR: controller binding failed")
    write_sync_config(config_path, endpoint=args.endpoint, home=home, account_id=account_id, controller=controller)
    install_timer(Path(__file__).resolve().parents[1])

    enabled = subprocess.run(
        ["systemctl", "--user", "is-enabled", "xibalba-cortex-core-sync.timer"],
        check=False,
        capture_output=True,
        text=True,
    )
    active = subprocess.run(
        ["systemctl", "--user", "is-active", "xibalba-cortex-core-sync.timer"],
        check=False,
        capture_output=True,
        text=True,
    )
    print(json.dumps({
        "created": created,
        "bound": True,
        "account_uuid": account_id,
        "controller": controller,
        "config": str(config_path),
        "timer_enabled": enabled.stdout.strip() == "enabled",
        "timer_active": active.stdout.strip() == "active",
        "core_finalized": snapshot.get("finalized") is True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("\nCancelled")
