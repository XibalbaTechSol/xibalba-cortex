from xibalba_cortex.store import GraphStore
from xibalba_cortex.exchange_builder import build_session_exchanges
from pathlib import Path
import os
home = Path(os.path.expanduser("~/.hermes/xibalba-cortex"))
store = GraphStore(home)
for session in store.list_sessions(limit=1000):
    res = build_session_exchanges(store, session["external_session_id"])
    if res["exchanges_built"] > 0:
        print(f"Built {res['exchanges_built']} exchanges for {session['external_session_id']}")
store.close()
