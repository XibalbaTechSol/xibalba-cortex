"""Profile-scoped configuration for local and hybrid Cortex deployments.

Configuration is descriptive and provider selection does not grant a provider write access to
canonical storage. The native harness and local embedding worker remain the safe defaults.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

_MODES = {"local", "hybrid", "remote-inference"}
_SECRET_KEYS = {"api_key", "token", "password", "secret", "bearer_token", "connection_string"}


@dataclass(frozen=True)
class StorageConfig:
    backend: str = "sqlite"
    home: Path = Path.home() / ".hermes" / "xibalba-cortex"
    dsn: str | None = None
    pool_size: int = 5
    ssl_mode: str | None = None


@dataclass(frozen=True)
class InferenceConfig:
    enabled: bool = True
    provider: str = "native_harness"
    harness: str = "hermes"
    profile_name: str = "xibalba-cortex-worker"
    allow_fallback: bool = False
    task_types: tuple[str, ...] = ("extract_entities", "extract_relations", "classify_para", "detect_contradictions")
    batch_size: int = 5
    interval_seconds: float = 5.0
    max_attempts: int = 3
    timeout_seconds: int = 120
    max_parallel_families: int = 2
    combined_batching: bool = True
    max_evidence_chars_per_memory: int = 12_000
    max_items_per_type: int = 20
    human_review_confidence_threshold: float = 0.75
    task_confidence_thresholds: dict[str, float] = field(default_factory=dict)
    promotion_policy: str = "confidence_gated"
    contradictions_require_review: bool = True

@dataclass(frozen=True)
class AuthConfig:
    """Network transport policy; stdio remains local and does not need bearer auth."""

    rate_limit_per_minute: int | None = None


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "local"
    model_id: str = "BAAI/bge-small-en-v1.5"
    dimension: int = 384
    normalize: bool = True
    batch_size: int = 16


@dataclass(frozen=True)
class RetrievalConfig:
    lexical: bool = True
    vector: bool = True
    graph: bool = True


@dataclass(frozen=True)
class QuotaConfig:
    """Hard per-profile resource limits; None means unlimited."""

    max_memories: int | None = None

    def as_dict(self) -> dict[str, int | None]:
        return {"max_memories": self.max_memories}

@dataclass(frozen=True)
class FeatureConfig:
    """Deployment policy for optional Cortex capabilities."""

    provenance: bool = True
    lexical: bool = True
    vector: bool = True
    inference: bool = True
    embeddings: bool = True
    graph: bool = True
    context_assembly: bool = True
    connectors: bool = True
    governance: bool = True
    telemetry: bool = True
    audit: bool = True

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderTelemetryConfig:
    """Explicit opt-in policy for external provider telemetry."""

    enabled: bool = False
    consented_providers: tuple[str, ...] = ()
    retention_tier: str = "digest"
    allow_raw_payloads: bool = False


@dataclass(frozen=True)
class CortexConfig:
    profile_id: str = "default"
    mode: str = "local"
    storage: StorageConfig = field(default_factory=StorageConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    embeddings: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    telemetry: ProviderTelemetryConfig = field(default_factory=ProviderTelemetryConfig)
    quotas: QuotaConfig = field(default_factory=QuotaConfig)
    remote: dict[str, Any] = field(default_factory=dict)

    def redacted_dict(self) -> dict[str, Any]:
        return _redact(asdict(self))


def _redact(value: Any, key: str | None = None) -> Any:
    if key and key.lower() in _SECRET_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def load_config(*, home: Path | str | None = None, environ: dict[str, str] | None = None) -> CortexConfig:
    """Load config.yaml, then apply environment overrides without requiring a config file."""
    profile_home = Path(home or Path.home() / ".hermes" / "xibalba-cortex").expanduser()
    config_path = profile_home / "config.yaml"
    raw: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text())
        raw = _mapping(loaded, "config")

    env = os.environ if environ is None else environ
    profile_id = str(env.get("XIBALBA_CORTEX_PROFILE_ID", raw.get("profile_id", "default"))).strip()
    if not profile_id:
        raise ValueError("profile_id must be a non-empty string")
    mode = str(env.get("XIBALBA_CORTEX_MODE", raw.get("mode", "local")))
    if mode not in _MODES:
        raise ValueError(f"unsupported mode: {mode!r}; expected one of {sorted(_MODES)}")

    storage_raw = _mapping(raw.get("storage"), "storage")
    storage = StorageConfig(
        backend=str(storage_raw.get("backend", "sqlite")),
        home=Path(storage_raw.get("home", profile_home)).expanduser(),
        dsn=str(storage_raw["dsn"]) if storage_raw.get("dsn") is not None else None,
        pool_size=int(storage_raw.get("pool_size", 5)),
        ssl_mode=str(storage_raw["ssl_mode"]) if storage_raw.get("ssl_mode") is not None else None,
    )
    if storage.backend not in {"sqlite", "postgresql"}:
        raise ValueError(f"unsupported storage backend: {storage.backend!r}")
    if storage.pool_size < 1:
        raise ValueError("storage pool_size must be positive")
    if storage.backend == "postgresql" and not storage.dsn:
        raise ValueError("storage.dsn is required for postgresql backend")

    inference_raw = _mapping(raw.get("inference"), "inference")
    task_types_raw = inference_raw.get("task_types", InferenceConfig().task_types)
    if not isinstance(task_types_raw, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in task_types_raw):
        raise ValueError("inference.task_types must be a list of non-empty strings")
    inference = InferenceConfig(
        enabled=bool(inference_raw.get("enabled", True)),
        provider=str(inference_raw.get("provider", "native_harness")),
        harness=str(inference_raw.get("harness", "hermes")),
        profile_name=str(inference_raw.get("profile_name", "xibalba-cortex-worker")),
        allow_fallback=bool(inference_raw.get("allow_fallback", False)),
        task_types=tuple(dict.fromkeys(item.strip() for item in task_types_raw)),
        batch_size=int(inference_raw.get("batch_size", 5)),
        interval_seconds=float(inference_raw.get("interval_seconds", 5.0)),
        max_attempts=int(inference_raw.get("max_attempts", 3)),
        timeout_seconds=int(inference_raw.get("timeout_seconds", 120)),
        max_parallel_families=int(inference_raw.get("max_parallel_families", 2)),
        combined_batching=bool(inference_raw.get("combined_batching", True)),
        max_evidence_chars_per_memory=int(inference_raw.get("max_evidence_chars_per_memory", 12_000)),
        max_items_per_type=int(inference_raw.get("max_items_per_type", 20)),
        human_review_confidence_threshold=float(inference_raw.get("human_review_confidence_threshold", 0.75)),
        task_confidence_thresholds={str(k): float(v) for k, v in _mapping(inference_raw.get("task_confidence_thresholds"), "inference.task_confidence_thresholds").items()},
        promotion_policy=str(inference_raw.get("promotion_policy", "confidence_gated")),
        contradictions_require_review=bool(inference_raw.get("contradictions_require_review", True)),
    )
    supported_inference_tasks = {"extract_memory_metadata", "extract_entities", "extract_relations", "classify_para", "detect_contradictions"}
    unknown_tasks = set(inference.task_types) - supported_inference_tasks
    if inference.provider != "native_harness":
        raise ValueError("inference.provider must currently be native_harness")
    if not inference.harness.strip() or not inference.profile_name.strip():
        raise ValueError("inference harness and profile_name must be non-empty")
    if unknown_tasks:
        raise ValueError(f"unsupported inference task types: {sorted(unknown_tasks)}")
    if inference.batch_size < 1 or inference.interval_seconds < 0.25 or inference.max_attempts < 1 or inference.timeout_seconds < 1 or not 1 <= inference.max_parallel_families <= 3 or inference.max_evidence_chars_per_memory < 256 or not 1 <= inference.max_items_per_type <= 100 or not 0 <= inference.human_review_confidence_threshold <= 1:
        raise ValueError("inference batch_size/max_attempts/timeout must be positive and interval_seconds must be at least 0.25")
    if inference.promotion_policy not in {"confidence_gated", "review_required"}:
        raise ValueError("inference.promotion_policy must be confidence_gated or review_required")
    supported_threshold_tasks = {"classify_para", "extract_entities", "extract_relations", "detect_contradictions"}
    if set(inference.task_confidence_thresholds) - supported_threshold_tasks:
        raise ValueError("inference.task_confidence_thresholds contains an unsupported task type")
    if any(not 0 <= value <= 1 for value in inference.task_confidence_thresholds.values()):
        raise ValueError("task confidence thresholds must be between 0 and 1")
    auth_raw = _mapping(raw.get("auth"), "auth")
    rate_limit_value = env.get("XIBALBA_CORTEX_RATE_LIMIT_PER_MINUTE", auth_raw.get("rate_limit_per_minute"))
    rate_limit = None if rate_limit_value in (None, "", "none", "null") else int(rate_limit_value)
    if rate_limit is not None and rate_limit < 1:
        raise ValueError("auth.rate_limit_per_minute must be positive or null")
    embeddings_raw = _mapping(raw.get("embeddings"), "embeddings")
    embeddings = EmbeddingConfig(
        provider=str(embeddings_raw.get("provider", "local")),
        model_id=str(embeddings_raw.get("model_id", "BAAI/bge-small-en-v1.5")),
        dimension=int(embeddings_raw.get("dimension", 384)),
        normalize=bool(embeddings_raw.get("normalize", True)),
        batch_size=int(embeddings_raw.get("batch_size", 16)),
    )
    if embeddings.dimension < 1 or embeddings.batch_size < 1:
        raise ValueError("embedding dimension and batch_size must be positive")

    retrieval_raw = _mapping(raw.get("retrieval"), "retrieval")
    retrieval = RetrievalConfig(
        lexical=bool(retrieval_raw.get("lexical", True)),
        vector=bool(retrieval_raw.get("vector", True)),
        graph=bool(retrieval_raw.get("graph", True)),
    )
    feature_raw = _mapping(raw.get("features"), "features")
    defaults = FeatureConfig()

    def feature_value(name: str) -> bool:
        env_name = f"XIBALBA_CORTEX_FEATURE_{name.upper()}"
        raw_value = env.get(env_name, feature_raw.get(name, getattr(defaults, name)))
        if isinstance(raw_value, bool):
            return raw_value
        if str(raw_value).lower() in {"1", "true", "yes", "on", "enabled"}:
            return True
        if str(raw_value).lower() in {"0", "false", "no", "off", "disabled"}:
            return False
        raise ValueError(f"{name} feature flag must be boolean")

    features = FeatureConfig(**{name: feature_value(name) for name in defaults.__dataclass_fields__})

    telemetry_raw = _mapping(raw.get("telemetry"), "telemetry")
    consented_raw = telemetry_raw.get("consented_providers", ())
    if not isinstance(consented_raw, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in consented_raw):
        raise ValueError("telemetry.consented_providers must be a list of non-empty strings")
    telemetry = ProviderTelemetryConfig(
        enabled=bool(telemetry_raw.get("enabled", False)),
        consented_providers=tuple(dict.fromkeys(item.strip() for item in consented_raw)),
        retention_tier=str(telemetry_raw.get("retention_tier", "digest")),
        allow_raw_payloads=bool(telemetry_raw.get("allow_raw_payloads", False)),
    )
    if telemetry.retention_tier not in {"digest", "synopsis", "verbatim"}:
        raise ValueError("telemetry.retention_tier must be digest, synopsis, or verbatim")
    quota_raw = _mapping(raw.get("quotas"), "quotas")
    quota_value = env.get("XIBALBA_CORTEX_QUOTA_MAX_MEMORIES", quota_raw.get("max_memories"))
    max_memories = None if quota_value in (None, "", "none", "null") else int(quota_value)
    if max_memories is not None and max_memories < 1:
        raise ValueError("quotas.max_memories must be positive or null")
    return CortexConfig(
        profile_id=profile_id,
        mode=mode,
        storage=storage,
        inference=inference,
        auth=AuthConfig(rate_limit_per_minute=rate_limit),
        embeddings=embeddings,
        retrieval=retrieval,
        features=features,
        telemetry=telemetry,
        quotas=QuotaConfig(max_memories=max_memories),
        remote=_mapping(raw.get("remote"), "remote"),
    )
