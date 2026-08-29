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
