from __future__ import annotations

import logging
from typing import Any
import httpx

from .config import SuperCortexConfig

logger = logging.getLogger(__name__)


class SupermemoryClientError(Exception):
    """Base exception for Supermemory client errors."""


class SupermemoryClient:
    """Async HTTP client for the Supermemory Local REST API."""

    def __init__(self, config: SuperCortexConfig | None = None) -> None:
        self.config = config or SuperCortexConfig()
        self.base_url = self.config.supermemory_url.rstrip("/")
        self.api_key = self.config.supermemory_api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def ping(self) -> bool:
        """Check if Supermemory Local is alive and accepting requests."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/namespaces", headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False

    async def list_namespaces(self) -> list[str]:
        """List all active namespaces in Supermemory Local."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/namespaces", headers=self._headers())
            if resp.status_code != 200:
                raise SupermemoryClientError(
                    f"Failed to list namespaces: {resp.status_code} {resp.text}"
                )
            data = resp.json()
            return [
                ns.get("namespace") or ns.get("name") or str(ns)
                if isinstance(ns, dict)
                else str(ns)
                for ns in data.get("namespaces", [])
            ]

    async def ingest_document(
        self,
        namespace: str,
        content: str,
        doc_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ingest a document/memory into Supermemory Local."""
        payload: dict[str, Any] = {"content": content}
        if doc_id:
            payload["id"] = doc_id
        if metadata:
            payload["metadata"] = metadata

        url = f"{self.base_url}/ns/{namespace}/document"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            if resp.status_code not in (200, 201, 202):
                raise SupermemoryClientError(
                    f"Ingest document failed: {resp.status_code} {resp.text}"
                )
            return resp.json()

    async def get_document(self, namespace: str, doc_id: str) -> dict[str, Any]:
        """Retrieve a document by ID."""
        url = f"{self.base_url}/ns/{namespace}/document/{doc_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code != 200:
                raise SupermemoryClientError(
                    f"Get document '{doc_id}' failed: {resp.status_code} {resp.text}"
                )
            return resp.json()

    async def delete_documents(self, namespace: str, doc_ids: list[str]) -> dict[str, Any]:
        """Delete documents from a namespace."""
        url = f"{self.base_url}/ns/{namespace}/document"
        async with httpx.AsyncClient(timeout=10.0) as client:
            req = client.build_request("DELETE", url, json={"ids": doc_ids}, headers=self._headers())
            resp = await client.send(req)
            if resp.status_code != 200:
                raise SupermemoryClientError(
                    f"Delete documents failed: {resp.status_code} {resp.text}"
                )
            return resp.json()

    async def search(
        self,
        namespace: str,
        query: str,
        filter_expr: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantic search against Supermemory Local.

        `limit` is sent to the server (its default is 10, which used to cap every request), and
        source documents are requested so a hit can be traced to the memory it came from: a
        hit's own `id` names a chunk or learned memory, not the document.
        """
        payload: dict[str, Any] = {"query": query, "limit": limit, "include": {"documents": True}}
        if filter_expr:
            payload["filter"] = filter_expr

        url = f"{self.base_url}/ns/{namespace}/search"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            if resp.status_code != 200:
                raise SupermemoryClientError(
                    f"Search failed: {resp.status_code} {resp.text}"
                )
            data = resp.json()
            results = data.get("results", [])
            return results[:limit]

    async def get_profile(
        self,
        namespace: str,
        filter_expr: dict[str, Any] | None = None,
        buckets: list[str] | None = None,
    ) -> dict[str, Any]:
        """Retrieve synthesized profile buckets for a namespace."""
        payload: dict[str, Any] = {}
        if filter_expr:
            payload["filter"] = filter_expr
        if buckets:
            payload["buckets"] = buckets

        url = f"{self.base_url}/ns/{namespace}/profile"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            if resp.status_code != 200:
                raise SupermemoryClientError(
                    f"Get profile failed: {resp.status_code} {resp.text}"
                )
            return resp.json()

    # -- session extraction (SuperCortex engine only) ----------------------------------------

    async def _extraction_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
        if resp.status_code == 404:
            raise SupermemoryClientError(
                "session extraction needs the SuperCortex engine; this backend does not serve it "
                f"({self.base_url})"
            )
        if resp.status_code != 200:
            raise SupermemoryClientError(f"Extraction request failed: {resp.status_code} {resp.text}")
        return resp.json()

    async def claim_extraction(self, namespace: str, limit: int = 5) -> dict[str, Any]:
        """Lease pending documents and get the extractor prompt to run on the caller's model."""
        return await self._extraction_post(f"/ns/{namespace}/extraction/claim", {"limit": limit})

    async def submit_extraction(
        self,
        claim_id: str,
        model: str,
        documents: list[dict[str, Any]] | None = None,
        proposals: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Submit the caller's extraction for a claim; the engine grounds and stores it."""
        payload: dict[str, Any] = {"model": model}
        if documents is not None:
            payload["documents"] = documents
        if proposals is not None:
            payload["proposals"] = proposals
        return await self._extraction_post(f"/extraction/claims/{claim_id}/submit", payload)

    async def release_extraction(self, claim_id: str) -> dict[str, Any]:
        """Give a claim back unfinished; its documents return to the queue."""
        return await self._extraction_post(f"/extraction/claims/{claim_id}/release", {})
