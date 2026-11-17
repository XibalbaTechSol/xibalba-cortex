"""Embedding backends for the SuperCortex engine.

Every backend returns L2-normalised float vectors, so cosine similarity is a dot product and
the store never has to renormalise. The model identity (`model_key`) is recorded next to every
stored vector: a vector is only ever compared with vectors from the same model, and a model
change is detected rather than silently mixing spaces.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol

import httpx


class Embedder(Protocol):
    model_key: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def l2_normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return list(vector)
    return [v / norm for v in vector]


class HashingEmbedder:
    """Deterministic bag-of-words hashing embedder.

    No model, no network: used by tests and as an offline floor. It captures term overlap only,
    so it is a lexical signal wearing a vector's clothes -- never a production choice.
    """

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension
        self.model_key = f"hashing-bow-{dimension}@v1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dimension
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
                idx = int.from_bytes(digest[:4], "little") % self.dimension
                sign = 1.0 if digest[4] & 1 else -1.0
                vec[idx] += sign
            out.append(l2_normalise(vec))
        return out


class FastEmbedEmbedder:
    """Local ONNX embeddings via fastembed (optional dependency: `super-cortex[engine-local]`).

    Default model is the one the old Cortex engine registered (bge-small, 384 dims); Supermemory
    Local uses bge-base (768). Which one we keep is decided by the retrieval eval, not here.
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding  # imported lazily: heavy and optional

        self._model = TextEmbedding(model_name=model_name)
        probe = next(iter(self._model.embed(["probe"])))
        self.dimension = len(probe)
        self.model_key = f"{model_name}@fastembed"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [l2_normalise([float(x) for x in v]) for v in self._model.embed(texts)]


class GeminiEmbedder:
    """Gemini embedding API (free tier). Batches up to 100 texts per request."""

    BATCH = 100

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-embedding-001",
        dimension: int = 768,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        if not self.api_key:
            raise RuntimeError("GeminiEmbedder needs GEMINI_API_KEY or GOOGLE_API_KEY")
        self.model = model
        self.dimension = dimension
        self.timeout = timeout
        self.model_key = f"{model}-{dimension}@gemini"

    def embed(self, texts: list[str]) -> list[list[float]]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"
        out: list[list[float]] = []
        with httpx.Client(timeout=self.timeout) as client:
            for start in range(0, len(texts), self.BATCH):
                batch = texts[start : start + self.BATCH]
                body = {
                    "requests": [
                        {
                            "model": f"models/{self.model}",
                            "content": {"parts": [{"text": t}]},
                            "outputDimensionality": self.dimension,
                        }
                        for t in batch
                    ]
                }
                resp = client.post(url, json=body, headers={"x-goog-api-key": self.api_key})
                resp.raise_for_status()
                out.extend(l2_normalise(e["values"]) for e in resp.json()["embeddings"])
        return out


def default_embedder() -> Embedder:
    """Pick the embedder from SUPER_CORTEX_EMBEDDER (fastembed | gemini | hashing).

    Unset means fastembed when installed, otherwise Gemini when a key exists. There is no
    silent fallback to hashing: a production engine without a real embedder must fail loudly.
    """
    choice = os.getenv("SUPER_CORTEX_EMBEDDER", "").strip().lower()
    if choice == "hashing":
        return HashingEmbedder()
    if choice == "gemini":
        return GeminiEmbedder()
    if choice in ("", "fastembed"):
        try:
            return FastEmbedEmbedder(os.getenv("SUPER_CORTEX_EMBED_MODEL", "BAAI/bge-small-en-v1.5"))
        except ImportError:
            if choice == "fastembed":
                raise
            return GeminiEmbedder()
    raise ValueError(f"unknown SUPER_CORTEX_EMBEDDER={choice!r}")
