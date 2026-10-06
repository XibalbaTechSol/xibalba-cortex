"""Install/remove Cortex's observation-only hooks in an explicit JSON settings file."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

from .observer_capture import CLAUDE_HOOKS, CODEX_HOOKS

MARKER = " # cortex-observer:v1"


def _owned(hook: dict) -> bool:
    return hook.get("type") == "command" and str(hook.get("command", "")).endswith(MARKER)


def configure(settings: Path, *, home: Path, mode: str = "metadata", uninstall: bool = False,
              runtime: str = "claude") -> bool:
    if mode not in {"metadata", "redacted"}:
        raise ValueError("unsupported capture mode")
    if runtime not in {"claude", "codex"}:
        raise ValueError("unsupported runtime")
    if settings.is_symlink():
        raise ValueError("settings must not be a symlink")
    data = json.loads(settings.read_text()) if settings.exists() else {}
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise ValueError("invalid settings object")
    original = json.dumps(data, sort_keys=True)
    hooks = data.setdefault("hooks", {})
    command = shlex.join([sys.executable, "-m", "xibalba_cortex.observer_capture", runtime + "-hook",
                          "--home", str(home.expanduser().resolve()), "--mode", mode]) + MARKER
    for event in (CLAUDE_HOOKS if runtime == "claude" else CODEX_HOOKS):
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError("invalid hook groups")
        preserved = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError("invalid hook group")
            remaining = [h for h in group.get("hooks", []) if not (isinstance(h, dict) and _owned(h))]
            if remaining or not group.get("hooks"):
                preserved.append(group if remaining == group.get("hooks", []) else {**group, "hooks": remaining})
        if not uninstall:
            timeout = 3 if runtime == "codex" and event in {"Interrupt", "SessionEnd"} else 5
            preserved.append({"hooks": [{"type": "command", "command": command, "timeout": timeout}]})
        if preserved:
            hooks[event] = preserved
        else:
            hooks.pop(event, None)
    if not hooks:
        data.pop("hooks", None)
    if json.dumps(data, sort_keys=True) == original:
        return False
    settings.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement; backup existing settings once, without overwriting prior evidence.
    if settings.exists():
        backup = settings.with_name(settings.name + ".cortex-observer-backup")
        if not backup.exists():
            with backup.open("x") as handle:
                os.chmod(backup, 0o600)
                handle.write(settings.read_text())
    fd, temporary = tempfile.mkstemp(dir=settings.parent, prefix=".cortex-observer-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, settings)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--mode", choices=("metadata", "redacted"), default="metadata")
    parser.add_argument("--runtime", choices=("claude", "codex"), default="claude")
    args = parser.parse_args()
    changed = configure(args.settings, home=args.home, mode=args.mode,
                        uninstall=args.action == "uninstall", runtime=args.runtime)
    print(json.dumps({"changed": changed, "runtime": args.runtime, "observer_only": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
