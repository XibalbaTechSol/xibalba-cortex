"""Small bounded client for the local embedding sidecar."""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


def embed_query(text: str, *, timeout: float = 8.0) -> list[float] | None:
    if not text or len(text) > 20_000:
        return None
    url = os.environ.get("XIBALBA_CORTEX_EMBEDDING_URL", "http://127.0.0.1:8433/embed")
    request = Request(url, data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(64_000))
        vector = payload.get("vector")
        if not isinstance(vector, list) or len(vector) != 384:
            return None
        return [float(value) for value in vector]
    except Exception:
        return None
