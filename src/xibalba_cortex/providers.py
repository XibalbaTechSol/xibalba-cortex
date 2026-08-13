"""Provider boundaries for the configurable Cortex deployment modes.

These adapters describe capabilities and orchestration boundaries. They intentionally do not load
models or write the canonical store; workers remain responsible for bounded execution and store
validation.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class EvidenceScope:
    """Bounded evidence permission for a single inference task."""

    subject_ids: tuple[str, ...] = ()
    max_items: int = 20
    max_bytes: int = 32_000
    max_depth: int = 1

    def validate(self) -> None:
        if not 1 <= self.max_items <= 100:
            raise ValueError("evidence max_items must be between 1 and 100")
        if not 256 <= self.max_bytes <= 1_000_000:
            raise ValueError("evidence max_bytes must be between 256 and 1000000")
        if not 0 <= self.max_depth <= 3:
            raise ValueError("evidence max_depth must be between 0 and 3")
        if any(not item for item in self.subject_ids):
            raise ValueError("evidence subject ids must be non-empty")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {"subject_ids": list(self.subject_ids), "max_items": self.max_items, "max_bytes": self.max_bytes, "max_depth": self.max_depth}


@dataclass(frozen=True)
class ExtractedEntity:
    name: str
    entity_type: str
    evidence_quote: str
    confidence: float

    def validate(self) -> None:
        if not self.name.strip() or not self.entity_type.strip() or not self.evidence_quote.strip():
            raise ValueError("entity name, entity_type, and evidence_quote are required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("entity confidence must be between 0 and 1")


@dataclass(frozen=True)
class ExtractedRelation:
    subject: str
    predicate: str
    object: str
    evidence_quote: str
    confidence: float

    def validate(self) -> None:
        if not all(value.strip() for value in (self.subject, self.predicate, self.object, self.evidence_quote)):
            raise ValueError("relation subject, predicate, object, and evidence_quote are required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("relation confidence must be between 0 and 1")


def validate_extraction_output(output: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Validate bounded, reviewable entity/relation extraction output."""
    if output.get("schema_version") != f"xibalba.{kind}.v1":
        raise ValueError(f"output schema_version must be xibalba.{kind}.v1")
    evidence_hash = output.get("input_snapshot_hash")
    if not isinstance(evidence_hash, str) or not evidence_hash.startswith("sha256:"):
        raise ValueError("input_snapshot_hash is required")
    items = output.get(kind)
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError(f"{kind} must be a list with at most 100 items")
    validated = []
    item_type = ExtractedEntity if kind == "entities" else ExtractedRelation
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{kind} items must be objects")
        fields = ("name", "entity_type", "evidence_quote", "confidence") if kind == "entities" else ("subject", "predicate", "object", "evidence_quote", "confidence")
        try:
            record = item_type(**{field: item[field] for field in fields})
            record.validate()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid {kind} item") from exc
        validated.append(item)
    return {"schema_version": output["schema_version"], "input_snapshot_hash": evidence_hash, kind: validated}


@dataclass(frozen=True)
class InferenceTaskContract:
    """Versioned, harness-facing task envelope metadata.

    The contract is additive: legacy callers may omit optional fields, but new workers can use
    the explicit evidence and promotion boundaries without changing the SQLite task schema.
    """

    schema_version: str = "xibalba.inference.task.v1"
    evidence_scope: tuple[str, ...] = ()
    input_snapshot_hash: str | None = None
    output_schema: str = "xibalba.inference.output.v1"
    promotion_policy: str = "review_required"
    worker_runtime: str | None = None
    evidence_limits: EvidenceScope | None = None

    def validate(self) -> None:
        if self.evidence_limits is not None:
            self.evidence_limits.validate()
        if not self.schema_version or not self.schema_version.startswith("xibalba.inference.task."):
            raise ValueError("invalid inference task schema_version")
        if self.input_snapshot_hash is not None and not self.input_snapshot_hash.startswith("sha256:"):
            raise ValueError("input_snapshot_hash must use sha256: prefix")
        if not self.output_schema:
            raise ValueError("output_schema is required")
        if self.promotion_policy not in {"review_required", "derived_only", "operator_allowed"}:
            raise ValueError("invalid promotion_policy")
        if any(not item for item in self.evidence_scope):
            raise ValueError("evidence_scope entries must be non-empty")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        payload = {
            "schema_version": self.schema_version,
            "evidence_scope": list(self.evidence_scope),
            "input_snapshot_hash": self.input_snapshot_hash,
            "output_schema": self.output_schema,
            "promotion_policy": self.promotion_policy,
            "worker_runtime": self.worker_runtime,
        }
        if self.evidence_limits is not None:
            payload["evidence_limits"] = self.evidence_limits.as_dict()
        return payload


class InferenceProvider(Protocol):
    def capabilities(self) -> dict[str, Any]: ...


class EmbeddingProvider(Protocol):
    def capabilities(self) -> dict[str, Any]: ...


class RetrievalProvider(Protocol):
    def capabilities(self) -> dict[str, Any]: ...


class ProjectionProvider(Protocol):
    def capabilities(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class NativeHarnessInferenceProvider:
    """Native agent-harness boundary; the harness, not Cortex, performs inference."""

    harness: str = "hermes"
    runner: Callable[..., str] | None = None

    def capabilities(self) -> dict[str, Any]:
        return {"queue": True, "direct_model": False, "harness": self.harness}

    def infer(self, prompt: str, *, timeout: int = 120) -> str:
        command = [self.harness, "-z", prompt]
        if self.runner is not None:
            return self.runner(command, prompt=prompt, timeout=timeout)
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode:
            raise RuntimeError(f"{self.harness} inference failed with exit code {result.returncode}")
        return result.stdout


@dataclass(frozen=True)
class LocalEmbeddingProvider:
    """Metadata-only local embedding boundary used by the external worker."""

    model_id: str = "BAAI/bge-small-en-v1.5"
    dimension: int = 384
    normalize: bool = True

    def capabilities(self) -> dict[str, Any]:
        return {"local": True, "dimension": self.dimension, "model_id": self.model_id}


@dataclass(frozen=True)
class SqliteRetrievalProvider:
    def capabilities(self) -> dict[str, Any]:
        return {"lexical": True, "vector": True, "graph": True, "authoritative": True}


def provider_manifest() -> dict[str, Any]:
    return {
        "inference": "native_harness",
        "embeddings": "local",
        "retrieval": "sqlite",
        "canonical_store": "sqlite",
        "remote_projections": "optional",
    }
