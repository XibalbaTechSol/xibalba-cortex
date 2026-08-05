"""CLI bridge invoked by the Hermes plugin at ~/.hermes/plugins/xibalba_graph_memory/.

The Hermes agent's own venv (~/.hermes/hermes-agent/venv) does not have xibalba_graph
installed -- it's a separate project with its own dependencies (mcp, eth-hash, sqlite-vec) --
so the plugin shells out to this project's own venv, the same cross-venv pattern already
established by ~/.hermes/plugins/integrity_telemetry (which shells out to integrity-sdk's venv
for the same reason). This process is spawned fire-and-forget per hook call; it must exit
promptly and never raise past its own boundary, matching the observer contract's fail-open
guarantee at the Hermes side and integrity_telemetry's swallow-everything posture at the
subprocess side.

Usage: python -m xibalba_graph.hermes_bridge <hook_name>, with the hook's kwargs as a JSON
object on stdin. stdin (not argv) because hook payloads carry full prompt/response text, which
can exceed OS argv length limits and contain characters that need cross-venv shell escaping.
"""
from __future__ import annotations

import json
import sys

from xibalba_graph.hermes_observer import HermesObserverAdapter
from xibalba_graph.server import _default_home, _identity_mode
from xibalba_graph.store import GraphStore

_store: GraphStore | None = None


def _get_adapter() -> HermesObserverAdapter:
    global _store
    if _store is None:
        _store = GraphStore(_default_home(), identity_mode=_identity_mode())
    return HermesObserverAdapter(_store)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: hermes_bridge.py <hook_name>", file=sys.stderr)
        sys.exit(2)
    hook_name = sys.argv[1]
    kwargs = json.loads(sys.stdin.read() or "{}")

    adapter = _get_adapter()
    handler = getattr(adapter, hook_name, None)
    if handler is None:
        print(f"unknown hook: {hook_name}", file=sys.stderr)
        sys.exit(1)
    handler(**kwargs)


if __name__ == "__main__":
    main()
