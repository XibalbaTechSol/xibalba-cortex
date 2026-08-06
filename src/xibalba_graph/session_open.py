"""Open a runtime session in graph memory and Hermes state.db."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .store import GraphStore

DEFAULT_HOME = Path(os.environ.get("XIBALBA_GRAPH_MEMORY_HOME", "~/.hermes/xibalba-graph-memory")).expanduser()
HERMES_AGENT_ROOT = Path(os.environ.get("HERMES_AGENT_ROOT", "~/.hermes/hermes-agent")).expanduser()


def open_session(session_id: str, runtime: str, home: Path = DEFAULT_HOME) -> dict[str, object]:
    home.mkdir(parents=True, exist_ok=True)
    store = GraphStore(home)
    try:
        session = store.start_session(session_id, retention_tier="verbatim")
    finally:
        store.close()
    hermes: dict[str, object] = {"created": False}
    if runtime != "hermes":
        try:
            if str(HERMES_AGENT_ROOT) not in sys.path:
                sys.path.insert(0, str(HERMES_AGENT_ROOT))
            from hermes_state import SessionDB  # type: ignore
            db = SessionDB()
            try:
                try:
                    existing_session = db.get_session(session_id)
                except Exception:
                    existing_session = None
                if not existing_session:
                    db.create_session(session_id, f"xibalba-{runtime}")
                    hermes["created"] = True
            finally:
                db.close()
        except Exception as exc:
            hermes["error"] = type(exc).__name__
    return {"session": session, "hermes": hermes}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--runtime", required=True, choices=("claude", "codex", "agy", "hermes"))
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    args = parser.parse_args()
    print(open_session(args.session_id, args.runtime, args.home))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
