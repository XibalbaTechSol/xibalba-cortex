"""Search targets the harness can evaluate.

`HttpTarget` speaks the Supermemory API, so the same class measures Supermemory Local and the
SuperCortex engine. `RandomTarget` is the control: a ranker that ignores the query.
"""

from __future__ import annotations

import random
from typing import Any, Protocol

import httpx


class SearchTarget(Protocol):
    name: str

    def search(self, query: str, k: int) -> list[str]:
        """Return document ids, best first, without duplicates."""
        ...


def document_id(item: dict[str, Any]) -> str | None:
    """The source document of a search hit.

    Supermemory's `id` is the id of the chunk or learned memory, not of the document it came
    from; the document is only reachable through `include.documents`. Scoring on the hit `id`
    would count every Supermemory result as a miss.
    """
    included = item.get("included") or {}
    doc = included.get("document") if isinstance(included, dict) else None
    if isinstance(doc, dict) and doc.get("id"):
        return str(doc["id"])
    if item.get("documentId"):
        return str(item["documentId"])
    return None


def dedupe(ids: list[str | None]) -> list[str]:
    return [i for i in dict.fromkeys(i for i in ids if i)]


class HttpTarget:
    def __init__(
        self,
        name: str,
        base_url: str,
        namespace: str,
        api_key: str = "",
        search_extras: dict[str, Any] | None = None,
        ingest_extras: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.namespace = namespace
        self.search_extras = search_extras or {}
        self.ingest_extras = ingest_extras or {}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(timeout=timeout, headers=headers)

    def ingest(self, docs: list[dict[str, Any]]) -> None:
        for doc in docs:
            payload = {"content": doc["content"], "id": doc["id"], "metadata": doc.get("metadata") or {}}
            payload.update(self.ingest_extras)
            resp = self._client.post(f"{self.base_url}/ns/{self.namespace}/document", json=payload)
            if resp.status_code not in (200, 201, 202):
                raise RuntimeError(f"{self.name}: ingest {doc['id']} failed: {resp.status_code} {resp.text[:200]}")

    def search(self, query: str, k: int) -> list[str]:
        # Ask for more hits than k: several chunks of one document collapse into one id.
        payload = {"query": query, "limit": min(100, k * 3), "include": {"documents": True}}
        payload.update(self.search_extras)
        resp = self._client.post(f"{self.base_url}/ns/{self.namespace}/search", json=payload)
        resp.raise_for_status()
        return dedupe([document_id(item) for item in resp.json().get("results", [])])[:k]


class RandomTarget:
    """Control ranker: a fixed random order of the corpus, independent of the query."""

    def __init__(self, corpus_ids: list[str], seed: int = 13) -> None:
        self.name = "control:random"
        self._ids = list(corpus_ids)
        self._rng = random.Random(seed)

    def search(self, query: str, k: int) -> list[str]:
        return self._rng.sample(self._ids, min(k, len(self._ids)))
