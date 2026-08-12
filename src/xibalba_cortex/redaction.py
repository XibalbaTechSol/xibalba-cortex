"""Shared secret-redaction logic for every ingestion path that captures externally-sourced
content (transcript files, session-sync finalization, and the network-reachable generic
ingestion path). Previously duplicated near-identically in `transcript_ingest.py` and
`session_sync.py` -- extracted here so a fix to the pattern set only needs to happen once, and
so new ingestion paths (which see less-trusted content than a local transcript file) apply the
same scrubbing by default rather than by copy-paste.
"""
from __future__ import annotations

import re
from typing import Any

# Order matters only in that each pattern runs independently over the same string -- they don't
# depend on each other's output.
_SECRET_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(secret|password|token|private[_ -]?key)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED]"),
    (re.compile(r"\b(?:0x)?[0-9a-fA-F]{64}\b"), "[REDACTED]"),
)


def redact(value: Any) -> Any:
    """Recursively scrub likely secrets (bearer tokens, api keys, password/token/secret
    fields, sk-... style keys, 64-hex-char strings) out of a string, or out of every string
    found inside a list/dict. Non-string/list/dict values pass through unchanged."""
    if isinstance(value, str):
        for pattern, replacement in _SECRET_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {str(key): redact(item) for key, item in value.items()}
    return value
