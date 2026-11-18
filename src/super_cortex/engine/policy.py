"""Retention policy: how much of what an agent sends is kept, per namespace.

Use cases want opposite things. An auditor wants every version of every document (including
every agent thought the capture side chose to send) kept verbatim and provably untouched. A
researcher wants distilled memories and fast search, not a growing pile of raw transcripts. So
retention is a per-namespace policy: one of three presets, with individual settings adjustable
except under `audit`.

- audit     every received version kept forever; deletes only hide; evidence history kept;
            the database refuses rewrites (SQLite triggers). One-way: once a namespace is audit
            it stays audit, so an auditor can trust history was never pruned.
- standard  current version only; edits replace; deletes remove. (Default.)
- research  raw content dropped once dreaming has extracted memories; search defaults to
            memories. Needs dreaming, so needs the extractor (Gemini free tier).

Data classes: what was ingested is `content`, the record. Everything synthesised from it
(chunks, embeddings, learned memories, their evidence links) is `metadata`, and every such item
says what it was derived from (`derivedFrom`) and what made it (`generator`). Retention presets
govern content; metadata can always be regenerated from retained content.

What gets *sent* (every thought vs final answers) is decided by the capture side; the engine
keeps whatever arrives according to this policy.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace
from typing import Any

PRESETS = ("audit", "standard", "research")
VERSION_MODES = ("all", "latest")
ON_DELETE = ("tombstone", "remove")
RAW_AFTER_DREAM = ("keep", "drop")
DEFAULT_SEARCH = ("chunks", "memories")
DREAMING = ("auto", "off")


@dataclass(frozen=True)
class RetentionPolicy:
    preset: str
    versions: str             # all: every received version; latest: only the current one
    version_ttl_days: int | None  # with versions=all: prune replaced versions older than this (None = never)
    on_delete: str            # tombstone: hide from search, keep content; remove: drop content
    raw_after_dream: str      # drop: delete raw text and chunks once memories are extracted
    default_search: str       # searchMode used when a request does not name one
    dreaming: str             # auto: follow each document's taskType; off: never extract

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "locked": self.preset == "audit"}


PRESET_POLICIES: dict[str, RetentionPolicy] = {
    "audit": RetentionPolicy("audit", "all", None, "tombstone", "keep", "chunks", "auto"),
    "standard": RetentionPolicy("standard", "latest", None, "remove", "keep", "chunks", "auto"),
    "research": RetentionPolicy("research", "latest", None, "remove", "drop", "memories", "auto"),
}


def default_preset() -> str:
    preset = os.getenv("SUPER_CORTEX_DEFAULT_RETENTION", "standard")
    if preset not in PRESETS:
        raise ValueError(f"SUPER_CORTEX_DEFAULT_RETENTION must be one of {PRESETS}")
    return preset


def build_policy(preset: str, overrides: dict[str, Any] | None = None) -> RetentionPolicy:
    """A preset plus validated overrides. `audit` takes no overrides: its guarantees are the point."""
    if preset not in PRESETS:
        raise ValueError(f"preset must be one of {PRESETS}")
    overrides = dict(overrides or {})
    if preset == "audit" and overrides:
        raise ValueError("the audit preset cannot be customised")
    unknown = set(overrides) - {"versions", "version_ttl_days", "on_delete", "raw_after_dream", "default_search", "dreaming"}
    if unknown:
        raise ValueError(f"unknown policy settings: {sorted(unknown)}")
    policy = replace(PRESET_POLICIES[preset], **overrides)
    for name, allowed in (("versions", VERSION_MODES), ("on_delete", ON_DELETE),
                          ("raw_after_dream", RAW_AFTER_DREAM), ("default_search", DEFAULT_SEARCH),
                          ("dreaming", DREAMING)):
        if getattr(policy, name) not in allowed:
            raise ValueError(f"{name} must be one of {allowed}")
    ttl = policy.version_ttl_days
    if ttl is not None and (not isinstance(ttl, int) or ttl < 1):
        raise ValueError("version_ttl_days must be a positive integer or null")
    if ttl is not None and policy.versions != "all":
        raise ValueError("version_ttl_days only applies with versions=all")
    if policy.raw_after_dream == "drop" and policy.dreaming == "off":
        raise ValueError("raw_after_dream=drop needs dreaming=auto, or nothing would be kept")
    return policy
