from __future__ import annotations

import json
from unittest.mock import patch

from xibalba_cortex.embedding_client import embed_query


class Response:
    def __init__(self, body: bytes): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, _limit): return self.body


def test_query_embedding_validates_dimension_and_converts_values():
    with patch("xibalba_cortex.embedding_client.urlopen", return_value=Response(json.dumps({"vector": [1] * 384}).encode())):
        vector = embed_query("hello")
    assert vector == [1.0] * 384


def test_query_embedding_degrades_cleanly_when_sidecar_unavailable():
    with patch("xibalba_cortex.embedding_client.urlopen", side_effect=OSError("offline")):
        assert embed_query("hello") is None
    assert embed_query("") is None
