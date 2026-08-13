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


@dataclass(frozen=True)
class InferenceConfig:
    provider: str = "native_harness"
    harness: str = "hermes"
    allow_fallback: bool = False


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
class CortexConfig:
    mode: str = "local"
    storage: StorageConfig = field(default_factory=StorageConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    embeddings: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
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
    mode = str(env.get("XIBALBA_CORTEX_MODE", raw.get("mode", "local")))
    if mode not in _MODES:
        raise ValueError(f"unsupported mode: {mode!r}; expected one of {sorted(_MODES)}")

    storage_raw = _mapping(raw.get("storage"), "storage")
    storage = StorageConfig(
        backend=str(storage_raw.get("backend", "sqlite")),
        home=Path(storage_raw.get("home", profile_home)).expanduser(),
    )
    if storage.backend != "sqlite":
        raise ValueError(f"unsupported storage backend: {storage.backend!r}")

    inference_raw = _mapping(raw.get("inference"), "inference")
    inference = InferenceConfig(
        provider=str(inference_raw.get("provider", "native_harness")),
        harness=str(inference_raw.get("harness", "hermes")),
        allow_fallback=bool(inference_raw.get("allow_fallback", False)),
    )
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
    return CortexConfig(
        mode=mode,
        storage=storage,
        inference=inference,
        embeddings=embeddings,
        retrieval=retrieval,
        remote=_mapping(raw.get("remote"), "remote"),
    )
