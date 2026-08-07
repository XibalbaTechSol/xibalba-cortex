import json
from pathlib import Path

from xibalba_graph.canonical import canonical_json_bytes
from xibalba_graph.events import Event, merkle_root, verify_events


def test_published_event_vector_is_reproducible():
    vector = json.loads((Path(__file__).parent / "conformance/test_vectors.json").read_text())
    event = Event(**vector["events"][0])
    assert canonical_json_bytes(event.envelope())
    assert verify_events([event])["head"] == event.digest()
    assert merkle_root(vector["merkle_leaves"]) == "sha256:90f4b39548df55ad6187a1d20d731ecee78c545b94afd16f42ef7592d99cd365"
