"""Deterministic, regex-based entity extraction -- no model, no inference, no isolation
question to reason about at all.

From ~/.claude/plans/velvet-giggling-quill.md: URLs, file paths, UUIDs, git commit hashes,
and fenced code blocks are unambiguous by pattern -- the regex match IS the evidence, so
there's nothing to hallucinate and no `evidence_quote`-grounding risk to guard against, unlike
LLM-produced extraction. Every match gets confidence 1.0 for exactly that reason. Output is
the same `{name, entity_type, evidence_quote, confidence}` shape `ExtractedEntity` (providers.py)
already validates, so it rides the identical `validate_extraction_result` gate every other
extraction path (isolated worker, in-session self-extraction) goes through.
"""
from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
_FILE_PATH_RE = re.compile(r"(?:(?:\.{1,2}|~)?/[\w.\-]+)+\.\w{1,10}\b")
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_GIT_HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
_CODE_FENCE_RE = re.compile(r"```(\w+)?\n")


def _dedupe(entities: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, object]] = []
    for e in entities:
        key = (str(e["entity_type"]), str(e["name"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def extract_structural_entities(content: str) -> list[dict[str, object]]:
    """Returns entities in ExtractedEntity shape: {name, entity_type, evidence_quote, confidence}."""
    entities: list[dict[str, object]] = []

    url_spans: list[tuple[int, int]] = []
    for match in _URL_RE.finditer(content):
        url = match.group(0)
        url_spans.append(match.span())
        entities.append({"name": url, "entity_type": "url", "evidence_quote": url, "confidence": 1.0})

    for match in _FILE_PATH_RE.finditer(content):
        span = match.span()
        if any(span[0] >= u[0] and span[1] <= u[1] for u in url_spans):
            continue
        path = match.group(0)
        entities.append({"name": path, "entity_type": "file_path", "evidence_quote": path, "confidence": 1.0})

    for match in _UUID_RE.finditer(content):
        uuid_str = match.group(0)
        entities.append({"name": uuid_str, "entity_type": "uuid", "evidence_quote": uuid_str, "confidence": 1.0})

    # Git hashes are a bare hex-string pattern, easily confused with other hex data (a UUID
    # segment, a hash of something unrelated) -- only match ones NOT already captured as part
    # of a UUID match, and require a `commit`/`sha`/`rev` cue nearby to avoid false positives
    # on arbitrary hex-looking tokens, since "7-40 lowercase hex chars" alone is far too loose.
    uuid_spans = [m.span() for m in _UUID_RE.finditer(content)]
    for match in _GIT_HASH_RE.finditer(content):
        span = match.span()
        if any(span[0] >= u[0] and span[1] <= u[1] for u in uuid_spans):
            continue
        window_start = max(0, span[0] - 20)
        window = content[window_start:span[0]].lower()
        if not any(cue in window for cue in ("commit", "sha", "rev ", "hash")):
            continue
        commit_hash = match.group(0)
        entities.append({"name": commit_hash, "entity_type": "git_commit", "evidence_quote": commit_hash, "confidence": 1.0})

    for match in _CODE_FENCE_RE.finditer(content):
        lang = match.group(1)
        if lang:
            entities.append({"name": lang, "entity_type": "code_language", "evidence_quote": match.group(0).strip(), "confidence": 1.0})

    return _dedupe(entities)
