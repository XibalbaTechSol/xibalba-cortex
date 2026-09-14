"""CLI bridge for the OpenClaw native plugin."""
from __future__ import annotations

import json
import sys

from .openclaw_adapter import OpenClawAdapter
from .server import _default_home, _identity_mode
from .store import GraphStore
from .runtime_controller import XibalbaRuntimeController


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m xibalba_cortex.openclaw_bridge <hook-name>")
    event = json.loads(sys.stdin.read() or "{}")
    store = GraphStore(_default_home(), identity_mode=_identity_mode())
    try:
        result = OpenClawAdapter(XibalbaRuntimeController(store)).ingest_hook(sys.argv[1], event)
        print(json.dumps(result, sort_keys=True))
    finally:
        store.close()


if __name__ == "__main__":
    main()
