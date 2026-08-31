from pathlib import Path

import pytest

from xibalba_cortex.config import load_config


def test_default_config_is_local_and_uses_native_harness_and_local_embeddings():
    config = load_config(home=Path("/tmp/example-cortex"))

    assert config.mode == "local"
    assert config.inference.provider == "native_harness"
    assert config.inference.harness == "hermes"
    assert config.embeddings.provider == "local"
    assert config.storage.backend == "sqlite"
    assert config.storage.home == Path("/tmp/example-cortex")


def test_profile_config_supports_hybrid_mode_and_environment_overrides(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(
        "mode: hybrid\n"
        "inference:\n"
        "  provider: native_harness\n"
        "  harness: hermes\n"
        "embeddings:\n"
        "  provider: local\n"
        "  model_id: local/test-model\n"
        "  dimension: 3\n"
        "storage:\n"
        "  backend: sqlite\n"
    )
    monkeypatch.setenv("XIBALBA_CORTEX_MODE", "local")

    config = load_config(home=tmp_path)

    assert config.mode == "local"
    assert config.embeddings.model_id == "local/test-model"
    assert config.embeddings.dimension == 3


def test_invalid_provider_mode_is_rejected(tmp_path):
    (tmp_path / "config.yaml").write_text("mode: unsupported\n")

    with pytest.raises(ValueError, match="unsupported mode"):
        load_config(home=tmp_path)


def test_effective_config_redacts_secret_like_values(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "mode: hybrid\n"
        "remote:\n"
        "  endpoint: https://example.invalid\n"
        "  api_key: should-not-be-shown\n"
    )

    config = load_config(home=tmp_path)
    rendered = config.redacted_dict()

    assert rendered["remote"]["api_key"] == "[REDACTED]"
    assert "should-not-be-shown" not in str(rendered)


def test_feature_flags_support_yaml_and_environment_overrides(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "features:\n"
        "  context_assembly: false\n"
        "  connectors: false\n"
        "retrieval:\n"
        "  vector: false\n"
    )
    config = load_config(home=tmp_path, environ={"XIBALBA_CORTEX_FEATURE_CONNECTORS": "true"})

    assert config.features.context_assembly is False
    assert config.features.connectors is True
    assert config.retrieval.vector is False


def test_quota_config_supports_yaml_and_environment_overrides(tmp_path):
    (tmp_path / "config.yaml").write_text("quotas:\n  max_memories: 7\n")
    config = load_config(home=tmp_path, environ={"XIBALBA_CORTEX_QUOTA_MAX_MEMORIES": "9"})
    assert config.quotas.max_memories == 9
    assert config.quotas.as_dict() == {"max_memories": 9}


def test_postgresql_storage_requires_dsn_and_preserves_pool_policy(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "storage:\n  backend: postgresql\n  dsn: postgresql://cortex@db/cortex\n  pool_size: 9\n  ssl_mode: require\n"
    )
    config = load_config(home=tmp_path)
    assert config.storage.backend == "postgresql"
    assert config.storage.dsn.endswith("/cortex")
    assert config.storage.pool_size == 9
    assert config.storage.ssl_mode == "require"


def test_profile_id_is_configurable_and_required(tmp_path):
    config = load_config(home=tmp_path, environ={"XIBALBA_CORTEX_PROFILE_ID": "tenant-a"})
    assert config.profile_id == "tenant-a"
    with pytest.raises(ValueError, match="profile_id"):
        load_config(home=tmp_path, environ={"XIBALBA_CORTEX_PROFILE_ID": "   "})



def test_auth_rate_limit_supports_yaml_and_environment_overrides(tmp_path):
    (tmp_path / "config.yaml").write_text("auth:\n  rate_limit_per_minute: 12\n")
    config = load_config(home=tmp_path, environ={"XIBALBA_CORTEX_RATE_LIMIT_PER_MINUTE": "24"})
    assert config.auth.rate_limit_per_minute == 24


def test_invalid_auth_rate_limit_is_rejected(tmp_path):
    (tmp_path / "config.yaml").write_text("auth:\n  rate_limit_per_minute: 0\n")
    with pytest.raises(ValueError, match="rate_limit_per_minute"):
        load_config(home=tmp_path)
