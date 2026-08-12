"""Versioned canonical encodings used by the portable event kernel."""

from __future__ import annotations

import hashlib
import json
from typing import Any

CANONICAL_JSON_V1 = "xibalba.canonical-json.v1"


def canonical_json_bytes(value: Any) -> bytes:
    """Return the UTF-8 encoding shared with integrity-core BCC JSON."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def sha256_prefixed(value: bytes | str) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(payload).hexdigest()
